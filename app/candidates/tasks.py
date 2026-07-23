"""Background tasks (django-tasks).

Run out-of-band by the ``db_worker`` service when TASKS uses the database backend;
with the default immediate backend they run inline (fine for dev/tests).
"""
import logging

from django_tasks import task

from candidates.models import Candidate
from candidates.photometry_utils import get_atlas_fp, get_lasair_api_token, get_ztf_fp
from candidates.services.enrichment import try_forced_photometry

logger = logging.getLogger(__name__)


@task()
def run_forced_photometry(candidate_id: int) -> None:
    """Fetch ATLAS (and, if configured, ZTF) forced photometry for one candidate.

    Deferred out of ingest because the submit-and-poll against ATLAS/ZTF is slow and
    rate-limited; running it here keeps candidate ingestion fast. Best-effort: per-source
    failures are logged (via try_forced_photometry), not raised, so one bad candidate
    doesn't wedge the worker.
    """
    candidate = Candidate.objects.filter(id=candidate_id).first()
    if candidate is None:
        logger.warning("run_forced_photometry: candidate %s no longer exists", candidate_id)
        return

    try_forced_photometry(candidate, get_atlas_fp, "Atlas")

    if get_lasair_api_token():
        try_forced_photometry(candidate, get_ztf_fp, "ZTF")
    else:
        logger.info(
            "Skipping ZTF forced photometry for candidate %s: LASAIR not configured",
            candidate_id,
        )
