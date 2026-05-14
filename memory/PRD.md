# Searce MDM — AI-MDM Intelligence & Identity Portal (PRD)

## Original Problem Statement
Build a professional, cloud-native Identity Intelligence Portal named "Searce MDM."
The core innovation is an Agent-Driven Engine that interprets user-defined logic for
matching and survivorship in Plain English and converts it into scalable BigQuery
SQL. Manage a 3-tier data lifecycle (Raw → Staging → Curated) entirely within GCP.

## Architecture
- **Frontend**: React 19 + React Router + Shadcn UI + Tailwind. Theme: Swiss /
  Google-styled light theme. Fonts: Chivo (headings), IBM Plex Sans (body),
  JetBrains Mono (code).
- **Backend**: FastAPI (`/api` prefix), MongoDB (audit + result store), pandas,
  jellyfish (Soundex/Metaphone), rapidfuzz (token fuzzy), pyyaml.
- **LLM Agent**: Emergent Universal LLM key, model `gemini-3-flash-preview`.
  Architecture pluggable to Vertex AI Gemini when `VERTEX_AI_CREDS_PATH` is set.
- **GCP Layer**: Stubbed/preview mode — generates BigQuery SQL but does not
  execute. Files saved to `/app/backend/storage/<job_id>/` simulating
  `gs://<bucket>/landing/<job_id>/`.
- **Config Files**:
  - `/app/backend/configs/gcp_config.yaml` — static infra params (project, dataset, bucket).
  - `/app/backend/configs/user_intent_store.json` — per-job dynamic intent (attributes, match types, weights, NL prompts).

## User Personas
1. **Data Engineer** — uploads CSV/Excel/JSON, configures matching, downloads BigQuery SQL.
2. **Data Steward / Analyst** — reviews Master/Suspect records, searches identities,
   audits historical runs.
3. **Platform Architect** — edits `gcp_config.yaml`, swaps in Vertex AI creds for live mode.

## Core Requirements (Static)
- Plain-English Survivorship Intent textarea per attribute.
- Deterministic vs Probabilistic match type selector.
- Slider + Numeric input weight (sum must equal 100%).
- Agent Strategy Summary confirmation panel before execution.
- 4-state lifecycle (GCS → Raw → Staging → Curated Master + Suspect + Search Index).
- 75% threshold separates Unique Master from Suspect cluster.
- BigQuery SQL is auditable and downloadable.
- `user_intent_store.json` updated before pipeline → reproducible re-runs.

## What's Implemented (updated 2026-02-14)
- All v4.0 MVP features (hero upload, configure, agent strategy, pipeline, results, search, SQL viewer, audit, settings).
- **Pagination** on Master/Suspect endpoints + Results table footer (default page = 50, prev/next buttons, `has_more` flag).
- **Live-mode plumbing** for Vertex AI Gemini 2.5 Pro, BigQuery, and GCS via `mdm/gcp_client.py`:
  - Detects placeholder service-account JSON and falls back to preview mode without crashing.
  - On real credentials, upload → GCS, pipeline execute → BigQuery, agent → Vertex AI Gemini 2.5 Pro.
  - Emergent Gemini 3 Flash is the LLM in preview mode; deterministic rule-based summary as final fallback.
- `/api/health` reports `mode`, `vertex_ready`, `gcp_project`.
- Pipeline execution response now includes `bq_state` (`stubbed_local`, `executed_on_bigquery`, or `bq_failed:<error>`).
- Placeholder service-account JSON at `/app/backend/configs/gcp_service_account.json` — replace this single file with a real key to flip the app to live mode.

## API Endpoints (all `/api` prefixed)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | mode + LLM readiness |
| POST | `/upload` | multipart file → job_id |
| POST | `/demo/load` | load bundled demo dataset |
| GET | `/jobs/{job_id}` | job metadata |
| POST | `/intent/save` | persist user intent (validates weights = 100) |
| GET | `/intent/{job_id}` | fetch intent |
| POST | `/agent/strategy/{job_id}` | LLM strategy summary |
| POST | `/pipeline/execute/{job_id}` | run matching engine |
| GET | `/pipeline/status/{job_id}` | lifecycle state + stats |
| GET | `/results/master/{job_id}` | master records |
| GET | `/results/suspect/{job_id}` | suspect records sorted by score |
| GET | `/search?q=&job_id=` | identity search |
| GET | `/sql/{job_id}` | generated BQ SQL (5 layers) |
| GET | `/sql/{job_id}/download` | downloadable .sql blob |
| GET | `/audit` | jobs history |
| GET | `/dashboard/kpis` | aggregated KPIs |
| GET/PUT | `/config/gcp` | gcp_config.yaml CRUD |

## Backlog (P1/P2)
- P1: Live Vertex AI Gemini path (drop `VERTEX_AI_CREDS_PATH` into .env to activate).
- P1: Real BigQuery `LOAD DATA` execution (currently SQL-only).
- P1: Pagination on master/suspect tables (currently 200-row cap).
- P2: Export master records to GCS / CSV.
- P2: Reltio-style hierarchical relationship graph.
- P2: Multi-tenant auth (JWT or Emergent Google login).

## Mocked / Stubbed
- **GCP execution layer is MOCKED**. Files persist locally; BigQuery SQL is generated but not executed.
- The 4-state lifecycle is simulated by the in-memory matching engine.
- To go live: add a GCP Service Account JSON, set `VERTEX_AI_CREDS_PATH`, switch `mode: live` in `gcp_config.yaml`, and wire `google-cloud-bigquery` + `google-cloud-storage` SDKs.
