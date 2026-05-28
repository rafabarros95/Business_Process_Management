# AI Use Case 2 — AI-Driven Carrier Selection (BPA Lab Shipment BPMN, surgical swap)

This folder takes the **real** BPA Lab Shipment BPMN from
[`bpa_lab_demonstration_factory@main/bpa_lab_shipment_process`](https://github.com/BpaLabTHCologne/bpa_lab_demonstration_factory/tree/main/bpa_lab_shipment_process)
and changes exactly **one** node: the `UserTask_CheckInformation` user task
(originally a human review with the `output_ShippingInformation` form)
becomes a Service Task of type `recommend-carrier` powered by AI. Every other
element — IDs, flows, gateways, HTTP connector tasks, message events, data
store, the embedded user-task form definitions — is preserved verbatim from
upstream.

This mirrors **[`../AI_useCase/`](../AI_useCase/) (Showcase 1)** which did the
same surgical swap on the Purchasing BPMN's `adjustPurchaseOrder` user task.

```
                     ┌─ original Shipment BPMN ─────────────────────────────────────┐
msg → … → checkProductInformation → [Check information: USER TASK (form)] → shipBikeInstances → … → end
                                              ▼   surgical swap, only this node
                                  [AI: Recommend Carrier: SERVICE TASK recommend-carrier]
```

## Files

```
AI_useCase_2/
├── bpmn/bpa_lab_shipment_process_ai.bpmn   ← upstream BPMN, one-element swap
├── data/carriers.json                       ← carrier catalogue (5 carriers)
├── llm_client.py                            ← Claude API + deterministic fallback
├── ai_worker.py                             ← recommend-carrier + mocks of other Shipment Zeebe tasks
├── deploy_and_run.py                        ← deploys & publishes 3 MsgStartShippingOrder messages
└── .env.example                             ← AI_MODE / ANTHROPIC_API_KEY
```

## What stayed identical to upstream

| Element | Identity preserved |
|---|---|
| Process ID `BPALabBikeFactoryShipment` | ✓ |
| `StartEvent_ShipmentStarted` / `EndEvent_ShipmentCompleted` (message events) | ✓ |
| HTTP connector service tasks `Get Coordinates`, `Calculate travel distance` (`io.camunda:http-json:1`) | ✓ |
| Service tasks `checkProductInformation`, `shipBikeInstances`, `sendShippedEmail`, `sendFinishedShipment` | ✓ |
| `UserTask_CheckShippingInformation` (human input check at start) | ✓ |
| `ManualTask_HandoverProductToCustomer` | ✓ |
| Alt start path: `Event_1fd3vjb` → `Activity_0lgry03` user task → gateway | ✓ |
| Data store `Bike Instance`, all embedded `<zeebe:userTaskForm>` definitions | ✓ |
| All sequence flow IDs, gateway IDs, BPMN DI bounds | ✓ |

## What changed

**Primary swap (one node)** — the AI insertion point:

| Element id | Before (upstream) | After (this folder) |
|---|---|---|
| `UserTask_CheckInformation` | `<bpmn:userTask>` + `output_ShippingInformation` form | `<bpmn:serviceTask>` + `zeebe:taskDefinition type="recommend-carrier"` |

**Two HTTP-connector tasks → regular Zeebe service tasks** so the demo runs
without depending on OpenRouteService (their hardcoded API key is shared and
gets rate-limited / revoked in practice — the upstream tasks tend to leave
process instances stuck at "Calculate travel distance" with HTTP incidents):

| Element id | Before (upstream) | After (this folder) |
|---|---|---|
| `ServiceTask_GetCoordinatesOfShippingAdress` | `io.camunda:http-json:1` calling OpenRouteService `/geocode/search` | `zeebe:taskDefinition type="getShippingCoordinates"` — mocked in `ai_worker.py` |
| `ServiceTask_CalculateTravelDistance` | `io.camunda:http-json:1` calling OpenRouteService `/v2/directions/driving-car` | `zeebe:taskDefinition type="calculateTravelDistance"` — mocked in `ai_worker.py` |

The mocked workers echo back the `latitudeSA` / `longitudeSA` / `distance` /
`duration` values that the deploy script pre-injects, so the BPMN diagram is
unchanged (same task names, same positions) but the calls are local instead
of external. To plug real geocoding/routing back in, swap those two task
handlers with calls to your geocoder of choice.

Plus one minor demo enabler (same as Showcase 1): added `<zeebe:subscription correlationKey="=shipmentOrderCorrelation"/>` to `Message_2ocrkme` so the demo can publish-message-start the process.

## Side-by-side with Showcase 1

| Aspect | Showcase 1 (Purchasing) | Showcase 2 (Shipment) |
|---|---|---|
| BPA Lab process | `bpa_lab_purchasing_process` | `bpa_lab_shipment_process` |
| Swapped user task id | `adjustPurchaseOrder` (`chooseVendorForm`) | `UserTask_CheckInformation` (`output_ShippingInformation`) |
| New service task type | `recommend-vendor` | `recommend-carrier` |
| Output variable preserved | `selectedVendor` | `selectedCarrier` |
| Downstream consumer | `storeBikeComponents` | `shipBikeInstances` |
| Approval triggers | value > 1000€ · reliability < 0.85 · no feasible vendor | cost > 500€ · on-time rate < 0.90 · no feasible carrier |

## Worker mocks (for standalone demo)

So the demo runs end-to-end without the upstream Node.js workers and MySQL,
`ai_worker.py` also implements lightweight mocks of:

- `getShippingCoordinates` — echoes pre-injected geocode (replaces upstream HTTP connector)
- `calculateTravelDistance` — echoes pre-injected distance/duration (replaces upstream HTTP connector)
- `checkProductInformation` — validates basic shipment fields
- `shipBikeInstances` — generates a tracking ID
- `sendShippedEmail` — logs the customer notification
- `sendFinishedShipment` — logs the completion message

If you point this BPMN at a live BPA Lab stack instead, just stop the mocks
from registering; only the `recommend-carrier` worker is genuinely new.

## Process Variables — AI contract

`recommend-carrier` reads:

| variable | type | example |
|---|---|---|
| `shipment` | object | `{order_id, destination_country, weight_kg, required_delivery_days}` |
| `urgency` | string | `"normal"` / `"express"` |
| `sustainability_priority` | bool | `false` (optional) |

`recommend-carrier` writes:

| variable | type | description |
|---|---|---|
| `selectedCarrier` | string | **picks up the role of the original form's output** |
| `ai_ranked_carriers` | list | each `{carrier_name, score, feasible, rationale}` |
| `ai_estimated_cost_eur` | float | `base_price + per_kg × weight_kg` |
| `ai_estimated_transit_days` | int | from the chosen carrier |
| `ai_requires_human_approval` | bool | cost > 500€, on-time < 0.90, or no feasible carrier |
| `ai_approval_reason` | string? | populated when approval is required |

Scoring weights (chosen at runtime by `urgency` + `sustainability_priority`):

| Mode | cost | transit | reliability | CO₂ |
|---|---|---|---|---|
| normal | 0.5 | 0.2 | 0.3 | — |
| express | 0.1 | 0.6 | 0.3 | — |
| sustainability ON | 0.3 | 0.2 | 0.3 | 0.2 |

## Demo cases & expected outcomes

| # | Order | Mode | Expected AI choice |
|---|---|---|---|
| 1 | Citybike → DE, 18 kg, 5-day | normal | **DPD Classic** — auto-approves (cheap, EU, fits weight) |
| 2 | Mountainbike → US, 15 kg, 2-day | express | **DHL Express** — DPD Classic shown but `feasible: false` (US not served) |
| 3 | Lastenrad → NL, 45 kg | sustainability ON | **GLS Eco** — flagged (on-time rate 0.89 < 0.90) |

## Running the showcase

Prereq: Camunda 8 core stack is up (see [`../README.md`](../README.md)).

```powershell
# Terminal 1 — workers (deterministic mode, no API key needed)
bpm\Scripts\activate
python AI_useCase_2\ai_worker.py

# Terminal 2 — deploy BPMN + publish 3 MsgStartShippingOrder messages
python AI_useCase_2\deploy_and_run.py
```

Then:

1. **Operate** <http://localhost:8081> (`demo`/`demo`) → process
   `BPALabBikeFactoryShipment` → three running instances. Click each to see
   the variables panel — `selectedCarrier`, `ai_ranked_carriers`,
   `ai_estimated_cost_eur`, `ai_requires_human_approval`, etc.
2. **Tasklist** <http://localhost:8082> (`demo`/`demo`) → the upstream
   BPMN's `UserTask_CheckShippingInformation` (the human check that runs
   *before* the AI task) will appear here — complete it to release the token
   into the AI step. After the AI step, the `ManualTask_HandoverProductToCustomer`
   at the very end also requires a click to complete the instance.

### Switching to Claude

```powershell
$env:AI_MODE = "claude"
$env:ANTHROPIC_API_KEY = "sk-ant-..."
pip install anthropic
python AI_useCase_2\ai_worker.py
```

The system prompt pins the JSON output schema; failures fall back to
deterministic scoring so the process never gets stuck.
