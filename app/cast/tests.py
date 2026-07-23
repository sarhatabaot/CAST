import json
from io import BytesIO
from unittest.mock import MagicMock, call, mock_open, patch

import requests
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from candidates.ingestion import (
    IngestionResult,
    IngestOutcome,
    has_lasair_credentials,
    process_json_file,
    process_multiple_json_files,
    scan_json_dir,
)
from candidates.models import Candidate
from candidates.photometry_utils import get_lasair_api_token, get_ztf_fp
from cast.external_api_status import (
    EXTERNAL_API_STATUS_CACHE_KEY,
    check_atlas_status,
    check_lasair_status,
    check_tns_status,
    get_external_api_status_snapshot,
    refresh_external_api_status,
)


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
        mock_try_associate_host_galaxy.assert_called_once_with(candidate)

    @patch("candidates.ingestion.process_json_file")
    @patch("candidates.ingestion.has_lasair_credentials")
    @patch("candidates.ingestion.scan_json_dir")
    @patch("candidates.ingestion.get_json_names_from_db")
    def test_process_multiple_json_files_checks_lasair_credentials_once(
        self,
        mock_get_json_names_from_db,
        mock_scan_json_dir,
        mock_has_lasair_credentials,
        mock_process_json_file,
    ):
        mock_get_json_names_from_db.return_value = set()
        mock_scan_json_dir.return_value = (["/tmp/a.json", "/tmp/b.json"], 100.0)
        mock_has_lasair_credentials.return_value = False
        mock_process_json_file.side_effect = [
            (1, IngestionResult.CREATED, "LAST J000000.00+000000.00"),
            (0, IngestionResult.PARSE_FAILED, None),
        ]

        with patch("builtins.open", mock_open(read_data=b"{}")):
            outcome = process_multiple_json_files("/tmp/input", cutoff=1)

        self.assertEqual(outcome.added, 1)
        self.assertEqual(outcome.new_watermark, 100.0)
        mock_has_lasair_credentials.assert_called_once_with()
        self.assertEqual(len(mock_process_json_file.call_args_list), 2)
        self.assertTrue(all(args.args[1] is False for args in mock_process_json_file.call_args_list))


@override_settings(CACHES={"default": {
    "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    "LOCATION": "ingest-safety-tests",
}})
class IngestSafetyTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_redis_lock_is_exclusive(self):
        from candidates.services.locking import redis_lock

        with redis_lock("test:lock", 300) as first:
            self.assertTrue(first)
            with redis_lock("test:lock", 300) as second:
                self.assertFalse(second)  # already held -> not acquired
        # released on exit -> acquirable again
        with redis_lock("test:lock", 300) as third:
            self.assertTrue(third)

    def test_command_skips_when_lock_held(self):
        from django.core.management import call_command
        from candidates.management.commands.ingest_candidates import INGEST_LOCK_KEY

        cache.add(INGEST_LOCK_KEY, "someone-else", 300)  # simulate a run in progress
        with patch(
            "candidates.management.commands.ingest_candidates.process_multiple_json_files"
        ) as mock_process:
            call_command("ingest_candidates")
        mock_process.assert_not_called()  # heavy work skipped while locked

    def test_command_passes_watermark_and_advances_it(self):
        from django.core.management import call_command
        from candidates.management.commands.ingest_candidates import INGEST_WATERMARK_KEY

        cache.set(INGEST_WATERMARK_KEY, 100.0, timeout=None)
        with patch(
            "candidates.management.commands.ingest_candidates.process_multiple_json_files",
            return_value=IngestOutcome(added=2, new_watermark=555.0, scanned=3, selected=2),
        ) as mock_process:
            call_command("ingest_candidates")

        # the stored watermark is read and passed in as the gate...
        self.assertEqual(mock_process.call_args.kwargs["min_mtime"], 100.0)
        self.assertFalse(mock_process.call_args.kwargs["full"])
        # ...and advanced forward to the newest mtime the run observed
        self.assertEqual(cache.get(INGEST_WATERMARK_KEY), 555.0)

    def test_command_full_ignores_watermark(self):
        from django.core.management import call_command
        from candidates.management.commands.ingest_candidates import INGEST_WATERMARK_KEY

        cache.set(INGEST_WATERMARK_KEY, 100.0, timeout=None)
        with patch(
            "candidates.management.commands.ingest_candidates.process_multiple_json_files",
            return_value=IngestOutcome(added=0, new_watermark=90.0),
        ) as mock_process:
            call_command("ingest_candidates", "--full")

        self.assertIsNone(mock_process.call_args.kwargs["min_mtime"])
        self.assertTrue(mock_process.call_args.kwargs["full"])
        # watermark is forward-only: an older observed mtime must not regress it
        self.assertEqual(cache.get(INGEST_WATERMARK_KEY), 100.0)

    def test_scan_json_dir_gates_settle_watermark_cutoff(self):
        import os
        import tempfile
        import time

        now = time.time()
        with tempfile.TemporaryDirectory() as d:
            def make(name, mtime):
                p = os.path.join(d, name)
                with open(p, "w") as f:
                    f.write("{}")
                os.utime(p, (mtime, mtime))
                return mtime

            m_old = make("old.json", now - 20 * 86400)     # settled but older than cutoff
            m_a = make("a.json", now - 5 * 86400)           # settled, within cutoff
            m_b = make("b.json", now - 3600)                # settled, within cutoff, newest
            make("fresh.json", now - 5)                     # inside settle window -> excluded
            make("note.txt", now - 3600)                    # not .json -> ignored

            cutoff_ts = now - 10 * 86400
            settle_ts = now - 60

            # No watermark: a.json + b.json selected; old excluded (cutoff); fresh excluded (settle)
            files, max_settled = scan_json_dir(d, cutoff_ts, settle_ts, None)
            self.assertEqual({os.path.basename(f) for f in files}, {"a.json", "b.json"})
            # max_settled is the newest *settled* file (fresh.json is excluded from it)
            self.assertAlmostEqual(max_settled, m_b, places=3)

            # Watermark at a.json's mtime gates a.json out, leaving only b.json
            files2, _ = scan_json_dir(d, cutoff_ts, settle_ts, m_a)
            self.assertEqual({os.path.basename(f) for f in files2}, {"b.json"})


@override_settings(TASKS={"default": {
    "BACKEND": "django_tasks.backends.immediate.ImmediateBackend",
}})
class ForcedPhotometryTaskTests(TestCase):
    def _make_candidate(self):
        return Candidate.objects.create(
            ra=123.456, dec=-45.678, discovery_datetime=timezone.now(),
        )

    @patch("candidates.tasks.get_lasair_api_token", return_value="token")
    @patch("candidates.tasks.get_ztf_fp")
    @patch("candidates.tasks.get_atlas_fp")
    def test_task_runs_atlas_and_ztf(self, mock_atlas, mock_ztf, _mock_token):
        from candidates.tasks import run_forced_photometry

        candidate = self._make_candidate()
        # ImmediateBackend runs the task on commit; execute the on-commit hook so it fires.
        with self.captureOnCommitCallbacks(execute=True):
            run_forced_photometry.enqueue(candidate.id)

        mock_atlas.assert_called_once_with(candidate)
        mock_ztf.assert_called_once_with(candidate)

    @patch("candidates.tasks.get_lasair_api_token", return_value="")
    @patch("candidates.tasks.get_ztf_fp")
    @patch("candidates.tasks.get_atlas_fp")
    def test_task_skips_ztf_without_lasair(self, mock_atlas, mock_ztf, _mock_token):
        from candidates.tasks import run_forced_photometry

        candidate = self._make_candidate()
        with self.captureOnCommitCallbacks(execute=True):
            run_forced_photometry.enqueue(candidate.id)

        mock_atlas.assert_called_once_with(candidate)
        mock_ztf.assert_not_called()

    @patch("candidates.tasks.get_atlas_fp")
    def test_task_noop_for_missing_candidate(self, mock_atlas):
        from candidates.tasks import run_forced_photometry

        with self.captureOnCommitCallbacks(execute=True):
            run_forced_photometry.enqueue(999999)  # no such candidate
        mock_atlas.assert_not_called()

    @patch("candidates.tasks.run_forced_photometry")
    @patch("candidates.ingestion.try_associate_host_galaxy")
    @patch("candidates.ingestion.try_add_cutout")
    @patch("candidates.ingestion.update_candidate_cutouts")
    @patch("candidates.ingestion.add_ToO_names_to_candidate")
    @patch("candidates.ingestion.add_photometry_from_last_report")
    @patch("candidates.ingestion.handle_candidate_identity")
    def test_ingest_enqueues_forced_photometry(
        self,
        mock_handle_candidate_identity,
        _mock_add_photometry,
        _mock_add_too_names,
        _mock_update_cutouts,
        _mock_try_add_cutout,
        _mock_try_associate_host_galaxy,
        mock_run_fp,
    ):
        candidate = self._make_candidate()
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

        process_json_file(mock_file, lasair_enabled=False)

        mock_run_fp.enqueue.assert_called_once_with(candidate.id)


class ExternalApiStatusTests(TestCase):
    def setUp(self):
        cache.delete(EXTERNAL_API_STATUS_CACHE_KEY)
        self.superuser = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pass",
        )
        self.user = get_user_model().objects.create_user(
            username="user",
            email="user@example.com",
            password="pass",
        )

    def test_external_api_status_requires_superuser(self):
        response = self.client.get(reverse("external-api-status"))
        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.user)
        response = self.client.get(reverse("external-api-status"))
        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.superuser)
        with patch("cast.views.refresh_external_api_status") as mock_refresh:
            mock_refresh.return_value = {"refreshed_at": "now", "services": []}
            response = self.client.get(reverse("external-api-status"))
        self.assertEqual(response.status_code, 200)

    @patch("cast.views.refresh_external_api_status")
    def test_external_api_status_page_refreshes_when_cache_is_empty(self, mock_refresh):
        mock_refresh.return_value = {"refreshed_at": "now", "services": [{"name": "TNS"}]}
        self.client.force_login(self.superuser)

        response = self.client.get(reverse("external-api-status"))

        self.assertEqual(response.status_code, 200)
        mock_refresh.assert_called_once_with()
        self.assertContains(response, "TNS")

    @patch("cast.views.refresh_external_api_status")
    def test_external_api_status_page_uses_cached_snapshot(self, mock_refresh):
        cache.set(EXTERNAL_API_STATUS_CACHE_KEY, {"refreshed_at": "cached", "services": [{"name": "LASAIR"}]}, None)
        self.client.force_login(self.superuser)

        response = self.client.get(reverse("external-api-status"))

        self.assertEqual(response.status_code, 200)
        mock_refresh.assert_not_called()
        self.assertContains(response, "LASAIR")

    @patch("cast.views.refresh_external_api_status")
    def test_external_api_status_manual_refresh_overwrites_cache(self, mock_refresh):
        mock_refresh.return_value = {"refreshed_at": "new", "services": [{"name": "ATLAS"}]}
        self.client.force_login(self.superuser)

        response = self.client.post(reverse("external-api-status"))

        self.assertEqual(response.status_code, 200)
        mock_refresh.assert_called_once_with()
        self.assertContains(response, "ATLAS")

    @override_settings(BROKERS={"TNS": {"api_key": "", "bot_id": "", "bot_name": ""}}, TNS_TEST=True)
    def test_tns_status_reports_not_configured(self):
        status = check_tns_status()

        self.assertFalse(status["configured"])
        self.assertIsNone(status["auth_ok"])
        self.assertEqual(status["metadata"]["environment"], "sandbox")

    @override_settings(BROKERS={"TNS": {"api_key": "key", "bot_id": "1", "bot_name": "bot"}}, TNS_TEST=False)
    @patch("cast.external_api_status.requests.post")
    def test_tns_status_reports_success_and_prod_environment(self, mock_post):
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"data": []}
        mock_post.return_value = response

        status = check_tns_status()

        self.assertTrue(status["configured"])
        self.assertTrue(status["auth_ok"])
        self.assertEqual(status["metadata"]["environment"], "production")

    @override_settings(BROKERS={"LASAIR": {"api_key": "token"}}, LASAIR_API_KEY="")
    @patch("cast.external_api_status.lasair_client")
    def test_lasair_status_uses_normalized_token_source(self, mock_client):
        mock_client.return_value.cone.return_value = {"object": "ZTF"}

        status = check_lasair_status()

        self.assertTrue(status["configured"])
        self.assertTrue(status["auth_ok"])
        mock_client.assert_called_once()
        self.assertEqual(mock_client.call_args.args[0], "token")

    @override_settings(BROKERS={"ATLAS": {"api_token": "secret"}})
    @patch("cast.external_api_status.requests.get")
    def test_atlas_status_reports_auth_failure(self, mock_get):
        response = MagicMock()
        response.status_code = 401
        mock_get.return_value = response

        status = check_atlas_status()

        self.assertTrue(status["configured"])
        self.assertFalse(status["auth_ok"])
        self.assertEqual(status["status_label"], "auth_failed")

    @patch("cast.external_api_status.build_external_api_status_snapshot")
    def test_refresh_external_api_status_writes_cache(self, mock_build):
        mock_build.return_value = {"refreshed_at": "stored", "services": [{"name": "TNS"}]}

        snapshot = refresh_external_api_status()

        self.assertEqual(snapshot["refreshed_at"], "stored")
        self.assertEqual(get_external_api_status_snapshot()["refreshed_at"], "stored")

    @override_settings(BROKERS={"LASAIR": {"api_key": "broker-token"}}, LASAIR_API_KEY="")
    def test_get_lasair_api_token_prefers_broker_value(self):
        self.assertEqual(get_lasair_api_token(), "broker-token")
        self.assertTrue(has_lasair_credentials())

    @override_settings(BROKERS={"LASAIR": {}}, LASAIR_API_KEY="legacy-token")
    def test_get_lasair_api_token_falls_back_to_legacy_setting(self):
        self.assertEqual(get_lasair_api_token(), "legacy-token")
        self.assertTrue(has_lasair_credentials())

    @override_settings(BROKERS={"TNS": {"api_key": "key", "bot_id": "1", "bot_name": "bot"}}, TNS_TEST=True)
    @patch("cast.external_api_status.requests.post", side_effect=requests.Timeout("boom"))
    def test_tns_status_reports_network_error(self, _mock_post):
        status = check_tns_status()

        self.assertTrue(status["configured"])
        self.assertFalse(status["auth_ok"])
        self.assertEqual(status["status_label"], "network_error")
