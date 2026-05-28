"""Worker set for the BPA Lab Purchasing process with AI-driven vendor selection.

Surgical swap in `bpmn/bpa_lab_purchase_process_ai.bpmn`:
the original `adjustPurchaseOrder` USER TASK (manual `chooseVendorForm`) is
replaced by a SERVICE TASK with Zeebe type `recommend-vendor`. Every other
node, ID, gateway and message flow is preserved from the upstream BPMN
(`miowui` branch of BpaLabTHCologne/bpa_lab_demonstration_factory).

This file also stands in for the BPA Lab Node.js workers
(`getPurchaseOrder`, `storeBikeComponents`, `sendFinishedPurchaseOrder`) so
the demo runs end-to-end inside this Python project, without the upstream
TypeScript stack or MySQL. The mocks intentionally mirror the variable
contract documented in the upstream `purchaseprocessapp.ts`.
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

VENDOR_DATA_PATH = Path(__file__).parent / "data" / "vendors.json"

Vendor = dict[str, Any]
VendorListEntry = dict[str, str]


def _load_vendor_catalogue() -> list[Vendor]:
    with VENDOR_DATA_PATH.open(encoding="utf-8") as f:
        return json.load(f)["vendors"]


def _build_vendor_list_for(component: str, catalogue: list[Vendor]) -> list[VendorListEntry]:
    """Mirrors the upstream {label, value} shape consumed by the original chooseVendorForm."""
    entries: list[VendorListEntry] = []
    for v in catalogue:
        c = v["components"].get(component)
        if not c:
            continue
        entries.append({
            "label": f"{v['vendor_name']} ({v['contact']}) — {c['price']}€",
            "value": v["vendor_name"],
        })
    return entries


async def on_error(exception: Exception, job: Job, job_controller: JobController) -> None:
    print(f"[worker] Job {job.type} failed: {exception}")
    await job_controller.set_error_status(job, str(exception))


async def main() -> None:
    channel = create_insecure_channel(grpc_address="localhost:26500")
    worker = ZeebeWorker(channel)

    # --- mock of BPA Lab `getPurchaseOrder` --------------------------------
    @worker.task(task_type="getPurchaseOrder", exception_handler=on_error)
    async def get_purchase_order(purchaseBikeComponent: dict[str, Any]) -> dict[str, Any]:
        catalogue = _load_vendor_catalogue()
        component = purchaseBikeComponent["title"]
        amount = int(purchaseBikeComponent["amount"])
        vendor_list = _build_vendor_list_for(component, catalogue)
        purchase_order_number = f"PO-{uuid.uuid4().hex[:8].upper()}"
        print(f"[getPurchaseOrder] {component} x{amount} → {len(vendor_list)} vendors, {purchase_order_number}")
        return {
            "vendorList": vendor_list,
            "purchaseOrderNumber": purchase_order_number,
            "purchaseComponentDTO": {"title": component, "amount": amount},
            "vendorCatalogue": catalogue,
        }

    # --- AI replacement for the original `adjustPurchaseOrder` user task ----
    @worker.task(task_type="recommend-vendor", exception_handler=on_error)
    async def recommend_vendor(
        purchaseComponentDTO: dict[str, Any],
        vendorCatalogue: list[Vendor],
        urgency: str = "normal",
    ) -> dict[str, Any]:
        component = purchaseComponentDTO["title"]
        amount = int(purchaseComponentDTO["amount"])
        result = recommend(component=component, amount=amount, urgency=urgency, vendors=vendorCatalogue)
        print(
            f"[recommend-vendor] {component} x{amount} (urgency={urgency}) → "
            f"selectedVendor='{result['recommended_vendor']}' | "
            f"total={result['estimated_total_eur']}€ | "
            f"needs_approval={result['requires_human_approval']}"
        )
        # `selectedVendor` is the same variable name the original chooseVendorForm
        # produced, so the downstream `storeBikeComponents` task sees no difference.
        return {
            "selectedVendor": result["recommended_vendor"],
            "ai_ranked_vendors": result["ranked_vendors"],
            "ai_estimated_total_eur": result["estimated_total_eur"],
            "ai_estimated_lead_time_days": result["estimated_lead_time_days"],
            "ai_requires_human_approval": result["requires_human_approval"],
            "ai_approval_reason": result["approval_reason"],
        }

    # --- mock of BPA Lab `storeBikeComponents` ------------------------------
    @worker.task(task_type="storeBikeComponents", exception_handler=on_error)
    async def store_bike_components(
        purchaseComponentDTO: dict[str, Any],
        selectedVendor: str,
        purchaseOrderNumber: str,
    ) -> dict[str, Any]:
        print(
            f"[storeBikeComponents] {purchaseOrderNumber}: "
            f"{purchaseComponentDTO['amount']} x {purchaseComponentDTO['title']} "
            f"from {selectedVendor} — stock updated"
        )
        return {}

    # --- mock of BPA Lab message end event `sendFinishedPurchaseOrder` ------
    @worker.task(task_type="sendFinishedPurchaseOrder", exception_handler=on_error)
    async def send_finished_purchase_order(
        purchaseOrderCorrelation: str,
        purchaseComponentDTO: dict[str, Any],
    ) -> dict[str, Any]:
        print(
            f"[sendFinishedPurchaseOrder] correlation={purchaseOrderCorrelation} "
            f"finished={purchaseComponentDTO} at {datetime.now(timezone.utc).isoformat()}"
        )
        return {}

    print("[worker] Purchasing workers running: getPurchaseOrder · recommend-vendor (AI) · storeBikeComponents · sendFinishedPurchaseOrder")
    await worker.work()


if __name__ == "__main__":
    asyncio.run(main())
