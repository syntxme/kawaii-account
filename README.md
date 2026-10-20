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

Serverda (pm2):

```bash
pm2 start .venv/bin/python --name kawaii-account -- -m kawaii_account
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

Homiylik uchun majburan qo'shilgan kanallardan 24 soatdan keyin chiqiladi.
Harakatlar orasida tasodifiy kutish bor — `.env` dagi `PAUSE_*` bilan sozlanadi.

## Egasi bilan muloqot (@OWNER → akkaunt)

| Xabar | Natija |
|---|---|
| ID so'roviga javob: `123` / `#123` | Shu Kawaii ID ga yuklaydi (manba va nom eslab qolinadi) |
| ID so'roviga javob: `0` | Anime o'tkazib yuboriladi |
| Xato xabariga javob: `qayta` / ID / `skip` | Qayta urinish / boshqa ID bilan / o'tkazish |
| Post havolasi `t.me/kanal/123` | Shu postni qo'lda ishlaydi |
| `/jobs` | Ochiq vazifalar |

Holat `data/state.db` (SQLite) da saqlanadi.
