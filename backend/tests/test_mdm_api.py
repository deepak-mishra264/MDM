"""Searce MDM backend API tests — iteration 3 schema.

Schema:
  deterministic_columns: List[str]
  probabilistic_columns: List[{name, weight}]
  survivorship_rules:    List[{column, rule, precedence}]
"""
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
assert BASE_URL, "REACT_APP_BACKEND_URL not set"
API = f"{BASE_URL}/api"


@pytest.fixture(scope="session")
def session():
    return requests.Session()


@pytest.fixture(scope="session")
def demo_job(session):
    r = session.post(f"{API}/demo/load", timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def _payload(job_id, det=None, prob_weights=(40, 30, 30), rules=None):
    prob_cols = ["first_name", "last_name", "phone"]
    body = {
        "job_id": job_id,
        "threshold": 0.75,
        "deterministic_columns": det if det is not None else ["email"],
        "probabilistic_columns": [
            {"name": prob_cols[i], "weight": prob_weights[i]} for i in range(len(prob_weights))
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


# ---------- Intent: new schema ----------
def test_intent_reject_empty_both(session, demo_job):
    body = {
        "job_id": demo_job["job_id"],
        "deterministic_columns": [],
        "probabilistic_columns": [],
        "survivorship_rules": [],
    }
    r = session.post(f"{API}/intent/save", json=body, timeout=15)
    assert r.status_code == 400
    assert "at least one column" in r.text.lower()


def test_intent_reject_sum_99(session, demo_job):
    r = session.post(
        f"{API}/intent/save",
        json=_payload(demo_job["job_id"], prob_weights=(40, 30, 29)),
        timeout=15,
    )
    assert r.status_code == 400
    assert "100" in r.text


def test_intent_reject_sum_101(session, demo_job):
    r = session.post(
        f"{API}/intent/save",
        json=_payload(demo_job["job_id"], prob_weights=(40, 30, 31)),
        timeout=15,
    )
    assert r.status_code == 400


def test_intent_accept_sum_100(session, demo_job):
    r = session.post(
        f"{API}/intent/save",
        json=_payload(demo_job["job_id"], prob_weights=(40, 30, 30)),
        timeout=15,
    )
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["saved"] is True
    intent = saved["intent"]
    assert intent["deterministic_columns"] == ["email"]
    assert len(intent["probabilistic_columns"]) == 3


def test_intent_accept_deterministic_only(session, demo_job):
    """Det only — no weight check should run."""
    body = {
        "job_id": demo_job["job_id"],
        "deterministic_columns": ["email", "phone"],
        "probabilistic_columns": [],
        "survivorship_rules": [],
        "threshold": 0.75,
    }
    r = session.post(f"{API}/intent/save", json=body, timeout=15)
    assert r.status_code == 200, r.text
    intent = r.json()["intent"]
    assert intent["deterministic_columns"] == ["email", "phone"]
    assert intent["probabilistic_columns"] == []


def test_intent_sorts_rules(session, demo_job):
    rules = [
        {"column": "last_name", "rule": "Most frequent", "precedence": 3},
        {"column": "email", "rule": "Most recent non-null", "precedence": 1},
        {"column": "first_name", "rule": "Longest value", "precedence": 2},
    ]
    r = session.post(
        f"{API}/intent/save",
        json=_payload(demo_job["job_id"], prob_weights=(40, 30, 30), rules=rules),
        timeout=15,
    )
    assert r.status_code == 200, r.text
    sr = r.json()["intent"]["survivorship_rules"]
    assert [x["precedence"] for x in sr] == [1, 2, 3]

    # GET intent
    r2 = session.get(f"{API}/intent/{demo_job['job_id']}", timeout=15)
    assert r2.status_code == 200
    intent = r2.json()
    assert "deterministic_columns" in intent
    assert "probabilistic_columns" in intent


# ---------- Agent strategy ----------
def test_agent_strategy(session, demo_job):
    r = session.post(f"{API}/agent/strategy/{demo_job['job_id']}", timeout=60)
    assert r.status_code == 200, r.text
    j = r.json()
    assert isinstance(j.get("summary"), str) and len(j["summary"]) > 10
    assert "backend" in j


# ---------- Pipeline ----------
def test_pipeline_execute_and_progress(session, demo_job):
    r = session.post(f"{API}/pipeline/execute/{demo_job['job_id']}", timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["state"] == "running"
    keys = [s["key"] for s in j["stages"]]
    assert keys == [
        "validating", "standardizing", "deterministic", "probabilistic",
        "embedding", "clustering", "survivorship", "sql", "bigquery", "complete",
    ]

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
    assert final is not None
    assert final["state"] == "complete"

    states = {s["key"]: s for s in final["stages"]}
    for k in ["validating", "standardizing", "deterministic", "probabilistic",
              "embedding", "clustering", "survivorship", "sql", "complete"]:
        assert states[k]["state"] == "done"
    assert states["bigquery"]["state"] in ("skipped", "done")

    # Detail content checks per the new schema
    val_det = states["validating"]["detail"]
    assert "deterministic" in val_det and "probabilistic" in val_det
    assert isinstance(val_det["deterministic"], list)
    assert isinstance(val_det["probabilistic"], list)

    det_detail = states["deterministic"]["detail"]
    assert "keys" in det_detail

    prob_detail = states["probabilistic"]["detail"]
    assert "attrs" in prob_detail
    # weights present in attr strings like "first_name(40%)"
    assert any("%" in str(a) for a in prob_detail["attrs"])


# ---------- Results ----------
def test_master_results(session, demo_job):
    r = session.get(
        f"{API}/results/master/{demo_job['job_id']}",
        params={"limit": 5, "offset": 0}, timeout=30,
    )
    assert r.status_code == 200
    j = r.json()
    assert len(j["rows"]) > 0
    assert "enterprise_id" in j["rows"][0]


def test_suspect_results(session, demo_job):
    r = session.get(
        f"{API}/results/suspect/{demo_job['job_id']}",
        params={"limit": 50, "offset": 0}, timeout=30,
    )
    assert r.status_code == 200
    assert "rows" in r.json()


# ---------- SQL ----------
def test_get_sql_5_layers(session, demo_job):
    r = session.get(f"{API}/sql/{demo_job['job_id']}", timeout=30)
    assert r.status_code == 200
    j = r.json()
    for key in ("raw_layer", "staging_layer", "curated_master", "curated_suspect", "search_index"):
        assert key in j and len(j[key]) > 0


def test_audit(session):
    r = session.get(f"{API}/audit", timeout=30)
    assert r.status_code == 200
    assert r.json()["count"] >= 1
