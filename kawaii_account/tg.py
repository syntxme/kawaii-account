"""Telegram yordamchilari: bot javoblarini kutish, tugmalar, t.me havolalar, kanalga qo'shilish."""

import asyncio
import contextlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from telethon import TelegramClient, errors, events
from telethon.tl import functions, types
from telethon.tl.custom import Message

log = logging.getLogger(__name__)


class NeedHuman(Exception):
    """Avtomatik davom etib bo'lmaydi — egasiga xabar berish kerak."""


# ─────────────────────────── Javoblarni kutish ───────────────────────────


class Inbox:
    """Bitta chatdan keladigan yangi va tahrirlangan xabarlar.

    Botlar "single message" uslubida ishlashi mumkin (xabarni tahrirlaydi), shuning uchun
    tahrirlar ham yangi xabar kabi keladi. `latest` — har bir xabarning eng oxirgi holati.
    """

    def __init__(self) -> None:
        self.q: asyncio.Queue[Message] = asyncio.Queue()
        self.latest: dict[int, Message] = {}

    def _push(self, m: Message) -> None:
        self.latest[m.id] = m
        self.q.put_nowait(m)

    def forget(self, msg_id: int) -> None:
        self.latest.pop(msg_id, None)

    async def get(self, timeout: float) -> Message | None:
        try:
            return await asyncio.wait_for(self.q.get(), timeout)
        except asyncio.TimeoutError:
            return None

    async def until(self, pred, timeout: float = 30) -> Message | None:
        """Shartga mos birinchi xabar (yangi yoki tahrirlangan)."""
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while (left := end - loop.time()) > 0:
            m = await self.get(left)
            if m is None:
                return None
            if pred(m):
                return m
        return None

    async def settle(self, quiet: float = 3, timeout: float = 30) -> list[Message]:
        """Bot "jim" bo'lguncha kelgan xabarlar (har biri eng oxirgi holatida)."""
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        got: dict[int, Message] = {}
        while (left := end - loop.time()) > 0:
            m = await self.get(min(quiet, left))
            if m is None:
                if got:
                    break
                continue
            got[m.id] = m
        return sorted(got.values(), key=lambda m: m.id)

    def drain(self) -> None:
        while not self.q.empty():
            self.q.get_nowait()


class Watcher:
    def __init__(self, client: TelegramClient) -> None:
        self.inboxes: dict[int, list[Inbox]] = {}
        self.labels: dict[int, str] = {}
        client.add_event_handler(self._on, events.NewMessage(incoming=True))
        client.add_event_handler(self._on, events.MessageEdited(incoming=True))
        client.add_event_handler(self._on_deleted, events.MessageDeleted())

    async def _on(self, ev) -> None:
        boxes = self.inboxes.get(ev.chat_id, [])
        if boxes:
            edited = isinstance(ev, events.MessageEdited.Event)
            log.info("← @%s %s#%d: %s", self.labels.get(ev.chat_id, ev.chat_id), "✎" if edited else "", ev.message.id, brief(ev.message))
        for box in boxes:
            box._push(ev.message)

    async def _on_deleted(self, ev) -> None:
        # Shaxsiy chatlarda chat_id kelmaydi — barcha ochiq inboxlardan olib tashlaymiz
        for boxes in self.inboxes.values():
            for box in boxes:
                for i in ev.deleted_ids:
                    box.forget(i)

    @contextlib.contextmanager
    def watch(self, chat_id: int, label: str = ""):
        self.labels[chat_id] = label or str(chat_id)
        box = Inbox()
        self.inboxes.setdefault(chat_id, []).append(box)
        try:
            yield box
        finally:
            self.inboxes[chat_id].remove(box)


# ─────────────────────────── Xabar turlari ───────────────────────────


def is_video(m: Message) -> bool:
    if m.video:
        return True
    doc = m.document
    return bool(doc and (doc.mime_type or "").startswith("video"))


@dataclass
class Btn:
    """Inline tugma (Telethon layer'iga bog'liq bo'lmagan ko'rinish)."""

    text: str
    url: str | None = None
    data: bytes | None = None


def _btn(b) -> Btn:
    # Yangi layer: KeyboardInlineButton(text, type=InlineButtonType*); eski: KeyboardButtonUrl/Callback
    t = getattr(b, "type", b)
    return Btn(b.text, url=getattr(t, "url", None), data=getattr(t, "data", None))


def brief(m: Message) -> str:
    """Log uchun xabarning qisqa ko'rinishi: turi, matni, tugmalari."""
    kind = "[video] " if is_video(m) else "[rasm] " if m.photo else ""
    text = " / ".join(line.strip() for line in (m.message or "").splitlines() if line.strip())
    if len(text) > 120:
        text = text[:119] + "…"
    btns = " | ".join(b.text for b in buttons(m))
    if len(btns) > 200:
        btns = btns[:199] + "…"
    return kind + text + (f"  [{btns}]" if btns else "")


async def send(client: TelegramClient, peer, text: str, label: str) -> Message:
    log.info("→ @%s: %s", label, text)
    return await client.send_message(peer, text)


def buttons(m: Message) -> list[Btn]:
    """Inline tugmalar ro'yxati (tekis)."""
    rm = m.reply_markup
    if not isinstance(rm, types.ReplyInlineMarkup):
        return []
    return [_btn(b) for row in rm.rows for b in row.buttons]


def url_buttons(m: Message) -> list[Btn]:
    return [b for b in buttons(m) if b.url]


def cb_buttons(m: Message) -> list[Btn]:
    return [b for b in buttons(m) if b.data is not None]


async def click(client: TelegramClient, m: Message, btn: Btn) -> str:
    """Callback tugmani bosish. Bot javobidagi (alert/toast) matnni qaytaradi."""
    log.info("⇢ «%s» bosildi (#%d)", btn.text, m.id)
    try:
        r = await client(functions.messages.GetBotCallbackAnswerRequest(peer=m.peer_id, msg_id=m.id, data=btn.data))
        if r.message:
            log.info("  ↳ bot javobi: %s", r.message)
        return r.message or ""
    except errors.BotResponseTimeoutError:
        return ""  # bot answerCallbackQuery qilmadi — bu normal holat
    except errors.MessageIdInvalidError:
        log.warning("Tugma bosilmadi: xabar o'chirilgan (%s)", btn.text)
        return ""


# ─────────────────────────── t.me havolalar ───────────────────────────

TME = re.compile(r"^(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/(.+)$", re.I)


@dataclass
class Link:
    kind: str  # "invite" | "name"
    value: str  # invite hash yoki username
    start: str | None = None  # ?start= parametri


def parse_tme(url: str) -> Link | None:
    m = TME.match(url.strip())
    if not m:
        return None
    path = m.group(1)
    path, _, query = path.partition("?")
    path = path.strip("/")
    if path.startswith("+"):
        return Link("invite", path[1:])
    if path.startswith("joinchat/"):
        return Link("invite", path.split("/", 1)[1])
    if path.startswith("s/"):
        path = path[2:]
    name = path.split("/")[0]
    if not re.fullmatch(r"[A-Za-z0-9_]{4,}", name):
        return None
    start = None
    for part in query.split("&"):
        k, _, v = part.partition("=")
        if k in ("start", "startgroup") and v:
            start = v
    return Link("name", name, start)


JOIN_DELAY = 5  # homiylarga qo'shilish orasidagi kutish (s)


Joined = tuple[str, types.TypeChat | None]


async def join(client: TelegramClient, link: Link) -> Joined:
    """Homiy kanal/guruhga qo'shilish (yoki homiy botni ishga tushirish).
    (natija matni, yangi qo'shilgan chat — keyin chiqib ketish uchun; allaqachon a'zo bo'lsa None)."""
    while True:
        try:
            return await _join(client, link)
        except errors.FloodWaitError as e:
            log.warning("FLOOD_WAIT %d s (%s) — kutyapman", e.seconds, link.value)
            await asyncio.sleep(e.seconds + 2)
        except errors.RPCError as e:
            return f"xato: {e}", None


async def leave(client: TelegramClient, chat_id: int, access_hash: int | None) -> None:
    """Kanal/guruhdan chiqish."""
    if access_hash is not None:
        await client(functions.channels.LeaveChannelRequest(types.InputChannel(chat_id, access_hash)))
    else:
        await client(functions.messages.DeleteChatUserRequest(chat_id, types.InputUserSelf()))


async def mute(client: TelegramClient, peer) -> None:
    """Chatni butunlay ovozsiz qilish (akkaunt egasining Telegramiga ham ulangan — bildirishnoma chalg'itmasin)."""
    try:
        await client(functions.account.UpdateNotifySettingsRequest(
            peer=types.InputNotifyPeer(await client.get_input_entity(peer)),
            settings=types.InputPeerNotifySettings(mute_until=datetime(2038, 1, 1, tzinfo=timezone.utc), show_previews=False),
        ))
    except errors.FloodWaitError:
        raise
    except (errors.RPCError, ValueError) as e:
        log.warning("Mute bo'lmadi: %s", e)


async def _join(client: TelegramClient, link: Link) -> Joined:
    if link.kind == "invite":
        check = await client(functions.messages.CheckChatInviteRequest(link.value))
        if isinstance(check, types.ChatInviteAlready):
            # Telegram kanalni "taniydi", lekin a'zo bo'lmasligimiz mumkin (left=True)
            if not getattr(check.chat, "left", False):
                await mute(client, check.chat)
                return "allaqachon a'zo, mute", None
            if isinstance(check.chat, types.Channel):
                try:
                    await client(functions.channels.JoinChannelRequest(check.chat))
                    await mute(client, check.chat)
                    return "qo'shildim, mute", check.chat
                except errors.FloodWaitError:
                    raise
                except errors.RPCError as e:
                    log.info("JoinChannel bo'lmadi (%s) — taklif havolasi orqali urinyapman", e)
        try:
            upd = await client(functions.messages.ImportChatInviteRequest(link.value))
        except errors.UserAlreadyParticipantError:
            return "allaqachon a'zo", None
        except errors.InviteRequestSentError:
            return "a'zolik so'rovi yuborildi", None
        chats = getattr(upd, "chats", [])
        for chat in chats:
            await mute(client, chat)
        return "qo'shildim, mute", chats[0] if chats else None
    ent = await client.get_entity(link.value)
    if isinstance(ent, types.User):
        if not ent.bot:
            return "oddiy foydalanuvchi — o'tkazildi", None
        await send(client, ent, f"/start {link.start}" if link.start else "/start", link.value)
        await mute(client, ent)
        return "bot — /start yuborildi, mute", None
    was_member = isinstance(ent, types.Channel) and not ent.left
    # A'zo bo'lsa ham JoinChannelRequest zarar qilmaydi; `left` bayrog'iga to'liq ishonmaymiz
    await client(functions.channels.JoinChannelRequest(ent))
    await mute(client, ent)
    return ("allaqachon a'zo, mute", None) if was_member else ("qo'shildim, mute", ent)
