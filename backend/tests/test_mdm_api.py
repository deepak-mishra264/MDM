"""Searce MDM backend API tests — full lifecycle of a job."""
import io
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://golden-records.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="session")
def session():
    s = requests.Session()
    return s


@pytest.fixture(scope="session")
def demo_job(session):
    r = session.post(f"{API}/demo/load", timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------- Health ----------------
def test_health(session):
    r = session.get(f"{API}/health", timeout=15)
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "ok"
    assert j["mode"] == "preview"
    assert j["llm_ready"] is True


# ---------------- Demo / Upload ----------------
def test_demo_load(demo_job):
    assert "job_id" in demo_job
    assert demo_job["row_count"] == 20
    assert isinstance(demo_job["columns"], list) and len(demo_job["columns"]) >= 6
    assert isinstance(demo_job["sample"], list) and len(demo_job["sample"]) > 0


def test_upload_csv(session):
    csv = b"first_name,last_name,email\nJohn,Doe,j@x.com\nJane,Roe,jr@x.com\n"
    files = {"file": ("TEST_upload.csv", csv, "text/csv")}
    r = session.post(f"{API}/upload", files=files, timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["row_count"] == 2
    assert "job_id" in j and len(j["columns"]) == 3


# ---------------- Intent save ----------------
def _intent_payload(job_id, weights=(40, 30, 30)):
    cols = ["first_name", "last_name", "email"]
    return {
        "job_id": job_id,
        "threshold": 0.75,
        "attributes": [
            {"name": cols[0], "match_type": "probabilistic", "weight": weights[0], "survivorship_intent": "most recent"},
            {"name": cols[1], "match_type": "probabilistic", "weight": weights[1], "survivorship_intent": "longest"},
            {"name": cols[2], "match_type": "probabilistic", "weight": weights[2], "survivorship_intent": "most frequent"},
        ],
    }


def test_intent_save_rejects_99(session, demo_job):
    payload = _intent_payload(demo_job["job_id"], (40, 30, 29))
    r = session.post(f"{API}/intent/save", json=payload, timeout=15)
    assert r.status_code == 400
    assert "100" in r.text


def test_intent_save_rejects_101(session, demo_job):
    payload = _intent_payload(demo_job["job_id"], (40, 30, 31))
    r = session.post(f"{API}/intent/save", json=payload, timeout=15)
    assert r.status_code == 400


def test_intent_save_accepts_100_and_persists(session, demo_job):
    payload = _intent_payload(demo_job["job_id"], (40, 30, 30))
    r = session.post(f"{API}/intent/save", json=payload, timeout=15)
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["saved"] is True
    assert saved["intent"]["job_id"] == demo_job["job_id"]

    # Persistence: file-based audit trail
    intent_file = "/app/backend/configs/user_intent_store.json"
    assert os.path.exists(intent_file)
    import json as _json
    with open(intent_file) as f:
        store = _json.load(f)
    assert demo_job["job_id"] in store.get("jobs", {})

    # Verify GET intent endpoint
    r2 = session.get(f"{API}/intent/{demo_job['job_id']}", timeout=15)
    assert r2.status_code == 200
    assert r2.json()["threshold"] == 0.75


# ---------------- Agent strategy ----------------
def test_agent_strategy(session, demo_job):
    r = session.post(f"{API}/agent/strategy/{demo_job['job_id']}", timeout=60)
    assert r.status_code == 200, r.text
    j = r.json()
    assert isinstance(j.get("summary"), str) and len(j["summary"]) > 20
    assert isinstance(j.get("survivorship_breakdown"), list) and len(j["survivorship_breakdown"]) >= 1
    assert "backend" in j


# ---------------- Pipeline execution ----------------
def test_pipeline_execute(session, demo_job):
    r = session.post(f"{API}/pipeline/execute/{demo_job['job_id']}", timeout=120)
    assert r.status_code == 200, r.text
    j = r.json()
    stats = j["stats"]
    assert stats["total_records"] == 20
    assert stats["unique_masters"] > 0
    assert stats["duplicate_suspects"] > 0
    assert set(j["sql_layers"]) == {"raw_layer", "staging_layer", "curated_master", "curated_suspect", "search_index"}


# ---------------- Results ----------------
def test_master_results(session, demo_job):
    r = session.get(f"{API}/results/master/{demo_job['job_id']}", timeout=30)
    assert r.status_code == 200
    j = r.json()
    assert len(j["rows"]) > 0
    row = j["rows"][0]
    assert "enterprise_id" in row
    assert "match_method" in row
    # at least one golden_* field
    assert any(k.startswith("golden_") for k in row.keys())


def test_suspect_results(session, demo_job):
    r = session.get(f"{API}/results/suspect/{demo_job['job_id']}", timeout=30)
    assert r.status_code == 200
    j = r.json()
    assert len(j["rows"]) > 0, "Expected duplicate suspects on demo data"
    row = j["rows"][0]
    assert "suspect_score" in row
    assert "suspect_reason" in row
    assert "match_explanation" in row
    assert row["suspect_score"] >= 75


# ---------------- SQL ----------------
def test_get_sql_5_layers(session, demo_job):
    r = session.get(f"{API}/sql/{demo_job['job_id']}", timeout=30)
    assert r.status_code == 200
    j = r.json()
    for key in ("raw_layer", "staging_layer", "curated_master", "curated_suspect", "search_index"):
        assert key in j, f"missing {key}"
        assert len(j[key]) > 0


def test_download_sql(session, demo_job):
    r = session.get(f"{API}/sql/{demo_job['job_id']}/download", timeout=30)
    assert r.status_code == 200
    assert "STATE" in r.text or "LOAD DATA" in r.text or "CREATE" in r.text


# ---------------- Search ----------------
def test_identity_search(session, demo_job):
    # search for one of the known demo names
    r = session.get(f"{API}/search", params={"q": "doe", "job_id": demo_job["job_id"]}, timeout=30)
    assert r.status_code == 200
    j = r.json()
    assert j["count"] >= 1
    assert len(j["matches"]) >= 1


# ---------------- Audit + KPIs ----------------
def test_audit(session):
    r = session.get(f"{API}/audit", timeout=30)
    assert r.status_code == 200
    j = r.json()
    assert "jobs" in j
    assert j["count"] >= 1
    # verify sort desc by created_at when present
    created = [job.get("created_at") for job in j["jobs"] if job.get("created_at")]
    assert created == sorted(created, reverse=True)


def test_dashboard_kpis(session):
    r = session.get(f"{API}/dashboard/kpis", timeout=30)
    assert r.status_code == 200
    j = r.json()
    for k in ("total_jobs", "curated_jobs", "records_ingested", "golden_records", "duplicates_found"):
        assert k in j


# ---------------- GCP Config ----------------
def test_get_and_put_gcp_config(session):
    r = session.get(f"{API}/config/gcp", timeout=15)
    assert r.status_code == 200
    cfg = r.json()
    assert isinstance(cfg, dict) and len(cfg) > 0
    original = dict(cfg)
    # PUT a slightly modified config
    new_cfg = dict(cfg)
    new_cfg["_test_marker"] = "TEST_marker"
    r2 = session.put(f"{API}/config/gcp", json={"config": new_cfg}, timeout=15)
    assert r2.status_code == 200
    assert r2.json().get("_test_marker") == "TEST_marker"
    # restore
    session.put(f"{API}/config/gcp", json={"config": original}, timeout=15)
