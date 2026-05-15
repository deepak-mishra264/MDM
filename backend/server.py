"""Searce MDM Backend — AI-MDM Intelligence & Identity Portal."""
import asyncio
import io
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from dotenv import load_dotenv
from fastapi import APIRouter, BackgroundTasks, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from starlette.middleware.cors import CORSMiddleware

from mdm.agent import generate_strategy_summary
from mdm.gcp_client import GCPUnavailable, get_gcp
from mdm.matching_engine import run_pipeline_async
from mdm.sql_generator import generate_pipeline_sql
from mdm.storage import (
    get_job_file,
    get_job_intent,
    read_gcp_config,
    save_uploaded_file,
    upsert_job_intent,
    write_gcp_config,
)

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# Mongo
mongo_url = os.environ["MONGO_URL"]
db_name = os.environ.get("DB_NAME_MDM") or os.environ["DB_NAME"]
client = AsyncIOMotorClient(mongo_url)
db = client[db_name]

app = FastAPI(title="Searce MDM")
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("searce-mdm")


# ---------------- Models ----------------
class MatchColumn(BaseModel):
    name: str
    weight: float = 0.0


class SurvivorshipRule(BaseModel):
    column: str
    rule: str = ""
    precedence: int = 1


class IntentPayload(BaseModel):
    job_id: str
    match_columns: List[MatchColumn] = []
    survivorship_rules: List[SurvivorshipRule] = []
    threshold: float = 0.75


class GcpConfigPayload(BaseModel):
    config: Dict[str, Any]


# ---------------- Helpers ----------------
def _read_dataframe(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in (".xlsx", ".xls"):
        return pd.read_excel(path)
    if suffix == ".json":
        return pd.read_json(path)
    raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")


async def _record_job(job_id: str, payload: Dict[str, Any]) -> None:
    payload = {**payload, "job_id": job_id, "updated_at": datetime.now(timezone.utc).isoformat()}
    await db.jobs.update_one({"job_id": job_id}, {"$set": payload}, upsert=True)


async def _get_job(job_id: str) -> Optional[Dict[str, Any]]:
    return await db.jobs.find_one({"job_id": job_id}, {"_id": 0})


# ---------------- Routes ----------------
@api_router.get("/")
async def root():
    return {"service": "Searce MDM", "status": "ok"}


@api_router.get("/health")
async def health():
    cfg = read_gcp_config()
    gcp = get_gcp()
    return {
        "status": "ok",
        "mode": "live" if gcp.is_live else "preview",
        "config_mode": cfg.get("mode", "preview"),
        "vertex_ready": gcp.is_live,
        "gcp_project": gcp.project_id,
        "llm_ready": bool(os.environ.get("EMERGENT_LLM_KEY")),
    }


@api_router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    content = await file.read()
    job_id = uuid.uuid4().hex[:12]
    saved = save_uploaded_file(job_id, file.filename, content)
    try:
        df = _read_dataframe(Path(saved))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse file: {e}")

    columns = [str(c) for c in df.columns]
    sample = df.head(5).fillna("").astype(str).to_dict("records")

    # Attempt GCS upload if we have live credentials
    cfg = read_gcp_config()
    bucket = cfg.get("gcs_bucket", "searce-mdm-landing")
    gcs_uri = f"gs://{bucket}/landing/{job_id}/{file.filename}"
    gcs_state = "stubbed_local"
    gcp = get_gcp()
    if gcp.is_live:
        try:
            gcs_uri = gcp.upload_to_gcs(
                bucket=bucket,
                blob_path=f"landing/{job_id}/{file.filename}",
                content=content,
                content_type=file.content_type or "text/csv",
            )
            gcs_state = "uploaded_to_gcs"
        except (GCPUnavailable, Exception) as e:
            logger.warning("[upload] GCS upload failed: %s — keeping local copy", e)
            gcs_state = f"gcs_failed:{type(e).__name__}"

    await _record_job(
        job_id,
        {
            "job_id": job_id,
            "filename": file.filename,
            "saved_path": saved,
            "row_count": int(len(df)),
            "columns": columns,
            "sample": sample,
            "state": "gcs_landed",
            "gcs_uri": gcs_uri,
            "gcs_state": gcs_state,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return {
        "job_id": job_id,
        "filename": file.filename,
        "row_count": int(len(df)),
        "columns": columns,
        "sample": sample,
        "gcs_uri": gcs_uri,
        "gcs_state": gcs_state,
    }


@api_router.post("/demo/load")
async def load_demo():
    demo_path = ROOT_DIR / "configs" / "demo_customers.csv"
    if not demo_path.exists():
        raise HTTPException(status_code=404, detail="Demo dataset not found")
    with open(demo_path, "rb") as f:
        content = f.read()
    job_id = uuid.uuid4().hex[:12]
    saved = save_uploaded_file(job_id, "demo_customers.csv", content)
    df = _read_dataframe(Path(saved))
    columns = [str(c) for c in df.columns]
    sample = df.head(5).fillna("").astype(str).to_dict("records")
    await _record_job(
        job_id,
        {
            "job_id": job_id,
            "filename": "demo_customers.csv",
            "saved_path": saved,
            "row_count": int(len(df)),
            "columns": columns,
            "sample": sample,
            "state": "gcs_landed",
            "is_demo": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return {"job_id": job_id, "filename": "demo_customers.csv", "row_count": int(len(df)),
            "columns": columns, "sample": sample,
            "gcs_uri": f"gs://searce-mdm-landing/landing/{job_id}/demo_customers.csv"}


@api_router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = await _get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@api_router.post("/intent/save")
async def save_intent(payload: IntentPayload):
    intent = payload.model_dump()
    if not intent["match_columns"]:
        raise HTTPException(status_code=400, detail="Select at least one column for matching.")
    total = sum(c["weight"] for c in intent["match_columns"])
    if abs(total - 100.0) > 0.01:
        raise HTTPException(
            status_code=400,
            detail=f"Column weights must sum to exactly 100 (got {total:.2f}).",
        )
    # Survivorship rules optional; validate columns belong to matchable set or original columns
    job = await _get_job(intent["job_id"])
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    intent["source_file"] = job.get("filename")
    # Sort rules by precedence ascending (1 = highest priority)
    intent["survivorship_rules"] = sorted(
        intent.get("survivorship_rules", []), key=lambda r: r.get("precedence", 999)
    )
    upsert_job_intent(intent["job_id"], intent)
    await _record_job(intent["job_id"], {"intent": intent, "state": "intent_saved"})
    return {"saved": True, "intent": intent}


@api_router.get("/intent/{job_id}")
async def get_intent(job_id: str):
    intent = get_job_intent(job_id)
    if not intent:
        raise HTTPException(status_code=404, detail="No intent stored")
    return intent


@api_router.post("/agent/strategy/{job_id}")
async def agent_strategy(job_id: str):
    intent = get_job_intent(job_id)
    if not intent:
        raise HTTPException(status_code=404, detail="Save intent before requesting strategy")
    summary = await generate_strategy_summary(intent)
    await _record_job(job_id, {"strategy": summary})
    return summary


STAGE_LABELS = [
    ("validating", "Validating intent & schema"),
    ("standardizing", "Standardizing & normalizing records"),
    ("deterministic", "Running deterministic exact-match algorithm"),
    ("probabilistic", "Running probabilistic weighted fuzzy match"),
    ("embedding", "Generating vector embeddings (ML.GENERATE_EMBEDDING)"),
    ("clustering", "Clustering matches into enterprise_ids"),
    ("survivorship", "Applying survivorship rules to build golden records"),
    ("sql", "Generating BigQuery SQL for all 5 layers"),
    ("bigquery", "Executing pipeline on BigQuery"),
    ("complete", "Pipeline complete"),
]


def _init_stages() -> List[Dict[str, Any]]:
    return [
        {"key": k, "label": label, "state": "pending", "detail": {},
         "started_at": None, "finished_at": None}
        for k, label in STAGE_LABELS
    ]


# In-memory progress tracker (process-local; OK for single-pod preview deployment)
_progress_store: Dict[str, Dict[str, Any]] = {}


def _set_progress(job_id: str, stages: List[Dict[str, Any]], extras: Dict[str, Any] = None):
    _progress_store[job_id] = {
        "job_id": job_id,
        "stages": stages,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        **(extras or {}),
    }


def _update_stage(job_id: str, key: str, state: str, detail: Dict[str, Any] = None):
    snap = _progress_store.get(job_id)
    if not snap:
        return
    for s in snap["stages"]:
        if s["key"] == key:
            now = datetime.now(timezone.utc).isoformat()
            s["state"] = state
            if state == "running" and not s["started_at"]:
                s["started_at"] = now
            if state in ("done", "failed", "skipped"):
                s["finished_at"] = now
            if detail:
                s["detail"].update(detail)
            break
    snap["updated_at"] = datetime.now(timezone.utc).isoformat()


async def _run_pipeline_task(job_id: str):
    """Background task that walks the pipeline emitting progress."""
    try:
        intent = get_job_intent(job_id)
        if not intent:
            _update_stage(job_id, "validating", "failed", {"error": "No intent saved"})
            return
        job = await _get_job(job_id)
        if not job:
            _update_stage(job_id, "validating", "failed", {"error": "Job not found"})
            return
        saved = job.get("saved_path") or (
            str(get_job_file(job_id)) if get_job_file(job_id) else None
        )
        if not saved:
            _update_stage(job_id, "validating", "failed", {"error": "File missing"})
            return

        df = _read_dataframe(Path(saved))
        # Pass full column list to SQL generator
        intent = {**intent, "all_columns": [str(c) for c in df.columns]}

        async def progress(key: str, state: str, detail: Dict[str, Any]):
            _update_stage(job_id, key, state, detail)

        result = await run_pipeline_async(
            df, intent, threshold=float(intent.get("threshold", 0.75)), progress=progress
        )

        # SQL generation
        _update_stage(job_id, "sql", "running")
        gcp_cfg = read_gcp_config()
        sql = generate_pipeline_sql(intent, gcp_cfg)
        _update_stage(job_id, "sql", "done", {"layers": list(sql.keys())})

        # BigQuery execute (live only)
        gcp = get_gcp()
        bq_state = "stubbed_local"
        bq_jobs: Dict[str, Any] = {}
        if gcp.is_live:
            _update_stage(job_id, "bigquery", "running")
            try:
                bq_jobs = gcp.run_bigquery_sql(sql)
                bq_state = "executed_on_bigquery"
                _update_stage(job_id, "bigquery", "done", {"jobs": list(bq_jobs.keys())})
            except (GCPUnavailable, Exception) as e:
                bq_state = f"bq_failed:{type(e).__name__}"
                _update_stage(job_id, "bigquery", "failed", {"error": str(e)})
        else:
            _update_stage(
                job_id, "bigquery", "skipped",
                {"note": "Preview mode — replace gcp_service_account.json to enable"},
            )

        # Persist results
        await db.results.update_one(
            {"job_id": job_id},
            {"$set": {
                "job_id": job_id,
                "master": result["master"],
                "suspect": result["suspect"],
                "stats": result["stats"],
                "sql": sql,
                "bq_state": bq_state,
                "bq_jobs": bq_jobs,
                "computed_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )
        await _record_job(
            job_id,
            {
                "state": "curated",
                "stats": result["stats"],
                "bq_state": bq_state,
                "lifecycle": {
                    "gcs_landed": True, "raw": True, "staging": True, "curated": True,
                },
            },
        )
        _update_stage(job_id, "complete", "done", {**result["stats"], "bq_state": bq_state})
    except Exception as e:
        logger.exception("[pipeline] task crashed")
        _update_stage(job_id, "complete", "failed", {"error": str(e)})


@api_router.post("/pipeline/execute/{job_id}")
async def execute_pipeline(job_id: str, background_tasks: BackgroundTasks):
    intent = get_job_intent(job_id)
    if not intent:
        raise HTTPException(status_code=404, detail="Save intent first")
    job = await _get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    stages = _init_stages()
    _set_progress(job_id, stages, {"state": "running"})
    background_tasks.add_task(_run_pipeline_task, job_id)
    return {"job_id": job_id, "state": "running", "stages": stages}


@api_router.get("/pipeline/progress/{job_id}")
async def pipeline_progress(job_id: str):
    snap = _progress_store.get(job_id)
    if not snap:
        # No active run — fall back to last-known lifecycle state from MongoDB
        job = await _get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if job.get("state") == "curated":
            stages = _init_stages()
            for s in stages:
                s["state"] = "done"
                s["finished_at"] = job.get("updated_at")
            return {
                "job_id": job_id, "stages": stages, "state": "complete",
                "stats": job.get("stats", {}),
                "bq_state": job.get("bq_state", "stubbed_local"),
            }
        return {"job_id": job_id, "stages": _init_stages(), "state": "idle"}
    # Determine top-level state
    all_done = all(s["state"] in ("done", "skipped") for s in snap["stages"])
    any_failed = any(s["state"] == "failed" for s in snap["stages"])
    top_state = "failed" if any_failed else "complete" if all_done else "running"
    return {**snap, "state": top_state}


@api_router.get("/pipeline/status/{job_id}")
async def pipeline_status(job_id: str):
    job = await _get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job_id,
        "state": job.get("state", "unknown"),
        "lifecycle": job.get("lifecycle", {
            "gcs_landed": True, "raw": False, "staging": False, "curated": False
        }),
        "stats": job.get("stats", {}),
    }


@api_router.get("/results/master/{job_id}")
async def master_results(job_id: str, limit: int = 50, offset: int = 0):
    res = await db.results.find_one({"job_id": job_id}, {"_id": 0})
    if not res:
        raise HTTPException(status_code=404, detail="No results yet")
    rows = res.get("master", [])
    total = len(rows)
    page = rows[offset : offset + limit]
    return {
        "job_id": job_id,
        "rows": page,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
    }


@api_router.get("/results/suspect/{job_id}")
async def suspect_results(job_id: str, limit: int = 50, offset: int = 0):
    res = await db.results.find_one({"job_id": job_id}, {"_id": 0})
    if not res:
        raise HTTPException(status_code=404, detail="No results yet")
    rows = sorted(res.get("suspect", []), key=lambda r: r.get("suspect_score", 0), reverse=True)
    total = len(rows)
    page = rows[offset : offset + limit]
    return {
        "job_id": job_id,
        "rows": page,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
    }


@api_router.get("/search")
async def identity_search(q: str = Query(..., min_length=1), job_id: str = Query(...)):
    res = await db.results.find_one({"job_id": job_id}, {"_id": 0})
    if not res:
        raise HTTPException(status_code=404, detail="No results to search")
    needle = q.lower().strip()
    hits = []
    for m in res.get("master", []):
        haystack = " ".join(str(v) for v in m.values() if v is not None).lower()
        if needle in haystack:
            hits.append(m)
    return {"query": q, "count": len(hits), "matches": hits[:50]}


@api_router.get("/sql/{job_id}")
async def get_sql(job_id: str):
    res = await db.results.find_one({"job_id": job_id}, {"_id": 0})
    if res and res.get("sql"):
        return res["sql"]
    intent = get_job_intent(job_id)
    if not intent:
        raise HTTPException(status_code=404, detail="Job not configured")
    return generate_pipeline_sql(intent, read_gcp_config())


@api_router.get("/sql/{job_id}/download", response_class=PlainTextResponse)
async def download_sql(job_id: str):
    res = await db.results.find_one({"job_id": job_id}, {"_id": 0})
    sql = res.get("sql") if res else None
    if not sql:
        intent = get_job_intent(job_id)
        if not intent:
            raise HTTPException(status_code=404, detail="Job not configured")
        sql = generate_pipeline_sql(intent, read_gcp_config())
    blob = "\n\n".join(sql.values())
    return PlainTextResponse(blob, headers={"Content-Disposition": f"attachment; filename=mdm_{job_id}.sql"})


@api_router.get("/audit")
async def audit_trail(limit: int = 100):
    jobs = await db.jobs.find({}, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return {"jobs": jobs, "count": len(jobs)}


@api_router.get("/dashboard/kpis")
async def dashboard_kpis():
    total_jobs = await db.jobs.count_documents({})
    curated = await db.jobs.count_documents({"state": "curated"})
    agg_stats = await db.results.find({}, {"_id": 0, "stats": 1}).to_list(1000)
    total_records = sum(s.get("stats", {}).get("total_records", 0) for s in agg_stats)
    total_masters = sum(s.get("stats", {}).get("unique_masters", 0) for s in agg_stats)
    total_suspects = sum(s.get("stats", {}).get("duplicate_suspects", 0) for s in agg_stats)
    return {
        "total_jobs": total_jobs,
        "curated_jobs": curated,
        "records_ingested": total_records,
        "golden_records": total_masters,
        "duplicates_found": total_suspects,
    }


@api_router.get("/config/gcp")
async def get_gcp_config():
    return read_gcp_config()


@api_router.put("/config/gcp")
async def put_gcp_config(payload: GcpConfigPayload):
    write_gcp_config(payload.config)
    return read_gcp_config()


# Mount router
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown():
    client.close()
