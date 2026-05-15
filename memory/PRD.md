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

## What's Implemented (updated 2026-02-15 · LIVE MODE)
- **LIVE GCP MODE active** with the user's real service-account JSON (`searce-practice-data-analytics` project):
  - Vertex AI Gemini 2.5 Pro generates the Strategy Summary
  - GCS uploads CSV to `gs://searce-mdm-landing/landing/<job_id>/` (bucket auto-created)
  - BigQuery dataset `searce_mdm` auto-created; raw_layer/staging/master/suspect/search_index DDL+DML executed
- `/api/health` returns `mode=live`, `vertex_ready=true`, `gcp_project=searce-practice-data-analytics`. Sidebar shows green "Live mode · GCP active · Project · …".
- **SQL hardening** for live BigQuery:
  - LOAD DATA column list matches CSV exactly (metadata added in Staging stage)
  - "Most frequent" rule uses `APPROX_TOP_COUNT(col, 1)[SAFE_OFFSET(0)].value`
  - Clustering uses bi-directional edge union (uid_a↔uid_b) so all merged records share an enterprise_id
- All previous features preserved: column multi-select, survivorship rules with precedence, staged async pipeline with 10-step live progress, pagination, audit, identity search, SQL viewer with copy/download.

## Verified Live in BigQuery
- Demo dataset of 20 customer rows produced 13 master records (6 probabilistic clusters + 7 unique) in `searce_mdm.curated_master`, plus a populated `searce_mdm.curated_suspect` with suspect_score values in BigQuery.

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
