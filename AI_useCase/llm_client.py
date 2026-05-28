"""LLM client for vendor recommendation.

Two modes:
  - "claude":       calls Anthropic's Claude API (requires `anthropic` package and
                    ANTHROPIC_API_KEY env var).
  - "deterministic": rule-based scoring, no API needed. Default fallback so the
                    showcase runs out of the box even without an API key.

Both modes return the same structured shape so the BPMN worker doesn't care
which one produced the recommendation.
"""
from __future__ import annotations

import json
import os
from typing import Any

CLAUDE_MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are a procurement decision-support assistant inside a Camunda 8
purchasing workflow for a bicycle factory. You score and rank vendors for a single
component purchase order using three weighted criteria:

  - price       (lower is better)        weight 0.4
  - lead time   (shorter is better)      weight 0.3
  - reliability (higher is better;       weight 0.3
                 combines on_time_delivery_rate and 1 - defect_rate)

Constraints:
  - Only consider vendors whose `components` dict contains the requested component.
  - If a vendor's in_stock is below the requested amount, mark it as `feasible: false`
    and exclude it from the recommendation (but still return it in ranked_vendors).
  - `requires_human_approval` MUST be true when:
      * order_value_eur > 1000, OR
      * the recommended vendor's reliability_score < 0.85, OR
      * no vendor can fully fulfil the requested amount.

Respond with ONLY a JSON object, no prose, with this exact shape:
{
  "ranked_vendors": [
    {"vendor_name": str, "score": float, "feasible": bool, "rationale": str}
  ],
  "recommended_vendor": str,
  "estimated_total_eur": float,
  "estimated_lead_time_days": int,
  "requires_human_approval": bool,
  "approval_reason": str | null
}
"""


def _build_user_prompt(component: str, amount: int, urgency: str, vendors: list[dict[str, Any]]) -> str:
    return (
        f"Component requested: {component}\n"
        f"Amount: {amount}\n"
        f"Urgency: {urgency}\n\n"
        f"Vendor catalogue:\n{json.dumps(vendors, indent=2)}\n\n"
        "Return only the JSON object."
    )


def recommend_with_claude(component: str, amount: int, urgency: str, vendors: list[dict[str, Any]]) -> dict[str, Any]:
    from anthropic import Anthropic

    client = Anthropic()
    msg = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_user_prompt(component, amount, urgency, vendors)}],
    )
    text = msg.content[0].text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if text.startswith("json") else text
    return json.loads(text)


def recommend_deterministic(component: str, amount: int, urgency: str, vendors: list[dict[str, Any]]) -> dict[str, Any]:
    """Multi-criteria scoring, same shape as the LLM output."""
    eligible = [v for v in vendors if component in v.get("components", {})]
    if not eligible:
        return {
            "ranked_vendors": [],
            "recommended_vendor": "",
            "estimated_total_eur": 0.0,
            "estimated_lead_time_days": 0,
            "requires_human_approval": True,
            "approval_reason": f"No vendor offers '{component}'",
        }

    prices = [v["components"][component]["price"] for v in eligible]
    leads = [v["components"][component]["avg_lead_time_days"] for v in eligible]
    p_min, p_max = min(prices), max(prices)
    l_min, l_max = min(leads), max(leads)
    w_price, w_lead, w_rel = (0.2, 0.5, 0.3) if urgency == "high" else (0.4, 0.3, 0.3)

    def norm(value: float, lo: float, hi: float, lower_is_better: bool) -> float:
        if hi == lo:
            return 1.0
        n = (value - lo) / (hi - lo)
        return 1.0 - n if lower_is_better else n

    ranked = []
    for v in eligible:
        c = v["components"][component]
        rel = 0.5 * v["on_time_delivery_rate"] + 0.5 * (1.0 - v["defect_rate"])
        score = (
            w_price * norm(c["price"], p_min, p_max, lower_is_better=True)
            + w_lead * norm(c["avg_lead_time_days"], l_min, l_max, lower_is_better=True)
            + w_rel * rel
        )
        feasible = c["in_stock"] >= amount
        ranked.append({
            "vendor_name": v["vendor_name"],
            "score": round(score, 3),
            "feasible": feasible,
            "rationale": (
                f"price {c['price']}€, lead {c['avg_lead_time_days']}d, "
                f"reliability {round(rel, 2)}, stock {c['in_stock']}"
            ),
        })

    ranked.sort(key=lambda r: (not r["feasible"], -r["score"]))
    top = next((r for r in ranked if r["feasible"]), ranked[0])
    top_vendor = next(v for v in eligible if v["vendor_name"] == top["vendor_name"])
    component_data = top_vendor["components"][component]
    total = component_data["price"] * amount

    requires_approval = (
        total > 1000.0
        or top_vendor["reliability_score"] < 0.85
        or not top["feasible"]
    )
    reason = None
    if requires_approval:
        reasons = []
        if total > 1000.0:
            reasons.append(f"order value {total:.2f}€ > 1000€")
        if top_vendor["reliability_score"] < 0.85:
            reasons.append(f"reliability {top_vendor['reliability_score']} < 0.85")
        if not top["feasible"]:
            reasons.append("insufficient stock at recommended vendor")
        reason = "; ".join(reasons)

    return {
        "ranked_vendors": ranked,
        "recommended_vendor": top["vendor_name"],
        "estimated_total_eur": round(total, 2),
        "estimated_lead_time_days": component_data["avg_lead_time_days"],
        "requires_human_approval": requires_approval,
        "approval_reason": reason,
    }


def recommend(component: str, amount: int, urgency: str, vendors: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick mode by env var: AI_MODE=claude uses the Claude API; anything else is deterministic."""
    mode = os.environ.get("AI_MODE", "deterministic").lower()
    if mode == "claude" and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return recommend_with_claude(component, amount, urgency, vendors)
        except Exception as exc:
            print(f"[llm_client] Claude call failed ({exc}); falling back to deterministic.")
    return recommend_deterministic(component, amount, urgency, vendors)
