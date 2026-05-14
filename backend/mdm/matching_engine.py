"""In-memory matching engine for preview/demo mode.
Mimics the BigQuery pipeline so the user can inspect Master/Suspect outputs
without needing a live GCP backend.
"""
from __future__ import annotations
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import jellyfish
import pandas as pd
from rapidfuzz import fuzz


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


def standardize(df: pd.DataFrame, attributes: List[Dict[str, Any]]) -> pd.DataFrame:
    out = df.copy()
    out.columns = [c.strip() for c in out.columns]
    for a in attributes:
        col = a["name"]
        if col in out.columns:
            out[col] = out[col].apply(lambda v: _normalize_value(col, v))
    out["record_uid"] = [str(uuid.uuid4()) for _ in range(len(out))]
    out["ingested_at"] = datetime.now(timezone.utc).isoformat()
    return out


def _pair_score(
    a: pd.Series,
    b: pd.Series,
    det_cols: List[str],
    prob_attrs: List[Dict[str, Any]],
) -> Tuple[float, str, str]:
    # Deterministic short-circuit
    if det_cols:
        all_match = all(
            (a.get(c, "") or "") != "" and (a.get(c, "") == b.get(c, ""))
            for c in det_cols
        )
        if all_match:
            return 1.0, "deterministic", f"Exact match on {', '.join(det_cols)}"

    if not prob_attrs:
        return 0.0, "none", "No probabilistic attributes configured"

    score = 0.0
    parts = []
    for attr in prob_attrs:
        col = attr["name"]
        w = float(attr.get("weight", 0)) / 100.0
        va, vb = str(a.get(col, "") or ""), str(b.get(col, "") or "")
        if not va or not vb:
            parts.append(f"{col}: missing")
            continue
        soundex_match = (
            jellyfish.soundex(va or " ") == jellyfish.soundex(vb or " ")
        )
        metaphone_match = (
            jellyfish.metaphone(va) == jellyfish.metaphone(vb)
        )
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
    return score, "probabilistic", "; ".join(parts)


def _union_find_clusters(n: int, edges: List[Tuple[int, int]]) -> List[int]:
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for a, b in edges:
        union(a, b)
    return [find(i) for i in range(n)]


def run_pipeline(
    df: pd.DataFrame, intent: Dict[str, Any], threshold: float = 0.75
) -> Dict[str, Any]:
    attributes = intent.get("attributes", [])
    det_cols = [a["name"] for a in attributes if a.get("match_type") == "deterministic"]
    prob_attrs = [a for a in attributes if a.get("match_type") == "probabilistic"]

    staged = standardize(df, attributes)
    n = len(staged)
    edges: List[Tuple[int, int]] = []
    pair_meta: Dict[Tuple[int, int], Dict[str, Any]] = {}

    rows = staged.to_dict("records")
    for i in range(n):
        for j in range(i + 1, n):
            score, method, explanation = _pair_score(
                pd.Series(rows[i]), pd.Series(rows[j]), det_cols, prob_attrs
            )
            if score >= threshold:
                edges.append((i, j))
                pair_meta[(i, j)] = {
                    "score": round(score * 100, 2),
                    "method": method,
                    "explanation": explanation,
                }

    cluster_roots = _union_find_clusters(n, edges)
    # Map root index -> enterprise_id uuid
    root_to_eid: Dict[int, str] = {}
    enterprise_ids = []
    for r in cluster_roots:
        if r not in root_to_eid:
            root_to_eid[r] = f"ENT-{uuid.uuid4().hex[:10].upper()}"
        enterprise_ids.append(root_to_eid[r])
    staged["enterprise_id"] = enterprise_ids

    # Build master (survivorship)
    master_records: List[Dict[str, Any]] = []
    for eid, group in staged.groupby("enterprise_id"):
        record: Dict[str, Any] = {"enterprise_id": eid}
        # Determine match_method
        if len(group) == 1:
            record["match_method"] = "unique"
        elif det_cols and all(group[c].nunique(dropna=True) <= 1 for c in det_cols):
            record["match_method"] = "deterministic"
        else:
            record["match_method"] = "probabilistic"
        record["source_record_count"] = len(group)
        for a in attributes:
            col = a["name"]
            prompt = (a.get("survivorship_intent") or "").lower()
            values = group[col].dropna().astype(str).tolist() if col in group.columns else []
            values = [v for v in values if v != ""]
            if not values:
                record[f"golden_{col}"] = None
                continue
            if "most recent" in prompt or "latest" in prompt or "newest" in prompt:
                record[f"golden_{col}"] = (
                    group.sort_values("ingested_at", ascending=False)[col].iloc[0]
                )
            elif "longest" in prompt:
                record[f"golden_{col}"] = max(values, key=len)
            elif "frequent" in prompt or "most often" in prompt or "mode" in prompt:
                counts = Counter(values)
                top, _ = counts.most_common(1)[0]
                # tie-breaker: most recent
                ties = [v for v, c in counts.items() if c == counts[top]]
                if len(ties) > 1:
                    record[f"golden_{col}"] = (
                        group[group[col].isin(ties)]
                        .sort_values("ingested_at", ascending=False)[col]
                        .iloc[0]
                    )
                else:
                    record[f"golden_{col}"] = top
            elif "first" in prompt or "earliest" in prompt or "oldest" in prompt:
                record[f"golden_{col}"] = (
                    group.sort_values("ingested_at", ascending=True)[col].iloc[0]
                )
            else:
                # default: most recent non-null
                record[f"golden_{col}"] = (
                    group.sort_values("ingested_at", ascending=False)[col].iloc[0]
                )
        record["ingested_at"] = datetime.now(timezone.utc).isoformat()
        master_records.append(record)

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
                sus[c] = src.get(c)
            sus["ingested_at"] = datetime.now(timezone.utc).isoformat()
            suspect_records.append(sus)

    # Dedupe suspect records by suspect_record_uid (keep highest score)
    seen: Dict[str, Dict[str, Any]] = {}
    for s in suspect_records:
        uid = s["suspect_record_uid"]
        if uid not in seen or s["suspect_score"] > seen[uid]["suspect_score"]:
            seen[uid] = s
    suspect_records = list(seen.values())

    return {
        "staging": staged.drop(columns=["ingested_at"]).to_dict("records"),
        "master": master_records,
        "suspect": suspect_records,
        "stats": {
            "total_records": n,
            "unique_masters": len(master_records),
            "duplicate_suspects": len(suspect_records),
            "deterministic_matches": sum(
                1 for m in master_records if m["match_method"] == "deterministic"
            ),
            "probabilistic_matches": sum(
                1 for m in master_records if m["match_method"] == "probabilistic"
            ),
        },
    }
