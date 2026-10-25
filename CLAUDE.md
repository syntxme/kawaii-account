# kawaii-account — anime yig'uvchi Telegram akkaunt (Python)

Foydalanuvchi bilan **o'zbek tilida** gaplashiladi. Til: **Python** (Telethon). Rust emas — tez yozish va tez o'zgartirish uchun.

## Maqsad

Kawaii UZ support akkaunti (userbot) boshqa anime kanallari/botlaridan yangi animelarni olib, Kawaii botga epizod sifatida yuklaydi.

### 1-bosqich: avtomatik zanjir (birinchi shu qilinadi)

1. Akkaunt **1–2 ta** kanalni kuzatadi (ko'p emas). Yangi anime haqidagi post kelsa — post tagidagi tugmani bosadi (odatda `t.me/<bot>?start=...` URL tugma) → botga kirib `/start <param>` yuboradi.
2. Bot "homiy kanallarga obuna bo'ling" desa: faqat `t.me/...` / `telegram.me/...` havolalariga qo'shiladi (`t.me/+hash` / `joinchat` → `ImportChatInviteRequest`, `t.me/name` → `JoinChannelRequest`), boshqalari o'tkazib yuboriladi. Qo'shilishlar orasida 5 s kutiladi, keyin "tekshirish" tugmasini bosadi. Hech narsa bo'lmasa — postdagi tugmani qayta bosib `/start` qiladi. 5 urinishda o'ta olmasa — @syntxme ga xabar beradi.
3. Bot anime nomi va qism tugmalari bilan xabar yuboradi → qismlarni **bittalab** bosadi, kelgan videolarni yig'adi (sahifalash tugmalari bo'lishi mumkin).
4. Tartib: avval manbadan faqat **nom** aniqlanadi (kartochka) → **@syntxme** ga nomni yuborib Kawaii **ID** ni so'raydi (avto-qidiruv yo'q; bir marta berilgan ID nom bo'yicha eslab qolinadi). ID kutilayotganda egasidan faqat raqam qabul qilinadi (`0` — o'tkazish). → Kawaii'da `#id` ochib "📺 N / M - epizoddan boshlab yuboring" dan **N** ni oladi → manbadan faqat **N va undan keyingi** qismlarni yig'adi (N yo'q bo'lsa — yangi qism yo'q, keyingi postga o'tadi) → yuklaydi. Skan har ishga tushganda avtomatik: kanal postlarini pastdan tepaga bittalab ishlaydi, qayerga yetgani bazada (`scan`). ID so'rovi har anime uchun bir marta yuboriladi, javob kutilmaydi — skan davom etadi. Bir animening postlari tugmadagi bot + `?start=` parametri bo'yicha taniladi: eski (tepadagi) takroriy postlar o'tkaziladi, yangi post kelsa — yangi qism tekshiriladi.
6. Homiylik uchun majburan qo'shilgan kanallar (`joined`) 24 soatdan keyin tark etiladi (oldindan a'zo bo'lganlariga tegilmaydi). Homiy kanallar, homiy botlar va manba bot qo'shilgach mute qilinadi (akkaunt egasining Telegramiga ham ulangan).
5. Akkaunt Kawaii bot orqali **epizod qo'shadi** (pastdagi "Kawaii botga yuklash").

### 2-bosqich: o'rgatish (savol-javob)

Telegram o'z sessiyasidan bosilgan inline tugmani boshqa sessiyaga yubormaydi — shuning uchun "qo'lda bajaraman, akkaunt kuzatadi" ishlamaydi. O'rniga:
- Manba botda tiqilib qolsa (`Teach`) — @syntxme ga botning oxirgi xabari va raqamlangan tugmalari yuboriladi (`need_teach`). Javobga raqam → tugma matni umumlashtirilib (`recipes.pattern`: kichik harf, emoji/raqamsiz) `data/recipes/<bot>.json` ga yoziladi, vazifa to'xtagan bosqichdan davom etadi.
- Retsept rollari: `press` (kartochka → qismlar), `check` (homiy tekshiruvi), `never`. Qo'lda tuzatsa bo'ladi. `/learn @bot`, `/forget @bot so'z`.

## Deploy

Server: `/root/other-bots/kawaii-account`, pm2 `kawaii-account`. Cron har daqiqada `deploy/update.sh`: `origin/main` o'zgarsa — `git reset --hard`, kerak bo'lsa pip, `pm2 restart`. `.env`, `kawaii_account.session`, `data/` serverda qo'lda. Bitta sessiya bir vaqtda faqat bitta joyda ishlasin (lokal + server birga — sessiya bekor bo'lishi mumkin).

## Kawaii botga yuklash (mavjud admin oqimi — Kawaii bot kodini o'zgartirmaymiz)

Akkaunt Kawaii botda **admin** bo'lishi kerak. Oqim (kod: `../kawaii-bot/bot/src/handlers/admin/`):
1. `/admin` → reply-klaviaturada **`➕ Epizod qo'shish`** tugmasi (matnini yuborish).
2. Bot qidiruv so'raydi → anime nomi yoki **`#<id>`** yuboriladi (`#123` — aniq ID bo'yicha). Natijalar inline tugmalar (`🔸`/`🔹 <nom>`) — keraklisini bosish.
3. Anime **OnGoing** bo'lmasa bot rad etadi ("avval anime statusini OnGoing qilish kerak") → @syntxme ga xabar.
4. Videolar yuboriladi (forward ham bo'ladi). **Har video captionida faqat bitta raqam** — epizod raqami (masalan `Naruto 12-qism`; `1-fasl 12-qism` rad etiladi). Bazada bor raqam → almashtiriladi.
5. Oxirida **`♻️ Epizodlarni bazaga qo'shish`** inline tugmasini bosish. Chiqish: `⬅️ Chiqish`.

Bot "single message" uslubida ishlaydi (eski xabarni o'chirib/tahrirlab yangisini yuboradi) — javobni kutishda `edit` va yangi xabarlarni ham kuzatish kerak.

## Talablar va qoidalar

- **FLOOD_WAIT**: Telethon `flood_sleep_threshold` + qo'lda ushlash; kanalga qo'shilishlar orasida tasodifiy kutish. Foydalanuvchi floodni o'zi kuzatadi — ortiqcha cheklov shart emas, lekin xatoda yiqilmasin.
- Holat (ko'rilgan postlar, yuklangan qismlar, retseptlar) faylda/SQLite'da saqlansin — qayta ishga tushganda takrorlamasin.
- Sozlamalar `.env` da: `API_ID`, `API_HASH`, `SESSION` (fayl nomi), `WATCH_CHANNELS`, `KAWAII_BOT` (username), `OWNER=syntxme`. `.env` va `*.session` git'ga kirmasin.
- Kawaii botning o'zida ham shu akkaunt bilan grammers sessiyasi bor (avto-tuzatish uchun) — bu loyiha **alohida** Telethon sessiyasi ishlatadi, ular bir-biriga xalaqit bermaydi.
- Serverda ishlatiladi: `178.104.65.194`, pm2 (boshqa python botlar `/root/other-bots/*` da pm2 bilan ishlaydi). Avval kompyuterda test qilinadi.

## Atrof

- Qo'shni loyihalar: `../kawaii-bot` (Rust bot+sayt, foydalanuvchi o'zi push qiladi), `../kawaii-id`, `../kawaii-radio`.
- Serverda hech qachon commit/merge qilinmaydi — server faqat GitHub'ning ko'zgusi.
