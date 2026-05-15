"""In-memory matching engine — new schema.

Schema:
- match_columns: [{name, weight}]  # used for BOTH deterministic and probabilistic
- survivorship_rules: [{column, rule, precedence}]  # smaller precedence wins
"""
from __future__ import annotations
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import jellyfish
import pandas as pd
from rapidfuzz import fuzz


ProgressFn = Optional[Callable[[str, str, Dict[str, Any]], Awaitable[None]]]


def _normalize_value(col: str, value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    s = str(value).strip()
    col_l = col.lower()
    if "phone" in col_l or "mobile" in col_l:
        return re.sub(r"[^0-9]", "", s)
    if "email" in col_l:
        return s.lower()
    return re.sub(r"\s+", " ", s).lower()


def standardize(df: pd.DataFrame, match_cols: List[str]) -> pd.DataFrame:
    out = df.copy()
    out.columns = [c.strip() for c in out.columns]
    for col in match_cols:
        if col in out.columns:
            out[col] = out[col].apply(lambda v: _normalize_value(col, v))
    out["record_uid"] = [str(uuid.uuid4()) for _ in range(len(out))]
    out["ingested_at"] = datetime.now(timezone.utc).isoformat()
    return out


def _deterministic_match(a: Dict[str, Any], b: Dict[str, Any], cols: List[str]) -> bool:
    """All selected columns must have non-empty equal values."""
    if not cols:
        return False
    for c in cols:
        va = (a.get(c) or "")
        vb = (b.get(c) or "")
        if not va or not vb or va != vb:
            return False
    return True


def _probabilistic_score(
    a: Dict[str, Any], b: Dict[str, Any], cols: List[Dict[str, Any]]
) -> Tuple[float, str]:
    score = 0.0
    parts = []
    for attr in cols:
        col = attr["name"]
        w = float(attr.get("weight", 0)) / 100.0
        va, vb = str(a.get(col) or ""), str(b.get(col) or "")
        if not va or not vb:
            parts.append(f"{col}: missing")
            continue
        soundex_match = jellyfish.soundex(va or " ") == jellyfish.soundex(vb or " ")
        metaphone_match = jellyfish.metaphone(va) == jellyfish.metaphone(vb)
        token_ratio = fuzz.token_sort_ratio(va, vb) / 100.0
        sub = (
            0.30 * (1.0 if soundex_match else 0.0)
            + 0.20 * (1.0 if metaphone_match else 0.0)
            + 0.50 * token_ratio
        )
        score += w * sub
        if soundex_match and token_ratio > 0.8:
            parts.append(f"{col} matched phonetically ({int(token_ratio*100)}%)")
        elif token_ratio > 0.7:
            parts.append(f"{col} similar ({int(token_ratio*100)}%)")
        else:
            parts.append(f"{col} differs ({int(token_ratio*100)}%)")
    return score, "; ".join(parts)


def _union_find(n: int, edges: List[Tuple[int, int]]) -> List[int]:
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    return [find(i) for i in range(n)]


def _to_python(v: Any) -> Any:
    """Coerce numpy/pandas scalar to plain Python scalar for JSON / Mongo safety."""
    if v is None:
        return None
    try:
        import numpy as np
        if isinstance(v, (np.integer,)):
            return int(v)
        if isinstance(v, (np.floating,)):
            return float(v)
        if isinstance(v, (np.bool_,)):
            return bool(v)
    except Exception:
        pass
    if isinstance(v, float) and pd.isna(v):
        return None
    return v


def _apply_survivorship(
    group: pd.DataFrame, col: str, rules: List[Dict[str, Any]]
) -> Any:
    """Apply the first-matching survivorship rule (by precedence) to a column.

    Rules array is expected to already be sorted ascending by precedence.
    A rule "matches" if its column == col. If no rule matches, defaults to
    'most recent non-null'.
    """
    values = group[col].dropna().astype(str).tolist() if col in group.columns else []
    values = [v for v in values if v != ""]
    if not values:
        return None

    applicable = [r for r in rules if r["column"] == col]
    rule_text = (applicable[0]["rule"] if applicable else "").lower()

    if "most recent" in rule_text or "latest" in rule_text or "newest" in rule_text:
        return _to_python(group.sort_values("ingested_at", ascending=False)[col].iloc[0])
    if "longest" in rule_text:
        return _to_python(max(values, key=len))
    if "shortest" in rule_text:
        return _to_python(min(values, key=len))
    if "frequent" in rule_text or "most often" in rule_text or "mode" in rule_text or "majority" in rule_text:
        counts = Counter(values)
        top, _ = counts.most_common(1)[0]
        ties = [v for v, c in counts.items() if c == counts[top]]
        if len(ties) > 1:
            return _to_python(
                group[group[col].isin(ties)]
                .sort_values("ingested_at", ascending=False)[col]
                .iloc[0]
            )
        return _to_python(top)
    if "first" in rule_text or "earliest" in rule_text or "oldest" in rule_text:
        return _to_python(group.sort_values("ingested_at", ascending=True)[col].iloc[0])
    # default
    return _to_python(group.sort_values("ingested_at", ascending=False)[col].iloc[0])


async def run_pipeline_async(
    df: pd.DataFrame,
    intent: Dict[str, Any],
    threshold: float = 0.75,
    progress: ProgressFn = None,
) -> Dict[str, Any]:
    """Run the pipeline emitting progress events at each stage.

    Stages emitted via progress(key, state, detail_dict):
      validating, standardizing, deterministic, probabilistic, embedding,
      clustering, survivorship, complete
    """
    import asyncio

    async def emit(key: str, state: str, **detail):
        if progress:
            await progress(key, state, detail)

    match_cols: List[Dict[str, Any]] = intent.get("match_columns", [])
    survivorship_rules: List[Dict[str, Any]] = intent.get("survivorship_rules", [])
    col_names = [c["name"] for c in match_cols]

    # Stage 1 — validating
    await emit("validating", "running")
    if not match_cols:
        await emit("validating", "failed", error="No match columns selected")
        raise ValueError("No match columns selected")
    await emit("validating", "done", columns=col_names, rules=len(survivorship_rules))

    # Stage 2 — standardizing
    await emit("standardizing", "running")
    await asyncio.sleep(0.3)
    staged = standardize(df, col_names)
    rows = staged.to_dict("records")
    n = len(rows)
    await emit("standardizing", "done", rows=n)

    # Stage 3 — deterministic pass
    await emit("deterministic", "running")
    await asyncio.sleep(0.3)
    edges: List[Tuple[int, int]] = []
    pair_meta: Dict[Tuple[int, int], Dict[str, Any]] = {}
    det_hits = 0
    for i in range(n):
        for j in range(i + 1, n):
            if _deterministic_match(rows[i], rows[j], col_names):
                edges.append((i, j))
                pair_meta[(i, j)] = {
                    "score": 100.0,
                    "method": "deterministic",
                    "explanation": f"Exact match on {', '.join(col_names)}",
                }
                det_hits += 1
    await emit("deterministic", "done", matches=det_hits)

    # Stage 4 — probabilistic pass
    await emit("probabilistic", "running")
    await asyncio.sleep(0.3)
    prob_hits = 0
    for i in range(n):
        for j in range(i + 1, n):
            if (i, j) in pair_meta:
                continue
            score, explanation = _probabilistic_score(rows[i], rows[j], match_cols)
            if score >= threshold:
                edges.append((i, j))
                pair_meta[(i, j)] = {
                    "score": round(score * 100, 2),
                    "method": "probabilistic",
                    "explanation": explanation,
                }
                prob_hits += 1
    await emit("probabilistic", "done", matches=prob_hits)

    # Stage 5 — embedding (simulated for preview; ML.GENERATE_EMBEDDING in live)
    await emit("embedding", "running")
    await asyncio.sleep(0.4)
    await emit(
        "embedding", "done",
        note="Soundex + Metaphone + token similarity used as embedding proxy in preview",
    )

    # Stage 6 — clustering (union-find)
    await emit("clustering", "running")
    await asyncio.sleep(0.2)
    roots = _union_find(n, edges)
    root_to_eid: Dict[int, str] = {}
    eids = []
    for r in roots:
        if r not in root_to_eid:
            root_to_eid[r] = f"ENT-{uuid.uuid4().hex[:10].upper()}"
        eids.append(root_to_eid[r])
    staged["enterprise_id"] = eids
    clusters = len(set(eids))
    await emit("clustering", "done", clusters=clusters)

    # Stage 7 — survivorship
    await emit("survivorship", "running")
    await asyncio.sleep(0.3)
    master_records: List[Dict[str, Any]] = []
    for eid, group in staged.groupby("enterprise_id"):
        record: Dict[str, Any] = {"enterprise_id": eid}
        if len(group) == 1:
            record["match_method"] = "unique"
        else:
            # Detect if all selected cols match exactly in this cluster
            det = all(
                group[c].nunique(dropna=True) <= 1 and (group[c].iloc[0] or "") != ""
                for c in col_names
            )
            record["match_method"] = "deterministic" if det else "probabilistic"
        record["source_record_count"] = int(len(group))
        # Apply survivorship per column (use original df columns, not just match cols)
        for col in df.columns:
            if col in ("record_uid", "ingested_at", "enterprise_id"):
                continue
            record[f"golden_{col}"] = _apply_survivorship(group, col, survivorship_rules)
        record["ingested_at"] = datetime.now(timezone.utc).isoformat()
        master_records.append(record)
    await emit("survivorship", "done", masters=len(master_records),
               rules_applied=len(survivorship_rules))

    # Build suspect table
    suspect_records: List[Dict[str, Any]] = []
    for (i, j), meta in pair_meta.items():
        a, b = rows[i], rows[j]
        for src in (a, b):
            sus = {
                "parent_enterprise_id": staged.iloc[i]["enterprise_id"],
                "suspect_record_uid": src["record_uid"],
                "suspect_score": meta["score"],
                "suspect_reason": (
                    f"{meta['method'].title()} match >= {int(threshold*100)}%"
                ),
                "match_explanation": meta["explanation"],
            }
            for c in df.columns:
                if c in ("record_uid", "ingested_at", "enterprise_id"):
                    continue
                sus[c] = _to_python(src.get(c))
            sus["ingested_at"] = datetime.now(timezone.utc).isoformat()
            suspect_records.append(sus)

    # Dedupe suspects by suspect_record_uid (keep highest score)
    seen: Dict[str, Dict[str, Any]] = {}
    for s in suspect_records:
        uid = s["suspect_record_uid"]
        if uid not in seen or s["suspect_score"] > seen[uid]["suspect_score"]:
            seen[uid] = s
    suspect_records = list(seen.values())

    stats = {
        "total_records": n,
        "unique_masters": len(master_records),
        "duplicate_suspects": len(suspect_records),
        "deterministic_matches": det_hits,
        "probabilistic_matches": prob_hits,
        "clusters": clusters,
    }

    await emit("complete", "done", **stats)

    return {
        "staging": staged.drop(columns=["ingested_at"]).to_dict("records"),
        "master": master_records,
        "suspect": suspect_records,
        "stats": stats,
    }


# Backwards-compat sync entry used by tests
def run_pipeline(df: pd.DataFrame, intent: Dict[str, Any], threshold: float = 0.75):
    import asyncio
    return asyncio.run(run_pipeline_async(df, intent, threshold, progress=None))
