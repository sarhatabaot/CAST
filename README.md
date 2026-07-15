# CAST: Candidate Alert System for Transients

**CAST** is a Target and Observation Manager (TOM) system designed to manage and follow up on astronomical transient candidates from the Large Array Survey Telescope (LAST; [Ofek et al. 2023](https://ui.adsabs.harvard.edu/abs/2023PASP..135f5001O/abstract)). It builds on the [TOM Toolkit](https://github.com/TOMToolkit/tom_base) and adds custom functionality such as a scanning page for the survey through the **Candidates** app.

> 📦 Migrating an existing (non-docker) CAST deployment onto this dockerized version? See [importing-legacy-cast.md](importing-legacy-cast.md).

---

## Overview

On top of the TOM Toolkit, CAST adds three apps:

- **Candidates** — the scanning page: ingestion of LAST alerts, coordinate-based clustering, cutouts, photometry (incl. ATLAS/ZTF forced photometry), host-galaxy association, and TNS / Astro-COLIBRI reporting.
- **LAST** — the observed-fields sky-coverage plot.
- **FP** — an on-demand forced-photometry tool.

It runs as a **Docker Compose** stack: a Django app served by **gunicorn**, a **Redis** cache, and an **ofelia** scheduler, backed by **SQLite** by default (Postgres optional).

## Requirements

- Docker and Docker Compose (v2)
- Read access to the LAST transients directory (mounted read-only into the `web` container)
- Credentials for the external services you plan to use: TNS, ATLAS, LASAIR, Astro-COLIBRI, and the LAST / forced-photometry ClickHouse databases

## Quick start

```bash
# 1. Clone
git clone https://github.com/erezimm/CAST.git && cd CAST

# 2. Configure environment (see "Configuration" below)
cp .env.example .env
#    → set at minimum SECRET_KEY and ALLOWED_HOSTS, plus DB + service credentials

# 3. Configure the large-file bootstrap (GLADE catalog, TNS catalog, sky fields)
cp large_files_manifest.example.json large_files_manifest.json
#    → adjust URLs / destination paths as needed

# 4. Point the transients mount at your data
#    docker-compose.yml → web service volumes:
#      - /mnt/euclid/last/data/transients:/transients:ro

# 5. Build and start
CAST_VERSION=$(date +%Y.%m.%d)-0 docker compose up -d --build
```

Then open **http://&lt;host&gt;:8000**.

Migrations and static collection run automatically (one-shot `migrate` and `collect-static` services) before `web` starts.

## Services

| Service | Role |
|---|---|
| `web` | Django app via gunicorn (port 8000) |
| `redis` | cache backend |
| `scheduler` | ofelia cron (TNS download → ingest → TNS match) |
| `migrate` | one-shot — applies DB migrations |
| `collect-static` | one-shot — `collectstatic` |
| `download-large-files` | one-shot — fetches catalogs/pickles per the manifest |

The Postgres `db` service is present but **commented out** (SQLite is the default) — see below to re-enable it.

## Configuration (`.env`)

**Core**
- `DEBUG` — `False` in production.
- `SECRET_KEY` — **required** (no default; the app fails to boot without it).
- `ALLOWED_HOSTS` — **required**, comma-separated.
- `CAST_VERSION` — CalVer `YYYY.MM.DD-N`, shown on the home page.

**Database** (SQLite by default)
- `DB_ENGINE=django.db.backends.sqlite3`, `DB_DATABASE=/data/db.sqlite3` (the file lives in the mounted `./data` dir; WAL mode is enabled automatically).
- To use **Postgres** instead: set `DB_ENGINE=…postgresql` + `DB_USER/PASSWORD/DATABASE/HOST/PORT`, and uncomment the `db` service, its two `depends_on` references, and the `postgres_data` volume in `docker-compose.yml`.

**Cache** — `CACHE_BACKEND=django.core.cache.backends.redis.RedisCache`, `CACHE_LOCATION=redis://:<REDIS_PASSWORD>@redis:6379/0`, and `REDIS_PASSWORD` (must match `CACHE_LOCATION`).

**External data DBs (ClickHouse)** — `LAST_DB` (observed-fields plot) and `FORCED_PHOTOMETRY_DB` (FP tool), each a JSON object.

**External services** — TNS (`TNS_API_KEY`, `TNS_BOT_ID`, `TNS_BOT_NAME`, `TNS_API_LOOKUPS_ENABLED`, and the `TNS_PUBLIC_OBJECTS_*` offline-catalog settings), `ATLAS_API_TOKEN`, `LASAIR_API_KEY`, and Astro-COLIBRI (`ASTRO_COLIBRI_*`).

> ⚠️ `TNS_TEST` (in `settings.py`) routes TNS submissions to the sandbox. Flip it off only when you intend to submit to the real TNS.

## Data & migrating from a legacy install

- The SQLite DB is `./data/db.sqlite3` (git-ignored). **Back it up before upgrades** — migrations rewrite it in place.
- Media (cutouts, data products) live in the `media_data` volume, served under `/data/…`.
- To import an existing **non-docker** CAST deployment — DB snapshot, migration-history reconciliation, the SQLite switch, and cutout regeneration — follow **[importing-legacy-cast.md](importing-legacy-cast.md)**.

## Scheduled jobs (ofelia)

Configured on the `scheduler` service (server timezone, `Asia/Jerusalem`):

| Time | Job |
|---|---|
| 06:30 | `download_tns_public_objects` — refresh the offline TNS catalog |
| 07:00 | `ingest_candidates --cutoff 1` — ingest new LAST alerts |
| 07:30 | `match_candidates_to_tns` — match candidates against the catalog |

## Management commands

Run inside the running web container:

```bash
sudo docker compose exec web uv run manage.py <command>
```

- `ingest_candidates [--cutoff N]` — ingest LAST alert JSON from the transients dir.
- `download_tns_public_objects` — download the public TNS catalog.
- `match_candidates_to_tns [--dry-run]` — match candidates against the local catalog.
- `regenerate_cutouts [--types ref,new,diff,ps1,sdss] [--limit N] [--dry-run]` — rebuild missing cutout files (`ref/new/diff` from the transients mount; `ps1/sdss` re-fetched from the web). Idempotent.

## Versioning

CAST uses CalVer **`YYYY.MM.DD-N`** via `CAST_VERSION` (build date + same-day build number), shown on the home page. Bump it per deploy:

```bash
CAST_VERSION=$(date +%Y.%m.%d)-0 sudo docker compose up -d
```

## Development notes

- The stack bind-mounts `./app` into the containers, so **restart `web` after any `.py` change** (`sudo docker compose restart web`). Template/CSS/JS edits show on the next request (no restart needed).
- Static assets (Plotly, Alpine, favicon, logo) are self-hosted and served by whitenoise; `collect-static` regenerates the hashed manifest on each build.

## Large-file bootstrap

Large reference files (GLADE catalog, LAST sky-fields pickle, TNS catalog) are fetched by the one-shot `download-large-files` service before the app starts.

1. Copy `large_files_manifest.example.json` → `large_files_manifest.json`.
2. Replace placeholder URLs, headers, and destination paths with your real sources.
3. `docker compose up` runs the download (existing files are skipped by default).
