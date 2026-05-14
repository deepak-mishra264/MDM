"""File handling, gcp_config.yaml, user_intent_store.json persistence."""
import json
import os
from pathlib import Path
from typing import Any, Dict
import yaml

ROOT = Path(__file__).resolve().parent.parent
STORAGE_DIR = ROOT / "storage"
CONFIGS_DIR = ROOT / "configs"
GCP_CONFIG_PATH = CONFIGS_DIR / "gcp_config.yaml"
INTENT_STORE_PATH = CONFIGS_DIR / "user_intent_store.json"

STORAGE_DIR.mkdir(parents=True, exist_ok=True)
CONFIGS_DIR.mkdir(parents=True, exist_ok=True)


def read_gcp_config() -> Dict[str, Any]:
    if not GCP_CONFIG_PATH.exists():
        return {}
    with open(GCP_CONFIG_PATH, "r") as f:
        return yaml.safe_load(f) or {}


def write_gcp_config(config: Dict[str, Any]) -> Dict[str, Any]:
    with open(GCP_CONFIG_PATH, "w") as f:
        yaml.safe_dump(config, f, sort_keys=False)
    return config


def read_intent_store() -> Dict[str, Any]:
    if not INTENT_STORE_PATH.exists():
        return {"jobs": {}}
    with open(INTENT_STORE_PATH, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {"jobs": {}}


def write_intent_store(store: Dict[str, Any]) -> None:
    with open(INTENT_STORE_PATH, "w") as f:
        json.dump(store, f, indent=2, default=str)


def upsert_job_intent(job_id: str, intent: Dict[str, Any]) -> Dict[str, Any]:
    store = read_intent_store()
    store.setdefault("jobs", {})[job_id] = intent
    write_intent_store(store)
    return intent


def get_job_intent(job_id: str) -> Dict[str, Any] | None:
    store = read_intent_store()
    return store.get("jobs", {}).get(job_id)


def save_uploaded_file(job_id: str, filename: str, content: bytes) -> str:
    job_dir = STORAGE_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    path = job_dir / filename
    with open(path, "wb") as f:
        f.write(content)
    return str(path)


def get_job_file(job_id: str) -> Path | None:
    job_dir = STORAGE_DIR / job_id
    if not job_dir.exists():
        return None
    files = list(job_dir.iterdir())
    return files[0] if files else None
