import logging
import os
import time
import traceback
from collections import Counter
from dataclasses import dataclass
from enum import Enum

from django.conf import settings

from candidates.models import CandidatePhotometry, CandidateDataProduct
from candidates.photometry_utils import add_photometry_from_last_report, get_lasair_api_token
from candidates.services.enrichment import add_ToO_names_to_candidate, update_candidate_cutouts, try_add_cutout, \
    try_associate_host_galaxy
from candidates.services.identity import handle_candidate_identity
from candidates.services.parsing import parse_json_file, ensure_aware_utc
from candidates.utils import fetch_ps1_cutout, fetch_sdss_cutout

logger = logging.getLogger(__name__)
CAST_SETTINGS = settings.CAST_CANDIDATES

class IngestionResult(Enum):
    CREATED = "created"
    NO_JSON_FILES = "no_json_files"
    PARSE_FAILED = "parse_failed"
    INVALID_COORDS = "invalid_coords"
    CANDIDATE_EXISTS = "candidate_exists"
    UNKNOWN_ERROR = "unknown_error"

def process_json_file(file, lasair_enabled: bool = None) -> tuple[int, IngestionResult, str]:
    """
    Processes the uploaded JSON file and adds candidates to the database.
    :param file: Ingested json file object
    :return: The number of candidates successfully added
    """
    try:
        payload = parse_json_file(file)
    except ValueError as e:
        logger.warning(str(e))
        return 0, IngestionResult.PARSE_FAILED, None

    logger.info(f"Processing file: {file.name}")

    at_report = payload.at_report
    last_report = payload.last_report
    ra = payload.ra
    dec = payload.dec

    candidate, is_new = handle_candidate_identity(payload, file, lasair_enabled)

    if not is_new:
        logger.info(
            f"Candidate already exists for {file.name} "
            f"(RA={payload.ra}, Dec={payload.dec})"
        )
        return 0, IngestionResult.CANDIDATE_EXISTS, None

    instr_cfg = CAST_SETTINGS["instruments"]
    # ---- AT (old JSON format) photometry ----
    if not last_report:
        non_detection = at_report.get("non_detection", {})
        if non_detection:
            raw_obs_date = non_detection.get("obsdate", [None])[0]
            obs_date = ensure_aware_utc(raw_obs_date)
            limit = non_detection.get("flux")
            filter_value = non_detection.get("filter_value")

            CandidatePhotometry.objects.create(
                candidate=candidate,
                obs_date=obs_date,
                limit=limit,
                filter_band=str(filter_value),
                telescope=instr_cfg["last_telescope"],
                instrument=instr_cfg["last_instrument"],
            )

        photometry_data = at_report.get("photometry", {}).get("photometry_group", {})
        obs_date = photometry_data.get("obsdate", [None])[0]
        if obs_date:
            raw_obs_date = non_detection.get("obsdate", [None])[0]
            obs_date = ensure_aware_utc(raw_obs_date)
            magnitude = photometry_data.get("flux")
            filter_value = photometry_data.get("filter_value")

            CandidatePhotometry.objects.create(
                candidate=candidate,
                obs_date=obs_date,
                magnitude=magnitude,
                magnitude_error=instr_cfg["default_magnitude_error"],
                filter_band=str(filter_value),
                telescope=instr_cfg["last_telescope"],
                instrument=instr_cfg["last_instrument"],
            )

    if last_report:
        try:
            add_photometry_from_last_report(candidate, last_report)
        except Exception as e:
            logger.warning(f"Error adding photometry: {e}")

        add_ToO_names_to_candidate(candidate, last_report)

        update_candidate_cutouts(candidate)

    # ---- PS1 cutout ----
    try_add_cutout(
        candidate=candidate,
        fetch_func=fetch_ps1_cutout,
        ra=ra,
        dec=dec,
        product_type="ps1",
        name_suffix="PS1 cutout",
    )

    # ---- SDSS cutout ----
    try_add_cutout(
        candidate=candidate,
        fetch_func=fetch_sdss_cutout,
        ra=ra,
        dec=dec,
        product_type="sdss",
        name_suffix="SDSS cutout",
    )

    # ---- Host galaxy association ----
    try_associate_host_galaxy(candidate)

    # ---- Forced photometry (deferred) ----
    # ATLAS/ZTF forced photometry submit-and-poll (plus ATLAS rate-limiting) can take
    # 10-20 min per candidate, so it runs out-of-band in the db_worker rather than
    # blocking ingest. Enqueue after the candidate is fully created; in a management
    # command (autocommit) it's already committed, so the worker can load it. Imported
    # lazily to avoid an import cycle. `lasair_enabled` is now unused here.
    try:
        from candidates.tasks import run_forced_photometry
        run_forced_photometry.enqueue(candidate.id)
    except Exception as e:
        logger.warning(f"Failed to enqueue forced photometry for candidate {candidate.id}: {e}")

    return 1, IngestionResult.CREATED, candidate.name


# Step 1: Get JSON names already in DB
# Could be a problem if too large...
def get_json_names_from_db():
    return set(
        CandidateDataProduct.objects.filter(data_product_type='json')
        .values_list('name', flat=True)
    )


@dataclass
class IngestOutcome:
    """Result of an ingest run, including the watermark to persist for the next run."""
    added: int = 0
    new_watermark: float | None = None  # highest mtime observed among settled files
    scanned: int = 0                    # files that passed the fs gates
    selected: int = 0                   # of those, the ones not already in the DB


def scan_json_dir(directory_path, cutoff_ts, settle_ts, min_mtime):
    """Single-pass filesystem scan of the JSON drop dir. Cheap: one ``os.scandir``, no DB.

    Returns ``(candidate_files, max_settled_mtime)``:

    * ``candidate_files`` — ``*.json`` paths that are *settled* (mtime <= ``settle_ts``,
      i.e. not being written right now), newer than the cutoff (mtime > ``cutoff_ts``),
      and — unless ``min_mtime`` is None (a ``--full`` run) — newer than the watermark
      (mtime > ``min_mtime``). These are NOT yet DB-deduped.
    * ``max_settled_mtime`` — the highest mtime among *all* settled ``*.json`` entries
      (not just the selected ones), or None if none were settled. This drives the
      watermark, so files we've already seen are gated out next run even when they
      weren't selected (already ingested).
    """
    if not os.path.isdir(directory_path):
        logger.warning(f"Directory does not exist: {directory_path}")
        return [], None

    candidate_files = []
    max_settled_mtime = None
    scanned = 0
    try:
        with os.scandir(directory_path) as entries:
            for entry in entries:
                if not entry.name.endswith(".json"):
                    continue
                try:
                    mtime = entry.stat().st_mtime
                except OSError:
                    continue
                # Skip files still being written (mtime within the settle window).
                if mtime > settle_ts:
                    continue
                scanned += 1
                if max_settled_mtime is None or mtime > max_settled_mtime:
                    max_settled_mtime = mtime
                if mtime <= cutoff_ts:
                    continue
                if min_mtime is not None and mtime <= min_mtime:
                    continue
                candidate_files.append(entry.path)
    except OSError as e:
        logger.warning(f"Failed to scan {directory_path}: {e}")
        return [], None

    logger.info(
        f"Scanned {scanned} settled JSON files; {len(candidate_files)} pass the "
        f"cutoff/watermark gates"
    )
    return candidate_files, max_settled_mtime


def process_multiple_json_files(
    directory_path,
    cutoff=3,
    check_tns: bool = True,
    min_mtime: float | None = None,
    settle_seconds: int = 60,
    full: bool = False,
) -> IngestOutcome:
    """Ingest new candidate JSON files, cheaply skipping the DB when nothing is new.

    :param directory_path: directory containing the JSON drop files
    :param cutoff: max age in days of files to consider
    :param min_mtime: watermark — ignore files at/below this mtime (skipped when ``full``)
    :param settle_seconds: ignore files modified within this many seconds (torn-write guard)
    :param full: rescan everything within ``cutoff``, ignoring the watermark
    :return: an :class:`IngestOutcome` (count added + watermark to persist)
    """
    now = time.time()
    cutoff_ts = now - cutoff * 86400
    settle_ts = now - settle_seconds
    gate_mtime = None if full else min_mtime

    # Cheap gate first: a single filesystem pass, no DB work.
    candidate_files, max_settled = scan_json_dir(
        directory_path, cutoff_ts, settle_ts, gate_mtime
    )

    if not candidate_files:
        logger.info(
            f"No new settled JSON files in {directory_path} "
            f"(cutoff={cutoff}d, settle={settle_seconds}s, full={full})"
        )
        return IngestOutcome(added=0, new_watermark=max_settled)

    # Only now that there is filesystem work do we pay for the DB name load + dedup.
    existing_json_names = get_json_names_from_db()
    json_files = [
        f for f in candidate_files
        if os.path.basename(f) not in existing_json_names
    ]

    if not json_files:
        logger.info("All scanned files are already ingested; nothing to do.")
        return IngestOutcome(
            added=0, new_watermark=max_settled, scanned=len(candidate_files)
        )

    logger.info(f"Found {len(json_files)} new files to process.")
    total_candidates_added = 0

    # Check credentials once at the beginning
    lasair_enabled = has_lasair_credentials()
    logger.info(
        "Enrichment capabilities: "
        f"LASAIR={'enabled' if lasair_enabled else 'disabled'}"
    )

    summary = Counter()
    # Step 4: Process each new file
    for json_file in json_files:
        try:
            with open(json_file, 'rb') as file:
                count, result, candidate_name = process_json_file(file, lasair_enabled)

                if result == IngestionResult.CREATED:
                    total_candidates_added += count
                    # Use the candidate's generated name for success messages
                    if candidate_name:
                        logger.info(f"{candidate_name}: new candidate created")
                    else:
                        logger.info(f"{os.path.basename(json_file)}: new candidate created")

                elif result == IngestionResult.CANDIDATE_EXISTS:
                    logger.info(f"{file.name}: candidate already exists")

                elif result == IngestionResult.PARSE_FAILED:
                    logger.warning(f"{file.name}: parse failed")

                elif result == IngestionResult.INVALID_COORDS:
                    logger.warning(f"{file.name}: invalid coordinates")

                else:
                    logger.warning(f"{file.name}: ingestion skipped ({result.value})")

                summary[result] += 1

        except Exception as e:
            logger.error(f"Error processing {os.path.basename(json_file)}: {e}")
            traceback.print_exc()

    logger.info("Ingestion summary:")
    for result, n in summary.items():
        logger.info(f"  {result.value}: {n}")

    logger.info(f"Total candidates added: {total_candidates_added}")
    return IngestOutcome(
        added=total_candidates_added,
        new_watermark=max_settled,
        scanned=len(candidate_files),
        selected=len(json_files),
    )


def has_lasair_credentials() -> bool:
    return bool(get_lasair_api_token())
