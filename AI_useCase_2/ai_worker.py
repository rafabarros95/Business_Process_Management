"""Worker set for the BPA Lab Shipment process with AI-driven carrier selection.

Surgical swap in `bpmn/bpa_lab_shipment_process_ai.bpmn`:
the original `UserTask_CheckInformation` USER TASK (manual review with the
`output_ShippingInformation` form) is replaced by a SERVICE TASK with
Zeebe type `recommend-carrier`. Every other node, ID, gateway, message and
data store is preserved from the upstream BPMN
(`main` branch of BpaLabTHCologne/bpa_lab_demonstration_factory).

This file also stands in for the upstream BPA Lab Node.js workers
(`checkProductInformation`, `shipBikeInstances`, `sendShippedEmail`,
`sendFinishedShipment`) so the demo runs end-to-end inside this Python
project, without the upstream TypeScript stack or MySQL.

Note on HTTP connector tasks: the upstream BPMN's two `io.camunda:http-json:1`
tasks (Get Coordinates / Calculate travel distance) are handled by the
Camunda Connectors runtime container (localhost:8085) — not by this worker.
The deploy script pre-injects `latitudeSA`, `longitudeSA`, `distance` and
`duration` so the demo doesn't depend on those calls succeeding; if the
Connectors do fire and succeed, they simply overwrite the values.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pyzeebe import Job, JobController, ZeebeWorker, create_insecure_channel

from llm_client import recommend

CARRIER_DATA_PATH = Path(__file__).parent / "data" / "carriers.json"

Carrier = dict[str, Any]


def _load_carrier_catalogue() -> list[Carrier]:
    with CARRIER_DATA_PATH.open(encoding="utf-8") as f:
        return json.load(f)["carriers"]


async def on_error(exception: Exception, job: Job, job_controller: JobController) -> None:
    print(f"[worker] Job {job.type} failed: {exception}")
    await job_controller.set_error_status(job, str(exception))


async def main() -> None:
    channel = create_insecure_channel(grpc_address="localhost:26500")
    worker = ZeebeWorker(channel)

    # --- mock of upstream HTTP-connector `Get Coordinates` ------------------
    # Originally `io.camunda:http-json:1` against OpenRouteService; the deploy
    # script pre-injects synthetic geocodes so we just acknowledge and echo.
    @worker.task(task_type="getShippingCoordinates", exception_handler=on_error)
    async def get_shipping_coordinates(  # pyright: ignore[reportUnusedFunction]
        shippingAddress: str = "",
        latitudeSA: float = 0.0,
        longitudeSA: float = 0.0,
    ) -> dict[str, Any]:
        print(f"[getShippingCoordinates] '{shippingAddress}' → ({latitudeSA}, {longitudeSA})")
        return {"latitudeSA": latitudeSA, "longitudeSA": longitudeSA}

    # --- mock of upstream HTTP-connector `Calculate travel distance` --------
    @worker.task(task_type="calculateTravelDistance", exception_handler=on_error)
    async def calculate_travel_distance(  # pyright: ignore[reportUnusedFunction]
        latitudeWA: float = 0.0,
        longitudeWA: float = 0.0,
        latitudeSA: float = 0.0,
        longitudeSA: float = 0.0,
        distance: float = 0.0,
        duration: float = 0.0,
    ) -> dict[str, Any]:
        print(
            f"[calculateTravelDistance] WA({latitudeWA},{longitudeWA}) → SA({latitudeSA},{longitudeSA}) "
            f"= {distance}km / {duration}min"
        )
        return {"distance": distance, "duration": duration}

    # --- mock of BPA Lab `checkProductInformation` --------------------------
    @worker.task(task_type="checkProductInformation", exception_handler=on_error)
    async def check_product_information(shipment: dict[str, Any]) -> dict[str, Any]:
        ok = bool(shipment.get("order_id")) and float(shipment.get("weight_kg", 0)) > 0
        print(f"[checkProductInformation] order={shipment.get('order_id')} weight={shipment.get('weight_kg')}kg → ok={ok}")
        return {"product_check_ok": ok}

    # --- AI replacement for the original `UserTask_CheckInformation` --------
    @worker.task(task_type="recommend-carrier", exception_handler=on_error)
    async def recommend_carrier(
        shipment: dict[str, Any],
        urgency: str = "normal",
        sustainability_priority: bool = False,
    ) -> dict[str, Any]:
        catalogue = _load_carrier_catalogue()
        result = recommend(
            shipment=shipment,
            urgency=urgency,
            sustainability=bool(sustainability_priority),
            carriers=catalogue,
        )
        print(
            f"[recommend-carrier] {shipment.get('order_id')} ({shipment.get('destination_country')}, "
            f"{shipment.get('weight_kg')}kg, urgency={urgency}, sustainability={sustainability_priority}) → "
            f"selectedCarrier='{result['recommended_carrier']}' | "
            f"cost={result['estimated_cost_eur']}€ | "
            f"transit={result['estimated_transit_days']}d | "
            f"needs_approval={result['requires_human_approval']}"
        )
        # `selectedCarrier` is the analogue of the original chooseVendorForm's `selectedVendor`
        # in Showcase 1 — downstream `shipBikeInstances` reads this name.
        return {
            "selectedCarrier": result["recommended_carrier"],
            "ai_ranked_carriers": result["ranked_carriers"],
            "ai_estimated_cost_eur": result["estimated_cost_eur"],
            "ai_estimated_transit_days": result["estimated_transit_days"],
            "ai_requires_human_approval": result["requires_human_approval"],
            "ai_approval_reason": result["approval_reason"],
        }

    # --- mock of BPA Lab `shipBikeInstances` --------------------------------
    @worker.task(task_type="shipBikeInstances", exception_handler=on_error)
    async def ship_bike_instances(
        shipment: dict[str, Any],
        selectedCarrier: str,
    ) -> dict[str, Any]:
        tracking_id = f"TRK-{uuid.uuid4().hex[:10].upper()}"
        print(
            f"[shipBikeInstances] {shipment.get('order_id')}: "
            f"handed off to {selectedCarrier} — tracking={tracking_id}"
        )
        return {"tracking_id": tracking_id}

    # --- mock of BPA Lab `sendShippedEmail` ---------------------------------
    @worker.task(task_type="sendShippedEmail", exception_handler=on_error)
    async def send_shipped_email(
        shipment: dict[str, Any],
        selectedCarrier: str,
        tracking_id: str,
    ) -> dict[str, Any]:
        print(
            f"[sendShippedEmail] notified customer for order {shipment.get('order_id')}: "
            f"carrier={selectedCarrier} tracking={tracking_id}"
        )
        return {}

    # --- mock of BPA Lab message end event `sendFinishedShipment` -----------
    @worker.task(task_type="sendFinishedShipment", exception_handler=on_error)
    async def send_finished_shipment(
        shipmentOrderCorrelation: str,
        shipment: dict[str, Any],
    ) -> dict[str, Any]:
        print(
            f"[sendFinishedShipment] correlation={shipmentOrderCorrelation} "
            f"order={shipment.get('order_id')} at {datetime.now(timezone.utc).isoformat()}"
        )
        return {}

    print("[worker] Shipment workers running: checkProductInformation · recommend-carrier (AI) · shipBikeInstances · sendShippedEmail · sendFinishedShipment")
    await worker.work()


if __name__ == "__main__":
    asyncio.run(main())
