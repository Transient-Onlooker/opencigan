import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from backend.access_logs import AccessLogStore
from backend.analytics import AnalyticsStore
from backend.app import dispatch_request
from backend.cache import Cache
from backend.history import HistoryStore
from backend.suggestion_store import SuggestionStore


class SharedAdminAuthTests(unittest.TestCase):
    def test_one_admin_token_authenticates_all_admin_routes(self):
        token = "shared-admin-token-0123456789"
        with TemporaryDirectory() as directory:
            analytics_store = AnalyticsStore(":memory:", "x" * 40)
            access_log_store = AccessLogStore(":memory:")
            history_store = HistoryStore(Path(directory) / "history.sqlite")
            suggestion_store = SuggestionStore(Path(directory) / "suggestions.sqlite")
            self.addCleanup(analytics_store.close)
            self.addCleanup(access_log_store.close)

            api_recorder = Mock(dropped=0)
            routes = (
                ("/api/v1/admin/analytics", "days=30"),
                ("/api/v1/admin/history-stats", "school=1%3AExample&week=2026-11-16"),
                ("/api/v1/admin/access-logs", ""),
                ("/api/v1/admin/suggestions", ""),
            )
            with patch.dict(
                "os.environ",
                {"OPENCIGAN_ADMIN_TOKEN": token, "OPENCIGAN_HISTORY_STATS_ENABLED": "1"},
            ), patch("backend.app._analytics_store", return_value=analytics_store), patch(
                "backend.app._api_recorder", api_recorder
            ), patch("backend.app._history_store", return_value=history_store), patch(
                "backend.app._access_log_store", return_value=access_log_store
            ), patch("backend.app._suggestion_store", return_value=suggestion_store):
                for path, query in routes:
                    with self.subTest(path=path, credential="shared"):
                        status, _, _ = dispatch_request(
                            "GET", path, query,
                            request_headers={"Authorization": f"Bearer {token}"},
                        )
                        self.assertEqual(status, 200)

                    with self.subTest(path=path, credential="different"):
                        status, _, _ = dispatch_request(
                            "GET", path, query,
                            request_headers={"Authorization": "Bearer different-admin-token"},
                        )
                        self.assertEqual(status, 401)


if __name__ == "__main__":
    unittest.main()
