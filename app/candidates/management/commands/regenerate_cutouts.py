"""
Regenerate missing candidate cutout files.

Context: cutout *files* live under MEDIA_ROOT (the `media_data` volume), while the
DB only stores their relative paths. When the DB is migrated to a fresh deployment
without its media tree, every cutout path points at a missing file. This command
rebuilds them:

  * ref / new / diff -> copied from the local transients mount
    (settings.TRANSIENT_DIR/cutouts), using each candidate's latest alert's
    *_cutout_filename. No network.
  * ps1 / sdss       -> re-fetched from the web (slow; opt-in via --types).

It is idempotent: for each (candidate, type) it checks whether the current newest
cutout's file actually exists on disk and skips it unless --force is given. The
UI shows the newest cutout per type, so regenerated rows automatically supersede
the broken ones; old rows are left in place (harmless).

Run inside the web container (it has /transients and the media volume mounted):

    docker compose exec web uv run manage.py regenerate_cutouts --limit 20 --dry-run
    docker compose exec web uv run manage.py regenerate_cutouts            # ref/new/diff, all
    docker compose exec web uv run manage.py regenerate_cutouts --types ps1,sdss  # web re-fetch
"""
from __future__ import annotations

import logging
import os

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError

from candidates.models import Candidate, CandidateAlert, CandidateDataProduct
from candidates.services.enrichment import try_add_cutout
from candidates.utils import create_candidate_cutouts, fetch_ps1_cutout, fetch_sdss_cutout

logger = logging.getLogger(__name__)

LOCAL_TYPES = ("ref", "new", "diff")
WEB_TYPES = ("ps1", "sdss")
ALL_TYPES = LOCAL_TYPES + WEB_TYPES

ALERT_FIELD = {
    "ref": "ref_cutout_filename",
    "new": "new_cutout_filename",
    "diff": "diff_cutout_filename",
}
WEB_FETCH = {
    "ps1": (fetch_ps1_cutout, "PS1 cutout"),
    "sdss": (fetch_sdss_cutout, "SDSS cutout"),
}


def _latest_cutout(candidate, ptype):
    return (
        CandidateDataProduct.objects
        .filter(candidate=candidate, data_product_type=ptype)
        .exclude(datafile="")
        .exclude(datafile__isnull=True)
        .order_by("-created_at")
        .first()
    )


def _has_file_on_disk(candidate, ptype) -> bool:
    dp = _latest_cutout(candidate, ptype)
    if not dp or not dp.datafile:
        return False
    try:
        return default_storage.exists(dp.datafile.name)
    except Exception:
        return False


class Command(BaseCommand):
    help = (
        "Regenerate missing candidate cutouts: ref/new/diff from the local transients "
        "mount, ps1/sdss re-fetched from the web (opt-in). Idempotent."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--types",
            default="ref,new,diff",
            help="Comma-separated subset of ref,new,diff,ps1,sdss (or 'all'). "
                 "Default is the local-only set 'ref,new,diff'.",
        )
        parser.add_argument("--limit", type=int, default=None, help="Process at most N candidates.")
        parser.add_argument("--candidate-id", type=int, default=None, help="Only this candidate id.")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Regenerate even when an on-disk file already exists.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be regenerated without writing anything.",
        )

    def handle(self, *args, **opts):
        raw = opts["types"].strip().lower()
        types = ALL_TYPES if raw == "all" else tuple(t.strip() for t in raw.split(",") if t.strip())
        unknown = [t for t in types if t not in ALL_TYPES]
        if unknown:
            raise CommandError(f"Unknown cutout type(s): {unknown}. Valid: {list(ALL_TYPES)}")

        force = opts["force"]
        dry = opts["dry_run"]

        if any(t in WEB_TYPES for t in types) and not opts["limit"] and not opts["candidate_id"]:
            self.stdout.write(self.style.WARNING(
                "ps1/sdss re-fetch hits external services once per candidate and can take "
                "a long time / be rate-limited. Consider --limit for a trial run first."
            ))

        cutouts_dir = os.path.join(settings.TRANSIENT_DIR, "cutouts")

        qs = Candidate.objects.all().order_by("id")
        if opts["candidate_id"]:
            qs = qs.filter(id=opts["candidate_id"])
        if opts["limit"]:
            qs = qs[: opts["limit"]]

        stats = {t: {"made": 0, "skipped": 0, "no_source": 0, "failed": 0} for t in types}
        processed = 0

        for candidate in qs.iterator():
            processed += 1
            last_alert = None  # lazily fetched, only if a local type needs it

            for t in types:
                if not force and _has_file_on_disk(candidate, t):
                    stats[t]["skipped"] += 1
                    continue

                if t in LOCAL_TYPES:
                    if last_alert is None:
                        last_alert = (
                            CandidateAlert.objects
                            .filter(candidate=candidate)
                            .order_by("-created_at")
                            .first()
                        )
                    source = getattr(last_alert, ALERT_FIELD[t], None) if last_alert else None
                    if not source:
                        stats[t]["no_source"] += 1
                        continue
                    if not os.path.exists(os.path.join(cutouts_dir, source)):
                        stats[t]["no_source"] += 1
                        continue
                    if dry:
                        stats[t]["made"] += 1
                        continue
                    try:
                        create_candidate_cutouts(candidate, source, t)
                        stats[t]["made"] += 1
                    except Exception as e:
                        stats[t]["failed"] += 1
                        logger.warning("regen %s failed for candidate %s: %s", t, candidate.id, e)

                else:  # web type
                    if dry:
                        stats[t]["made"] += 1
                        continue
                    fetch_func, suffix = WEB_FETCH[t]
                    try:
                        try_add_cutout(
                            candidate=candidate,
                            fetch_func=fetch_func,
                            ra=candidate.ra,
                            dec=candidate.dec,
                            product_type=t,
                            name_suffix=suffix,
                        )
                        # try_add_cutout is best-effort; confirm a file actually landed
                        if _has_file_on_disk(candidate, t):
                            stats[t]["made"] += 1
                        else:
                            stats[t]["failed"] += 1
                    except Exception as e:
                        stats[t]["failed"] += 1
                        logger.warning("fetch %s failed for candidate %s: %s", t, candidate.id, e)

            if processed % 500 == 0:
                self.stdout.write(f"...processed {processed} candidates")

        verb = "would regenerate" if dry else "regenerated"
        self.stdout.write(self.style.SUCCESS(f"Done. Processed {processed} candidates."))
        for t in types:
            s = stats[t]
            self.stdout.write(
                f"  {t:5} {verb} {s['made']:6}  skipped(present) {s['skipped']:6}  "
                f"no-source {s['no_source']:6}  failed {s['failed']:6}"
            )
