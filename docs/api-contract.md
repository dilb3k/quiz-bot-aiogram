# Telegram API shartnomasi

2026-10-24 kuni Telegram Bot API 10.3 va o‘rnatilgan Aiogram 3.31.0 bilan tekshirildi.

Rasmiy manbalar:
- https://core.telegram.org/bots/api#sendpoll
- https://core.telegram.org/bots/api#pollanswer
- https://core.telegram.org/bots/api#getchatmember
- https://core.telegram.org/bots/api#keyboardbuttonrequestchat
- https://docs.aiogram.dev/en/latest/api/methods/send_poll.html

`sendPoll`: savol 1–300, variant matni 1–100, tushuntirish 0–200 belgi va ko‘pi bilan 2 yangi qator.
API 1–12 variantni qo‘llaydi; ushbu bot mahsulot talabi bo‘yicha 2–4 variant qabul qiladi.
`type=quiz`, `allows_multiple_answers=false`, `allows_revoting=false`.
`correct_option_ids` bitta elementdan iborat. Eskirgan `correct_option_id` ishlatilmaydi.
`open_period` 5–2628000 soniya; `close_date` bilan birga yuborilmaydi.
Bot variantlarni o‘zi aralashtiradi, `shuffle_options=false`: indeks va nusxa aniq saqlanadi.

Guruh/private: `is_anonymous=false`. Kanal: `is_anonymous=true` va alohida private deep link.
`poll_answer` faqat botning o‘zi yuborgan non-anonymous pollarda keladi; `user` bo‘lmasligi,
`voter_chat` bo‘lishi yoki `option_ids=[]` qaytarib olishni anglatishi mumkin. Shaxsi noma’lum
ovozga individual ball yozilmaydi. Bot foydalanuvchi tugmani bosgan aniq vaqtni bilmaydi.

`getChatMember` boshqa foydalanuvchilar uchun faqat bot admin bo‘lganda kafolatlangan.
Shuning uchun chat tanlash tugmasi botni ham admin sifatida qo‘shishni so‘raydi.
Guruhda xabar va poll yuborish, kanalda `can_post_messages` tekshiriladi.
`stopPoll`, `getChat`, `my_chat_member`, chat migration va `RetryAfter` ishlatiladi.

Orbit discovery so‘rovi mahalliy DNS cheklovi sabab bajarilmadi. Manba sifatida rasmiy
Telegram/Aiogram hujjatlari ishlatildi. Owner mock qidiruvi uchun tarmoq ulanishi yo‘q;
mahalliy Postman mock shu shartnomaning faqat sendPoll/stopPoll/sendMessage qismini ifodalaydi.
U real Telegram testi emas. HTTP simulyatsiya port ochish EPERM sabab bu muhitda ishlamadi.
