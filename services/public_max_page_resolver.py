import json
import logging
import os
import re
import sqlite3
from typing import Any
from urllib.parse import quote

import httpx

from database.storage import DB_PATH

logger = logging.getLogger(__name__)

ALLOWED_HOSTS = {"max.ru", "www.max.ru"}
ALIAS_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
MAX_RESPONSE_SIZE = 2 * 1024 * 1024
REQUEST_TIMEOUT = 7
CONNECT_TIMEOUT = 3


def _normalize_alias(value: str) -> str | None:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    if value.startswith("@"):
        value = value[1:]
    if "://" in value:
        rest = value.split("://", 1)[1]
    else:
        rest = value
    if "/" in rest:
        host_part = rest.split("/", 1)[0]
        path = rest.split("/", 1)[1]
    else:
        host_part = rest
        path = ""
    if host_part not in ALLOWED_HOSTS:
        if "/" not in rest and "?" not in rest and "#" not in rest and host_part:
            path = host_part
        else:
            return None
    if "?" in path:
        path = path.split("?", 1)[0]
    if "#" in path:
        path = path.split("#", 1)[0]
    path = path.strip("/")
    if not path or "/" in path or "\\" in path or "\x00" in path:
        return None
    if "." in path:
        return None
    if not ALIAS_PATTERN.match(path):
        return None
    return path


def _parse_channel_info(html: str, alias: str) -> dict[str, Any] | None:
    start_marker = "linkInfo:{channel:{"
    start = html.find(start_marker)
    if start == -1:
        return None
    pos = start + len(start_marker)
    depth = 2
    while pos < len(html) and depth > 0:
        ch = html[pos]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        pos += 1
    if depth != 0:
        return None
    payload = html[start + len(start_marker): pos - 1]
    data: dict[str, Any] = {}
    for field in re.finditer(r"(?P<key>[A-Za-z0-9]+):(?P<value>[^,}]+)", payload):
        key = field.group("key")
        raw_value = field.group("value").strip()
        if key == "channelId":
            try:
                data[key] = int(raw_value)
            except (TypeError, ValueError):
                return None
        elif key == "participantsCount":
            try:
                data[key] = int(raw_value)
            except (TypeError, ValueError):
                data[key] = None
        else:
            data[key] = raw_value.strip('"')
    if "channelId" not in data or not isinstance(data["channelId"], int):
        return None
    canonical = data.get("canonical") or _extract_canonical(html, start)
    if not canonical:
        return None
    canonical_lower = canonical.lower()
    if not canonical_lower.startswith(("https://max.ru/", "https://www.max.ru/")):
        return None
    if not canonical_lower.rstrip("/").endswith("/" + alias.lower()):
        return None
    return data


def _extract_canonical(html: str, link_info_start: int) -> str:
    """Извлекает canonical из области около linkInfo."""
    window = html[link_info_start: link_info_start + 2000]
    match = re.search(r"canonical:\"(?P<value>[^\"]+)\"", window)
    if not match:
        return ""
    return match.group("value").strip('"')


def _apply_proven_chat_id_mapping(channel_id: int) -> int:
    return -abs(channel_id)


def init_public_link_cache() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS known_public_max_links (
                normalized_link TEXT PRIMARY KEY,
                raw_channel_id INTEGER NOT NULL,
                bot_chat_id INTEGER NOT NULL,
                title TEXT,
                participants_count INTEGER,
                source TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def get_cached_public_link(normalized_link: str) -> dict[str, Any] | None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM known_public_max_links WHERE normalized_link = ?",
            (normalized_link,),
        ).fetchone()
    if not row:
        return None
    return dict(row)


def upsert_public_link_cache(record: dict[str, Any]) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO known_public_max_links (
                normalized_link,
                raw_channel_id,
                bot_chat_id,
                title,
                participants_count,
                source,
                first_seen_at,
                last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(normalized_link) DO UPDATE SET
                raw_channel_id = excluded.raw_channel_id,
                bot_chat_id = excluded.bot_chat_id,
                title = excluded.title,
                participants_count = excluded.participants_count,
                last_seen_at = excluded.last_seen_at
            """,
            (
                record["normalized_link"],
                record["raw_channel_id"],
                record["bot_chat_id"],
                record.get("title"),
                record.get("participants_count"),
                record["source"],
                record["first_seen_at"],
                record["last_seen_at"],
            ),
        )
        conn.commit()


async def resolve_public_max_link(url_or_alias: str) -> dict[str, Any] | None:
    alias = _normalize_alias(url_or_alias)
    if not alias:
        return None

    encoded_alias = quote(alias, safe="")
    target_url = f"https://max.ru/{encoded_alias}"
    cache_key = "@" + alias

    try:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=CONNECT_TIMEOUT),
            follow_redirects=True,
        ) as client:
            response = await client.get(target_url, headers=headers)
        if response.status_code != 200:
            return None
        content_type = response.headers.get("content-type", "").lower()
        if "text/html" not in content_type:
            return None
        if len(response.content) > MAX_RESPONSE_SIZE:
            return None
        html = response.text
        info = _parse_channel_info(html, alias)
        if not info:
            return None
        raw_channel_id = int(info["channelId"])
        bot_chat_id = _apply_proven_chat_id_mapping(raw_channel_id)
        result = {
            "normalized_link": cache_key,
            "raw_channel_id": raw_channel_id,
            "bot_chat_id": bot_chat_id,
            "title": info.get("title"),
            "participants_count": info.get("participantsCount"),
            "source": "public_page",
        }
        return result
    except httpx.TimeoutException:
        cached = get_cached_public_link(cache_key)
        if cached:
            cached["source"] = "public_page_cache"
            return cached
        return None
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return None
        cached = get_cached_public_link(cache_key)
        if cached:
            cached["source"] = "public_page_cache"
            return cached
        return None
    except Exception as exc:
        logger.warning("Public MAX page resolver failed: %s", type(exc).__name__)
        cached = get_cached_public_link(cache_key)
        if cached:
            cached["source"] = "public_page_cache"
            return cached
        return None
