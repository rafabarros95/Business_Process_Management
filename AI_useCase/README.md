# AI Use Case — AI-Driven Vendor Selection (BPA Lab BPMN, surgical swap)

This folder takes the **real** BPA Lab Purchasing BPMN from
[`bpa_lab_demonstration_factory@miowui/bpa_lab_purchasing_process`](https://github.com/BpaLabTHCologne/bpa_lab_demonstration_factory/tree/miowui/bpa_lab_purchasing_process)
and changes exactly **one** node: the `adjustPurchaseOrder` user task (manual
`chooseVendorForm`) becomes a Service Task of type `recommend-vendor` powered
by AI. Every other element — IDs, flows, gateways, the `confirmSupply` user
task, the message start/end events, data stores — is preserved verbatim from
upstream.

```
                     ┌─ original BPMN ────────────────────────────────────────────┐
msg ─► getPurchaseOrder ─► [adjust Purchase Order: USER TASK chooseVendorForm] ─► confirm Supply ─► storeBikeComponents ─► end
                                          ▼   surgical swap, only this node
                            [adjust Purchase Order: SERVICE TASK recommend-vendor]
```

## Files

```
AI_useCase/
├── bpmn/bpa_lab_purchase_process_ai.bpmn   ← upstream BPMN, one-element swap
├── data/vendors.json                       ← enriched vendor catalogue
├── llm_client.py                           ← Claude API + deterministic fallback
├── ai_worker.py                            ← recommend-vendor + mocks of the BPA Lab Node.js workers
├── deploy_and_run.py                       ← deploys & publishes 3 MsgStartPurchaseOrder messages
└── .env.example                            ← AI_MODE / ANTHROPIC_API_KEY
```

## What stayed identical to upstream

| Element                           | Identity preserved |
|-----------------------------------|--------------------|
| Process ID `BPALabBikeFactoryPurchase` | ✓ |
| `MsgStartEventPurchaseOrder` / `MsgEndEventPurchaseOrder` | ✓ |
| Service tasks `getPurchaseOrder`, `storeBikeComponents`, `sendFinishedPurchaseOrder` | ✓ (Zeebe task types unchanged) |
| User task `confirmSupply` (+ PT1M timer boundary) | ✓ |
| Alt start path: `Event_1ksa721` → `put Message Data` user task → gateway | ✓ |
| Data stores `Vendor`, `Purchase Order`, `Bike Component` | ✓ |
| All sequence flow IDs, gateway IDs, BPMN DI bounds | ✓ |

## What changed (one node)

| Element id            | Before (upstream)                              | After (this folder)                                |
|-----------------------|-----------------------------------------------|----------------------------------------------------|
| `adjustPurchaseOrder` | `<bpmn:userTask>` + `chooseVendorForm`         | `<bpmn:serviceTask>` + `zeebe:taskDefinition type="recommend-vendor"` |

The variable contract is preserved: the AI service task **writes `selectedVendor`**
— the same variable name the original `chooseVendorForm` produced — so the
downstream `storeBikeComponents` task sees no difference between manual choice
and AI choice.

## Worker mocks (for standalone demo)

So the demo runs end-to-end without the upstream Node.js workers and MySQL,
`ai_worker.py` also implements lightweight mocks of:

- `getPurchaseOrder` — builds `vendorList` + `purchaseComponentDTO` from `data/vendors.json`
- `storeBikeComponents` — logs the action
- `sendFinishedPurchaseOrder` — logs the completion message

If you point this BPMN at a live BPA Lab stack instead, just stop the mocks
from registering; only the `recommend-vendor` worker is genuinely new.

## Process Variables — AI contract

`recommend-vendor` reads (set by `getPurchaseOrder` upstream):

| variable                | type                | source                          |
|-------------------------|---------------------|---------------------------------|
| `purchaseComponentDTO`  | `{title, amount}`   | `getPurchaseOrder` output       |
| `vendorCatalogue`       | list of vendor dicts| `getPurchaseOrder` output (added by our mock) |
| `urgency`               | `"normal"`/`"high"` | message variables               |

`recommend-vendor` writes:

| variable                      | type    | description                                                       |
|-------------------------------|---------|-------------------------------------------------------------------|
| `selectedVendor`              | string  | **same name as the original chooseVendorForm output**             |
| `ai_ranked_vendors`           | list    | each `{vendor_name, score, feasible, rationale}`                  |
| `ai_estimated_total_eur`      | float   | unit price × amount for the chosen vendor                         |
| `ai_estimated_lead_time_days` | int     | lead time from the chosen vendor                                  |
| `ai_requires_human_approval`  | bool    | true when order > 1000€, reliability < 0.85, or no feasible vendor|
| `ai_approval_reason`          | string? | populated when approval is required                               |

The `confirmSupply` user task (preserved from upstream) is still the
human-in-the-loop checkpoint — the workshop's "human confirms only exceptions"
principle is realised by reviewing `ai_requires_human_approval` and
`ai_approval_reason` at that step.

## Running the showcase

Prereq: Camunda 8 core stack is up (see [`../README.md`](../README.md)).

```powershell
# Terminal 1 — workers (deterministic mode, no API key needed)
bpm\Scripts\activate
python AI_useCase\ai_worker.py

# Terminal 2 — deploy BPMN + publish 3 MsgStartPurchaseOrder messages
python AI_useCase\deploy_and_run.py
```

Then:

1. **Operate** <http://localhost:8081> (`demo`/`demo`) → process
   `BPALabBikeFactoryPurchase` → three running instances. Inspect variables
   panel to see what the AI returned (`ai_ranked_vendors`, `selectedVendor`, …).
2. **Tasklist** <http://localhost:8082> (`demo`/`demo`) → each instance parks
   at `confirm Supply` (upstream user task). Complete it to release the token;
   the `storeBikeComponents` and end-event log entries should appear in
   Terminal 1.

### Switching to Claude

```powershell
$env:AI_MODE = "claude"
$env:ANTHROPIC_API_KEY = "sk-ant-..."
pip install anthropic
python AI_useCase\ai_worker.py
```

`llm_client.py` pins the JSON output schema in the system prompt, so the BPMN
contract above is preserved regardless of which mode is active. Claude failures
fall back to deterministic scoring so the process never gets stuck.
