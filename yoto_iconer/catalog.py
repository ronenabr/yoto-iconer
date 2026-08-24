"""Local SQLite catalog of icons, with an FTS5 index for candidate lookup."""

from __future__ import annotations

import sqlite3
import time

from . import api, config, yotoicons

SCHEMA = """
CREATE TABLE IF NOT EXISTS icons (
    key        TEXT PRIMARY KEY,   -- 'official:<mediaId>' | 'community:<id>' | 'user:<mediaId>'
    source     TEXT NOT NULL,      -- official | community | user
    ref        TEXT NOT NULL,      -- mediaId, or the yotoicons numeric id
    title      TEXT NOT NULL,
    tags       TEXT NOT NULL DEFAULT '',
    category   TEXT NOT NULL DEFAULT '',
    author     TEXT NOT NULL DEFAULT '',
    downloads  INTEGER NOT NULL DEFAULT 0,
    media_id   TEXT,               -- resolved Yoto mediaId (NULL until a community icon is uploaded)
    img_url    TEXT,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS icons_source ON icons(source);

CREATE VIRTUAL TABLE IF NOT EXISTS icons_fts USING fts5(
    key UNINDEXED,
    text,
    tokenize='porter unicode61'
);

CREATE TABLE IF NOT EXISTS uploads (
    sha256     TEXT PRIMARY KEY,
    media_id   TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""


def connect(path=None) -> sqlite3.Connection:
    config.ensure_home()
    conn = sqlite3.connect(str(path or config.catalog_path()))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _fts_text(rec: dict) -> str:
    parts = [rec.get("title", ""), rec.get("tags", ""), rec.get("category", "")]
    return " ".join(p for p in parts if p).lower()


def upsert(conn: sqlite3.Connection, records: list[dict]) -> int:
    """Insert or refresh icon rows and keep the FTS index in step."""
    now = int(time.time())
    written = 0
    for rec in records:
        rec = {**rec, "updated_at": now}
        conn.execute(
            """
            INSERT INTO icons (key, source, ref, title, tags, category, author,
                               downloads, media_id, img_url, updated_at)
            VALUES (:key, :source, :ref, :title, :tags, :category, :author,
                    :downloads, :media_id, :img_url, :updated_at)
            ON CONFLICT(key) DO UPDATE SET
                title=excluded.title, tags=excluded.tags, category=excluded.category,
                author=excluded.author, downloads=excluded.downloads,
                img_url=excluded.img_url, updated_at=excluded.updated_at,
                media_id=COALESCE(icons.media_id, excluded.media_id)
            """,
            {
                "key": rec["key"],
                "source": rec["source"],
                "ref": rec["ref"],
                "title": rec.get("title", ""),
                "tags": rec.get("tags", ""),
                "category": rec.get("category", ""),
                "author": rec.get("author", ""),
                "downloads": rec.get("downloads", 0),
                "media_id": rec.get("media_id"),
                "img_url": rec.get("img_url"),
                "updated_at": now,
            },
        )
        conn.execute("DELETE FROM icons_fts WHERE key = ?", (rec["key"],))
        conn.execute(
            "INSERT INTO icons_fts (key, text) VALUES (?, ?)", (rec["key"], _fts_text(rec))
        )
        written += 1
    conn.commit()
    return written


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
        (key, value),
    )
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT v FROM meta WHERE k = ?", (key,)).fetchone()
    return row["v"] if row else None


def stats(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT source, COUNT(*) n FROM icons GROUP BY source").fetchall()
    out = {r["source"]: r["n"] for r in rows}
    out["uploaded"] = conn.execute("SELECT COUNT(*) n FROM uploads").fetchone()["n"]
    for name in ("official_synced_at", "community_synced_at"):
        if (val := get_meta(conn, name)):
            out[name] = val
    return out


def get(conn: sqlite3.Connection, key: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM icons WHERE key = ?", (key,)).fetchone()


def remember_upload(conn: sqlite3.Connection, sha: str, media_id: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO uploads (sha256, media_id, created_at) VALUES (?, ?, ?)",
        (sha, media_id, int(time.time())),
    )
    conn.commit()


def upload_for_sha(conn: sqlite3.Connection, sha: str) -> str | None:
    row = conn.execute("SELECT media_id FROM uploads WHERE sha256 = ?", (sha,)).fetchone()
    return row["media_id"] if row else None


def set_media_id(conn: sqlite3.Connection, key: str, media_id: str) -> None:
    conn.execute("UPDATE icons SET media_id = ? WHERE key = ?", (media_id, key))
    conn.commit()


# --- sync sources ------------------------------------------------------------


def _normalize_official(item: dict, source: str) -> dict | None:
    media_id = item.get("mediaId") or item.get("id")
    if not media_id:
        return None
    tags = item.get("publicTags") or item.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    return {
        "key": f"{source}:{media_id}",
        "source": source,
        "ref": media_id,
        "title": (item.get("title") or item.get("displayIconId") or media_id).strip(),
        "tags": " ".join(str(t).strip().lower() for t in tags),
        "category": item.get("category", "") or "",
        "author": "yoto" if source == "official" else "me",
        "downloads": 0,
        "media_id": media_id,
        "img_url": item.get("url"),
    }


def sync_official(conn: sqlite3.Connection, token: str) -> int:
    items = api.list_public_icons(token)
    records = [r for r in (_normalize_official(i, "official") for i in items) if r]
    n = upsert(conn, records)
    set_meta(conn, "official_synced_at", time.strftime("%Y-%m-%dT%H:%M:%S"))
    return n


def sync_user(conn: sqlite3.Connection, token: str) -> int:
    items = api.list_user_icons(token)
    records = [r for r in (_normalize_official(i, "user") for i in items) if r]
    n = upsert(conn, records)
    set_meta(conn, "user_synced_at", time.strftime("%Y-%m-%dT%H:%M:%S"))
    return n


def community_record(rec: dict) -> dict:
    return {
        "key": f"community:{rec['id']}",
        "source": "community",
        "ref": rec["id"],
        "title": rec.get("title", ""),
        "tags": " ".join(rec.get("tags", [])),
        "category": rec.get("category", ""),
        "author": rec.get("artist", ""),
        "downloads": rec.get("downloads", 0),
        "media_id": None,
        "img_url": yotoicons.png_url(rec["id"]),
    }


def sync_community(conn: sqlite3.Connection, pages: int, progress=None) -> int:
    records = [community_record(r) for r in yotoicons.crawl(pages, progress=progress)]
    n = upsert(conn, records)
    set_meta(conn, "community_synced_at", time.strftime("%Y-%m-%dT%H:%M:%S"))
    set_meta(conn, "community_pages", str(pages))
    return n


def absorb_community_search(conn: sqlite3.Connection, tag: str) -> int:
    """Fold a live yotoicons tag lookup into the catalog."""
    records = [community_record(r) for r in yotoicons.search(tag)]
    return upsert(conn, records)
