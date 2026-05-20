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
    """Weighted similarity score over the probabilistic columns.

    Null/empty fields on either side are REMOVED from BOTH the numerator and
    the denominator (i.e., weights re-normalised to the fields that are
    actually present). This avoids penalising records that merely have a
    missing value in one column while every other unique identifier matches.
    """
    raw_score = 0.0
    present_weight = 0.0
    parts: List[str] = []
    for attr in cols:
        col = attr["name"]
        w = float(attr.get("weight", 0)) / 100.0
        va, vb = str(a.get(col) or ""), str(b.get(col) or "")
        if not va or not vb:
            parts.append(f"{col}: missing on one side (excluded from score)")
            continue
        present_weight += w
        soundex_match = jellyfish.soundex(va or " ") == jellyfish.soundex(vb or " ")
        metaphone_match = jellyfish.metaphone(va) == jellyfish.metaphone(vb)
        token_ratio = fuzz.token_sort_ratio(va, vb) / 100.0
        sub = (
            0.30 * (1.0 if soundex_match else 0.0)
            + 0.20 * (1.0 if metaphone_match else 0.0)
            + 0.50 * token_ratio
        )
        raw_score += w * sub
        if soundex_match and token_ratio > 0.8:
            parts.append(f"{col} matched phonetically ({int(token_ratio*100)}%)")
        elif token_ratio > 0.7:
            parts.append(f"{col} similar ({int(token_ratio*100)}%)")
        else:
            parts.append(f"{col} differs ({int(token_ratio*100)}%)")
    # Re-normalise across the weight that actually contributed
    score = (raw_score / present_weight) if present_weight > 0 else 0.0
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

    Native dtypes are preserved — values are NOT coerced to strings (except
    transiently inside Counter for hashing). Numeric, boolean, and timestamp
    columns survive as their original types so the curated golden record
    keeps schema fidelity with BigQuery.
    """
    if col not in group.columns:
        return None
    series = group[col].dropna()
    series = series[series.astype(str).str.len() > 0]
    if series.empty:
        return None

    applicable = [r for r in rules if r["column"] == col]
    rule_text = (applicable[0]["rule"] if applicable else "").lower()

    if "most recent" in rule_text or "latest" in rule_text or "newest" in rule_text:
        return _to_python(group.sort_values("ingested_at", ascending=False)[col].iloc[0])
    if "longest" in rule_text:
        # Length only meaningful for string-like; fall back to most-recent otherwise
        if series.dtype == object or pd.api.types.is_string_dtype(series):
            return _to_python(max(series.tolist(), key=lambda v: len(str(v))))
        return _to_python(group.sort_values("ingested_at", ascending=False)[col].iloc[0])
    if "shortest" in rule_text:
        if series.dtype == object or pd.api.types.is_string_dtype(series):
            return _to_python(min(series.tolist(), key=lambda v: len(str(v))))
        return _to_python(group.sort_values("ingested_at", ascending=False)[col].iloc[0])
    if "frequent" in rule_text or "most often" in rule_text or "mode" in rule_text or "majority" in rule_text:
        # Counter needs hashable values; cast to str only for tally
        as_str = series.astype(str).tolist()
        counts = Counter(as_str)
        top, _ = counts.most_common(1)[0]
        ties = [v for v, c in counts.items() if c == counts[top]]
        if len(ties) > 1:
            return _to_python(
                group[group[col].astype(str).isin(ties)]
                .sort_values("ingested_at", ascending=False)[col]
                .iloc[0]
            )
        # Return the ORIGINAL-typed value, not the stringified key
        return _to_python(
            group[group[col].astype(str) == top]
            .sort_values("ingested_at", ascending=False)[col]
            .iloc[0]
        )
    if "first" in rule_text or "earliest" in rule_text or "oldest" in rule_text:
        return _to_python(group.sort_values("ingested_at", ascending=True)[col].iloc[0])
    # default: most-recent non-null
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

    det_cols: List[str] = list(intent.get("deterministic_columns", []))
    prob_cols: List[Dict[str, Any]] = list(intent.get("probabilistic_columns", []))
    survivorship_rules: List[Dict[str, Any]] = intent.get("survivorship_rules", [])
    standardize_cols = list({*det_cols, *(c["name"] for c in prob_cols)})

    # Stage 1 — validating
    await emit("validating", "running")
    if not det_cols and not prob_cols:
        await emit("validating", "failed", error="No match columns selected")
        raise ValueError("No match columns selected")
    await emit(
        "validating", "done",
        deterministic=det_cols,
        probabilistic=[c["name"] for c in prob_cols],
        rules=len(survivorship_rules),
    )

    # Stage 2 — standardizing
    await emit("standardizing", "running")
    await asyncio.sleep(0.3)
    staged = standardize(df, standardize_cols)
    rows = staged.to_dict("records")
    n = len(rows)
    await emit("standardizing", "done", rows=n)

    # Stage 3 — deterministic pass
    await emit("deterministic", "running")
    await asyncio.sleep(0.3)
    edges: List[Tuple[int, int]] = []
    pair_meta: Dict[Tuple[int, int], Dict[str, Any]] = {}
    det_hits = 0
    if det_cols:
        for i in range(n):
            for j in range(i + 1, n):
                if _deterministic_match(rows[i], rows[j], det_cols):
                    edges.append((i, j))
                    pair_meta[(i, j)] = {
                        "score": 100.0,
                        "method": "deterministic",
                        "explanation": f"Exact match on {', '.join(det_cols)}",
                    }
                    det_hits += 1
    await emit("deterministic", "done", matches=det_hits,
               keys=det_cols or ["(none)"])

    # Stage 4 — probabilistic pass
    await emit("probabilistic", "running")
    await asyncio.sleep(0.3)
    prob_hits = 0
    if prob_cols:
        for i in range(n):
            for j in range(i + 1, n):
                if (i, j) in pair_meta:
                    continue
                score, explanation = _probabilistic_score(rows[i], rows[j], prob_cols)
                if score >= threshold:
                    edges.append((i, j))
                    pair_meta[(i, j)] = {
                        "score": round(score * 100, 2),
                        "method": "probabilistic",
                        "explanation": explanation,
                    }
                    prob_hits += 1
    await emit("probabilistic", "done", matches=prob_hits,
               attrs=[f"{c['name']}({c.get('weight',0)}%)" for c in prob_cols] or ["(none)"])

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

    # Build a lookup of pair_meta by record_uid for downstream stages
    uid_to_idx = {r["record_uid"]: i for i, r in enumerate(rows)}

    # Stage 7 — survivorship & master assembly. ALSO selects a single
    # "primary" record per cluster (the one that survives into Master);
    # all other cluster members become Suspects (no double-counting).
    await emit("survivorship", "running")
    await asyncio.sleep(0.3)
    master_records: List[Dict[str, Any]] = []
    primary_by_eid: Dict[str, str] = {}
    for eid, group in staged.groupby("enterprise_id"):
        # Primary = first record_uid in this cluster (stable ordering)
        primary_uid = sorted(group["record_uid"].tolist())[0]
        primary_by_eid[eid] = primary_uid

        record: Dict[str, Any] = {"enterprise_id": eid}
        if len(group) == 1:
            record["match_method"] = "unique"
        else:
            # Promote to "deterministic" iff ALL key attributes are equal
            # across every member of the cluster (transitive determinism).
            det_ok = bool(det_cols) and all(
                group[c].nunique(dropna=True) <= 1 and bool(group[c].iloc[0])
                for c in det_cols if c in group.columns
            )
            record["match_method"] = "deterministic" if det_ok else "probabilistic"
        record["source_record_count"] = int(len(group))
        for col in df.columns:
            if col in ("record_uid", "ingested_at", "enterprise_id"):
                continue
            record[f"golden_{col}"] = _apply_survivorship(group, col, survivorship_rules)
        record["ingested_at"] = datetime.now(timezone.utc).isoformat()
        master_records.append(record)
    await emit("survivorship", "done", masters=len(master_records),
               rules_applied=len(survivorship_rules))

    # Build suspect table — EXCLUDE primaries, EXCLUDE singletons.
    # One suspect row per non-primary cluster member, pointing to its parent.
    # Carries lineage (score, reason, explanation, original columns) — but
    # NOT `match_method` (that classification lives only on the Master).
    suspect_records: List[Dict[str, Any]] = []
    # best score per non-primary uid
    best_meta_by_uid: Dict[str, Dict[str, Any]] = {}
    for (i, j), meta in pair_meta.items():
        for uid in (rows[i]["record_uid"], rows[j]["record_uid"]):
            prev = best_meta_by_uid.get(uid)
            if not prev or meta["score"] > prev["score"]:
                best_meta_by_uid[uid] = meta

    for _, srow in staged.iterrows():
        uid = srow["record_uid"]
        eid = srow["enterprise_id"]
        primary = primary_by_eid.get(eid)
        cluster_size = (staged["enterprise_id"] == eid).sum()
        if cluster_size <= 1 or uid == primary:
            continue
        meta = best_meta_by_uid.get(uid, {"score": 0.0, "explanation": "", "method": "probabilistic"})
        reason = _human_suspect_reason(meta, det_cols, prob_cols)
        sus: Dict[str, Any] = {
            "parent_enterprise_id": eid,
            "suspect_record_uid": uid,
            "suspect_score": meta["score"],
            "suspect_reason": reason,
            "match_explanation": meta.get("explanation", ""),
        }
        # Original columns (preserve native dtypes)
        idx = uid_to_idx.get(uid)
        if idx is not None:
            src = rows[idx]
            for c in df.columns:
                if c in ("record_uid", "ingested_at", "enterprise_id"):
                    continue
                sus[c] = _to_python(src.get(c))
        sus["ingested_at"] = datetime.now(timezone.utc).isoformat()
        suspect_records.append(sus)

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


def _human_suspect_reason(
    meta: Dict[str, Any], det_cols: List[str], prob_cols: List[Dict[str, Any]]
) -> str:
    """Plain-English reasoning a data steward can act on directly."""
    method = meta.get("method", "probabilistic")
    score = meta.get("score", 0.0)
    if method == "deterministic":
        cols = ", ".join(det_cols) if det_cols else "all key attributes"
        return (
            f"All key attributes ({cols}) matched the parent record exactly — "
            f"merged automatically without ambiguity."
        )
    prob_label = ", ".join(c["name"] for c in prob_cols) or "the configured attributes"
    return (
        f"Fuzzy match against {prob_label} produced a Suspect Score of "
        f"{score:.1f}% — the agent merged this row into the parent cluster "
        f"based on phonetic and lexical similarity. Review per-attribute "
        f"details in the Match Explanation column."
    )


# Backwards-compat sync entry used by tests
def run_pipeline(df: pd.DataFrame, intent: Dict[str, Any], threshold: float = 0.75):
    import asyncio
    return asyncio.run(run_pipeline_async(df, intent, threshold, progress=None))
