"""Deploy the surgically-modified BPA Lab Shipment BPMN and start demo instances.

Starts the process via the `MsgStartShippingOrder` message (the message start
event in the upstream BPMN) so the demo skips the manual `put Message Data`
user task. The three demo cases exercise the three scoring modes:

  1. Normal urgency       → DPD Classic should win (cheap, EU, fits weight)
  2. Express + USA        → FedEx Priority should win, likely flagged for approval
  3. Sustainability mode  → GLS Eco should win (lowest CO2)

The deploy script pre-injects the variables the upstream HTTP connectors
(`Get Coordinates` / `Calculate travel distance`) would normally produce, so
the demo doesn't depend on OpenRouteService being reachable.

Run AFTER `python ai_worker.py` is already polling.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

from pyzeebe import ZeebeClient, create_insecure_channel

BPMN_PATH = Path(__file__).parent / "bpmn" / "bpa_lab_shipment_process_ai.bpmn"
START_MESSAGE = "MsgStartShippingOrder"


DEMO_CASES: list[dict[str, Any]] = [
    {
        "label": "Citybike → DE, 18kg, 5-day normal — AI auto-approves cheap EU carrier",
        "shipment": {
            "order_id": "ORD-1001",
            "destination_country": "DE",
            "destination_city": "Berlin",
            "weight_kg": 18,
            "required_delivery_days": 5,
        },
        "urgency": "normal",
        "sustainability_priority": False,
        # synthetic geocode + distance the upstream HTTP connectors would have produced
        "shipping_geocode": {"latitudeSA": 52.5200, "longitudeSA": 13.4050, "distance": 580.0, "duration": 360.0},
    },
    {
        "label": "Mountainbike → US, 15kg, 2-day express — AI picks express global carrier (DPD infeasible)",
        "shipment": {
            "order_id": "ORD-1002",
            "destination_country": "US",
            "destination_city": "Boston",
            "weight_kg": 15,
            "required_delivery_days": 2,
        },
        "urgency": "express",
        "sustainability_priority": False,
        "shipping_geocode": {"latitudeSA": 42.3601, "longitudeSA": -71.0589, "distance": 6800.0, "duration": 4080.0},
    },
    {
        "label": "Lastenrad → NL, 45kg, sustainability ON — AI picks GLS Eco, flagged on reliability",
        "shipment": {
            "order_id": "ORD-1003",
            "destination_country": "NL",
            "destination_city": "Amsterdam",
            "weight_kg": 45,
            "required_delivery_days": 7,
        },
        "urgency": "normal",
        "sustainability_priority": True,
        "shipping_geocode": {"latitudeSA": 52.3676, "longitudeSA": 4.9041, "distance": 290.0, "duration": 210.0},
    },
]


async def main() -> None:
    channel = create_insecure_channel(grpc_address="localhost:26500")
    client = ZeebeClient(channel)

    deployment = await client.deploy_resource(str(BPMN_PATH))
    print(f"[deploy] {deployment}")

    for case in DEMO_CASES:
        correlation = f"ship-{uuid.uuid4().hex[:8]}"
        variables: dict[str, Any] = {
            "shipmentOrderCorrelation": correlation,
            "shipment": case["shipment"],
            "urgency": case["urgency"],
            "sustainability_priority": case["sustainability_priority"],
            # variables the upstream HTTP connectors normally compute — pre-injected
            # so the OpenRouteService calls aren't a hard dependency for the demo:
            "shippingAddress": f"{case['shipment']['destination_city']}, {case['shipment']['destination_country']}",
            "latitudeWA": 51.023238338791835,
            "longitudeWA": 7.562013168617832,
            **case["shipping_geocode"],
        }
        await client.publish_message(
            name=START_MESSAGE,
            correlation_key=correlation,
            variables=variables,
        )
        print(f"[start] {case['label']} (correlation={correlation})")

    await channel.close()


if __name__ == "__main__":
    asyncio.run(main())
