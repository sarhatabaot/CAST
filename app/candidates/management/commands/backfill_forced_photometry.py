from django.core.management.base import BaseCommand

from candidates.models import Candidate, CandidatePhotometry
from candidates.tasks import run_forced_photometry


class Command(BaseCommand):
    help = (
        "Enqueue forced-photometry tasks for candidates that don't have ATLAS photometry "
        "yet (e.g. those ingested before background forced photometry was wired up). "
        "The db_worker drains the queue at its own throttle-aware pace."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit", type=int, default=100,
            help="Enqueue at most this many candidates (newest first).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report how many would be enqueued without enqueuing.",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        dry = options["dry_run"]

        have_atlas = (
            CandidatePhotometry.objects.filter(telescope="ATLAS")
            .values_list("candidate_id", flat=True)
            .distinct()
        )
        pending = Candidate.objects.exclude(id__in=have_atlas).order_by("-id")[:limit]

        enqueued = 0
        for candidate in pending:
            if not dry:
                run_forced_photometry.enqueue(candidate.id)
            enqueued += 1

        verb = "Would enqueue" if dry else "Enqueued"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} forced photometry for {enqueued} candidate(s)."
        ))
