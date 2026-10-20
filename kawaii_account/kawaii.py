"""Kawaii bot admin oqimi: qidiruv va epizod yuklash (../kawaii-bot/bot/src/handlers/admin/)."""

import logging
import re
from dataclasses import dataclass

from telethon import TelegramClient
from telethon.tl.custom import Message

from .match import norm
from .pace import pause
from .tg import Btn, Inbox, NeedHuman, Watcher, cb_buttons, click, send

log = logging.getLogger(__name__)

BTN_ADD_EPISODES = "➕ Epizod qo'shish"
PICK_DATA = re.compile(rb"^a:pk:p:(\d+)$")


@dataclass
class Found:
    id: int
    title: str
    ongoing: bool
    msg: Message
    btn: Btn


def same_title(shown: str, title: str) -> bool:
    """Kawaii tugmada nomni 50 belgigacha qisqartiradi ("…" bilan)."""
    if shown.endswith("…"):
        head = norm(shown[:-1])
        return bool(head) and norm(title).startswith(head)
    return norm(shown) == norm(title)


def save_button(m: Message) -> Btn | None:
    return next((b for b in cb_buttons(m) if "bazaga qo'shish" in b.text), None)


def results(m: Message) -> list[Found]:
    out = []
    for b in cb_buttons(m):
        if mt := PICK_DATA.match(b.data or b""):
            out.append(Found(int(mt.group(1)), b.text[1:].strip(), b.text.startswith("🔸"), m, b))
    return out


class Kawaii:
    def __init__(self, client: TelegramClient, watcher: Watcher, bot: str, storage) -> None:
        self.client = client
        self.watcher = watcher
        self.bot_name = bot
        self.storage = storage

    async def _open(self, inbox: Inbox) -> None:
        """/admin → "➕ Epizod qo'shish" → qidiruv so'rovi."""
        inbox.drain()
        await send(self.client, self.bot_name, "/admin", self.bot_name)
        await inbox.settle(quiet=2, timeout=15)
        inbox.drain()
        await send(self.client, self.bot_name, BTN_ADD_EPISODES, self.bot_name)
        if not await inbox.until(lambda m: "yuboring" in (m.message or ""), timeout=20):
            raise NeedHuman("Kawaii bot epizod qo'shish menyusini ochmadi — akkaunt admin emasmi?")

    async def _search(self, inbox: Inbox, query: str) -> list[Found]:
        inbox.drain()
        await send(self.client, self.bot_name, query, self.bot_name)
        m = await inbox.until(lambda m: bool(results(m)) or "topilmadi" in (m.message or ""), timeout=20)
        return results(m) if m else []

    async def search(self, title: str) -> tuple[int | None, list[Found]]:
        """(aniq mos ID yoki None, barcha natijalar)."""
        bot = await self.client.get_entity(self.bot_name)
        with self.watcher.watch(bot.id, self.bot_name) as inbox:
            await self._open(inbox)
            found = await self._search(inbox, title)
        exact = [f for f in found if same_title(f.title, title)]
        return (exact[0].id if len(exact) == 1 else None), found

    async def _pick(self, inbox: Inbox, anime_id: int) -> tuple[str, int, Message]:
        """`#id` qidirib animeni tanlash. (nom, qaysi epizoddan boshlash kerak, kirish xabari).

        `#id` bo'yicha bot ko'pincha natijalar ro'yxatisiz to'g'ridan-to'g'ri yuklash ekranini ochadi."""
        await self._open(inbox)
        inbox.drain()
        await send(self.client, self.bot_name, f"#{anime_id}", self.bot_name)
        m = await inbox.until(
            lambda m: bool(results(m)) or any(k in (m.message or "") for k in ("epizoddan boshlab", "topilmadi", "OnGoing")),
            timeout=30,
        )
        if m is None:
            raise NeedHuman(f"Kawaii bot #{anime_id} qidiruviga javob bermadi")
        text = m.message or ""
        if "OnGoing" in text:
            raise NeedHuman(f"#{anime_id} OnGoing emas — avval statusini OnGoing qiling")

        if "epizoddan boshlab" in text:
            intro = m
            log.info("Kawaii #%d: yuklash ekrani darhol ochildi", anime_id)
        else:
            found = [f for f in results(m) if f.id == anime_id]
            log.info("Qidiruv natijasi: %s", [(f.id, f.title) for f in results(m)] or "bo'sh")
            if not found:
                raise NeedHuman(f"Kawaii'da #{anime_id} topilmadi (natijalar: {[f.id for f in results(m)] or 'yoq'})")
            f = found[0]
            if not f.ongoing:
                raise NeedHuman(f"«{f.title}» (#{anime_id}) OnGoing emas — avval statusini OnGoing qiling")
            inbox.drain()
            answer = await click(self.client, f.msg, f.btn)
            if "OnGoing" in answer:
                raise NeedHuman(f"«{f.title}» (#{anime_id}) OnGoing emas — avval statusini OnGoing qiling")
            intro = await inbox.until(lambda m: "epizoddan boshlab" in (m.message or ""), timeout=30)
            if intro is None:
                raise NeedHuman("Kawaii bot epizod yuklash ekranini ochmadi")

        # "📕 <nom>" / "📺 10 / 10 - epizoddan boshlab yuboring" — birinchi raqam: keyingi kerakli epizod
        title = re.sub(r"^[^\w]+", "", intro.message.splitlines()[0]).strip()
        mt = re.search(r"(\d+)\s*/\s*\S+\s*-\s*epizoddan", intro.message)
        return title, (int(mt.group(1)) if mt else 1), intro

    async def _exit(self, msg: Message) -> None:
        if back := next((b for b in cb_buttons(msg) if "Chiqish" in b.text), None):
            await click(self.client, msg, back)

    async def next_episode(self, anime_id: int) -> tuple[str, int]:
        """Kawaii'da animega qaysi epizoddan boshlab yuborish kerak. (nom, raqam)."""
        bot = await self.client.get_entity(self.bot_name)
        with self.watcher.watch(bot.id, self.bot_name) as inbox:
            title, nxt, intro = await self._pick(inbox, anime_id)
            await self._exit(intro)
        log.info("Kawaii #%d «%s»: %d-epizoddan boshlab kerak", anime_id, title, nxt)
        return title, nxt

    async def upload(self, anime_id: int, episodes: list[tuple[int, int]]) -> list[int]:
        """episodes: [(raqam, storage xabar id)]. Yuklangan raqamlarni qaytaradi."""
        bot = await self.client.get_entity(self.bot_name)
        with self.watcher.watch(bot.id, self.bot_name) as inbox:
            _, nxt, intro = await self._pick(inbox, anime_id)
            todo = [(n, s) for n, s in episodes if n >= nxt]
            if not todo:
                await self._exit(intro)
                log.info("#%d: yangi qism yo'q (Kawaii'da %d gacha bor)", anime_id, nxt - 1)
                return []
            nums = [n for n, _ in todo]
            # Oraliqda tushib qolgan qism bo'lsa bot saqlamaydi — oldindan tekshiramiz
            if nums != list(range(nxt, nums[-1] + 1)):
                await self._exit(intro)
                missing = sorted(set(range(nxt, nums[-1] + 1)) - set(nums))
                raise NeedHuman(f"#{anime_id}: {nxt}-qismdan boshlab kerak, lekin yetishmayapti: {missing}")

            for n, saved_id in todo:
                saved = await self.client.get_messages(self.storage, ids=saved_id)
                if saved is None or saved.media is None:
                    raise NeedHuman(f"{n}-qism saqlangan xabari ({saved_id}) topilmadi")
                log.info("→ @%s: [video] %d-qism (storage #%d)", self.bot_name, n, saved_id)
                await self.client.send_file(bot, saved.media, caption=f"{n}-qism")
                await pause("send")

            # Bot xulosani ("✅ Yangi epizodlar: …") oxirgi videodan 1.5 s keyin chiqaradi (va har safar qayta yuboradi)
            await inbox.settle(quiet=5, timeout=120)
            summaries = [m for m in inbox.latest.values() if save_button(m)]
            if not summaries:
                raise NeedHuman("Kawaii bot videolarni qabul qilmadi (saqlash tugmasi chiqmadi)")
            summary = max(summaries, key=lambda m: m.id)
            inbox.drain()
            answer = await click(self.client, summary, save_button(summary))
            if "yetishmayotgan" in answer:
                raise NeedHuman(f"#{anime_id}: Kawaii bot yetishmayotgan qism borligini aytdi")
            log.info("Bazaga qo'shilyapti…")

            done = await inbox.until(lambda m: "muvaffaqiyatli saqlandi" in (m.message or ""), timeout=len(todo) * 6 + 120)
            if done is None:
                raise NeedHuman(f"#{anime_id}: saqlash tugaganini kutib bo'lmadi — Kawaii botni tekshiring")
            await self._exit(done)
            if mt := re.search(r"(\d+) ta epizodni saqlab bo'lmadi", done.message):
                raise NeedHuman(f"#{anime_id}: {mt.group(1)} ta qismni Kawaii bot saqlay olmadi")
            return nums
