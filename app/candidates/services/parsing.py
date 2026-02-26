import json
import os
from dataclasses import dataclass
from django.utils import timezone
from datetime import timezone as dt_timezone

def ensure_aware_utc(dt):
    if dt is None:
        return None

    if timezone.is_naive(dt):
        dt = dt.replace(tzinfo=dt_timezone.utc)

    return dt.astimezone(dt_timezone.utc)

@dataclass
class ParsedAlertPayload:
    ra: float
    dec: float
    discovery_datetime: str
    at_report: dict
    last_report: dict
    filename: str

def parse_json_file(file) -> ParsedAlertPayload:
    """
    Read, decode, and validate an alert JSON file.
    Returns a ParsedAlertPayload or raises ValueError.
    """
    try:
        file_content = file.read().decode("utf-8")
        data = json.loads(file_content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON format: {e}")
    except Exception as e:
        raise ValueError(f"Error reading file: {e}")
    finally:
        file.seek(0)

    at_report = data.get("at_report", {})
    last_report = data.get("last_report", {})

    try:
        ra = float(at_report["RA"]["value"])
        dec = float(at_report["Dec"]["value"])
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"Missing or invalid RA/Dec in file {file.name}")

    discovery_datetime = at_report.get("discovery_datetime", {})[0]
    discovery_datetime = discovery_datetime[
        : discovery_datetime.find("UTC") - 1
    ]

    return ParsedAlertPayload(
        ra=ra,
        dec=dec,
        discovery_datetime=discovery_datetime,
        at_report=at_report,
        last_report=last_report,
        filename=os.path.basename(file.name),
    )