"""Intent Interpretation Agent.
Uses Emergent Universal LLM key (Gemini 3 Flash) as the demo backend; if a
GCP Vertex AI service-account JSON is present in the env (VERTEX_AI_CREDS_PATH),
the architecture allows swapping to Vertex AI without touching call sites.
"""
import json
import os
from typing import Any, Dict

from emergentintegrations.llm.chat import LlmChat, UserMessage


def _has_vertex() -> bool:
    return bool(os.environ.get("VERTEX_AI_CREDS_PATH"))


async def generate_strategy_summary(intent: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a plain-English Strategy Summary the user must confirm."""
    attributes = intent.get("attributes", [])
    det = [a["name"] for a in attributes if a.get("match_type") == "deterministic"]
    prob = [
        f"{a['name']} ({a.get('weight', 0)}%)"
        for a in attributes if a.get("match_type") == "probabilistic"
    ]
    surv = [
        {"attribute": a["name"], "intent": a.get("survivorship_intent", "")}
        for a in attributes
    ]

    backend = "Vertex AI Gemini" if _has_vertex() else "Emergent Gemini 3 Flash"

    fallback = _fallback_summary(det, prob, surv, backend)

    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        return fallback

    try:
        system = (
            "You are the Searce MDM Intent Interpreter. Given a user's matching "
            "and survivorship configuration, produce a JSON object with keys: "
            "summary (1-2 short paragraphs in plain English explaining what the "
            "pipeline will do), survivorship_breakdown (array of {attribute, "
            "interpreted_rule}), and confidence (string: 'high'|'medium'|'low'). "
            "Be concise, technical, and friendly. NEVER include markdown fences."
        )
        chat = LlmChat(
            api_key=api_key,
            session_id=f"strategy-{intent.get('job_id','adhoc')}",
            system_message=system,
        ).with_model("gemini", "gemini-3-flash-preview")
        prompt = (
            "Configuration:\n"
            f"- Deterministic attributes (exact match): {det or 'none'}\n"
            f"- Probabilistic attributes with weights: {prob or 'none'}\n"
            f"- Threshold: {intent.get('threshold', 0.75)*100:.0f}%\n"
            f"- Survivorship intents: {json.dumps(surv)}\n\n"
            "Return ONLY valid JSON."
        )
        resp = await chat.send_message(UserMessage(text=prompt))
        text = resp.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
        parsed = json.loads(text)
        parsed["backend"] = backend
        return parsed
    except Exception as e:
        fallback["agent_error"] = str(e)
        return fallback


def _fallback_summary(det, prob, surv, backend: str) -> Dict[str, Any]:
    parts = []
    if det:
        parts.append(
            f"match exactly on {', '.join(det)} (Deterministic)"
        )
    if prob:
        parts.append(f"compute a weighted fuzzy score on {', '.join(prob)} (Probabilistic)")
    line = (
        "I will " + " and ".join(parts) if parts else "I will run an identity scan."
    )
    summary = (
        f"{line}. Records with a combined match score of 75% or higher are merged "
        "under a single enterprise_id in the Curated Master table; the duplicate "
        "rows are written to the Suspect table with their score and a per-attribute "
        "match explanation. Survivorship logic is applied to build the Synthetic "
        "Golden Record for each master."
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
        elif "first" in intent_l or "earliest" in intent_l:
            rule = "Pick the earliest non-null value."
        elif not s["intent"]:
            rule = "Default: most recent non-null value."
        else:
            rule = f"Custom rule from prompt: \"{s['intent']}\""
        breakdown.append({"attribute": s["attribute"], "interpreted_rule": rule})
    return {
        "summary": summary,
        "survivorship_breakdown": breakdown,
        "confidence": "medium",
        "backend": backend,
    }
