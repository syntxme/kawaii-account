# kawaii-account

Anime kanallaridan yangi qismlarni olib, Kawaii botga yuklovchi userbot (Telethon).

## Ishga tushirish

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # to'ldiring
.venv/bin/python -m kawaii_account   # birinchi marta telefon raqam va kod so'raydi
```

| Bayroq | Natija |
|---|---|
| (yo'q) | Kanal skani avtomatik, cheksiz (qayerga yetgani bazada saqlanadi) |
| `--scan N` | Bu safar ko'pi bilan N ta eski post |
| `--no-scan` | Faqat yangi postlarni kuzatish |

## Server

`178.104.65.194` da `/root/other-bots/kawaii-account`, pm2 nomi `kawaii-account`.
Cron har daqiqada `deploy/update.sh` ni chaqiradi: GitHub'ga push bo'lsa — kodni oladi va pm2 ni qayta ishga tushiradi
(log: `data/update.log`). `.env`, `*.session`, `data/` serverda qo'lda turadi, git'ga kirmaydi.

```bash
pm2 logs kawaii-account          # loglar
pm2 restart kawaii-account
```

## Qanday ishlaydi

1. `WATCH_CHANNELS` dagi postlar pastdan tepaga ko'riladi; `t.me/<bot>?start=...` tugmasi bo'lsa — vazifa.
   Bir animening postlari bot + `start` parametri bo'yicha taniladi, eski takroriy postlar o'tkaziladi.
2. Manba botga `/start <param>` → homiylar (faqat `t.me`) — qo'shiladi va mute qilinadi → kartochkadan anime nomi.
3. Kawaii ID: avval ma'lum bo'lsa (manba yoki nom, imlo xatolariga chidamli) — o'zi; bo'lmasa `OWNER` ga
   post havolasi bilan **bir marta** so'rov yuboradi va javobni kutmasdan skanni davom ettiradi.
4. Kawaii botda `#id` → "📺 N / M - epizoddan boshlab yuboring" dan N olinadi.
5. Manbadan faqat N va undan keyingi qismlar `STORAGE_CHAT` ga (caption — qism raqami) nusxalanadi.
6. Kawaii'ga yuboriladi → `♻️ Epizodlarni bazaga qo'shish` → `⬅️ Chiqish` → egasiga hisobot.

Skan to'xtovsiz: aylana tugagach 10 daqiqadan keyin kanaldagi yangi postlar yana tekshiriladi.
Homiylik uchun majburan qo'shilgan kanallardan 24 soatdan keyin chiqiladi.

## O'rgatish

Akkaunt manba botda tiqilib qolsa (tanimagan tugma), egasiga botning oxirgi xabari va raqamlangan tugmalarini yuboradi.
Javobga tugma raqami yuboriladi — tugma matni (emoji/raqamsiz) `data/recipes/<bot>.json` ga yoziladi va vazifa davom etadi.
Keyingi animelarda o'sha bot uchun avtomatik ishlatiladi. Retseptni qo'lda ham tuzatsa bo'ladi
(`press` — bosiladigan, `check` — obuna tekshiruvi, `never` — hech qachon bosilmaydi).
Harakatlar orasida tasodifiy kutish bor — `.env` dagi `PAUSE_*` bilan sozlanadi.

## Egasi bilan muloqot (@OWNER → akkaunt)

| Xabar | Natija |
|---|---|
| ID so'roviga javob: `123` / `#123` | Shu Kawaii ID ga yuklaydi (manba va nom eslab qolinadi) |
| ID so'roviga javob: `0` | Anime o'tkazib yuboriladi |
| Xato xabariga javob: `qayta` / ID / `skip` | Qayta urinish / boshqa ID bilan / o'tkazish |
| Post havolasi `t.me/kanal/123` | Shu postni qo'lda ishlaydi |
| O'rgatish so'roviga javob: tugma raqami / `0` | O'rganib davom etadi / o'tkazish |
| `/jobs` | Ochiq vazifalar |
| `/learn @bot` | Bot retsepti |
| `/forget @bot so'z` | Retseptdan o'chirish |

Holat `data/state.db` (SQLite) da saqlanadi.
