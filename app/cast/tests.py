import json
from io import BytesIO
from unittest.mock import MagicMock, call, mock_open, patch

from django.test import TestCase, override_settings
from django.utils import timezone

from candidates.ingestion import IngestionResult, has_lasair_credentials, process_json_file, process_multiple_json_files
from candidates.models import Candidate
from candidates.photometry_utils import get_ztf_fp


class IngestionRegressionTests(TestCase):
    def test_candidate_with_extreme_coordinates_saves_generated_name(self):
        candidate = Candidate.objects.create(
            ra=359.9999583333333,
            dec=89.99999722222222,
            discovery_datetime=timezone.now(),
        )

        self.assertTrue(candidate.name.startswith("LAST J"))
        self.assertLessEqual(len(candidate.name), 150)

    @override_settings(LASAIR_API_KEY="")
    def test_has_lasair_credentials_false_without_api_key(self):
        self.assertFalse(has_lasair_credentials())

    @override_settings(BROKERS={"LASAIR": {}})
    def test_get_ztf_fp_returns_none_without_credentials(self):
        candidate = Candidate.objects.create(
            ra=123.456,
            dec=-45.678,
            discovery_datetime=timezone.now(),
        )

        self.assertIsNone(get_ztf_fp(candidate))

    def test_process_json_file_returns_three_values_on_parse_failure(self):
        mock_file = BytesIO(b"invalid json content")
        mock_file.name = "invalid_file.json"

        count, result, candidate_name = process_json_file(mock_file)

        self.assertEqual(count, 0)
        self.assertEqual(result, IngestionResult.PARSE_FAILED)
        self.assertIsNone(candidate_name)

    @patch("candidates.ingestion.try_associate_host_galaxy")
    @patch("candidates.ingestion.try_forced_photometry")
    @patch("candidates.ingestion.try_add_cutout")
    @patch("candidates.ingestion.update_candidate_cutouts")
    @patch("candidates.ingestion.add_ToO_names_to_candidate")
    @patch("candidates.ingestion.add_photometry_from_last_report")
    @patch("candidates.ingestion.handle_candidate_identity")
    def test_process_json_file_returns_candidate_name_when_created(
        self,
        mock_handle_candidate_identity,
        _mock_add_photometry,
        _mock_add_too_names,
        _mock_update_cutouts,
        mock_try_add_cutout,
        mock_try_forced_photometry,
        mock_try_associate_host_galaxy,
    ):
        candidate = Candidate.objects.create(
            ra=123.456,
            dec=-45.678,
            discovery_datetime=timezone.now(),
        )
        mock_handle_candidate_identity.return_value = (candidate, True)

        mock_data = {
            "at_report": {
                "RA": {"value": 123.456},
                "Dec": {"value": -45.678},
                "discovery_datetime": ["2026-02-26 15:00:00 UTC"],
            },
            "last_report": {},
        }
        mock_file = BytesIO(json.dumps(mock_data).encode())
        mock_file.name = "valid_file.json"

        count, result, candidate_name = process_json_file(mock_file, lasair_enabled=False)

        self.assertEqual((count, result, candidate_name), (1, IngestionResult.CREATED, candidate.name))
        self.assertEqual(mock_try_add_cutout.call_count, 2)
        mock_try_forced_photometry.assert_called_once()
        mock_try_associate_host_galaxy.assert_called_once_with(candidate)

    @patch("candidates.ingestion.process_json_file")
    @patch("candidates.ingestion.has_lasair_credentials")
    @patch("candidates.ingestion.collect_new_json")
    @patch("candidates.ingestion.get_json_names_from_db")
    def test_process_multiple_json_files_checks_lasair_credentials_once(
        self,
        mock_get_json_names_from_db,
        mock_collect_new_json,
        mock_has_lasair_credentials,
        mock_process_json_file,
    ):
        mock_get_json_names_from_db.return_value = set()
        mock_collect_new_json.return_value = ["/tmp/a.json", "/tmp/b.json"]
        mock_has_lasair_credentials.return_value = False
        mock_process_json_file.side_effect = [
            (1, IngestionResult.CREATED, "LAST J000000.00+000000.00"),
            (0, IngestionResult.PARSE_FAILED, None),
        ]

        with patch("builtins.open", mock_open(read_data=b"{}")):
            total = process_multiple_json_files("/tmp/input", cutoff=1)

        self.assertEqual(total, 1)
        mock_has_lasair_credentials.assert_called_once_with()
        self.assertEqual(len(mock_process_json_file.call_args_list), 2)
        self.assertTrue(all(args.args[1] is False for args in mock_process_json_file.call_args_list))
