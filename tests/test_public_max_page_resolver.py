from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.public_max_page_resolver import (
    _apply_proven_chat_id_mapping,
    _normalize_alias,
    _parse_channel_info,
    get_cached_public_link,
    init_public_link_cache,
    resolve_public_max_link,
    upsert_public_link_cache,
)


class TestNormalizeAlias(unittest.TestCase):
    def test_full_url(self):
        self.assertEqual(_normalize_alias("https://max.ru/olubimtseva"), "olubimtseva")

    def test_www_url(self):
        self.assertEqual(_normalize_alias("https://www.max.ru/olubimtseva"), "olubimtseva")

    def test_scheme_less(self):
        self.assertEqual(_normalize_alias("max.ru/olubimtseva"), "olubimtseva")

    def test_at_alias(self):
        self.assertEqual(_normalize_alias("@olubimtseva"), "olubimtseva")

    def test_plain_alias(self):
        self.assertEqual(_normalize_alias("olubimtseva"), "olubimtseva")

    def test_query_and_fragment_removed(self):
        self.assertEqual(
            _normalize_alias("https://max.ru/olubimtseva?foo=bar#frag"),
            "olubimtseva",
        )

    def test_trailing_slash_removed(self):
        self.assertEqual(_normalize_alias("https://max.ru/olubimtseva/"), "olubimtseva")

    def test_invalid_host(self):
        self.assertIsNone(_normalize_alias("https://other.ru/olubimtseva"))

    def test_join_url_rejected(self):
        self.assertIsNone(_normalize_alias("https://max.ru/join/abc"))

    def test_invite_url_rejected(self):
        self.assertIsNone(_normalize_alias("https://max.ru/invite/abc"))

    def test_post_url_rejected(self):
        self.assertIsNone(_normalize_alias("https://max.ru/post/123"))

    def test_path_traversal_rejected(self):
        self.assertIsNone(_normalize_alias("https://max.ru/../other"))
        self.assertIsNone(_normalize_alias("https://max.ru/olubimtseva/.."))

    def test_control_characters_rejected(self):
        self.assertIsNone(_normalize_alias("https://max.ru/olubi\x00mtseva"))

    def test_dots_rejected(self):
        self.assertIsNone(_normalize_alias("https://max.ru/olubimtseva.txt"))

    def test_empty(self):
        self.assertIsNone(_normalize_alias(""))
        self.assertIsNone(_normalize_alias("   "))


class TestParseChannelInfo(unittest.TestCase):
    @staticmethod
    def _build_html(channel_id: int, alias: str) -> str:
        return (
            "<html><script>"
            "data: [null,{type:\"data\",data:{linkInfo:{channel:{title:\"Test\",description:\"\",icon:\"\",participantsCount:10,channelId:"
            + str(channel_id)
            + "}},isBot:true,canonical:\"https://max.ru/"
            + alias
            + "\"}},uses:{url:1}},null,"
            "</script></html>"
        )

    def test_valid_channel(self):
        html = self._build_html(72143469522347, "id752703975446_biz")
        info = _parse_channel_info(html, "id752703975446_biz")
        self.assertIsNotNone(info)
        self.assertEqual(info["channelId"], 72143469522347)
        self.assertEqual(info["title"], "Test")

    def test_missing_link_info(self):
        html = "<html><script>data: [null,{type:'data'}]</script></html>"
        self.assertIsNone(_parse_channel_info(html, "alias"))

    def test_non_int_channel_id(self):
        html = self._build_html(0, "alias")
        html = html.replace("channelId:0", "channelId:not_a_number")
        self.assertIsNone(_parse_channel_info(html, "alias"))

    def test_wrong_canonical(self):
        html = self._build_html(123, "alias")
        html = html.replace("canonical:\"https://max.ru/alias\"", "canonical:\"https://other.max.ru/alias\"")
        self.assertIsNone(_parse_channel_info(html, "alias"))

    def test_channel_id_outside_link_info_ignored(self):
        html = """
        <html>
        <script>
        data: [null,{type:"data",data:{linkInfo:{channel:{channelId:111}},isBot:true,canonical:"https://max.ru/alias"}},{type:"data",data:{channelId:222}},null,
        </script>
        </html>
        """
        info = _parse_channel_info(html, "alias")
        self.assertIsNotNone(info)
        self.assertEqual(info["channelId"], 111)


class TestProvenChatIdMapping(unittest.TestCase):
    def test_positive_channel_id_returns_negative(self):
        self.assertEqual(_apply_proven_chat_id_mapping(72143469522347), -72143469522347)

    def test_negative_input_still_negative(self):
        self.assertEqual(_apply_proven_chat_id_mapping(-72143469522347), -72143469522347)


class TestPublicLinkCache(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="maxidbot_public_link_tests_")
        self.old_db = os.environ.get("MAXIDBOT_DB_PATH")
        os.environ["MAXIDBOT_DB_PATH"] = os.path.join(self.tmp_dir, "test.sqlite3")
        init_public_link_cache()

    def tearDown(self):
        if self.old_db is not None:
            os.environ["MAXIDBOT_DB_PATH"] = self.old_db
        else:
            os.environ.pop("MAXIDBOT_DB_PATH", None)

    def test_upsert_and_get(self):
        record = {
            "normalized_link": "@olubimtseva",
            "raw_channel_id": 69403472385364,
            "bot_chat_id": -69403472385364,
            "title": "Ольга Любимцева",
            "participants_count": 5866,
            "source": "public_page",
            "first_seen_at": "2026-07-18T00:00:00+00:00",
            "last_seen_at": "2026-07-18T00:00:00+00:00",
        }
        upsert_public_link_cache(record)
        cached = get_cached_public_link("@olubimtseva")
        self.assertIsNotNone(cached)
        self.assertEqual(cached["bot_chat_id"], -69403472385364)
        self.assertEqual(cached["title"], "Ольга Любимцева")


class TestResolvePublicMaxLink(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="maxidbot_public_link_tests_")
        self.old_db = os.environ.get("MAXIDBOT_DB_PATH")
        os.environ["MAXIDBOT_DB_PATH"] = os.path.join(self.tmp_dir, "test.sqlite3")
        init_public_link_cache()

    def tearDown(self):
        if self.old_db is not None:
            os.environ["MAXIDBOT_DB_PATH"] = self.old_db
        else:
            os.environ.pop("MAXIDBOT_DB_PATH", None)

    def _html(self, channel_id: int, alias: str) -> str:
        return (
            "<html><script>"
            "data: [null,{type:\"data\",data:{linkInfo:{channel:{title:\"Test\",icon:\"\",participantsCount:10,channelId:"
            + str(channel_id)
            + "}},isBot:true,canonical:\"https://max.ru/"
            + alias
            + "\"}},uses:{url:1}},null,"
            "</script></html>"
        )

    def test_success_from_page(self):
        html = self._html(72143469522347, "id752703975446_biz")
        response = AsyncMock()
        response.status_code = 200
        response.headers = {"content-type": "text/html; charset=utf-8"}
        response.content = html.encode("utf-8")
        response.text = html

        client = AsyncMock()
        client.get = AsyncMock(return_value=response)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("services.public_max_page_resolver.httpx.AsyncClient", return_value=client):
            result = asyncio.run(resolve_public_max_link("https://max.ru/id752703975446_biz"))

        self.assertIsNotNone(result)
        self.assertEqual(result["bot_chat_id"], -72143469522347)
        self.assertEqual(result["source"], "public_page")

    def test_cache_fallback_on_timeout(self):
        record = {
            "normalized_link": "@olubimtseva",
            "raw_channel_id": 69403472385364,
            "bot_chat_id": -69403472385364,
            "title": "Ольга Любимцева",
            "participants_count": 5866,
            "source": "public_page",
            "first_seen_at": "2026-07-18T00:00:00+00:00",
            "last_seen_at": "2026-07-18T00:00:00+00:00",
        }
        upsert_public_link_cache(record)

        client = AsyncMock()
        client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("services.public_max_page_resolver.httpx.AsyncClient", return_value=client):
            result = asyncio.run(resolve_public_max_link("https://max.ru/olubimtseva"))

        self.assertIsNotNone(result)
        self.assertEqual(result["bot_chat_id"], -69403472385364)
        self.assertEqual(result["source"], "public_page_cache")

    def test_404_returns_none(self):
        response = AsyncMock()
        response.status_code = 404
        response.headers = {"content-type": "text/html"}
        response.text = ""

        client = AsyncMock()
        client.get = AsyncMock(return_value=response)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("services.public_max_page_resolver.httpx.AsyncClient", return_value=client):
            result = asyncio.run(resolve_public_max_link("https://max.ru/doesnotexist"))

        self.assertIsNone(result)

    def test_too_large_response_returns_none(self):
        response = AsyncMock()
        response.status_code = 200
        response.headers = {"content-type": "text/html"}
        response.content = b"x" * (2 * 1024 * 1024 + 1)
        response.text = "x" * (2 * 1024 * 1024 + 1)

        client = AsyncMock()
        client.get = AsyncMock(return_value=response)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("services.public_max_page_resolver.httpx.AsyncClient", return_value=client):
            result = asyncio.run(resolve_public_max_link("https://max.ru/olubimtseva"))

        self.assertIsNone(result)

    def test_wrong_content_type_returns_none(self):
        response = AsyncMock()
        response.status_code = 200
        response.headers = {"content-type": "application/json"}
        response.text = '{"ok":true}'

        client = AsyncMock()
        client.get = AsyncMock(return_value=response)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("services.public_max_page_resolver.httpx.AsyncClient", return_value=client):
            result = asyncio.run(resolve_public_max_link("https://max.ru/olubimtseva"))

        self.assertIsNone(result)

    def test_external_redirect_blocked(self):
        response = AsyncMock()
        response.status_code = 200
        response.headers = {"content-type": "text/html"}
        response.url = "https://evil.example.com/"
        response.text = ""

        client = AsyncMock()
        client.get = AsyncMock(return_value=response)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("services.public_max_page_resolver.httpx.AsyncClient", return_value=client):
            result = asyncio.run(resolve_public_max_link("https://max.ru/olubimtseva"))

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
