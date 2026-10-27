DEMO: dict[str, list[tuple[str, list[str], int, str]]] = {
    "JavaScript": [
        (
            "Qaysi operator qiymat va turni birgalikda taqqoslaydi?",
            ["===", "==", "=", "!="],
            0,
            "=== qat’iy tenglik operatoridir.",
        ),
        (
            "Massiv oxiriga element qo‘shadigan metod?",
            ["push()", "pop()", "shift()", "slice()"],
            0,
            "push() massiv oxiriga qo‘shadi.",
        ),
        (
            "JSON matnini obyektga aylantiruvchi metod?",
            ["JSON.parse()", "JSON.stringify()", "JSON.object()"],
            0,
            "JSON.parse() JSON matnini o‘qiydi.",
        ),
        (
            "JavaScriptda typeof true natijasi?",
            ["boolean", "bool", "number", "string"],
            0,
            "Mantiqiy qiymat turi boolean.",
        ),
        (
            "O‘zgaruvchini blok doirasida e’lon qilish kalit so‘zi?",
            ["let", "var", "global", "define"],
            0,
            "let blok doirasida amal qiladi.",
        ),
    ],
    "Python": [
        (
            "Python ro‘yxati uzunligini qaysi funksiya beradi?",
            ["len()", "size()", "length()"],
            0,
            "len() elementlar sonini qaytaradi.",
        ),
        (
            "Python’da 7 // 2 natijasi?",
            ["3", "3.5", "4", "2"],
            0,
            "// pastga yaxlitlangan bo‘lishdir.",
        ),
        (
            "Qaysi tur o‘zgarmas ketma-ketlik hisoblanadi?",
            ["tuple", "list", "set", "dict"],
            0,
            "Tuple elementlari qayta tayinlanmaydi.",
        ),
        (
            "Python’da bo‘sh qiymat qanday yoziladi?",
            ["None", "null", "nil", "undefined"],
            0,
            "None — qiymat yo‘qligi belgisi.",
        ),
        (
            "Istisnoni ushlaydigan blok kalit so‘zi?",
            ["except", "catch", "error", "rescue"],
            0,
            "try blokidagi istisno except orqali ushlanadi.",
        ),
    ],
    "Umumiy bilim": [
        (
            "O‘zbekiston poytaxti qaysi shahar?",
            ["Toshkent", "Samarqand", "Buxoro", "Nukus"],
            0,
            "O‘zbekiston poytaxti — Toshkent.",
        ),
        (
            "Suvning kimyoviy formulasi?",
            ["H2O", "CO2", "O2", "NaCl"],
            0,
            "Suv ikki vodorod va bir kislorod atomidan tuzilgan.",
        ),
        ("Bir soatda nechta minut bor?", ["60", "100", "30", "24"], 0, "Bir soat 60 minutga teng."),
        (
            "Quyosh tizimidagi eng katta sayyora?",
            ["Yupiter", "Yer", "Mars", "Venera"],
            0,
            "Yupiter Quyosh tizimidagi eng katta sayyora.",
        ),
        (
            "Uchburchakning nechta tomoni bor?",
            ["3", "4", "2", "5"],
            0,
            "Uchburchak uch tomondan iborat.",
        ),
    ],
}
