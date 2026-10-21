"""Holat: ko'rilgan postlar, vazifalar (job), yig'ilgan qismlar. SQLite."""

import os
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    chat_id INTEGER NOT NULL,
    msg_id  INTEGER NOT NULL,
    PRIMARY KEY (chat_id, msg_id)
);
-- status: probing → need_id → checking → collecting → uploading → done | skipped | failed
CREATE TABLE IF NOT EXISTS jobs (
    id        INTEGER PRIMARY KEY,
    chat_id   INTEGER,
    msg_id    INTEGER,
    bot       TEXT,
    param     TEXT,
    title     TEXT,
    status    TEXT NOT NULL,
    kawaii_id INTEGER,
    owner_msg INTEGER,
    note      TEXT,
    created   REAL NOT NULL
);
-- saved_msg: STORAGE_CHAT dagi nusxa
CREATE TABLE IF NOT EXISTS episodes (
    job_id    INTEGER NOT NULL,
    number    INTEGER NOT NULL,
    saved_msg INTEGER NOT NULL,
    uploaded  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (job_id, number)
);
-- Bir marta aniqlangan anime: manba nomi → Kawaii ID (keyingi qismlarda qayta so'ramaslik uchun)
CREATE TABLE IF NOT EXISTS known (
    title_key TEXT PRIMARY KEY,
    kawaii_id INTEGER NOT NULL
);
-- Homiylik uchun majburan qo'shilgan kanallar — 24 soatdan keyin chiqib ketiladi
CREATE TABLE IF NOT EXISTS joined (
    chat_id     INTEGER PRIMARY KEY,
    access_hash INTEGER,
    title       TEXT,
    joined_at   REAL NOT NULL
);
-- Kanal skani: [bottom_id, top_id] oralig'i ko'rib chiqilgan; finished — kanal boshigacha yetildi
CREATE TABLE IF NOT EXISTS scan (
    chat_id   INTEGER PRIMARY KEY,
    top_id    INTEGER NOT NULL,
    bottom_id INTEGER NOT NULL,
    finished  INTEGER NOT NULL DEFAULT 0
);
-- Manba botdagi anime (bot + ?start= parametri) → Kawaii ID. Nomdan ishonchliroq
CREATE TABLE IF NOT EXISTS sources (
    bot       TEXT NOT NULL,
    param     TEXT NOT NULL,
    kawaii_id INTEGER NOT NULL,
    PRIMARY KEY (bot, param)
);
"""


class Db:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.c = sqlite3.connect(path, isolation_level=None)
        self.c.row_factory = sqlite3.Row
        self.c.executescript(SCHEMA)
        # next_ep: Kawaii'da qaysi epizoddan boshlab kerak (keyin qo'shilgan ustun)
        if "next_ep" not in {r[1] for r in self.c.execute("PRAGMA table_info(jobs)")}:
            self.c.execute("ALTER TABLE jobs ADD COLUMN next_ep INTEGER")
        # src_eps: manbadagi qismlar soni (kartochkadagi "Qismi: 9")
        if "src_eps" not in {r[1] for r in self.c.execute("PRAGMA table_info(jobs)")}:
            self.c.execute("ALTER TABLE jobs ADD COLUMN src_eps INTEGER")
        # known.title: asl nom (o'xshash nomlarni solishtirish uchun)
        if "title" not in {r[1] for r in self.c.execute("PRAGMA table_info(known)")}:
            self.c.execute("ALTER TABLE known ADD COLUMN title TEXT")
            self.c.execute("UPDATE known SET title = (SELECT j.title FROM jobs j WHERE j.kawaii_id = known.kawaii_id ORDER BY j.id DESC LIMIT 1)")

    # ── postlar ──
    def post_seen(self, chat_id: int, msg_id: int) -> bool:
        return self.c.execute("SELECT 1 FROM posts WHERE chat_id=? AND msg_id=?", (chat_id, msg_id)).fetchone() is not None

    def mark_post(self, chat_id: int, msg_id: int) -> None:
        self.c.execute("INSERT OR IGNORE INTO posts VALUES (?, ?)", (chat_id, msg_id))

    # ── vazifalar ──
    def new_job(self, chat_id: int, msg_id: int, bot: str, param: str) -> int:
        cur = self.c.execute(
            "INSERT INTO jobs (chat_id, msg_id, bot, param, status, created) VALUES (?, ?, ?, ?, 'probing', ?)",
            (chat_id, msg_id, bot, param, time.time()),
        )
        return cur.lastrowid

    def job(self, job_id: int) -> sqlite3.Row | None:
        return self.c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()

    def update_job(self, job_id: int, **fields) -> None:
        cols = ", ".join(f"{k}=?" for k in fields)
        self.c.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), job_id))

    def job_for_post(self, chat_id: int, msg_id: int) -> sqlite3.Row | None:
        return self.c.execute("SELECT * FROM jobs WHERE chat_id=? AND msg_id=? ORDER BY id DESC", (chat_id, msg_id)).fetchone()

    def job_by_owner_msg(self, owner_msg: int) -> sqlite3.Row | None:
        return self.c.execute("SELECT * FROM jobs WHERE owner_msg=?", (owner_msg,)).fetchone()

    def jobs_with_status(self, *status: str) -> list[sqlite3.Row]:
        q = ",".join("?" * len(status))
        return self.c.execute(f"SELECT * FROM jobs WHERE status IN ({q}) ORDER BY id", status).fetchall()

    # ── qismlar ──
    def add_episode(self, job_id: int, number: int, saved_msg: int) -> None:
        self.c.execute("INSERT OR REPLACE INTO episodes (job_id, number, saved_msg) VALUES (?, ?, ?)", (job_id, number, saved_msg))

    def episodes(self, job_id: int, min_n: int = 1) -> list[sqlite3.Row]:
        return self.c.execute("SELECT * FROM episodes WHERE job_id=? AND number>=? ORDER BY number", (job_id, min_n)).fetchall()

    def mark_uploaded(self, job_id: int, numbers: list[int]) -> None:
        self.c.executemany("UPDATE episodes SET uploaded=1 WHERE job_id=? AND number=?", [(job_id, n) for n in numbers])

    def job_for_source(self, bot: str, param: str) -> sqlite3.Row | None:
        return self.c.execute("SELECT * FROM jobs WHERE lower(bot)=lower(?) AND param=? ORDER BY id DESC", (bot, param)).fetchone()

    # ── homiy kanallar ──
    def add_joined(self, chat_id: int, access_hash: int | None, title: str) -> None:
        self.c.execute("INSERT OR IGNORE INTO joined VALUES (?, ?, ?, ?)", (chat_id, access_hash, title, time.time()))

    def joined_before(self, ts: float) -> list[sqlite3.Row]:
        return self.c.execute("SELECT * FROM joined WHERE joined_at < ? ORDER BY joined_at", (ts,)).fetchall()

    def remove_joined(self, chat_id: int) -> None:
        self.c.execute("DELETE FROM joined WHERE chat_id=?", (chat_id,))

    # ── skan ──
    def scan_state(self, chat_id: int) -> sqlite3.Row | None:
        return self.c.execute("SELECT * FROM scan WHERE chat_id=?", (chat_id,)).fetchone()

    def save_scan(self, chat_id: int, top_id: int, bottom_id: int, finished: bool = False) -> None:
        self.c.execute("INSERT OR REPLACE INTO scan VALUES (?, ?, ?, ?)", (chat_id, top_id, bottom_id, int(finished)))

    # ── ma'lum animelar ──
    def known_id(self, title_key: str) -> int | None:
        r = self.c.execute("SELECT kawaii_id FROM known WHERE title_key=?", (title_key,)).fetchone()
        return r[0] if r else None

    def known_titles(self) -> list[tuple[str, int]]:
        return [(r[0], r[1]) for r in self.c.execute("SELECT title, kawaii_id FROM known WHERE title IS NOT NULL")]

    def source_id(self, bot: str, param: str) -> int | None:
        r = self.c.execute("SELECT kawaii_id FROM sources WHERE bot=? AND param=?", (bot.lower(), param)).fetchone()
        return r[0] if r else None

    def remember(self, title_key: str, title: str, kawaii_id: int, bot: str | None = None, param: str | None = None) -> None:
        self.c.execute("INSERT OR REPLACE INTO known (title_key, kawaii_id, title) VALUES (?, ?, ?)", (title_key, kawaii_id, title))
        if bot and param:
            self.c.execute("INSERT OR REPLACE INTO sources VALUES (?, ?, ?)", (bot.lower(), param, kawaii_id))
