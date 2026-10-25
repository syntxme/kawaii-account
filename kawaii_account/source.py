"""Manba bot: /start → homiylar → qism tugmalari → videolarni yig'ish."""

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable

from telethon import TelegramClient
from telethon.tl import types
from telethon.tl.custom import Message

from .pace import pause
from .recipes import Recipes, matches
from .tg import JOIN_DELAY, Btn, Inbox, buttons, mute, send, NeedHuman, Watcher, cb_buttons, click, is_video, join, parse_tme, url_buttons

log = logging.getLogger(__name__)

# Bitta raqamli tugma — qism ("12", "▫️ 12", "12-qism", "[ 12 ]")
EP_BTN = re.compile(r"^\D{0,12}?(\d{1,4})\D{0,12}$")
NEXT_MARKS = ("▶", "➡", "⏩", "»", "›", "→", ">>", "keyingi", "next", "oldinga", "davomi")
WATCH_WORDS = ("tomosha", "yuklab olish", "watch", "download", "смотреть", "скачать")
CHECK_WORDS = ("tekshir", "obuna bo'ldim", "a'zo bo'ldim", "✅", "check", "davom", "проверить")

OnEpisode = Callable[[int, Message], Awaitable[None]]


def episode_buttons(m: Message) -> list[tuple[int, Btn]]:
    out = []
    for b in cb_buttons(m):
        text = b.text.strip()
        if any(k in text.lower() for k in NEXT_MARKS) or "◀" in text or "⬅" in text:
            continue
        if mt := EP_BTN.match(text):
            out.append((int(mt.group(1)), b))
    # Bitta raqamli tugma — bu sahifa raqami yoki tasodif, qismlar ro'yxati emas
    return out if len(out) >= 2 or (len(out) == 1 and len(cb_buttons(m)) <= 3) else []


def next_button(m: Message) -> Btn | None:
    for b in cb_buttons(m):
        if any(k in b.text.lower() for k in NEXT_MARKS):
            return b
    return None


def current_episode(m: Message) -> int | None:
    """Menyu xabarining o'zidagi video qaysi qism: bezatilgan tugma ("[📀] 1") yoki captiondagi "1-qism"."""
    eps = episode_buttons(m)
    marked = [n for n, b in eps if not b.text.strip().isdigit()]
    if len(marked) == 1 and len(eps) > 1:
        return marked[0]
    if mt := re.search(r"(\d+)\s*-?\s*qism", m.message or "", re.I):
        return int(mt.group(1))
    return None


def watch_button(m: Message, recipe: dict | None = None) -> Btn | None:
    """Anime kartochkasidagi "Tomosha qilish" / "Yuklab olish" (yoki retseptda o'rganilgan) tugma."""
    recipe = recipe or {}
    words = [*WATCH_WORDS, *recipe.get("press", [])]
    return next(
        (b for b in buttons(m) if matches(b.text, words) and not matches(b.text, recipe.get("never", []))),
        None,
    )


class Teach(NeedHuman):
    """Bot ekranini tushunmadim — egasi qaysi tugmani bosishni ko'rsatishi kerak."""

    def __init__(self, bot: str, msg: Message, role: str, reason: str) -> None:
        super().__init__(reason)
        self.bot = bot
        self.msg = msg
        self.role = role  # o'rganilgan tugma retseptda qaysi ro'lga yoziladi: "press" | "check"


def episode_count(text: str) -> int | None:
    """Kartochka/postdagi "🎥 Qismi: 9" (yoki "Qismlar soni: 9", "Epizod: 9")."""
    mt = re.search(r"(?i)(?:qism\w*|epizod\w*|seriya\w*)(?:\s+soni)?\s*[:\-–]\s*(\d+)", text or "")
    return int(mt.group(1)) if mt else None


def caption_number(text: str) -> int | None:
    nums = re.findall(r"\d+", text or "")
    return int(nums[0]) if len(nums) == 1 else None


def clean_title(text: str) -> str | None:
    for line in (text or "").replace("\\'", "'").splitlines():
        line = re.sub(r"^[^\w]+", "", line).strip()
        line = re.sub(r"(?i)^(anime|nomi|name|название)\s*[:\-–]\s*", "", line).strip(" *_`")
        if len(line) >= 2:
            return line[:120]
    return None


def doc_id(m: Message) -> int | None:
    return m.document.id if m.document else None


class Source:
    def __init__(self, client: TelegramClient, watcher: Watcher, recipes: Recipes, on_join: Callable[[object], None]) -> None:
        self.client = client
        self.watcher = watcher
        self.recipes = recipes
        self.on_join = on_join  # majburan qo'shilgan homiy chat — keyin chiqib ketish uchun yozib qo'yiladi
        self.count: int | None = None  # oxirgi `title()` da aniqlangan qismlar soni

    async def title(self, bot_name: str, param: str, post_text: str) -> tuple[str, int | None]:
        """Faqat anime nomi va manbadagi qismlar soni: homiylardan o'tib, kartochka yoki qismlar menyusigacha."""
        self.count = episode_count(post_text)
        title = await self.grab(bot_name, param, post_text, None)
        return title, self.count

    async def grab(self, bot_name: str, param: str, post_text: str, on_episode: OnEpisode | None, min_n: int = 1) -> str:
        """Botdan `min_n` va undan keyingi qismlarni oladi; har bir qism `on_episode` ga beriladi.
        `on_episode=None` — qism olinmaydi, faqat nom. Anime nomini qaytaradi."""
        bot = await self.client.get_entity(bot_name)
        if not (isinstance(bot, types.User) and bot.bot):
            raise NeedHuman(f"@{bot_name} bot emas")
        await mute(self.client, bot)  # manba bot ko'p video yuboradi
        recipe = self.recipes.get(bot_name)
        with self.watcher.watch(bot.id, bot_name) as inbox:
            screen = await self._start(bot, param, inbox)
            card_title = None
            for step in range(6):
                log.info("@%s: %d-qadam, %d ta xabar", bot_name, step + 1, len(screen))
                if menu := self._latest_menu(inbox):
                    if self.count is None:
                        self.count = max(n for n, _ in episode_buttons(menu))
                    title = card_title or clean_title(menu.message) or clean_title(post_text) or bot_name
                    if on_episode:
                        await self._collect_menu(inbox, menu, on_episode, min_n)
                    return title
                card = next((m for m in reversed(screen) if watch_button(m, recipe)), None)
                if card:
                    card_title = clean_title(card.message) or card_title
                    self.count = episode_count(card.message) or self.count
                    if on_episode is None and card_title:
                        return card_title
                    btn = watch_button(card, recipe)
                    log.info("@%s: «%s» — %s", bot_name, card_title, btn.text)
                    screen = await self._press(bot, bot_name, inbox, card, btn)
                    continue
                videos = [m for m in screen if is_video(m)]
                if videos:
                    if on_episode:
                        await self._take_videos(videos, on_episode, min_n)
                    return clean_title(videos[0].message) or clean_title(post_text) or bot_name
                sponsor = next((m for m in reversed(screen) if self._sponsor_links(m, bot_name)), None)
                if sponsor:
                    screen = await self._pass_sponsors(bot, bot_name, param, inbox, sponsor, recipe)
                    continue
                if step == 0:
                    screen = await self._start(bot, param, inbox)
                    continue
                self._teach(bot_name, inbox, "press", f"@{bot_name} javobini tushunmadim (qism tugmalari ham, video ham yo'q)")
            self._teach(bot_name, inbox, "press", f"@{bot_name} qismlar ro'yxatiga yetib bora olmadim (6 urinish)")
        raise NeedHuman(f"@{bot_name}: tushunmadim")

    def _teach(self, bot_name: str, inbox: Inbox, role: str, reason: str) -> None:
        """Botning tugmali oxirgi xabari bo'yicha egasidan o'rganish so'raladi (tugmasiz bo'lsa — oddiy xato)."""
        screens = [m for m in inbox.latest.values() if buttons(m)]
        if not screens:
            raise NeedHuman(reason)
        msg = max(screens, key=lambda m: m.id)
        if self._sponsor_links(msg, bot_name):
            role = "check"
        raise Teach(bot_name, msg, role, reason)

    async def _press(self, bot, bot_name: str, inbox: Inbox, msg: Message, btn: Btn) -> list[Message]:
        """Tugmani bosish: callback — bosamiz; botning o'ziga ?start= havola — /start yuboramiz."""
        await pause("click")
        inbox.drain()
        if btn.data is not None:
            answer = await click(self.client, msg, btn)
            if answer:
                log.info("@%s: %s", bot_name, answer)
        elif (link := parse_tme(btn.url or "")) and link.start:
            await send(self.client, bot, f"/start {link.start}", bot.username)
        else:
            raise NeedHuman(f"@{bot_name}: «{btn.text}» tugmasini bosib bo'lmaydi ({btn.url})")
        return await inbox.settle(quiet=3, timeout=30)

    async def _start(self, bot, param: str, inbox: Inbox) -> list[Message]:
        inbox.drain()
        await send(self.client, bot, f"/start {param}", bot.username)
        return await inbox.settle(quiet=3, timeout=30)

    # ── homiylar ──

    @staticmethod
    def _sponsor_links(m: Message, bot_name: str) -> list[str]:
        """Xabardagi homiy havolalari (botning o'ziga olib boruvchi havoladan tashqari)."""
        out = []
        for b in url_buttons(m):
            link = parse_tme(b.url)
            if link and link.kind == "name" and link.value.lower() == bot_name.lower():
                continue
            out.append(b.url)
        return out

    async def _pass_sponsors(self, bot, bot_name: str, param: str, inbox: Inbox, msg: Message, recipe: dict) -> list[Message]:
        urls = self._sponsor_links(msg, bot_name)
        log.info("@%s: %d ta homiy", bot_name, len(urls))
        joined = False
        for i, url in enumerate(urls, 1):
            link = parse_tme(url)
            if link is None:
                log.info("  %d/%d %s — t.me emas, o'tkazildi", i, len(urls), url)
                continue
            if joined:
                await asyncio.sleep(JOIN_DELAY)
            status, chat = await join(self.client, link)
            log.info("  %d/%d %s — %s", i, len(urls), url, status)
            if chat is not None:
                self.on_join(chat)
            joined = True

        # "Tekshirish" tugmasi: callback bo'lsa bosamiz, botning o'ziga havola bo'lsa — /start qayta
        checks = [b for b in cb_buttons(msg) if not matches(b.text, recipe["never"])]
        words = [*CHECK_WORDS, *recipe["check"]]
        btn = next((b for b in checks if matches(b.text, words)), checks[-1] if checks else None)
        if btn is None:
            return await self._start(bot, param, inbox)
        inbox.drain()
        answer = await click(self.client, msg, btn)
        log.info("@%s tekshiruv javobi: %s", bot_name, answer or "(yo'q)")
        if answer:
            await asyncio.sleep(JOIN_DELAY)
        screen = await inbox.settle(quiet=3, timeout=20)
        # Tekshiruvdan keyin bot animeni o'zi bermasa — postdagi /start ni qaytaramiz
        if not any(is_video(m) or episode_buttons(m) or watch_button(m, recipe) for m in screen):
            screen = await self._start(bot, param, inbox)
        return screen

    # ── qismlar ──

    @staticmethod
    def _latest_menu(inbox: Inbox) -> Message | None:
        menus = [m for m in inbox.latest.values() if episode_buttons(m)]
        return max(menus, key=lambda m: m.id) if menus else None

    async def _take_videos(self, videos: list[Message], on_episode: OnEpisode, min_n: int) -> None:
        """Bot qismlarni to'g'ridan-to'g'ri video qilib yuborgan."""
        numbered = [(caption_number(m.message), m) for m in videos]
        if all(n is not None for n, _ in numbered) and len({n for n, _ in numbered}) == len(numbered):
            pairs = numbered
        else:
            pairs = [(i + 1, m) for i, m in enumerate(videos)]
        for n, m in pairs:
            if n >= min_n:
                await on_episode(n, m)

    async def _collect_menu(self, inbox: Inbox, menu: Message, on_episode: OnEpisode, min_n: int) -> None:
        got: set[int] = set()
        failed: list[int] = []
        seen_docs: set[int] = {d for m in inbox.latest.values() if is_video(m) and (d := doc_id(m))}
        pages: set[tuple[int, ...]] = set()
        # Menyu ko'pincha joriy qism videosining o'zi bo'ladi — uni bosmasdan olamiz
        if is_video(menu) and (cur := current_episode(menu)) is not None and cur >= min_n:
            seen_docs.add(doc_id(menu))
            got.add(cur)
            log.info("%d-qism (menyudagi joriy video)", cur)
            await on_episode(cur, menu)
        while True:
            page = tuple(n for n, _ in episode_buttons(menu))
            if page in pages:
                break
            pages.add(page)
            for n in page:
                if n in got or n < min_n:
                    continue
                # Bot ro'yxatni qayta yuborgan/tahrirlagan bo'lishi mumkin — eng oxirgisidan bosamiz
                menu = self._latest_menu(inbox) or menu
                btn = next((b for k, b in episode_buttons(menu) if k == n), None)
                if btn is None:
                    log.warning("%d-qism tugmasi yo'qolib qoldi", n)
                    continue
                await pause("click")
                inbox.drain()
                answer = await click(self.client, menu, btn)
                vid = await inbox.until(lambda m: is_video(m) and doc_id(m) not in seen_docs, timeout=45)
                if vid is None:
                    log.warning("%d-qism kelmadi (bot javobi: %r)", n, answer)
                    failed.append(n)
                    continue
                seen_docs.add(doc_id(vid))
                got.add(n)
                log.info("%d-qism olindi", n)
                await on_episode(n, vid)

            menu = self._latest_menu(inbox) or menu
            nxt = next_button(menu)
            if nxt is None:
                break
            await pause("click")
            inbox.drain()
            log.info("Keyingi sahifa: %s", nxt.text)
            await click(self.client, menu, nxt)
            if not await inbox.settle(quiet=2, timeout=15):
                log.info("Keyingi sahifaga javob yo'q — qismlar shu")
                break
            menu = self._latest_menu(inbox) or menu
        if failed and not got:
            raise NeedHuman(f"Qism tugmalarini bosdim, lekin video kelmadi: {failed}")
        log.info("%d-qismdan boshlab %d ta qism yig'ildi: %s", min_n, len(got), sorted(got))
