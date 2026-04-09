import unittest
from unittest import mock

from services import sub2api_monitor


class Sub2ApiMonitorTests(unittest.TestCase):
    def test_classify_test_failure_preserves_quota(self):
        self.assertEqual(
            sub2api_monitor._classify_test_failure({"error": {"type": "usage_limit_reached"}}),
            "quota_exhausted",
        )

    def test_classify_test_failure_maps_401_like_errors(self):
        self.assertEqual(
            sub2api_monitor._classify_test_failure(
                {
                    "status": 401,
                    "error": {
                        "code": "token_invalidated",
                        "message": "Your authentication token has been invalidated.",
                    },
                }
            ),
            "account_401",
        )
        self.assertEqual(
            sub2api_monitor._classify_test_failure("HTTP 401 Unauthorized"),
            "account_401",
        )
        self.assertEqual(
            sub2api_monitor._classify_test_failure(
                "You do not have an account because it has been deleted or deactivated."
            ),
            "account_401",
        )

    def test_classify_test_failure_maps_other_failures_to_abnormal(self):
        self.assertEqual(
            sub2api_monitor._classify_test_failure({"message": "upstream service unavailable"}),
            "abnormal",
        )

    def test_build_counts_tracks_account_401_and_abnormal(self):
        accounts = [
            {"id": 1, "disabled": False, "has_access_token": True, "has_refresh_token": True, "expires_at": None},
            {"id": 2, "disabled": False, "has_access_token": True, "has_refresh_token": True, "expires_at": None},
            {"id": 3, "disabled": False, "has_access_token": True, "has_refresh_token": True, "expires_at": None},
            {"id": 4, "disabled": True, "has_access_token": False, "has_refresh_token": False, "expires_at": None},
        ]
        tested_accounts = [
            {"id": 1, "test": {"ok": False, "failure_type": "quota_exhausted"}},
            {"id": 2, "test": {"ok": False, "failure_type": "account_401"}},
            {"id": 3, "test": {"ok": False, "failure_type": "abnormal"}},
        ]

        counts = sub2api_monitor._build_counts(accounts, tested_accounts, [{"id": 3, "error": "boom"}])

        self.assertEqual(counts["total"], 4)
        self.assertEqual(counts["available"], 1)
        self.assertEqual(counts["tested_failed"], 3)
        self.assertEqual(counts["quota_exhausted"], 1)
        self.assertEqual(counts["account_401"], 1)
        self.assertEqual(counts["abnormal"], 1)
        self.assertEqual(counts["disabled"], 1)
        self.assertEqual(counts["errors"], 1)
        self.assertEqual(counts["untested"], 1)

    def test_run_monitor_exception_path_preserves_failure_type(self):
        accounts = [
            {
                "id": "acc-1",
                "email": "demo@example.com",
                "disabled": False,
                "has_access_token": True,
                "has_refresh_token": True,
                "expires_at": None,
                "status": "active",
                "platform": "openai",
                "type": "shared",
            }
        ]

        with mock.patch("services.sub2api_monitor.resolve_sub2api_config", return_value=("https://example.com", "key")):
            with mock.patch(
                "services.sub2api_monitor._fetch_accounts",
                return_value={
                    "accounts": accounts,
                    "pages_fetched": 1,
                    "page_errors": [],
                    "stopped_early": False,
                },
            ):
                with mock.patch(
                    "services.sub2api_monitor._test_account",
                    side_effect=RuntimeError("HTTP 401 Unauthorized"),
                ):
                    with mock.patch("services.sub2api_monitor._ensure_report_dir"):
                        with mock.patch("pathlib.Path.write_text"):
                            report = sub2api_monitor.run_sub2api_monitor()

        self.assertEqual(report["counts"]["account_401"], 1)
        self.assertEqual(report["counts"]["abnormal"], 0)
        self.assertEqual(report["accounts"][0]["test"]["failure_type"], "account_401")
        self.assertEqual(report["accounts"][0]["test"]["message"], "HTTP 401 Unauthorized")


if __name__ == "__main__":
    unittest.main()
