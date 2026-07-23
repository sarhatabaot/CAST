import os

from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.conf import settings

from candidates.ingestion import process_multiple_json_files
from candidates.services.locking import redis_lock

# Only one ingest may run at a time. The scheduler fires this every few minutes; if a
# run is still going (lots of new files + slow enrichment) the next tick must no-op
# rather than run concurrently and race on candidate creation.
INGEST_LOCK_KEY = "ingest:lock"
INGEST_LOCK_TTL = 60 * 30  # 30 min; comfortably longer than a run, auto-clears a crash

# High-water mark of the newest file mtime we've already scanned. Lets the frequent runs
# skip the whole directory/DB scan when nothing new has landed. Stored in the cache
# (Redis); if it's lost (e.g. Redis restart) the next run simply falls back to a full
# cutoff scan + DB dedup, which is safe, just more work once.
INGEST_WATERMARK_KEY = "ingest:max_mtime"


class Command(BaseCommand):
    help = "Ingest new candidate JSON files (incremental and safe for frequent runs)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--cutoff', type=int, default=3,
            help='Max age in days of files to consider.',
        )
        parser.add_argument(
            '--full', action='store_true',
            help='Ignore the mtime watermark and rescan everything within --cutoff '
                 '(the daily reconcile backstop; catches backfilled/odd-mtime files).',
        )
        parser.add_argument(
            '--settle-seconds', type=int, default=60,
            help='Skip files modified within this many seconds, so a half-written file '
                 'is never parsed mid-flight.',
        )

    def handle(self, *args, **options):
        cutoff = options['cutoff']
        full = options['full']
        settle = options['settle_seconds']
        directory = os.path.join(settings.TRANSIENT_DIR, "json")

        with redis_lock(INGEST_LOCK_KEY, INGEST_LOCK_TTL) as acquired:
            if not acquired:
                self.stdout.write(self.style.WARNING(
                    "Another ingest run is in progress; skipping this tick."
                ))
                return

            min_mtime = None if full else cache.get(INGEST_WATERMARK_KEY)
            try:
                outcome = process_multiple_json_files(
                    directory,
                    cutoff=cutoff,
                    min_mtime=min_mtime,
                    settle_seconds=settle,
                    full=full,
                )
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error processing files: {e}"))
                return

            # Advance the watermark forward-only, so nothing regresses it after a full run.
            if outcome.new_watermark is not None:
                prev = cache.get(INGEST_WATERMARK_KEY) or 0
                if outcome.new_watermark > prev:
                    cache.set(INGEST_WATERMARK_KEY, outcome.new_watermark, timeout=None)

            self.stdout.write(self.style.SUCCESS(
                f"Ingest done (full={full}): scanned={outcome.scanned} "
                f"selected={outcome.selected} added={outcome.added}"
            ))
