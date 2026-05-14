"""Google Cloud Platform client wrapper.

Provides Vertex AI Gemini, BigQuery, and Cloud Storage integrations.
On import-time failure (dummy/invalid service-account JSON), client
methods raise a typed GCPUnavailable error so callers can degrade
gracefully to preview mode.
"""
from __future__ import annotations
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("searce-mdm.gcp")


class GCPUnavailable(RuntimeError):
    """Raised when GCP calls fail (bad creds, network, etc.)."""


def _resolve_creds_path() -> Optional[Path]:
    p = os.environ.get("VERTEX_AI_CREDS_PATH") or os.environ.get(
        "GOOGLE_APPLICATION_CREDENTIALS"
    )
    if p:
        path = Path(p)
        if path.exists():
            return path
    # default location
    default = Path(__file__).resolve().parent.parent / "configs" / "gcp_service_account.json"
    return default if default.exists() else None


def _looks_dummy(creds_path: Path) -> bool:
    try:
        data = json.loads(creds_path.read_text())
        pk = data.get("private_key", "")
        return "PLACEHOLDER" in pk or len(pk) < 200
    except Exception:
        return True


class GCPClient:
    """Singleton-ish GCP client wrapper."""

    def __init__(self):
        self.creds_path: Optional[Path] = _resolve_creds_path()
        self.is_dummy: bool = (
            self.creds_path is None or _looks_dummy(self.creds_path)
        )
        self.project_id: Optional[str] = None
        self._sa_credentials = None
        self._bq_client = None
        self._gcs_client = None
        self._genai_client = None
        self._load_credentials()

    # ----- credentials -----
    def _load_credentials(self):
        if not self.creds_path:
            logger.info("[gcp] no service-account file found → preview mode")
            return
        try:
            data = json.loads(self.creds_path.read_text())
            self.project_id = data.get("project_id")
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(self.creds_path)
            if self.is_dummy:
                logger.info(
                    "[gcp] placeholder service-account detected (project=%s) "
                    "→ preview mode; SDK clients NOT initialized",
                    self.project_id,
                )
                return
            # only try to construct SDK clients with a real key
            from google.oauth2 import service_account

            self._sa_credentials = service_account.Credentials.from_service_account_file(
                str(self.creds_path)
            )
            logger.info("[gcp] live credentials loaded for project=%s", self.project_id)
        except Exception as e:
            logger.warning("[gcp] credential load failed: %s → preview mode", e)
            self.is_dummy = True

    # ----- live flag -----
    @property
    def is_live(self) -> bool:
        return not self.is_dummy and self._sa_credentials is not None

    # ----- BigQuery -----
    def bq(self):
        if not self.is_live:
            raise GCPUnavailable("BigQuery requires a real service-account key")
        if self._bq_client is None:
            from google.cloud import bigquery

            self._bq_client = bigquery.Client(
                project=self.project_id, credentials=self._sa_credentials
            )
        return self._bq_client

    def run_bigquery_sql(self, sql_layers: Dict[str, str]) -> Dict[str, Any]:
        """Execute the 5-layer SQL pipeline against BigQuery."""
        client = self.bq()
        results = {}
        for layer, sql in sql_layers.items():
            job = client.query(sql)
            job.result()  # blocks until done
            results[layer] = {"job_id": job.job_id, "state": "DONE"}
        return results

    # ----- GCS -----
    def gcs(self):
        if not self.is_live:
            raise GCPUnavailable("Cloud Storage requires a real service-account key")
        if self._gcs_client is None:
            from google.cloud import storage

            self._gcs_client = storage.Client(
                project=self.project_id, credentials=self._sa_credentials
            )
        return self._gcs_client

    def upload_to_gcs(
        self, bucket: str, blob_path: str, content: bytes, content_type: str = "text/csv"
    ) -> str:
        client = self.gcs()
        b = client.bucket(bucket).blob(blob_path)
        b.upload_from_string(content, content_type=content_type)
        return f"gs://{bucket}/{blob_path}"

    # ----- Vertex AI Gemini -----
    def gemini(self):
        if not self.is_live:
            raise GCPUnavailable("Vertex AI requires a real service-account key")
        if self._genai_client is None:
            from google import genai

            self._genai_client = genai.Client(
                vertexai=True,
                project=self.project_id,
                location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
            )
        return self._genai_client

    def gemini_text(self, prompt: str, system: str, model: str = "gemini-2.5-pro") -> str:
        client = self.gemini()
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config={"system_instruction": system, "temperature": 0.2},
        )
        return resp.text or ""


_singleton: Optional[GCPClient] = None


def get_gcp() -> GCPClient:
    global _singleton
    if _singleton is None:
        _singleton = GCPClient()
    return _singleton
