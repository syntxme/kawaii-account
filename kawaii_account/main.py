"""Kirish nuqtasi: kanallarni kuzatish, vazifalarni bajarish, egasi bilan muloqot.

Vazifa bosqichlari (jobs.status):
  probing    — manba botdan anime nomini aniqlash (homiylar → kartochka)
  need_id    — egasidan Kawaii ID kutilmoqda (nom avval aniqlangan bo'lsa so'ralmaydi)
  checking   — Kawaii'da qaysi epizoddan boshlab kerakligini aniqlash
  collecting — manbadan faqat kerakli qismlarni olish (STORAGE_CHAT ga)
  uploading  — Kawaii'ga yuborish va bazaga saqlash
  done | skipped | failed
"""

import argparse
import asyncio
import logging
import os
import re
import tempfile
import time
from html import escape

from telethon import TelegramClient, errors, events, utils
from telethon.tl.custom import Message

from . import config
from .db import Db
from .kawaii import Kawaii
from .match import AUTO, norm, rank
from .pace import pause
from .source import Source
from .tg import JOIN_DELAY, NeedHuman, Watcher, leave, parse_tme, url_buttons

log = logging.getLogger("kawaii_account")

POST_LINK = re.compile(r"(?:https?://)?t\.me/(?:c/(\d+)|([A-Za-z0-9_]{4,}))/(\d+)")
SKIP_WORDS = ("skip", "yo'q", "otkaz", "o'tkaz", "kerakmas", "kerak emas")
RETRY_WORDS = ("qayta", "retry", "yana")
FINAL = ("done", "skipped", "failed")
ACTIVE = ("probing", "checking", "collecting", "uploading")
LEAVE_AFTER = 24 * 3600  # homiy kanallardan chiqish (s)


def start_link(m: Message) -> tuple[str, str] | None:
    """Postdagi `t.me/<bot>?start=...` tugmasi → (bot, param). "Tomosha qilish" tugmasi birinchi."""
    found = []
    for b in url_buttons(m):
        link = parse_tme(b.url)
        if link and link.kind == "name" and link.start:
            found.append((0 if "tomosha" in b.text.lower() else 1, link.value, link.start))
    if not found:
        return None
    _, bot, param = min(found, key=lambda f: f[0])
    return bot, param


class App:
    def __init__(self, client: TelegramClient, cfg: config.Config) -> None:
        self.client = client
        self.cfg = cfg
        self.db = Db(cfg.db_path)
        self.watcher = Watcher(client)
        self.source = Source(client, self.watcher, self.on_join)
        self.kawaii = Kawaii(client, self.watcher, cfg.kawaii_bot, cfg.storage_chat)
        # Bir vaqtda bitta vazifa: botlar bilan suhbatlar aralashib ketmasin
        self.lock = asyncio.Lock()
        self.tasks: set[asyncio.Task] = set()

    def spawn(self, job_id: int) -> None:
        t = asyncio.create_task(self.run_job(job_id))
        self.tasks.add(t)
        t.add_done_callback(self.tasks.discard)

    # ─────────────────────────── Egasi ───────────────────────────

    async def tell_owner(self, text: str) -> Message | None:
        log.info("→ @%s: %s", self.cfg.owner, re.sub(r"<[^>]+>", "", text).replace("\n", " / "))
        try:
            return await self.client.send_message(self.cfg.owner, text, link_preview=False)
        except errors.RPCError as e:
            log.error("Egasiga yozib bo'lmadi: %s\n%s", e, text)
            return None

    async def on_owner(self, ev: events.NewMessage.Event) -> None:
        m: Message = ev.message
        text = (m.message or "").strip()
        log.info("← @%s: %s", self.cfg.owner, text)
        # ID kutilayotgan bo'lsa — faqat raqam qabul qilinadi
        if waiting := self.db.jobs_with_status("need_id"):
            # Reply bo'lsa — o'sha so'rovga, aks holda eng oxirgi yuborilgan so'rovga
            latest = max(waiting, key=lambda j: j["owner_msg"] or 0)
            job = next((j for j in waiting if m.is_reply and j["owner_msg"] == m.reply_to_msg_id), latest)
            await self.on_id(m, job, text)
            return
        if m.is_reply:
            job = self.db.job_by_owner_msg(m.reply_to_msg_id)
            if job:
                await self.on_owner_reply(m, job, text)
                return
        if mt := POST_LINK.search(text):
            await self.on_post_link(m, mt)
            return
        if text in ("/jobs", "/status"):
            await m.reply(self.status_text())

    async def on_id(self, m: Message, job, text: str) -> None:
        mt = re.fullmatch(r"#?\s*(\d{1,9})", text)
        if not mt:
            await m.reply(
                f"🔢 Faqat ID kutyapman: <b>{escape(job['title'] or '?')}</b> ning Kawaii botdagi ID sini raqam bilan yuboring\n"
                "<i>Kerak bo'lmasa — 0</i>"
            )
            return
        kid = int(mt.group(1))
        if kid == 0:
            self.db.update_job(job["id"], status="skipped")
            await m.reply(f"👌 O'tkazib yubordim: <b>{escape(job['title'])}</b>")
            return
        self.remember(job, kid)
        self.db.update_job(job["id"], kawaii_id=kid, status="checking")
        await m.reply(f"✅ <b>{escape(job['title'])}</b> → <code>#{kid}</code>")
        self.spawn(job["id"])

    async def on_owner_reply(self, m: Message, job, text: str) -> None:
        low = text.lower()
        if any(w in low for w in SKIP_WORDS):
            self.db.update_job(job["id"], status="skipped")
            await m.reply("👌 O'tkazib yubordim")
        elif any(w in low for w in RETRY_WORDS):
            self.db.update_job(job["id"], status="checking" if job["kawaii_id"] else "probing")
            await m.reply("🔁 Qayta urinyapman")
            self.spawn(job["id"])
        elif mt := re.fullmatch(r"#?\s*(\d{1,9})", text):
            kid = int(mt.group(1))
            if job["title"]:
                self.remember(job, kid)
            self.db.update_job(job["id"], kawaii_id=kid, status="checking")
            await m.reply(f"✅ <code>#{kid}</code> bilan qayta urinyapman")
            self.spawn(job["id"])
        else:
            await m.reply("ID yuboring (masalan <code>123</code>), yoki <code>skip</code> / <code>qayta</code>")

    async def on_post_link(self, m: Message, mt: re.Match) -> None:
        """Egasi post havolasini yuborsa — o'sha postni qo'lda ishlash (test uchun qulay)."""
        chat = int(f"-100{mt.group(1)}") if mt.group(1) else mt.group(2)
        try:
            post = await self.client.get_messages(chat, ids=int(mt.group(3)))
        except (errors.RPCError, ValueError) as e:
            await m.reply(f"Postni ololmadim: {escape(str(e))}")
            return
        if post is None or not start_link(post):
            await m.reply("Bu postda <code>t.me/bot?start=</code> tugmasi yo'q")
            return
        job_id = self.new_job(post)
        await m.reply(f"▶️ Vazifa #{job_id} boshlandi")

    def status_text(self) -> str:
        rows = self.db.jobs_with_status(*ACTIVE, "need_id", "failed")[-15:]
        if not rows:
            return "Ochiq vazifalar yo'q"
        return "\n".join(escape(f"#{r['id']} {r['status']} — {r['title'] or r['bot']} {r['note'] or ''}") for r in rows)

    # ─────────────────────────── Kanallar ───────────────────────────

    async def on_post(self, ev: events.NewMessage.Event) -> None:
        m: Message = ev.message
        if self.db.post_seen(m.chat_id, m.id):
            return
        self.db.mark_post(m.chat_id, m.id)
        if start_link(m) and self.wanted(m, newer=True):
            self.new_job(m)

    def wanted(self, m: Message, newer: bool) -> bool:
        """Post ishlanadimi? Bir animening postlari tugmadagi bot + ?start= bo'yicha taniladi.

        newer=True  — yangi post (kanalga hozir kelgan): anime avval qo'shilgan bo'lsa yangi qismini tekshiramiz.
        newer=False — eski post (skan tepaga ketyapti): shu anime pastroqda (yangiroq postda) ishlangan — o'tkazamiz."""
        bot, param = start_link(m)
        prev = self.db.job_for_source(bot, param)
        if prev is None:
            return True
        name = f"{m.chat_id}/{m.id}"
        if not newer:
            log.info("Post %s: @%s start=%s — shu anime #%d vazifada bor (%s), o'tkazildi", name, bot, param, prev["id"], prev["status"])
            return False
        if prev["status"] in (*ACTIVE, "need_id", "skipped"):
            log.info("Post %s: @%s start=%s — #%d vazifa %s, o'tkazildi", name, bot, param, prev["id"], prev["status"])
            return False
        return True

    def new_job(self, post: Message) -> int:
        bot, param = start_link(post)
        job_id = self.db.new_job(post.chat_id, post.id, bot, param)
        log.info("Vazifa #%d: @%s start=%s", job_id, bot, param)
        self.spawn(job_id)
        return job_id

    async def scan(self, channels, limit: int | None) -> None:
        for ch in channels:
            try:
                await self.scan_channel(ch, limit)
            except Exception:
                log.exception("Skan yiqildi: %s", getattr(ch, "username", None) or ch.id)

    async def scan_channel(self, ch, limit: int | None) -> None:
        """Kanal postlarini pastdan tepaga (yangidan eskiga) bittalab ishlash. Qayerga yetgani bazada saqlanadi:
        qayta ishga tushganda avval oraliqda chiqqan yangi postlar, keyin to'xtagan joydan tepaga davom etadi.
        ID so'ralgan anime javobni kutmaydi — skan davom etadi."""
        name = getattr(ch, "username", None) or ch.id
        cid = utils.get_peer_id(ch)
        st = self.db.scan_state(cid)
        done = 0

        if st:
            # 1) Oxirgi skandan beri chiqqan postlar (dastur o'chiq paytida)
            newest = st["top_id"]
            async for m in self.client.iter_messages(ch, min_id=st["top_id"], wait_time=3):
                newest = max(newest, m.id)
                await self.scan_post(m, newer=True)
            self.db.save_scan(cid, newest, st["bottom_id"], bool(st["finished"]))
            if st["finished"]:
                log.info("Skan: %s — kanal boshigacha avval ko'rilgan", name)
                return
            st = self.db.scan_state(cid)
            log.info("Skan: %s — %d-postdan tepaga davom etyapman", name, st["bottom_id"])
        else:
            log.info("Skan: %s — eng oxirgi postdan boshlayapman", name)

        # 2) Tepaga (eskiga) qarab
        top = st["top_id"] if st else 0
        bottom = st["bottom_id"] if st else 0
        async for m in self.client.iter_messages(ch, max_id=bottom, limit=limit, wait_time=3):
            top = max(top, m.id)
            await self.scan_post(m, newer=False)
            bottom = m.id
            self.db.save_scan(cid, top, bottom)
            done += 1
        finished = limit is None or done < limit
        if top:
            self.db.save_scan(cid, top, bottom, finished)
        log.info("Skan: %s — %s (%d ta post ko'rildi)", name, "kanal boshigacha yetdim" if finished else f"{bottom}-postda to'xtadim", done)

    async def scan_post(self, m: Message, newer: bool) -> None:
        if not start_link(m):
            return
        self.db.mark_post(m.chat_id, m.id)
        if job := self.db.job_for_post(m.chat_id, m.id):
            await self.wait_idle(job["id"])  # oldingi ishga tushirishdan qolgan — resume() davom ettiradi
            return
        if not self.wanted(m, newer):
            await pause("skip")
            return
        log.info("Skan: post %d", m.id)
        await self.wait_idle(self.new_job(m))
        await pause("post")

    async def wait_idle(self, job_id: int) -> None:
        """Vazifa ishlov bosqichidan chiqquncha (tugadi, yiqildi yoki egasidan ID kutyapti)."""
        while (job := self.db.job(job_id)) and job["status"] in ACTIVE:
            await asyncio.sleep(2)

    # ─────────────────────────── Homiy kanallardan chiqish ───────────────────────────

    def on_join(self, chat) -> None:
        self.db.add_joined(chat.id, getattr(chat, "access_hash", None), getattr(chat, "title", "") or "")

    async def janitor(self) -> None:
        """Har soatda: 24 soatdan oldin majburan qo'shilgan homiy kanallardan chiqish."""
        while True:
            rows = self.db.joined_before(time.time() - LEAVE_AFTER)
            if rows:
                async with self.lock:  # vazifa o'rtasida homiydan chiqib ketmaslik uchun
                    log.info("Homiy kanallardan chiqyapman: %d ta", len(rows))
                    for r in rows:
                        try:
                            await leave(self.client, r["chat_id"], r["access_hash"])
                            log.info("  chiqdim: %s (%d)", r["title"], r["chat_id"])
                        except errors.FloodWaitError as e:
                            log.warning("FLOOD_WAIT %d s — keyinroq davom etaman", e.seconds)
                            break
                        except errors.RPCError as e:
                            log.info("  %s (%d): %s — ro'yxatdan o'chirildi", r["title"], r["chat_id"], e)
                        self.db.remove_joined(r["chat_id"])
                        await asyncio.sleep(JOIN_DELAY)
            await asyncio.sleep(3600)

    # ─────────────────────────── Vazifa ───────────────────────────

    async def run_job(self, job_id: int) -> None:
        async with self.lock:
            try:
                while (job := self.db.job(job_id))["status"] in ACTIVE:
                    step = getattr(self, f"step_{job['status']}")
                    await step(job)
            except NeedHuman as e:
                await self.fail(job_id, str(e))
            except errors.FloodWaitError as e:
                await self.fail(job_id, f"FLOOD_WAIT {e.seconds} s")
            except Exception as e:
                log.exception("Vazifa #%d yiqildi", job_id)
                await self.fail(job_id, f"Xatolik: {type(e).__name__}: {e}")

    def remember(self, job, kid: int) -> None:
        """Nom va manba (bot + start parametri) → Kawaii ID: keyingi qismlarda so'ramaslik uchun."""
        self.db.remember(norm(job["title"]), job["title"], kid, job["bot"], job["param"])

    async def step_probing(self, job) -> None:
        # 1) Shu manba anime (bot + ?start=) avval aniqlangan — manba botga kirmasdan
        if kid := self.db.source_id(job["bot"], job["param"]):
            title = job["title"] or next((t for t, k in self.db.known_titles() if k == kid), None) or f"#{kid}"
            log.info("Vazifa #%d: @%s start=%s avvaldan ma'lum → #%d", job["id"], job["bot"], job["param"], kid)
            self.db.update_job(job["id"], title=title, kawaii_id=kid, status="checking")
            return

        title = job["title"]
        if not title:
            post = await self.client.get_messages(job["chat_id"], ids=job["msg_id"])
            title = await self.source.title(job["bot"], job["param"], post.message if post else "")
            self.db.update_job(job["id"], title=title)
        log.info("Vazifa #%d: «%s»", job["id"], title)

        # 2) Aynan shu nom yoki 3) imlo xatosi bilan yozilgan o'sha nom (raqamlar mos bo'lishi shart)
        kid = self.db.known_id(norm(title))
        ranked = rank(title, self.db.known_titles())
        # Qisqa nomlarda (Naruto/Boruto) bitta harf ham boshqa anime — avtomatik faqat uzun nomlarda
        if kid is None and ranked and ranked[0][0] >= AUTO and len(norm(title)) >= 8:
            score, kid, name = ranked[0]
            log.info("Vazifa #%d: «%s» ≈ «%s» (%.0f%%) → #%d", job["id"], title, name, score * 100, kid)
        if kid:
            log.info("Vazifa #%d: Kawaii ID ma'lum — #%d", job["id"], kid)
            self.remember(self.db.job(job["id"]), kid)
            self.db.update_job(job["id"], kawaii_id=kid, status="checking")
            return
        await self.ask_id(self.db.job(job["id"]))

    async def post_link(self, job) -> str:
        try:
            ch = await self.client.get_entity(job["chat_id"])
        except (errors.RPCError, ValueError):
            ch = None
        if ch is not None and getattr(ch, "username", None):
            return f"https://t.me/{ch.username}/{job['msg_id']}"
        return f"https://t.me/c/{str(job['chat_id']).removeprefix('-100')}/{job['msg_id']}"

    async def ask_id(self, job) -> None:
        lines = [
            f"🆕 <b>{escape(job['title'])}</b>",
            f"📎 {await self.post_link(job)}",
            f"🤖 @{job['bot']}",
        ]
        if similar := rank(job["title"], self.db.known_titles())[:3]:
            lines.append("\n🔎 O'xshashlari (avval qo'shilgan):")
            lines += [f"• <code>{kid}</code> — {escape(name)} ({score:.0%})" for score, kid, name in similar]
        lines.append("\nKawaii botdagi <b>ID</b> sini shu xabarga <b>javob qilib</b> yuboring <i>(kerak bo'lmasa — 0)</i>")
        msg = await self.tell_owner("\n".join(lines))
        self.db.update_job(job["id"], status="need_id", owner_msg=msg.id if msg else None)

    async def step_checking(self, job) -> None:
        log.info("Vazifa #%d: Kawaii'da #%d qaysi epizoddan kerakligini tekshiryapman", job["id"], job["kawaii_id"])
        _, nxt = await self.kawaii.next_episode(job["kawaii_id"])
        self.db.update_job(job["id"], next_ep=nxt, status="collecting")

    async def step_collecting(self, job) -> None:
        job_id, nxt = job["id"], job["next_ep"]
        post = await self.client.get_messages(job["chat_id"], ids=job["msg_id"])

        async def on_episode(n: int, m: Message) -> None:
            saved = await self.store(n, m)
            self.db.add_episode(job_id, n, saved.id)
            log.info("Storage'ga saqlandi: %d-qism (#%d)", n, saved.id)

        log.info("Vazifa #%d: manbadan %d-qismdan boshlab yig'yapman", job_id, nxt)
        await self.source.grab(job["bot"], job["param"], post.message if post else "", on_episode, min_n=nxt)
        eps = self.db.episodes(job_id, min_n=nxt)
        if not eps or eps[0]["number"] != nxt:
            have = f"manbada {eps[0]['number']}-qismdan boshlanadi" if eps else "manbada ham yo'q"
            log.info("Vazifa #%d: %d-qism kerak, %s — yangi qism yo'q", job_id, nxt, have)
            self.db.update_job(job_id, status="done", note=f"{nxt}-qism yo'q")
            await self.tell_owner(f"💤 <b>{escape(job['title'])}</b> (<code>#{job['kawaii_id']}</code>): {nxt}-qism kerak, {have}")
            return
        self.db.update_job(job_id, status="uploading")

    async def store(self, n: int, m: Message) -> Message:
        """Qismni STORAGE_CHAT ga caption'siz, faqat raqam bilan nusxalash."""
        caption = str(n)
        try:
            return await self.client.send_file(self.cfg.storage_chat, m.media, caption=caption)
        except errors.FloodWaitError:
            raise
        except errors.RPCError as e:
            # Himoyalangan kontent (forward taqiqlangan) — yuklab olib, qayta yuklaymiz
            log.info("%d-qismni nusxalab bo'lmadi (%s) — yuklab olyapman", n, e)
            with tempfile.TemporaryDirectory() as tmp:
                path = await self.client.download_media(m, file=tmp + os.sep)
                return await self.client.send_file(
                    self.cfg.storage_chat, path, caption=caption,
                    attributes=m.document.attributes if m.document else None, supports_streaming=True,
                )

    async def step_uploading(self, job) -> None:
        log.info("Vazifa #%d: Kawaii #%d ga yuklayapman", job["id"], job["kawaii_id"])
        eps = [(e["number"], e["saved_msg"]) for e in self.db.episodes(job["id"], min_n=job["next_ep"])]
        done = await self.kawaii.upload(job["kawaii_id"], eps)
        self.db.mark_uploaded(job["id"], done)
        self.db.update_job(job["id"], status="done", note=None)
        log.info("Vazifa #%d tugadi: #%d ga %s", job["id"], job["kawaii_id"], done)
        if done:
            qism = f"{done[0]}-qism" if len(done) == 1 else f"{done[0]}–{done[-1]} qismlar ({len(done)} ta)"
            await self.tell_owner(f"✅ <b>{escape(job['title'])}</b> (<code>#{job['kawaii_id']}</code>): {qism} qo'shildi")
        else:
            await self.tell_owner(f"💤 <b>{escape(job['title'])}</b> (<code>#{job['kawaii_id']}</code>): yangi qism yo'q")

    async def fail(self, job_id: int, reason: str) -> None:
        job = self.db.job(job_id)
        log.warning("Vazifa #%d: %s", job_id, reason)
        msg = await self.tell_owner(
            f"⚠️ Vazifa #{job_id} (@{job['bot']}, {escape(job['title'] or '?')}):\n{escape(reason)}\n\n"
            "Tuzatgach shu xabarga <code>qayta</code> deb javob bering, yoki ID / <code>skip</code>"
        )
        self.db.update_job(job_id, status="failed", note=reason[:300], owner_msg=msg.id if msg else job["owner_msg"])

    # ─────────────────────────── Ishga tushirish ───────────────────────────

    async def resume(self) -> None:
        if waiting := self.db.jobs_with_status("need_id"):
            log.info("ID kutayotgan vazifalar: %s", ", ".join(f"#{j['id']}" for j in waiting))
        for job in self.db.jobs_with_status(*ACTIVE, "paused"):
            # Eski oqimdan qolgan holatlar: Kawaii'dagi kerakli epizod hali aniqlanmagan
            if job["status"] in ("collecting", "uploading", "paused") and job["next_ep"] is None:
                self.db.update_job(job["id"], status="checking" if job["kawaii_id"] else "probing")
            log.info("Qayta ishga tushganda davom ettiryapman: #%d (%s)", job["id"], self.db.job(job["id"])["status"])
            self.spawn(job["id"])


async def amain(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("telethon").setLevel(logging.WARNING)
    cfg = config.load()
    client = TelegramClient(cfg.session, cfg.api_id, cfg.api_hash, flood_sleep_threshold=60)
    client.parse_mode = "html"
    await client.start()
    me = await client.get_me()
    log.info("Akkaunt: %s (@%s)", me.first_name, me.username)

    app = App(client, cfg)
    owner = await client.get_entity(cfg.owner)
    client.add_event_handler(app.on_owner, events.NewMessage(chats=[owner.id], incoming=True))
    channels = [await client.get_entity(c) for c in cfg.watch_channels]
    if channels:
        client.add_event_handler(app.on_post, events.NewMessage(chats=channels))
        log.info("Kuzatilyapti: %s", ", ".join(getattr(c, "username", None) or str(c.id) for c in channels))
    else:
        log.warning("WATCH_CHANNELS bo'sh — faqat egasi yuborgan post havolalari ishlanadi")
    await app.resume()
    asyncio.create_task(app.janitor())
    if not args.no_scan:
        asyncio.create_task(app.scan(channels, args.scan))
    await client.run_until_disconnected()


def main() -> None:
    p = argparse.ArgumentParser(prog="kawaii_account")
    p.add_argument("--scan", type=int, default=None, metavar="N", help="bu safar ko'pi bilan N ta eski post ko'rish (standart: cheksiz)")
    p.add_argument("--no-scan", action="store_true", help="eski postlarni skan qilmaslik, faqat yangilarini kuzatish")
    asyncio.run(amain(p.parse_args()))


if __name__ == "__main__":
    main()
