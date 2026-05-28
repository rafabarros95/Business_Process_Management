"""Deploy the surgically-modified BPA Lab Purchasing BPMN and start demo instances.

Starts the process via the `MsgStartPurchaseOrder` message (the message
start event in the upstream BPMN), so the demo skips the manual `put Message
Data` user task and goes straight through:

  msg → getPurchaseOrder → AI: Recommend Vendor → confirm Supply → storeBikeComponents → end

Run AFTER `python ai_worker.py` is already polling.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

from pyzeebe import ZeebeClient, create_insecure_channel

BPMN_PATH = Path(__file__).parent / "bpmn" / "bpa_lab_purchase_process_ai.bpmn"
START_MESSAGE = "MsgStartPurchaseOrder"


DEMO_CASES = [
    {
        "label": "Routine Citybike order — AI auto-selects cheapest reliable vendor",
        "purchaseBikeComponent": {"title": "Citybike Component Kit", "amount": 5},
        "urgency": "normal",
    },
    {
        "label": "High-value Lastenrad order — AI flags for human approval",
        "purchaseBikeComponent": {"title": "Lastenrad Component Kit", "amount": 10},
        "urgency": "normal",
    },
    {
        "label": "Urgent Mountainbike order — AI picks fastest-lead vendor",
        "purchaseBikeComponent": {"title": "Mountainbike Component Kit", "amount": 4},
        "urgency": "high",
    },
]


async def main() -> None:
    channel = create_insecure_channel(grpc_address="localhost:26500")
    client = ZeebeClient(channel)

    deployment = await client.deploy_resource(str(BPMN_PATH))
    print(f"[deploy] {deployment}")

    for case in DEMO_CASES:
        correlation = f"demo-{uuid.uuid4().hex[:8]}"
        variables: dict[str, Any] = {
            "purchaseOrderCorrelation": correlation,
            "purchaseBikeComponent": case["purchaseBikeComponent"],
            "productionOrderNumber": f"prod-{uuid.uuid4().hex[:6]}",
            "urgency": case["urgency"],
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
