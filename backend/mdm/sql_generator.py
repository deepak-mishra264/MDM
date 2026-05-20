"""BigQuery SQL generator for the 4-state pipeline.

Updated to consume the new schema:
- match_columns: [{name, weight}]  (used for both deterministic + probabilistic)
- survivorship_rules: [{column, rule, precedence}]

Generated layers: Raw, Staging, Curated Master, Curated Suspect, Search Index.
"""
from typing import Any, Dict, List


def _sanitize(name: str) -> str:
    return "".join(c if c.isalnum() or c == "_" else "_" for c in name.strip().lower())


def _rule_to_sql_agg(col: str, rule_text: str) -> str:
    """Map a survivorship rule (Plain English) to a BigQuery aggregation fragment."""
    p = (rule_text or "").lower()
    if "most recent" in p or "latest" in p or "newest" in p:
        return (
            f"ARRAY_AGG({col} IGNORE NULLS ORDER BY ingested_at DESC LIMIT 1)[OFFSET(0)] "
            f"AS golden_{col}"
        )
    if "longest" in p:
        return (
            f"ARRAY_AGG({col} IGNORE NULLS ORDER BY LENGTH({col}) DESC LIMIT 1)"
            f"[OFFSET(0)] AS golden_{col}"
        )
    if "shortest" in p:
        return (
            f"ARRAY_AGG({col} IGNORE NULLS ORDER BY LENGTH({col}) ASC LIMIT 1)"
            f"[OFFSET(0)] AS golden_{col}"
        )
    if "frequent" in p or "most often" in p or "mode" in p or "majority" in p:
        return (
            f"APPROX_TOP_COUNT({col}, 1)[SAFE_OFFSET(0)].value AS golden_{col}"
        )
    if "first" in p or "earliest" in p or "oldest" in p:
        return (
            f"ARRAY_AGG({col} IGNORE NULLS ORDER BY ingested_at ASC LIMIT 1)[OFFSET(0)] "
            f"AS golden_{col}"
        )
    # Default: most-recent non-null
    return (
        f"ARRAY_AGG({col} IGNORE NULLS ORDER BY ingested_at DESC LIMIT 1)[OFFSET(0)] "
        f"AS golden_{col}"
    )


def generate_pipeline_sql(intent: Dict[str, Any], gcp_config: Dict[str, Any]) -> Dict[str, str]:
    project = gcp_config.get("project_id", "your-project")
    dataset = gcp_config.get("dataset_id", "searce_mdm")
    bucket = gcp_config.get("gcs_bucket", "searce-mdm-landing")
    layers = gcp_config.get("layers", {})
    raw_t = layers.get("raw", "raw_layer")
    stg_t = layers.get("staging", "staging_layer")
    mst_t = layers.get("curated_master", "curated_master")
    sus_t = layers.get("curated_suspect", "curated_suspect")
    threshold = gcp_config.get("matching", {}).get("threshold", 0.75)

    job_id = intent.get("job_id", "job")
    det_cols: List[str] = intent.get("deterministic_columns", [])
    prob_cols: List[Dict[str, Any]] = intent.get("probabilistic_columns", [])
    survivorship_rules: List[Dict[str, Any]] = sorted(
        intent.get("survivorship_rules", []), key=lambda r: r.get("precedence", 999)
    )
    source_file = intent.get("source_file", "uploaded_file.csv")
    all_input_cols: List[str] = intent.get(
        "all_columns",
        list({*det_cols, *(c["name"] for c in prob_cols)}),
    )

    fq = f"`{project}.{dataset}"

    # ---------- 1. GCS -> Raw ----------
    # NOTE: column list must match the CSV exactly (no metadata cols here —
    # those are added in the Staging stage).
    raw_cols_sql = ",\n".join([f"  {_sanitize(c)} STRING" for c in all_input_cols])
    raw_sql = f"""-- ============================================================
-- STATE 1 & 2: GCS Landing -> Raw Layer (Partitioned)
-- ============================================================
LOAD DATA OVERWRITE {fq}.{raw_t}_{job_id}`
(
{raw_cols_sql}
)
OPTIONS(description = "Raw landing for job {job_id}")
FROM FILES (
  format = 'CSV',
  uris = ['gs://{bucket}/landing/{job_id}/{source_file}'],
  skip_leading_rows = 1
);"""

    # ---------- 2. Staging (adds metadata + UUID) ----------
    norm = []
    for c in all_input_cols:
        sc = _sanitize(c)
        lc = sc.lower()
        if "phone" in lc or "mobile" in lc:
            norm.append(f"REGEXP_REPLACE(LOWER(TRIM({sc})), r'[^0-9]', '') AS {sc}")
        elif "email" in lc:
            norm.append(f"LOWER(TRIM({sc})) AS {sc}")
        else:
            norm.append(f"TRIM(REGEXP_REPLACE({sc}, r'\\s+', ' ')) AS {sc}")
    staging_sql = f"""-- ============================================================
-- STATE 3: Staging Layer (Normalization + Metadata)
-- ============================================================
CREATE OR REPLACE TABLE {fq}.{stg_t}_{job_id}`
PARTITION BY DATE(ingested_at) AS
SELECT
{(',' + chr(10)).join(['  ' + n for n in norm])},
  '{source_file}' AS source_file,
  CURRENT_TIMESTAMP() AS ingested_at,
  GENERATE_UUID() AS record_uid
FROM {fq}.{raw_t}_{job_id}`
WHERE {' OR '.join([f"{_sanitize(c)} IS NOT NULL" for c in all_input_cols]) or 'TRUE'};"""

    # ---------- 3. Master ----------
    # Deterministic join: ALL deterministic columns equal (and non-null)
    if det_cols:
        det_join = " AND ".join(
            [
                f"a.{_sanitize(c)} = b.{_sanitize(c)} AND a.{_sanitize(c)} IS NOT NULL"
                for c in det_cols
            ]
        )
    else:
        det_join = "FALSE"

    # Probabilistic weighted score over the PROBABILISTIC columns only
    if prob_cols:
        terms = []
        for a in prob_cols:
            sc = _sanitize(a["name"])
            w = float(a.get("weight", 0)) / 100.0
            terms.append(
                f"({w} * IF(SOUNDEX(a.{sc}) = SOUNDEX(b.{sc}), 1.0, 0.0) * 0.5 + "
                f"{w} * (1 - SAFE_DIVIDE(EDIT_DISTANCE(a.{sc}, b.{sc}), "
                f"GREATEST(LENGTH(a.{sc}), LENGTH(b.{sc}), 1))) * 0.5)"
            )
        prob_score = " + ".join(terms)
    else:
        prob_score = "0.0"

    golden_lines = []
    for col in all_input_cols:
        sc = _sanitize(col)
        # Find applicable rule (smallest precedence wins)
        applicable = [r for r in survivorship_rules if r["column"] == col]
        rule_text = applicable[0]["rule"] if applicable else ""
        golden_lines.append("  " + _rule_to_sql_agg(sc, rule_text))

    master_sql = f"""-- ============================================================
-- STATE 4a: Curated Master Table (Golden Records)
-- Survivorship rules applied in precedence order:
{chr(10).join([f"--   [P{r['precedence']}] {r['column']}: {r['rule']}" for r in survivorship_rules]) or "--   (no rules — default: most recent non-null)"}
-- ============================================================
CREATE OR REPLACE TABLE {fq}.{mst_t}`
PARTITION BY DATE(ingested_at)
CLUSTER BY enterprise_id AS
WITH pairs AS (
  SELECT
    a.record_uid AS uid_a,
    b.record_uid AS uid_b,
    CASE WHEN {det_join} THEN 1.0 ELSE {prob_score} END AS score,
    CASE WHEN {det_join} THEN 'deterministic' ELSE 'probabilistic' END AS method
  FROM {fq}.{stg_t}_{job_id}` a
  JOIN {fq}.{stg_t}_{job_id}` b
    ON a.record_uid < b.record_uid
),
matched_pairs AS (
  SELECT * FROM pairs WHERE score >= {threshold}
),
edge_clusters AS (
  SELECT uid_a AS uid, uid_b AS cluster_root FROM matched_pairs
  UNION ALL
  SELECT uid_b AS uid, uid_a AS cluster_root FROM matched_pairs
  UNION ALL
  SELECT record_uid, record_uid FROM {fq}.{stg_t}_{job_id}`
),
final_clusters AS (
  SELECT uid, MIN(cluster_root) AS enterprise_id FROM edge_clusters GROUP BY uid
),
cluster_methods AS (
  SELECT
    fc.enterprise_id,
    MAX(IF(mp.method = 'deterministic', 1, 0)) AS has_det,
    MAX(IF(mp.method = 'probabilistic', 1, 0)) AS has_prob,
    COUNT(DISTINCT fc.uid) AS source_count
  FROM final_clusters fc
  LEFT JOIN matched_pairs mp
    ON mp.uid_a = fc.uid OR mp.uid_b = fc.uid
  GROUP BY fc.enterprise_id
),
joined AS (
  SELECT s.*, fc.enterprise_id
  FROM {fq}.{stg_t}_{job_id}` s
  JOIN final_clusters fc ON s.record_uid = fc.uid
)
SELECT
  j.enterprise_id,
  CASE
    WHEN cm.source_count = 1 THEN 'unique'
    WHEN cm.has_det = 1 THEN 'deterministic'
    ELSE 'probabilistic'
  END AS match_method,
{(',' + chr(10)).join(golden_lines) or "  ANY_VALUE(j.record_uid) AS golden_record_uid"},
  COUNT(*) AS source_record_count,
  CURRENT_TIMESTAMP() AS ingested_at
FROM joined j
JOIN cluster_methods cm USING (enterprise_id)
GROUP BY j.enterprise_id, cm.source_count, cm.has_det;"""

    # ---------- 4. Suspect ----------
    explain_terms = []
    for a in prob_cols:
        sc = _sanitize(a["name"])
        explain_terms.append(
            f"IF(SOUNDEX(a.{sc}) = SOUNDEX(b.{sc}), '{a['name']} matches phonetically; ', '{a['name']} differs; ')"
        )
    explain_expr = " || ".join(explain_terms) if explain_terms else "'See score'"

    suspect_sql = f"""-- ============================================================
-- STATE 4b: Curated Suspect Table (Duplicates >= threshold)
-- ============================================================
CREATE OR REPLACE TABLE {fq}.{sus_t}`
PARTITION BY DATE(ingested_at)
CLUSTER BY parent_enterprise_id AS
WITH pairs AS (
  SELECT
    a.record_uid AS uid_a,
    b.record_uid AS uid_b,
    CASE WHEN {det_join} THEN 1.0 ELSE {prob_score} END AS score,
    CASE WHEN {det_join} THEN 'deterministic' ELSE 'probabilistic' END AS method
  FROM {fq}.{stg_t}_{job_id}` a
  JOIN {fq}.{stg_t}_{job_id}` b ON a.record_uid < b.record_uid
),
matched_pairs AS (
  SELECT * FROM pairs WHERE score >= {threshold}
),
edge_clusters AS (
  SELECT uid_a AS uid, uid_b AS cluster_root FROM matched_pairs
  UNION ALL
  SELECT uid_b AS uid, uid_a AS cluster_root FROM matched_pairs
  UNION ALL
  SELECT record_uid, record_uid FROM {fq}.{stg_t}_{job_id}`
),
final_clusters AS (
  SELECT uid, MIN(cluster_root) AS enterprise_id FROM edge_clusters GROUP BY uid
)
SELECT
  fc.enterprise_id AS parent_enterprise_id,
  a.record_uid AS suspect_record_uid,
  ROUND(p.score * 100, 2) AS suspect_score,
  CONCAT(p.method, ' match >= {int(threshold*100)}%') AS suspect_reason,
  {explain_expr} AS match_explanation,
{(',' + chr(10)).join([f'  a.{_sanitize(c)}' for c in all_input_cols]) or '  a.record_uid'},
  CURRENT_TIMESTAMP() AS ingested_at
FROM matched_pairs p
JOIN {fq}.{stg_t}_{job_id}` a ON a.record_uid = p.uid_a
JOIN {fq}.{stg_t}_{job_id}` b ON b.record_uid = p.uid_b
JOIN final_clusters fc ON fc.uid = a.record_uid;"""

    # ---------- 5. Search Index ----------
    index_sql = f"""-- ============================================================
-- Search Index on Curated Master (sub-second identity lookup)
-- ============================================================
CREATE SEARCH INDEX IF NOT EXISTS searce_mdm_master_idx
ON {fq}.{mst_t}`(ALL COLUMNS);

-- Example lookup:
-- SELECT * FROM {fq}.{mst_t}`
-- WHERE SEARCH({fq}.{mst_t}`, 'john doe 555');"""

    return {
        "raw_layer": raw_sql,
        "staging_layer": staging_sql,
        "curated_master": master_sql,
        "curated_suspect": suspect_sql,
        "search_index": index_sql,
    }
