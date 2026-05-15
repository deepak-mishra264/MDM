"""Searce MDM backend API tests — iteration 2 schema (match_columns + survivorship_rules)."""
import os
import time

import pytest
import requests

def _load_frontend_env():
    p = "/app/frontend/.env"
    if os.path.exists(p):
        with open(p) as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    return line.split("=", 1)[1].strip()
    return os.environ.get("REACT_APP_BACKEND_URL", "")


BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or _load_frontend_env()).rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL not set in env or /app/frontend/.env"
API = f"{BASE_URL}/api"


@pytest.fixture(scope="session")
def session():
    return requests.Session()


@pytest.fixture(scope="session")
def demo_job(session):
    r = session.post(f"{API}/demo/load", timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def _payload(job_id, weights=(40, 30, 30), rules=None):
    cols = ["first_name", "last_name", "email"]
    body = {
        "job_id": job_id,
        "threshold": 0.75,
        "match_columns": [
            {"name": cols[i], "weight": weights[i]} for i in range(len(cols))
        ],
        "survivorship_rules": rules
        or [
            {"column": "email", "rule": "Pick most recent non-null", "precedence": 1},
            {"column": "last_name", "rule": "Most frequent value", "precedence": 2},
        ],
    }
    return body


# ---------- Health ----------
def test_health(session):
    r = session.get(f"{API}/health", timeout=15)
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "ok"
    assert j["llm_ready"] is True


# ---------- Demo ----------
def test_demo_load(demo_job):
    assert "job_id" in demo_job
    assert demo_job["row_count"] == 20
    assert isinstance(demo_job["columns"], list) and len(demo_job["columns"]) >= 6


# ---------- Intent: new schema ----------
def test_intent_reject_empty_match_columns(session, demo_job):
    body = {"job_id": demo_job["job_id"], "match_columns": [], "survivorship_rules": []}
    r = session.post(f"{API}/intent/save", json=body, timeout=15)
    assert r.status_code == 400
    assert "at least one column" in r.text.lower() or "column" in r.text.lower()


def test_intent_reject_sum_99(session, demo_job):
    r = session.post(f"{API}/intent/save", json=_payload(demo_job["job_id"], (40, 30, 29)), timeout=15)
    assert r.status_code == 400
    assert "100" in r.text


def test_intent_reject_sum_101(session, demo_job):
    r = session.post(f"{API}/intent/save", json=_payload(demo_job["job_id"], (40, 30, 31)), timeout=15)
    assert r.status_code == 400


def test_intent_accept_sum_100_and_sorts_rules(session, demo_job):
    # Submit rules in non-sorted order to verify backend sorts by precedence
    rules = [
        {"column": "last_name", "rule": "Most frequent", "precedence": 3},
        {"column": "email", "rule": "Most recent non-null", "precedence": 1},
        {"column": "first_name", "rule": "Longest value", "precedence": 2},
    ]
    r = session.post(
        f"{API}/intent/save",
        json=_payload(demo_job["job_id"], (40, 30, 30), rules=rules),
        timeout=15,
    )
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["saved"] is True
    sr = saved["intent"]["survivorship_rules"]
    assert [x["precedence"] for x in sr] == [1, 2, 3]
    assert sr[0]["column"] == "email"

    # GET intent endpoint
    r2 = session.get(f"{API}/intent/{demo_job['job_id']}", timeout=15)
    assert r2.status_code == 200
    intent = r2.json()
    assert len(intent["match_columns"]) == 3
    assert intent["match_columns"][0]["name"] == "first_name"


# ---------- Agent strategy ----------
def test_agent_strategy_new_schema(session, demo_job):
    r = session.post(f"{API}/agent/strategy/{demo_job['job_id']}", timeout=60)
    assert r.status_code == 200, r.text
    j = r.json()
    assert isinstance(j.get("summary"), str) and len(j["summary"]) > 10
    assert "backend" in j


# ---------- Pipeline: async + staged ----------
def test_pipeline_execute_async_and_progress(session, demo_job):
    r = session.post(f"{API}/pipeline/execute/{demo_job['job_id']}", timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["state"] == "running"
    # 10 stages exist
    keys = [s["key"] for s in j["stages"]]
    expected = [
        "validating", "standardizing", "deterministic", "probabilistic",
        "embedding", "clustering", "survivorship", "sql", "bigquery", "complete",
    ]
    assert keys == expected

    # Poll progress until complete (or 60s timeout)
    deadline = time.time() + 60
    final = None
    while time.time() < deadline:
        pr = session.get(f"{API}/pipeline/progress/{demo_job['job_id']}", timeout=15)
        assert pr.status_code == 200
        data = pr.json()
        if data["state"] in ("complete", "failed"):
            final = data
            break
        time.sleep(0.8)

    assert final is not None, "Pipeline did not reach terminal state within 60s"
    assert final["state"] == "complete", f"Pipeline ended in: {final['state']}"

    states = {s["key"]: s["state"] for s in final["stages"]}
    # All non-bigquery stages must be done; bigquery should be 'skipped' in preview mode
    for k in ["validating", "standardizing", "deterministic", "probabilistic",
              "embedding", "clustering", "survivorship", "sql", "complete"]:
        assert states[k] == "done", f"stage {k} state={states[k]}"
    assert states["bigquery"] in ("skipped", "done"), f"bigquery={states['bigquery']}"


# ---------- Results ----------
def test_master_results_paginate(session, demo_job):
    r = session.get(f"{API}/results/master/{demo_job['job_id']}", params={"limit": 5, "offset": 0}, timeout=30)
    assert r.status_code == 200
    j = r.json()
    assert len(j["rows"]) > 0
    assert j["limit"] == 5 and j["offset"] == 0
    assert isinstance(j["total"], int) and j["total"] >= len(j["rows"])
    assert "enterprise_id" in j["rows"][0]


def test_suspect_results_paginate(session, demo_job):
    r = session.get(f"{API}/results/suspect/{demo_job['job_id']}", params={"limit": 50, "offset": 0}, timeout=30)
    assert r.status_code == 200
    j = r.json()
    # Demo data has known duplicates → at least one suspect
    assert len(j["rows"]) > 0
    assert "suspect_score" in j["rows"][0]


# ---------- SQL ----------
def test_get_sql_5_layers(session, demo_job):
    r = session.get(f"{API}/sql/{demo_job['job_id']}", timeout=30)
    assert r.status_code == 200
    j = r.json()
    for key in ("raw_layer", "staging_layer", "curated_master", "curated_suspect", "search_index"):
        assert key in j and len(j[key]) > 0


# ---------- Audit ----------
def test_audit(session):
    r = session.get(f"{API}/audit", timeout=30)
    assert r.status_code == 200
    j = r.json()
    assert j["count"] >= 1
