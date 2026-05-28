# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Camunda 8 Business Process Management (BPM) research project on inserting AI into a bicycle-factory workflow. The repo is laid out as three working tracks:

1. **Root (`worker.py` + `loan-application.bpmn`)** — minimal loan-application toy that establishes the Camunda 8 + `pyzeebe` integration pattern.
2. **[AI_useCase/](AI_useCase/) — Showcase 1: AI-driven vendor selection** in the BPA Lab Purchasing process. Surgical swap of the `adjustPurchaseOrder` user task → service task `recommend-vendor`.
3. **[AI_useCase_2/](AI_useCase_2/) — Showcase 2: AI-driven carrier selection** in the BPA Lab Shipment process. Surgical swap of the `UserTask_CheckInformation` user task → service task `recommend-carrier`.

The two showcases each take the **real** upstream BPMN from [BpaLabTHCologne/bpa_lab_demonstration_factory](https://github.com/BpaLabTHCologne/bpa_lab_demonstration_factory) and change **exactly one node**. Every other element (IDs, gateways, message events, data stores, forms, BPMN DI bounds) is preserved verbatim so the swap is auditable against upstream. See each folder's `README.md` for the full diff table.

Background slides: [workshop/BPM_Workshop_BPMS_Camunda_AI.pdf](workshop/BPM_Workshop_BPMS_Camunda_AI.pdf).

## Prerequisites

- Docker Desktop running (Camunda stack must be up before running any Python code)
- Python 3.12 (enforced via `.python-version`)
- `uv` package manager (preferred over pip)
- Optional for Claude mode in the showcases: `ANTHROPIC_API_KEY` + `pip install anthropic`

## Running Camunda 8 Locally

```powershell
# Start the core stack (Zeebe + Operate + Tasklist + Connectors)
cd C:\camunda8
docker compose -f docker-compose-core.yaml up -d

# Verify all containers are healthy
docker compose -f docker-compose-core.yaml ps

# Stop (keep data)
docker compose -f docker-compose-core.yaml stop

# Stop and wipe all data
docker compose -f docker-compose-core.yaml down -v
```

Services once running:

| Service     | URL                    | Credentials |
|-------------|------------------------|-------------|
| Operate     | http://localhost:8081  | demo / demo |
| Tasklist    | http://localhost:8082  | demo / demo |
| Zeebe gRPC  | localhost:26500        | —           |
| Connectors  | localhost:8085         | —           |

The Connectors runtime is only used by Showcase 2 (the upstream Shipment BPMN has two `io.camunda:http-json:1` tasks). Showcase 1 and the root demo work without it.

## Python Environment

```powershell
# Activate the virtualenv
bpm\Scripts\activate   # Windows

# Install dependencies (root demo)
uv pip install pyzeebe

# For the AI showcases in Claude mode
uv pip install anthropic
```

## Running the Project

### Root demo — loan application

Start the worker first; it must be polling before a process instance is created.

```powershell
# Terminal 1 — start the worker
python worker.py

# Terminal 2 — deploy the BPMN and start a process instance
python deploy_and_run.py
```

### Showcase 1 — Purchasing (AI vendor selection)

```powershell
# Terminal 1 — workers (deterministic mode, no API key needed)
python AI_useCase\ai_worker.py

# Terminal 2 — deploy BPMN + publish 3 MsgStartPurchaseOrder messages
python AI_useCase\deploy_and_run.py
```

Each instance parks at the upstream `confirm Supply` user task in Tasklist — complete it to release the token through `storeBikeComponents` to the end event.

### Showcase 2 — Shipment (AI carrier selection)

```powershell
# Terminal 1 — workers
python AI_useCase_2\ai_worker.py

# Terminal 2 — deploy BPMN + publish 3 MsgStartShippingOrder messages
python AI_useCase_2\deploy_and_run.py
```

The upstream `UserTask_CheckShippingInformation` (human input check **before** the AI step) and the final `ManualTask_HandoverProductToCustomer` both appear in Tasklist and must be completed by hand.

### Switching either showcase to Claude

```powershell
$env:AI_MODE = "claude"
$env:ANTHROPIC_API_KEY = "sk-ant-..."
python AI_useCase\ai_worker.py        # or AI_useCase_2\ai_worker.py
```

`llm_client.py` pins the JSON output schema in the system prompt and falls back to deterministic scoring on any Claude failure, so the BPMN variable contract is preserved either way and the process never gets stuck. Default model: `claude-sonnet-4-6`.

## Architecture

All three tracks share the same two-process Camunda 8 pattern: a `deploy_and_run.py` deploys the BPMN and creates instances; an `ai_worker.py` / `worker.py` polls Zeebe over insecure gRPC at `localhost:26500` for the task types declared in the BPMN.

### Root — loan application

- [deploy_and_run.py](deploy_and_run.py) deploys [loan-application.bpmn](loan-application.bpmn) and starts one instance with `applicant_name`, `loan_amount`, `credit_score`.
- [worker.py](worker.py) handles task type `score-applicant`: approves if `credit_score >= 700` and `loan_amount <= 10000`, returns `approved` (bool) and `decision_reason`.

### Showcase 1 — `AI_useCase/` (Purchasing)

- [AI_useCase/bpmn/bpa_lab_purchase_process_ai.bpmn](AI_useCase/bpmn/bpa_lab_purchase_process_ai.bpmn) — upstream BPMN with one node changed:
  `adjustPurchaseOrder` user task → service task `recommend-vendor`.
- [AI_useCase/ai_worker.py](AI_useCase/ai_worker.py) registers four workers: the AI task `recommend-vendor` plus mocks of the upstream Node.js workers `getPurchaseOrder`, `storeBikeComponents`, `sendFinishedPurchaseOrder` so the demo runs without the upstream TypeScript stack or MySQL.
- [AI_useCase/llm_client.py](AI_useCase/llm_client.py) — Claude API client + deterministic scoring fallback (weights: price 0.4 / lead time 0.3 / reliability 0.3).
- [AI_useCase/data/vendors.json](AI_useCase/data/vendors.json) — vendor catalogue (price, lead time, in-stock, reliability per component).
- [AI_useCase/deploy_and_run.py](AI_useCase/deploy_and_run.py) deploys the BPMN and publishes three `MsgStartPurchaseOrder` messages (Citybike routine, Lastenrad high-value, Mountainbike urgent).

**Variable contract — `recommend-vendor`**
- Reads: `purchaseComponentDTO {title, amount}`, `vendorCatalogue`, `urgency`.
- Writes: `selectedVendor` (same name as the original `chooseVendorForm` output, so `storeBikeComponents` sees no difference), plus `ai_ranked_vendors`, `ai_estimated_total_eur`, `ai_estimated_lead_time_days`, `ai_requires_human_approval`, `ai_approval_reason`.
- `ai_requires_human_approval = true` when order > 1000 €, reliability < 0.85, or no vendor is feasible. The preserved `confirmSupply` user task is the human-in-the-loop exception checkpoint.

### Showcase 2 — `AI_useCase_2/` (Shipment)

- [AI_useCase_2/bpmn/bpa_lab_shipment_process_ai.bpmn](AI_useCase_2/bpmn/bpa_lab_shipment_process_ai.bpmn) — upstream BPMN with one primary node changed:
  `UserTask_CheckInformation` user task → service task `recommend-carrier`. Two upstream `io.camunda:http-json:1` connector tasks (`Get Coordinates`, `Calculate travel distance`) were also retyped to local Zeebe service tasks (`getShippingCoordinates`, `calculateTravelDistance`) so the demo doesn't depend on a shared OpenRouteService key that gets rate-limited in practice. A `correlationKey` subscription was added to `Message_2ocrkme` to allow message-start.
- [AI_useCase_2/ai_worker.py](AI_useCase_2/ai_worker.py) registers `recommend-carrier` plus mocks of `checkProductInformation`, `shipBikeInstances`, `sendShippedEmail`, `sendFinishedShipment`, `getShippingCoordinates`, `calculateTravelDistance`.
- [AI_useCase_2/llm_client.py](AI_useCase_2/llm_client.py) — Claude + deterministic fallback. Scoring weights depend on `urgency` / `sustainability_priority`:

  | Mode               | cost | transit | reliability | CO₂ |
  |--------------------|------|---------|-------------|-----|
  | normal             | 0.5  | 0.2     | 0.3         | —   |
  | express            | 0.1  | 0.6     | 0.3         | —   |
  | sustainability ON  | 0.3  | 0.2     | 0.3         | 0.2 |

- [AI_useCase_2/data/carriers.json](AI_useCase_2/data/carriers.json) — five carriers (DPD Classic, DHL Express, GLS Eco, …).
- [AI_useCase_2/deploy_and_run.py](AI_useCase_2/deploy_and_run.py) deploys the BPMN and publishes three `MsgStartShippingOrder` messages, pre-injecting `latitudeSA` / `longitudeSA` / `distance` / `duration` so the demo is independent of the geocoding/routing connectors.

**Variable contract — `recommend-carrier`**
- Reads: `shipment {order_id, destination_country, weight_kg, required_delivery_days}`, `urgency`, optional `sustainability_priority`.
- Writes: `selectedCarrier` (takes the role of the original `output_ShippingInformation` form output) plus `ai_ranked_carriers`, `ai_estimated_cost_eur`, `ai_estimated_transit_days`, `ai_requires_human_approval`, `ai_approval_reason`.
- `ai_requires_human_approval = true` when cost > 500 €, on-time rate < 0.90, or no carrier is feasible.

### Side-by-side

| Aspect                  | Showcase 1 (Purchasing)                       | Showcase 2 (Shipment)                                  |
|-------------------------|-----------------------------------------------|--------------------------------------------------------|
| Upstream BPA Lab process| `bpa_lab_purchasing_process` (`miowui` branch)| `bpa_lab_shipment_process` (`main` branch)             |
| Process ID              | `BPALabBikeFactoryPurchase`                   | `BPALabBikeFactoryShipment`                            |
| Swapped user task id    | `adjustPurchaseOrder` (`chooseVendorForm`)    | `UserTask_CheckInformation` (`output_ShippingInformation`) |
| New service task type   | `recommend-vendor`                            | `recommend-carrier`                                    |
| Output variable preserved| `selectedVendor`                             | `selectedCarrier`                                      |
| Downstream consumer     | `storeBikeComponents`                         | `shipBikeInstances`                                    |
| Start message           | `MsgStartPurchaseOrder`                       | `MsgStartShippingOrder`                                |
| Approval triggers       | > 1000 € · reliability < 0.85 · none feasible | > 500 € · on-time < 0.90 · none feasible               |

### When editing a BPMN

The Zeebe task type strings are the contract between BPMN and worker. If you rename `recommend-vendor`, `recommend-carrier`, or any of the mocked task types, the worker registrations in the matching `ai_worker.py` must change in lockstep, otherwise jobs go unhandled and the process stalls in Operate. Edit BPMN files in Camunda Desktop Modeler.

The `workers/` and `applications/` directories at the repo root are placeholders kept for future expansion.

## Key Dependencies

- `pyzeebe >= 4.7.x` — supports Camunda/Zeebe 8.5–8.8. All Zeebe communication is over gRPC to `localhost:26500` (insecure, no TLS — correct for local dev).
- `anthropic` — only needed when running either showcase with `AI_MODE=claude`. Default model: `claude-sonnet-4-6`.
