"""Manba botlar uchun o'rganilgan retseptlar: qaysi tugmani bosish kerak.

Har bot — `RECIPES_DIR/<bot>.json` (qo'lda tuzatsa bo'ladi):
    {
      "bot": "Animelar_Makoni_Bot",
      "press": ["yuklab olish"],   # kartochkadan qismlarga o'tkazuvchi tugmalar
      "check": ["tasdiqlash"],     # homiylarga obuna bo'lgach bosiladigan tugma
      "never": ["kadrlar"]         # hech qachon bosilmaydi
    }
So'zlar tugma matnida qidiriladi (kichik harf, emoji va raqamlarsiz), shuning uchun boshqa animelarda ham ishlaydi.
"""

import json
import logging
import os
import re

log = logging.getLogger(__name__)

ROLES = ("press", "check", "never")


def pattern(text: str) -> str:
    """Tugma matnini umumlashtirish: "YUKLAB OLISH 📥" → "yuklab olish". Faqat emoji bo'lsa — o'zi."""
    t = re.sub(r"[^\w\s']+|\d+|_", " ", text.lower().replace("’", "'").replace("ʻ", "'"))
    t = re.sub(r"\s+", " ", t).strip(" '")
    return t or text.strip()


def matches(text: str, words: list[str]) -> bool:
    t = text.lower().replace("’", "'").replace("ʻ", "'")
    return any(w and w in t for w in words)


class Recipes:
    def __init__(self, directory: str) -> None:
        self.dir = directory
        os.makedirs(directory, exist_ok=True)

    def _path(self, bot: str) -> str:
        return os.path.join(self.dir, f"{bot.lower()}.json")

    def get(self, bot: str) -> dict:
        try:
            with open(self._path(bot), encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            data = {}
        except (OSError, ValueError) as e:
            log.warning("Retsept o'qilmadi (%s): %s", bot, e)
            data = {}
        data.setdefault("bot", bot)
        for role in ROLES:
            data.setdefault(role, [])
        return data

    def words(self, bot: str, role: str) -> list[str]:
        return self.get(bot)[role]

    def _save(self, data: dict) -> None:
        with open(self._path(data["bot"]), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def add(self, bot: str, role: str, word: str) -> None:
        data = self.get(bot)
        if word not in data[role]:
            data[role].append(word)
            self._save(data)
            log.info("Retsept @%s: %s += %r", bot, role, word)

    def remove(self, bot: str, word: str) -> bool:
        data = self.get(bot)
        found = False
        for role in ROLES:
            if word in data[role]:
                data[role].remove(word)
                found = True
        if found:
            self._save(data)
        return found

    def show(self, bot: str) -> str:
        return json.dumps(self.get(bot), ensure_ascii=False, indent=2)
