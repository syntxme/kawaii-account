"""Harakatlar orasidagi tasodifiy kutish (flood bo'lmasligi va odamga o'xshab ishlash uchun).

Har biri `.env` da `PAUSE_<NOM>=min-max` (soniya) bilan o'zgartiriladi, masalan `PAUSE_POST=60-120`.
"""

import asyncio
import logging
import os
import random

log = logging.getLogger(__name__)

DEFAULTS = {
    "post": (40, 90),  # skanda bitta anime posti ishlangandan keyin
    "skip": (3, 6),  # skanda o'tkazib yuborilgan (takroriy) postdan keyin
    "click": (3, 6),  # manba botda qism / sahifa tugmalari orasida
    "send": (2, 4),  # Kawaii botga videolar orasida
}


def _range(name: str) -> tuple[float, float]:
    raw = os.getenv(f"PAUSE_{name.upper()}", "")
    try:
        lo, _, hi = raw.partition("-")
        return float(lo), float(hi or lo)
    except ValueError:
        return DEFAULTS[name]


async def pause(name: str) -> None:
    lo, hi = _range(name)
    secs = random.uniform(lo, hi)
    if secs >= 10:
        log.info("⏸ %.0f s kutyapman (%s)", secs, name)
    await asyncio.sleep(secs)
