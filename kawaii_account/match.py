"""Anime nomlarini solishtirish: imlo xatolariga chidamli, lekin fasl/qism raqamlariga qat'iy."""

import re
from difflib import SequenceMatcher

# Bundan yuqori — o'sha anime deb avtomatik qabul qilinadi; SUGGEST..AUTO — egasiga taklif sifatida ko'rsatiladi
AUTO = 0.88
SUGGEST = 0.6

# O'zbek lotinidagi tez-tez almashadigan yozuvlar (guruxi/guruhi, eng/enh, tug'ulish/tug'ilish …)
_SIMILAR = str.maketrans({"x": "h", "q": "k", "w": "v", "y": "i", "u": "i", "ё": "е"})


def norm(title: str) -> str:
    """Taqqoslash uchun: kichik harf, faqat harf/raqam."""
    t = title.lower().replace("ʻ", "'").replace("‘", "'").replace("’", "'").replace("`", "'")
    return re.sub(r"[\W_]+", "", t)


def _numbers(title: str) -> list[str]:
    return [n.lstrip("0") or "0" for n in re.findall(r"\d+", title)]


def similarity(a: str, b: str) -> float:
    """0..1. Raqamlar ("3-fasl", "2-qism") farq qilsa — boshqa anime, 0."""
    if _numbers(a) != _numbers(b):
        return 0.0
    na, nb = norm(a), norm(b)
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na.translate(_SIMILAR), nb.translate(_SIMILAR)).ratio()


def rank(title: str, known: list[tuple[str, int]]) -> list[tuple[float, int, str]]:
    """known: [(nom, kawaii_id)] → [(o'xshashlik, kawaii_id, nom)] kamayish tartibida, har ID bir marta."""
    best: dict[int, tuple[float, int, str]] = {}
    for name, kid in known:
        score = similarity(title, name)
        if score >= SUGGEST and score > best.get(kid, (0.0,))[0]:
            best[kid] = (score, kid, name)
    return sorted(best.values(), reverse=True)
