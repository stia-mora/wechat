"""Run in the source image with PYTHONPATH=/app: python -m unittest source_bridge.test_discovery."""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException

from source_bridge import service


class DiscoveryTests(unittest.TestCase):
    def search(self, result, begin=0, status=200):
        response = httpx.Response(status, json=result, request=httpx.Request("GET", "https://mp.weixin.qq.com/cgi-bin/searchbiz"))
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.get.return_value = response
        with patch.object(service.auth_manager, "get_credentials", return_value={"token": "test", "cookie": "test"}), \
                patch.object(service.httpx, "AsyncClient", return_value=client), \
                patch.object(service.rss_store, "get_active_blacklist_fakeids", return_value=["blocked"]):
            return asyncio.run(service.search_accounts(query="科技", begin=begin))

    def test_filtered_accounts_do_not_move_the_upstream_cursor_back(self):
        result = self.search({"base_resp": {"ret": 0}, "total": 10,
                              "list": [{"fakeid": "one"}, {"fakeid": "blocked"},
                                       *[{"fakeid": str(i)} for i in range(8)]]}, begin=5)
        self.assertEqual(result["data"]["next_begin"], 15)
        self.assertTrue(result["data"]["has_more"])
        self.assertEqual([item["fakeid"] for item in result["data"]["list"]], ["one", *[str(i) for i in range(8)]])

    def test_partial_page_ends_pagination(self):
        result = self.search({"base_resp": {"ret": 0}, "total": 2,
                              "list": [{"fakeid": "one"}, {"fakeid": "two"}]}, begin=5)
        self.assertEqual(result["data"]["next_begin"], 7)
        self.assertFalse(result["data"]["has_more"])

    def test_empty_results_end_pagination(self):
        result = self.search({"base_resp": {"ret": 0}, "total": 9, "list": []}, begin=5)
        self.assertFalse(result["data"]["has_more"])

    def test_expired_login_and_rate_limits_are_not_successful_pages(self):
        self.assertFalse(self.search({"base_resp": {"ret": 200003}})["success"])
        self.assertIn("200013", self.search({"base_resp": {"ret": 200013, "err_msg": "freq control"}})["error"])
        with self.assertRaises(HTTPException) as blocked:
            self.search({}, status=429)
        self.assertEqual(blocked.exception.status_code, 429)


if __name__ == "__main__":
    unittest.main()
