"""BigQuery SQL generator for the 4-state pipeline.
Generates DDL/DML for Raw, Staging, Curated Master and Suspect tables,
plus the Search Index, based on user intent (attributes, match types,
weights, NL survivorship prompts).
"""
from typing import Any, Dict, List


def _sanitize(name: str) -> str:
    return "".join(c if c.isalnum() or c == "_" else "_" for c in name.strip().lower())


def _intent_to_sql_agg(col: str, prompt: str) -> str:
    """Heuristic mapper from NL prompt to BigQuery aggregation SQL fragment.
    The Vertex AI/Gemini agent refines this in production; here we provide
    a deterministic fallback for predictable output.
    """
    p = (prompt or "").lower()
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
    if "frequent" in p or "most often" in p or "mode" in p or "majority" in p:
        return (
            f"(SELECT v FROM UNNEST(ARRAY_AGG({col} IGNORE NULLS)) v "
            f"GROUP BY v ORDER BY COUNT(*) DESC, ANY_VALUE(ingested_at) DESC LIMIT 1) "
            f"AS golden_{col}"
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
    attributes: List[Dict[str, Any]] = intent.get("attributes", [])
    source_file = intent.get("source_file", "uploaded_file.csv")

    det_cols = [a["name"] for a in attributes if a.get("match_type") == "deterministic"]
    prob_cols = [a for a in attributes if a.get("match_type") == "probabilistic"]
    all_cols = [a["name"] for a in attributes]

    fq = f"`{project}.{dataset}"

    # ---------- 1. GCS -> Raw load job ----------
    raw_sql = f"""-- ============================================================
-- STATE 1 & 2: GCS Landing -> Raw Layer (Partitioned)
-- ============================================================
LOAD DATA OVERWRITE {fq}.{raw_t}_{job_id}`
(
{chr(10).join([f"  {_sanitize(c)} STRING," for c in all_cols])}
  source_file STRING,
  ingested_at TIMESTAMP
)
PARTITION BY DATE(ingested_at)
OPTIONS(description = "Raw landing for job {job_id}")
FROM FILES (
  format = 'CSV',
  uris = ['gs://{bucket}/landing/{job_id}/{source_file}'],
  skip_leading_rows = 1
);"""

    # ---------- 2. Staging (standardization) ----------
    norm_cols = []
    for c in all_cols:
        sc = _sanitize(c)
        lower = sc.lower()
        if "phone" in lower or "mobile" in lower:
            norm_cols.append(f"REGEXP_REPLACE(LOWER(TRIM({sc})), r'[^0-9]', '') AS {sc}")
        elif "email" in lower:
            norm_cols.append(f"LOWER(TRIM({sc})) AS {sc}")
        else:
            norm_cols.append(f"TRIM(REGEXP_REPLACE({sc}, r'\\s+', ' ')) AS {sc}")
    staging_sql = f"""-- ============================================================
-- STATE 3: Staging Layer (Normalization + Metadata)
-- ============================================================
CREATE OR REPLACE TABLE {fq}.{stg_t}_{job_id}`
PARTITION BY DATE(ingested_at) AS
SELECT
{(',' + chr(10)).join(['  ' + n for n in norm_cols])},
  source_file,
  CURRENT_TIMESTAMP() AS ingested_at,
  GENERATE_UUID() AS record_uid
FROM {fq}.{raw_t}_{job_id}`
WHERE {' OR '.join([f"{_sanitize(c)} IS NOT NULL" for c in all_cols]) or 'TRUE'};"""

    # ---------- 3. Curated Master ----------
    golden_lines = []
    for a in attributes:
        col = _sanitize(a["name"])
        prompt = a.get("survivorship_intent", "")
        golden_lines.append("  " + _intent_to_sql_agg(col, prompt))

    det_join = " AND ".join([f"a.{_sanitize(c)} = b.{_sanitize(c)}" for c in det_cols]) or "FALSE"

    # Probabilistic weighted score expression
    if prob_cols:
        weighted_terms = []
        for a in prob_cols:
            col = _sanitize(a["name"])
            w = float(a.get("weight", 0)) / 100.0
            weighted_terms.append(
                f"({w} * IF(SOUNDEX(a.{col}) = SOUNDEX(b.{col}), 1.0, 0.0) * 0.5 + "
                f"{w} * (1 - EDIT_DISTANCE(a.{col}, b.{col}) / GREATEST(LENGTH(a.{col}), LENGTH(b.{col}), 1)) * 0.5)"
            )
        prob_score = " + ".join(weighted_terms)
    else:
        prob_score = "0.0"

    master_sql = f"""-- ============================================================
-- STATE 4a: Curated Master Table (Golden Records)
-- ============================================================
CREATE OR REPLACE TABLE {fq}.{mst_t}`
PARTITION BY DATE(ingested_at)
CLUSTER BY enterprise_id AS
WITH pairs AS (
  SELECT
    a.record_uid AS uid_a,
    b.record_uid AS uid_b,
    CASE WHEN {det_join} THEN 1.0 ELSE {prob_score} END AS score
  FROM {fq}.{stg_t}_{job_id}` a
  JOIN {fq}.{stg_t}_{job_id}` b
    ON a.record_uid < b.record_uid
),
clusters AS (
  SELECT uid_a AS uid, MIN(uid_b) AS cluster_root
  FROM pairs WHERE score >= {threshold}
  GROUP BY uid_a
  UNION ALL
  SELECT record_uid, record_uid FROM {fq}.{stg_t}_{job_id}`
),
final_clusters AS (
  SELECT uid, MIN(cluster_root) AS enterprise_id FROM clusters GROUP BY uid
),
joined AS (
  SELECT s.*, fc.enterprise_id
  FROM {fq}.{stg_t}_{job_id}` s
  JOIN final_clusters fc ON s.record_uid = fc.uid
)
SELECT
  enterprise_id,
  CASE
    WHEN COUNT(*) > 1 AND MAX(IF(/*det_match*/ TRUE, 1, 0)) = 1 THEN 'deterministic'
    WHEN COUNT(*) > 1 THEN 'probabilistic'
    ELSE 'unique'
  END AS match_method,
{(',' + chr(10)).join(golden_lines) or "  ANY_VALUE(record_uid) AS golden_record_uid"},
  COUNT(*) AS source_record_count,
  CURRENT_TIMESTAMP() AS ingested_at
FROM joined
GROUP BY enterprise_id;"""

    # ---------- 4. Suspect Table ----------
    explanation_terms = []
    for a in prob_cols:
        col = _sanitize(a["name"])
        explanation_terms.append(
            f"IF(SOUNDEX(a.{col}) = SOUNDEX(b.{col}), '{a['name']} phonetic match; ', '{a['name']} differs; ')"
        )
    explain_expr = " || ".join(explanation_terms) if explanation_terms else "'See score'"

    suspect_sql = f"""-- ============================================================
-- STATE 4b: Curated Suspect Table (Duplicates above threshold)
-- ============================================================
CREATE OR REPLACE TABLE {fq}.{sus_t}`
PARTITION BY DATE(ingested_at)
CLUSTER BY parent_enterprise_id AS
SELECT
  fc_a.enterprise_id AS parent_enterprise_id,
  a.record_uid AS suspect_record_uid,
  ROUND(p.score * 100, 2) AS suspect_score,
  CASE
    WHEN {det_join} THEN 'Deterministic exact match on {", ".join(det_cols) or "n/a"}'
    ELSE 'Probabilistic weighted match >= {int(threshold*100)}%'
  END AS suspect_reason,
  {explain_expr} AS match_explanation,
{(',' + chr(10)).join([f'  a.{_sanitize(c)}' for c in all_cols]) or '  a.record_uid'},
  CURRENT_TIMESTAMP() AS ingested_at
FROM (
  SELECT
    a.record_uid AS uid_a,
    b.record_uid AS uid_b,
    CASE WHEN {det_join} THEN 1.0 ELSE {prob_score} END AS score
  FROM {fq}.{stg_t}_{job_id}` a
  JOIN {fq}.{stg_t}_{job_id}` b ON a.record_uid < b.record_uid
) p
JOIN {fq}.{stg_t}_{job_id}` a ON a.record_uid = p.uid_a
JOIN {fq}.{stg_t}_{job_id}` b ON b.record_uid = p.uid_b
JOIN (SELECT uid, MIN(cluster_root) AS enterprise_id FROM clusters GROUP BY uid) fc_a
  ON fc_a.uid = a.record_uid
WHERE p.score >= {threshold};"""

    # ---------- 5. Search Index ----------
    index_sql = f"""-- ============================================================
-- Search Index on Curated Master for sub-second identity lookup
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
