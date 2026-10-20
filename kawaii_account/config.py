"""Sozlamalar (.env dan)."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv


def _chat(v: str) -> str | int:
    v = v.strip().lstrip("@")
    return int(v) if v.lstrip("-").isdigit() else v


@dataclass(frozen=True)
class Config:
    api_id: int
    api_hash: str
    session: str
    watch_channels: list[str | int]
    kawaii_bot: str
    owner: str
    storage_chat: str | int
    db_path: str


def load() -> Config:
    load_dotenv()

    def need(name: str) -> str:
        v = os.getenv(name, "").strip()
        if not v:
            raise SystemExit(f".env da {name} yo'q")
        return v

    return Config(
        api_id=int(need("API_ID")),
        api_hash=need("API_HASH"),
        session=os.getenv("SESSION", "kawaii_account"),
        watch_channels=[_chat(c) for c in os.getenv("WATCH_CHANNELS", "").split(",") if c.strip()],
        kawaii_bot=need("KAWAII_BOT").lstrip("@"),
        owner=os.getenv("OWNER", "syntxme").lstrip("@"),
        storage_chat=_chat(os.getenv("STORAGE_CHAT", "me")),
        db_path=os.getenv("DB_PATH", "data/state.db"),
    )
