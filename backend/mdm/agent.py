"""Intent Interpretation Agent.

Dual-path:
- LIVE mode: Vertex AI Gemini via google-genai SDK (when a real GCP
  service-account JSON is present).
- PREVIEW mode: Emergent Universal LLM key (Gemini 3 Flash) so the demo
  always works.

Either way, falls back to a deterministic rule-based summary if the LLM
call itself errors.
"""
import json
import os
import logging
from typing import Any, Dict

from emergentintegrations.llm.chat import LlmChat, UserMessage

from mdm.gcp_client import GCPUnavailable, get_gcp

logger = logging.getLogger("searce-mdm.agent")

SYSTEM_PROMPT = (
    "You are the Searce MDM Intent Interpreter. Given a user's matching "
    "and survivorship configuration, produce a JSON object with keys: "
    "summary (1-2 short paragraphs in plain English explaining what the "
    "BigQuery pipeline will do), survivorship_breakdown (array of "
    "{attribute, interpreted_rule}), and confidence "
    "('high'|'medium'|'low'). Be concise, technical, and friendly. "
    "Return ONLY valid JSON, no markdown fences."
)


def _build_user_prompt(intent: Dict[str, Any]) -> str:
    det = intent.get("deterministic_columns", [])
    prob = intent.get("probabilistic_columns", [])
    rules = intent.get("survivorship_rules", [])
    prob_summary = [f"{c['name']} (weight {c.get('weight', 0)}%)" for c in prob]
    rules_summary = [
        {"precedence": r.get("precedence", 1), "column": r["column"], "rule": r.get("rule", "")}
        for r in sorted(rules, key=lambda r: r.get("precedence", 999))
    ]
    return (
        "Configuration:\n"
        f"- Deterministic key attributes (exact-match): {det or 'none'}\n"
        f"- Probabilistic suspect-score attributes with weights: {prob_summary or 'none'}\n"
        f"- Threshold: {intent.get('threshold', 0.75)*100:.0f}%\n"
        f"- Survivorship rules (lower precedence = higher priority): "
        f"{json.dumps(rules_summary)}\n\n"
        "Return ONLY valid JSON with keys summary, survivorship_breakdown "
        "(array of {attribute, interpreted_rule}), confidence."
    )


def _parse_json_block(text: str) -> Dict[str, Any]:
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.startswith("json"):
            t = t[4:]
    return json.loads(t)


async def generate_strategy_summary(intent: Dict[str, Any]) -> Dict[str, Any]:
    """Produce a plain-English Strategy Summary."""
    det = intent.get("deterministic_columns", [])
    prob = intent.get("probabilistic_columns", [])
    rules = sorted(intent.get("survivorship_rules", []), key=lambda r: r.get("precedence", 999))
    surv = [{"attribute": r["column"], "intent": r.get("rule", "")} for r in rules]

    gcp = get_gcp()
    user_prompt = _build_user_prompt(intent)

    # ----- 1. Try Vertex AI Gemini -----
    if gcp.is_live:
        try:
            text = gcp.gemini_text(
                prompt=user_prompt, system=SYSTEM_PROMPT, model="gemini-2.5-pro"
            )
            parsed = _parse_json_block(text)
            parsed["backend"] = "Vertex AI Gemini 2.5 Pro"
            return parsed
        except (GCPUnavailable, Exception) as e:
            logger.warning("[agent] Vertex AI call failed: %s — falling back to Emergent", e)

    # ----- 2. Emergent Universal LLM (preview) -----
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if api_key:
        try:
            chat = LlmChat(
                api_key=api_key,
                session_id=f"strategy-{intent.get('job_id','adhoc')}",
                system_message=SYSTEM_PROMPT,
            ).with_model("gemini", "gemini-3-flash-preview")
            resp = await chat.send_message(UserMessage(text=user_prompt))
            parsed = _parse_json_block(resp)
            parsed["backend"] = "Emergent Gemini 3 Flash (preview)"
            return parsed
        except Exception as e:
            logger.warning("[agent] Emergent LLM call failed: %s — using deterministic fallback", e)

    # ----- 3. Deterministic fallback -----
    return _deterministic_fallback(det, prob, surv, gcp.is_live)


def _deterministic_fallback(det, prob, surv, is_live: bool) -> Dict[str, Any]:
    backend = "Vertex AI Gemini (live · LLM error)" if is_live else "Deterministic fallback"
    parts = []
    if det:
        parts.append(f"first try an exact match on {', '.join(det)} (Key Attributes)")
    if prob:
        prob_label = ", ".join([f"{c['name']} ({c.get('weight',0)}%)" for c in prob])
        parts.append(f"then compute a weighted fuzzy Suspect Score on {prob_label}")
    line = "I will " + " and ".join(parts) if parts else "I will run an identity scan."
    summary = (
        f"{line}. Records with a combined score of 75% or higher are merged under one "
        "enterprise_id in the Curated Master table; duplicate rows go to the Suspect "
        "table with their score and a per-attribute match explanation. Survivorship "
        "rules are applied in precedence order to build the Synthetic Golden Record."
    )
    breakdown = []
    for s in surv:
        intent_l = (s["intent"] or "").lower()
        if "most recent" in intent_l or "latest" in intent_l:
            rule = "Pick the most recent non-null value (ORDER BY ingested_at DESC)."
        elif "frequent" in intent_l or "most often" in intent_l:
            rule = "Pick the most frequent value; tie-break by recency."
        elif "longest" in intent_l:
            rule = "Pick the longest non-null value."
        elif "shortest" in intent_l:
            rule = "Pick the shortest non-null value."
        elif "first" in intent_l or "earliest" in intent_l:
            rule = "Pick the earliest non-null value."
        elif not s["intent"]:
            rule = "Default: most recent non-null value."
        else:
            rule = f'Custom rule from prompt: "{s["intent"]}"'
        breakdown.append({"attribute": s["attribute"], "interpreted_rule": rule})
    return {
        "summary": summary,
        "survivorship_breakdown": breakdown,
        "confidence": "medium",
        "backend": backend,
    }
