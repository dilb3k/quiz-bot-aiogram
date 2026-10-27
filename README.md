# O‘zbekcha Telegram Quiz Bot

Python 3.12, Aiogram 3.31, PostgreSQL, SQLAlchemy 2 async/asyncpg va Alembic.
Shaxsiy chat, guruh va kanallar uchun native quiz poll; admin panel, doimiy FSM,
PostgreSQL scheduler, nusxalangan savollar va alohida reytinglar.

## Mahalliy o‘rnatish

Python 3.12 va PostgreSQL 14+ o‘rnating. Joriy papkada:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Mahalliy `.env` tayyorlangan va gitdan chiqarilgan. Uni `.env.example` bilan almashtirmang:
u yerda faqat placeholder qiymatlar bor. Yangi muhitda `.env.example`dan nusxa oling.
`BOT_TOKEN` — BotFather tokeni; bo‘sh bo‘lsa bot tushunarli konfiguratsiya xatosi bilan to‘xtaydi.
`DB_HOST=127.0.0.1`, `DB_PORT=5432`, `DB_NAME=nb_420`, `DB_USER=postgres`.
Parol `.env`dan o‘qiladi. `SUPERADMIN_ID=5583276966`, `TIMEZONE=Asia/Tashkent`.
Token/parol/database URL logga yozilmaydi. `.env` Docker image ichiga kirmaydi.

Baza avval yaratilmagan bo‘lsa, PostgreSQL foydalanuvchisi bilan yarating:

```bash
createdb -h 127.0.0.1 -p 5432 -U postgres nb_420
```

Mavjud `nb_420` bazasini o‘chirmang. Migratsiya faqat yangi bot jadvallarini yaratadi;
shu nomdagi begona jadvallar mavjud bo‘lsa alohida database tanlang.

```bash
alembic upgrade head
python -m quizbot.seed
python main.py
```

Seed alohida va idempotent: JavaScript, Python, Umumiy bilim bo‘yicha 5 tadan savol.
Startup avtomatik seed qilmaydi. Tahrirlangan demo savollar qayta seed bilan ustidan yozilmaydi.

## Docker

```bash
docker compose up --build -d
docker compose run --rm bot python -m quizbot.seed
docker compose logs -f bot
```

`db` healthcheck → `migrate` → `bot` ketma-ketligi. Docker ichida `DB_HOST=db` bo‘ladi.
PostgreSQL volume saqlanadi. Hostdagi mavjud PostgreSQL portiga tegilmaydi.
Host PostgreSQL bilan Docker bot ishlatish uchun `DB_HOST=host.docker.internal` override va
tashqi DB konfiguratsiyasidan foydalaning; odatiy mahalliy ishga tushirish yuqoridagi commandlar bilan.

## Telegram va huquqlar

BotFather orqali bot yarating va tokenni `.env`ga yozing. BotFather guruhga qo‘shishni
ruxsat etsin. Barcha guruh xabarlarini yig‘ish shart emas; quiz javoblari `poll_answer`
orqali keladi. Botni guruhda admin qilish `getChatMember` tekshiruvining ishonchli ishlashi
uchun tavsiya etiladi. Kanalda admin va post joylash huquqi majburiy.

Shaxsiy chatda `/start` → «Guruh yoki kanalga ulash» → chat tanlash. Muqobil:
`/linkchat -100...`. Telegram sizning haqiqiy adminligingiz va bot huquqlari qayta tekshiriladi.
Bot qo‘shilishi quizni o‘zi boshlamaydi. «Quiz boshlash» orqali joy, kategoriya, interval,
javob muddati va savollar sonini tanlab tasdiqlang. Yetishmagan son mavjud savollar soniga
kamaytirilib, yana tasdiqlanadi. Custom interval 1–1440 minut, muddat 5–2628000 soniya.

Guruh admini faqat o‘z chatini boshqaradi. Global savollarni o‘zgartirish uchun botning
`admin` roli kerak. Har bir boshqaruv amalida Telegram huquqi qayta tekshiriladi.
Shaxsiy sessiyani faqat egasi boshqaradi. Chat manager jadvali huquq manbasi emas.

## Admin panel

`SUPERADMIN_ID` startupda superadmin sifatida bazaga upsert qilinadi; `/start` ham rolni tiklaydi.
`/admin` yoki «Admin panel»: kategoriya yaratish/tahrirlash/aktivlik, savollar ro‘yxati,
savol qo‘shish/tahrirlash/aktivlik, bot statistikasi. Superadmin user ID orqali admin tayinlaydi
va olib tashlaydi; superadmin roli shu paneldan o‘zgarmaydi.

Savol FSM: kategoriya → matn → 2–4 variant (alohida qatorlarda) → to‘g‘ri variant raqami
→ tushuntirish (`-` bo‘lsa yo‘q) → preview → saqlash. Har bosqichda Orqaga/Bekor qilish bor.
Savol va kategoriya hard delete qilinmaydi. Yuborilgan poll matni/variantlari alohida nusxada.

## Natijalar va boshqaruv

- `/quiz`, `/sessions`, `/results`, `/ranking`, `/chatranking`, `/help`.
- `/pause`, `/resume`, `/stop`, `/status`, `/settings` — shu chatdagi faol sessiya.
- Shaxsiy chatdan boshqarish: masalan `/pause 12` (sessiya ID).
- Sozlamalarni o‘zgartirish uchun sessiyani to‘xtatib, yangisini yarating.
- `/cancel` — yaratilayotgan quiz/admin jarayonini bekor qilish.

To‘g‘ri javob 1 ball; xato 0. Reytingda ball, to‘g‘ri javoblarga sarflangan kuzatilgan jami
vaqt, so‘ng user ID ishlatiladi. Vaqt foydalanuvchi bosgan aniq payt emas, bot update olgan
vaqtga asoslangan taxmin. Kech kelgan haqiqiy javoblar ham saqlanadi; avval yuborilgan
xulosa kech update sabab eskirishi mumkin, «Reyting» tugmasi joriy DB hisobini chiqaradi.

Savol yopilganda ixcham natija va top 5; yakunda pagination bilan reyting. Chat admini
«Qatnashchi javoblari» orqali har savoldagi tanlovni ko‘radi. Javob bermaganlar butun guruh
ro‘yxati deb olinmaydi; faqat kuzatilgan qatnashchilarning savollari ko‘rsatiladi.
Shaxsiy va guruh reytinglari chat ID bilan ajratilgan. `/results` foydalanuvchining kategoriyalar
kesimidagi umumiy shaxsiy hisobotini beradi; bu boshqa chat reytingiga ball qo‘shmaydi.

Kanal ovozlari anonim: faqat pollning jami va variantlar bo‘yicha sonlari ko‘rsatiladi.
Turli savollardagi ovozlar yig‘indisi noyob qatnashchilar soni emas. Kanalda individual reyting
yo‘q. Poll ostidagi deep link alohida shaxsiy quiz ochadi (`source_session_id` saqlanadi),
uning ballari anonim kanal ovozlariga qo‘shilmaydi.

## Scheduler, restart va yetkazish siyosati

`next_run_at`, navbat, holat, lease token va lease muddati PostgreSQLda. `FOR UPDATE SKIP LOCKED`
workerlar vazifani ajratadi; lease 120 soniya, HTTP yuborish timeout 30 soniya. Har ishda token
qayta tekshiriladi, tarmoq amali davomida sessiya row lock saqlanadi. DB partial unique index
bir chatda bittadan active/paused/stopping sessiya va bir sessiyada bitta sending/open savolni himoya qiladi.

Birinchi savol schedulerning keyingi tickida (odatda 1 soniyagacha); keyingisi savol yopilishi
qayta ishlangach tanlangan intervaldan keyin. Restartda o‘tgan intervaldagi savollar to‘planib
yuborilmaydi. Muddati o‘tgan ochiq poll avval yopiladi; keyin yangi interval boshlanadi.
Davomiy rejim navbatni tugatmaguncha takrorlamaydi, keyingi sikl aralashtiriladi. Deaktiv savollar
navbatdan chiqariladi. Bir polling process ishlating; bir token bilan parallel long polling mumkin emas.
Scheduler lease mexanizmi esa bir nechta worker orasida DB darajasida himoyalangan.

Pauza ochiq savolni scheduler orqali yopadi. U yopilmasidan juda tez resume bosilsa kutish
xabari chiqadi. Resume keyingi savoldan davom etadi. Stop yakuniy natijani chiqaradi.
Huquqlar yo‘qolsa chat/sessiya `blocked` va sabab DBga yoziladi. Qayta ulab yangi sessiya yarating.
Guruh ID migratsiyasi FK `ON UPDATE CASCADE` bilan; yangi chat oldindan mavjud bo‘lsa tarixlar
birlashtirilib, konfliktli sessiyalar xavfsiz to‘xtatiladi.

`sendPoll` va PostgreSQL bitta atomik transaction emas:
1. Savol nusxasi `sending` sifatida commit qilinadi.
2. Telegram muvaffaqiyatli javob bersa poll/message ID yozilib `open` qilinadi.
3. Crash yoki noma’lum tarmoq natijasida `sending` → `uncertain`, sessiya pauzada.
   Ko‘r-ko‘rona qayta yuborilmaydi. Eski poll ehtimol mavjud; avtomatik `open_period` bilan yopiladi.
   Konservativ muddat + 35 soniyadan keyin resume mumkin; noma’lum savol qayta yuborilmaydi.
4. Aniq 429 javobida `retry_after` DBga yoziladi, yangi urinish shundan keyin. Boshqa retry
   qilish xavfsiz amallarda cheklangan eksponensial backoff, 5 urinishdan keyin pauza.
5. Forbidden sessiyani bloklaydi. Xulosa xabari va DB commit orasidagi crash xulosani
   takrorlatishi mumkin; pollni aynan bir marta yetkazish kafolati berilmaydi.

Telegram noma’lum yuborishning poll ID sini qaytarib olish API sini bermaydi. Shu sabab bunday
pollning individual javoblari sessiyaga bog‘lanmasligi mumkin. Xavfsizlik uchun yangi pollga
shoshilmaslik tanlangan. Oddiy qayta kelgan javob update’i unique constraint va update ID
bilan yangilanadi; jami ball qo‘shib yurilmaydi, answers jadvalidan hisoblanadi.

FSM ham PostgreSQLda. Advisory transaction lock bir foydalanuvchi FSM oqimini ketma-ket qiladi.
Timestamp `TIMESTAMPTZ`, ichki UTC, ko‘rsatish `Asia/Tashkent`. Loglar strukturali va sirlarni chiqarmaydi.

## Testlar

```bash
pytest -q tests/test_domain.py tests/test_contract.py
createdb -h 127.0.0.1 -U postgres quiz_test
export TEST_DATABASE_URL='postgresql+asyncpg://postgres:YOUR_PASSWORD@127.0.0.1:5432/quiz_test'
pytest -q
```

URLni shell tarixida saqlashni istamasangiz environment orqali yuklang. Test runner nomi `_test`
bilan tugamagan bazani rad etadi. Har test UUID sxemasiga migratsiya bajaradi va faqat o‘sha
sxemani olib tashlaydi; production bazani tozalamaydi. `TEST_DATABASE_URL` yo‘q bo‘lsa DB testlar skip.

Docker bilan alohida vaqtinchalik test bazasi:

```bash
docker compose -f compose.test.yaml up --build --abort-on-container-exit --exit-code-from tests
```

Postman va real Aiogram HTTP client uchun, ikki terminalda:

```bash
postman simulation run postman/simulations/quiz.sim.yaml --port 4900 --output ndjson --no-history
python -m tests.simulation_check
# TEST_DATABASE_URL ham berilgan bo‘lsa to‘liq scheduler HTTP testlari:
TELEGRAM_SIMULATION_URL=http://127.0.0.1:4900/telegram pytest -q
```

Bu mock faqat hujjatlashtirilgan poll oqimi va 429/403/500 xatolarni modellashtiradi. Token
sun’iy lokal fixture; `.env`dagi real token simulyatsiyaga yuborilmaydi. Bu live Telegram tekshiruvi emas.

Paketlar o‘rnatilmagan muhitdagi cheklangan offline test:

```bash
venv/bin/python -m unittest tests.test_domain tests.test_contract -v
```

## Ushbu ish sessiyasidagi tekshiruv holati

- 22 offline unittest testi o‘tdi (Python 3.14 va mavjud Aiogram 3.31).
- Ruff statik tekshiruvi o‘tdi; Python 3.12 sintaksis mosligi ham AST orqali tekshiriladi.
- Python 3.12 yo‘q; yangi dependency install DNS cheklovi sabab bajarilmadi.
- Alembic/pytest/SQLAlchemy/asyncpg bu muhitda o‘rnatilmagan: DB migratsiya va pytest integratsiyasi bajarilmadi.
- PostgreSQL TCP ulanishi va alohida initdb shared-memory amali sandbox tomonidan rad etildi.
- Postman simulyatsiyasi lokal listen EPERM bilan to‘xtadi. Docker o‘rnatilmagan.
- Real Telegram polling/poll yuborish sinovi bajarilmadi. Token `.env`da bor; cheklov token yetishmasligi emas.

To‘liq ishga tushgan production bot yoki DB/Telegram end-to-end test o‘tgan deb hisoblamang.
Rasmiy API tekshiruvi: [Telegram](https://core.telegram.org/bots/api#sendpoll),
[Aiogram](https://docs.aiogram.dev/en/latest/api/methods/send_poll.html). Tafsilot: `docs/api-contract.md`.
