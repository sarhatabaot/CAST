# Importing a legacy CAST installation into the dockerized CAST

Runbook for migrating an **old (non-docker) CAST** deployment onto **this
dockerized version**. The legacy install kept everything in-tree (SQLite DB +
media files under the project dir); the dockerized version runs the same Django
app but on SQLite in a mounted `data/` dir with media in a `media_data` volume.

"Importing" = bringing two things across: the **database** and the **media tree**
(cutouts). They are a pair — the DB stores *relative* file paths; the media files
hold the bytes. Bring only the DB and every cutout is a broken link.

> Companion docs: [migration-history reconciliation](#step-2--reconcile-migration-history),
> [docs/galaxy-association.md](docs/galaxy-association.md), [docs/tns-daily-catalog-download.md](docs/tns-daily-catalog-download.md).

---

## 0. Prerequisites

- This repo checked out, Docker + Docker Compose available (commands below use
  `sudo docker …`).
- The legacy **`db.sqlite3`** file.
- Ideally the legacy **media directory** (`<legacy>/data/candidates/…`). If you
  can't get it, cutouts are regenerated locally in Step 6.
- The `/transients` data mount available on the host
  (`/mnt/euclid/last/data/transients`) — needed to regenerate `ref/new/diff`
  cutouts and for ongoing ingest.

---

## 1. Obtain the legacy SQLite DB safely

Do **not** `cp` a database that's being written to — a plain copy can be torn, and
a WAL-mode DB needs its `-wal`/`-shm` sidecars. Either:

- Quiesce the legacy app (stop web + ingest cron), then copy the file, **or**
- Take a consistent online snapshot:
  ```bash
  sqlite3 /path/to/legacy/db.sqlite3 ".backup /tmp/cast_snapshot.sqlite3"
  ```

Keep a second copy as a rollback point — migrations rewrite the file in place.

---

## 2. Reconcile migration history

**Why this step exists:** the legacy DB's `candidates` migration history and this
repo's can diverge. In our case the original dev repo stopped at `0021`; the live
DB had gone on to `0022–0027` (incremental single-field migrations that were never
committed); and this branch had independently written a *squashed* `0022` plus a
new data migration. Same final schema, incompatible bookkeeping → a naive `migrate`
tries to re-add existing columns and fails with `duplicate column name`.

**How it was resolved in this repo (already done on `docker-minimal`):**

- Added the dev's real `0022`–`0027` verbatim (they match the live DB's names):
  ```
  0022_candidate_dist_mpc_candidate_host_galaxy
  0023_candidate_redshift
  0024_candidate_too_name
  0025_candidate_classification
  0026_candidate_reported_to_astro_colibri
  0027_candidate_marked_for_followup
  ```
- Removed the squashed `0022_candidate_too_name_candidate_classification_and_more`.
- Renumbered the target-comments data migration `0023 → 0028`, depending on `0027`.
- Added `0029` with the `AlterField`s that widen `name`/`filename`/`reference` to
  `max_length=150` (the live `candidatealert.filename` reaches 133 chars, so 150 is
  required — the dev's model at 100 under-declares reality).

**If you hit this again with a *different* legacy DB:** compare applied migrations to
the files on disk, and make the on-disk history a **prefix-match** of what the DB has
already applied, appending only new migrations:
```bash
# applied in the DB:
sqlite3 legacy.sqlite3 "select app,name from django_migrations where app='candidates' order by id"
# files on disk:
ls app/candidates/migrations
```
Confirm the graph is clean before deploying:
```bash
# from app/, offline (no DB writes):
DB_ENGINE=django.db.backends.sqlite3 DB_DATABASE=/tmp/throwaway.sqlite3 \
  .venv/bin/python manage.py makemigrations candidates --check --dry-run
# -> "No changes detected in app 'candidates'"
```

**What `migrate` will do against the live DB:** `candidates 0001–0027` are already
applied (names match — no fakes), so it applies only `0028` + `0029`, **plus** the
third-party framework catch-up (this branch pins newer `tomtoolkit`, so e.g.
`tom_targets 0022–0030` run against your data). That's expected — run it on the
copy first.

---

## 3. Switch the app to SQLite (already configured here)

`.env`:
```
DB_ENGINE=django.db.backends.sqlite3
DB_DATABASE=/data/db.sqlite3
# (the Postgres DB_* lines are commented out, kept for easy revert)
```

`docker-compose.yml`:
- `web` and `migrate` mount `./data:/data` (the DB lives at `data/db.sqlite3`).
- The Postgres `db` service, its two `depends_on` refs, and the `postgres_data`
  volume are **commented out** (not deleted) — uncomment all of them + swap the
  `.env` DB_* lines to switch back to Postgres.

> Note: `MEDIA_ROOT=/app/data` (the `media_data` volume) is unrelated to the SQLite
> mount at `/data` — one is the media dir, the other the DB file.

---

## 4. Place the DB

```bash
mkdir -p data
cp /tmp/cast_snapshot.sqlite3 data/db.sqlite3   # git-ignored (data/ + *.sqlite3)
```

---

## 5. Deploy & migrate

```bash
CAST_VERSION=$(date +%Y.%m.%d)-0 sudo docker compose up -d --build
sudo docker compose logs -f migrate    # watch the migration pass
```

The `migrate` service applies `candidates 0028/0029` + the `tom_*` catch-up, then
`collect-static` runs and `web` comes up. **If migrate fails:** restore and retry:
```bash
cp /tmp/cast_snapshot.sqlite3 data/db.sqlite3
```

---

## 6. Restore cutouts (media)

The DB rows point at `candidates/<name>/<file>` under `MEDIA_ROOT`, but the fresh
`media_data` volume is empty. Two paths:

**A. You have the legacy media tree** — copy it into the volume:
```bash
sudo docker cp /path/to/legacy/data/candidates cast-web:/app/data/
```

**B. Regenerate locally** (what to do when the old media is gone). `ref/new/diff`
rebuild from the `/transients` mount for free; `ps1/sdss` are re-fetched from the
web. Idempotent (skips cutouts whose file already exists); newest-per-type wins in
the UI, so old broken rows are shadowed automatically.
```bash
# trial:
sudo docker compose exec web uv run manage.py regenerate_cutouts --limit 20 --dry-run
# full local rebuild (ref/new/diff, no network):
sudo docker compose exec web uv run manage.py regenerate_cutouts
# optional web re-fetch (slow / rate-limited):
sudo docker compose exec -d web uv run manage.py regenerate_cutouts --types ps1,sdss
```

---

## 7. Versioning

CAST uses **CalVer `YYYY.MM.DD-N`** (build date + same-day build number), exposed by
`CAST_VERSION` and shown in the navbar (`v2026.07.15-0`).

- Runtime source of truth: `CAST_VERSION` in `.env` (read by
  `settings.CAST_VERSION`, surfaced to templates via
  `candidates.context_processors.cast_version`). Defaults to `dev` if unset.
- **Bump on each deploy:** edit `.env` (`CAST_VERSION=2026.07.16-0`) and restart, or
  pass it inline: `CAST_VERSION=$(date +%Y.%m.%d)-0 sudo docker compose up -d`.
- Increment the `-N` suffix for multiple builds on the same day.

*(Optional CI automation: bake it at image build with a Dockerfile
`ARG CAST_VERSION` → `ENV CAST_VERSION`, passed via compose `build.args`. Not wired
by default — the runtime env var is simpler.)*

---

## 8. Post-import verification checklist

- [ ] `migrate` completed without error (check `logs migrate`).
- [ ] Login works; existing accounts present.
- [ ] Candidate real/bogus + classification state persisted.
- [ ] Navbar shows the expected `vYYYY.MM.DD-N`.
- [ ] Candidates list paints fast; photometry plots stream in per row.
- [ ] Cutouts render (after Step 6). Spot-check a few candidates.
- [ ] A fresh ingest run still works: `sudo docker compose exec web uv run manage.py ingest_candidates --cutoff 1`.

---

## Rollback (to Postgres or a clean DB)

1. Restore `data/db.sqlite3` from your snapshot (or point `DB_DATABASE` elsewhere).
2. To revert to Postgres: uncomment the `db` service + `depends_on` + `postgres_data`
   volume in `docker-compose.yml`, and swap the `.env` DB_* lines back.
3. `sudo docker compose up -d --build`.
