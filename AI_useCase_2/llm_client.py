"""LLM client for carrier recommendation (Showcase 2 — Shipment).

Same dual-mode pattern as Showcase 1:
  - "claude":       calls Anthropic Claude (needs `anthropic` + ANTHROPIC_API_KEY).
  - "deterministic": rule-based scoring; default, runs out of the box.
"""
from __future__ import annotations

import json
import os
from typing import Any

CLAUDE_MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are a logistics decision-support assistant inside a Camunda 8
shipment workflow for a bicycle factory. You score and rank carriers for ONE
outbound shipment using these weighted criteria:

  - cost        (lower is better)
  - transit     (shorter is better)
  - reliability (higher is better; uses on_time_delivery_rate)
  - co2         (lower is better; only counts when sustainability_priority=true)

Weights:
  - normal urgency:   cost 0.5  transit 0.2  reliability 0.3
  - express urgency:  cost 0.1  transit 0.6  reliability 0.3
  - sustainability:   cost 0.3  transit 0.2  reliability 0.3  co2 0.2 (overrides above)

Feasibility rules (a carrier is `feasible: false` if any of these apply):
  - shipment.weight_kg > carrier.max_weight_kg
  - shipment.destination_country not in carrier.countries_served
  - carrier.transit_days > shipment.required_delivery_days

Approval rule — `requires_human_approval` MUST be true when:
  - estimated_cost_eur > 500, OR
  - no carrier is feasible, OR
  - the recommended carrier's on_time_delivery_rate < 0.90

Cost formula: estimated_cost_eur = base_price_eur + per_kg_price_eur * weight_kg.

Respond with ONLY a JSON object (no prose, no markdown fences) with this exact shape:
{
  "ranked_carriers": [
    {"carrier_name": str, "score": float, "feasible": bool, "rationale": str}
  ],
  "recommended_carrier": str,
  "estimated_cost_eur": float,
  "estimated_transit_days": int,
  "requires_human_approval": bool,
  "approval_reason": str | null
}
"""


def _build_user_prompt(shipment: dict[str, Any], urgency: str, sustainability: bool, carriers: list[dict[str, Any]]) -> str:
    return (
        f"Shipment: {json.dumps(shipment)}\n"
        f"Urgency: {urgency}\n"
        f"Sustainability priority: {sustainability}\n\n"
        f"Carrier catalogue:\n{json.dumps(carriers, indent=2)}\n\n"
        "Return only the JSON object."
    )


def recommend_with_claude(
    shipment: dict[str, Any],
    urgency: str,
    sustainability: bool,
    carriers: list[dict[str, Any]],
) -> dict[str, Any]:
    from anthropic import Anthropic

    client = Anthropic()
    msg = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_user_prompt(shipment, urgency, sustainability, carriers)}],
    )
    text = msg.content[0].text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if text.startswith("json") else text
    return json.loads(text)


def recommend_deterministic(
    shipment: dict[str, Any],
    urgency: str,
    sustainability: bool,
    carriers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Multi-criteria scoring; same output shape as the LLM path."""
    weight_kg = float(shipment["weight_kg"])
    destination = shipment["destination_country"]
    required_days = int(shipment.get("required_delivery_days", 99))

    feasibility: list[tuple[dict[str, Any], bool, str]] = []
    for c in carriers:
        reasons: list[str] = []
        if weight_kg > c["max_weight_kg"]:
            reasons.append(f"weight {weight_kg}kg > max {c['max_weight_kg']}kg")
        if destination not in c["countries_served"]:
            reasons.append(f"destination {destination} not served")
        if c["transit_days"] > required_days:
            reasons.append(f"transit {c['transit_days']}d > required {required_days}d")
        feasibility.append((c, len(reasons) == 0, "; ".join(reasons)))

    if sustainability:
        w_cost, w_transit, w_rel, w_co2 = 0.3, 0.2, 0.3, 0.2
    elif urgency == "express":
        w_cost, w_transit, w_rel, w_co2 = 0.1, 0.6, 0.3, 0.0
    else:
        w_cost, w_transit, w_rel, w_co2 = 0.5, 0.2, 0.3, 0.0

    costs = [c["base_price_eur"] + c["per_kg_price_eur"] * weight_kg for c in carriers]
    transits = [c["transit_days"] for c in carriers]
    co2s = [c["co2_per_km_g"] for c in carriers]
    c_min, c_max = min(costs), max(costs)
    t_min, t_max = min(transits), max(transits)
    co_min, co_max = min(co2s), max(co2s)

    def norm(value: float, lo: float, hi: float, lower_is_better: bool) -> float:
        if hi == lo:
            return 1.0
        n = (value - lo) / (hi - lo)
        return 1.0 - n if lower_is_better else n

    ranked: list[dict[str, Any]] = []
    for c, feasible, infeasibility in feasibility:
        cost = c["base_price_eur"] + c["per_kg_price_eur"] * weight_kg
        score = (
            w_cost * norm(cost, c_min, c_max, lower_is_better=True)
            + w_transit * norm(c["transit_days"], t_min, t_max, lower_is_better=True)
            + w_rel * c["on_time_delivery_rate"]
            + w_co2 * norm(c["co2_per_km_g"], co_min, co_max, lower_is_better=True)
        )
        rationale = (
            f"cost {round(cost, 2)}€, transit {c['transit_days']}d, "
            f"on-time {c['on_time_delivery_rate']}, co2 {c['co2_per_km_g']}g/km"
        )
        if not feasible:
            rationale = f"INFEASIBLE — {infeasibility}; would be {rationale}"
        ranked.append({
            "carrier_name": c["carrier_name"],
            "score": round(score, 3),
            "feasible": feasible,
            "rationale": rationale,
        })

    ranked.sort(key=lambda r: (not r["feasible"], -r["score"]))
    feasible_top = next((r for r in ranked if r["feasible"]), None)
    if feasible_top is None:
        return {
            "ranked_carriers": ranked,
            "recommended_carrier": "",
            "estimated_cost_eur": 0.0,
            "estimated_transit_days": 0,
            "requires_human_approval": True,
            "approval_reason": "no carrier is feasible for this shipment",
        }

    top_carrier = next(c for c in carriers if c["carrier_name"] == feasible_top["carrier_name"])
    cost = top_carrier["base_price_eur"] + top_carrier["per_kg_price_eur"] * weight_kg

    reasons: list[str] = []
    if cost > 500.0:
        reasons.append(f"cost {round(cost, 2)}€ > 500€")
    if top_carrier["on_time_delivery_rate"] < 0.90:
        reasons.append(f"on-time rate {top_carrier['on_time_delivery_rate']} < 0.90")

    return {
        "ranked_carriers": ranked,
        "recommended_carrier": top_carrier["carrier_name"],
        "estimated_cost_eur": round(cost, 2),
        "estimated_transit_days": int(top_carrier["transit_days"]),
        "requires_human_approval": bool(reasons),
        "approval_reason": "; ".join(reasons) if reasons else None,
    }


def recommend(
    shipment: dict[str, Any],
    urgency: str,
    sustainability: bool,
    carriers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Pick mode by env var: AI_MODE=claude uses Claude API; anything else is deterministic."""
    mode = os.environ.get("AI_MODE", "deterministic").lower()
    if mode == "claude" and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return recommend_with_claude(shipment, urgency, sustainability, carriers)
        except Exception as exc:
            print(f"[llm_client] Claude call failed ({exc}); falling back to deterministic.")
    return recommend_deterministic(shipment, urgency, sustainability, carriers)
