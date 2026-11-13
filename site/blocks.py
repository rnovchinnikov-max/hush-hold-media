"""Page blocks: what each block type has, how admin forms read it, and small text helpers."""
import html
import re

from markupsafe import Markup

# field types: line (one line), text (textarea), lines (textarea, one item per line),
# bool (checkbox), image (path with picker), widget (lava.top link or iframe code), int
BLOCK_TYPES = {
    "hero": {
        "label": "Первый экран (заголовок + кнопка)",
        "fields": [
            ("image", "image", "Картинка сверху (обложка гайда, фото)"),
            ("image_style", "choice:cover=Обложка с наклоном,circle=Круг,none=Без картинки", "Форма картинки"),
            ("kicker", "line", "Надпись над заголовком"),
            ("title", "line", "Заголовок (слово в *звёздочках* выделяется цветом)"),
            ("text", "text", "Текст под заголовком"),
            ("button_text", "line", "Текст кнопки (пусто = без кнопки). {price} подставит цену из блока оплаты"),
            ("button_link", "line", "Куда ведёт кнопка (#buy = к блоку оплаты, или ссылка)"),
            ("show_old_price", "bool", "Показать зачёркнутую старую цену рядом с кнопкой"),
        ],
    },
    "cards": {
        "label": "Карточки (главы гайда, преимущества)",
        "fields": [
            ("kicker", "line", "Надпись над заголовком"),
            ("title", "line", "Заголовок"),
            ("text", "text", "Подзаголовок"),
            ("items", "lines", "Карточки, по одной на строку: Заголовок | Текст"),
            ("numbered", "bool", "Нумеровать карточки"),
            ("columns", "int", "Колонок на компьютере (1-4)"),
            ("dark", "bool", "Тёмный (второстепенный) фон секции"),
        ],
    },
    "image_text": {
        "label": "Фото + текст (о маме, история)",
        "fields": [
            ("image", "image", "Фото"),
            ("image_style", "choice:circle=Круг,arch=Арка,rect=Прямоугольник", "Форма фото"),
            ("kicker", "line", "Надпись над заголовком"),
            ("title", "line", "Заголовок"),
            ("text", "text", "Текст"),
            ("bullets", "lines", "Пункты со звёздочкой, по одному на строку"),
            ("image_right", "bool", "Фото справа"),
            ("dark", "bool", "Тёмный (второстепенный) фон секции"),
        ],
    },
    "pay": {
        "label": "Оплата / донат (виджеты lava.top + переключатель валют)",
        "fields": [
            ("title", "line", "Заголовок"),
            ("text", "text", "Текст"),
            ("price_usd", "line", "Цена в USD (пусто = без цены, для донатов)"),
            ("old_usd", "line", "Старая цена в USD (зачёркнутая, можно пусто)"),
            ("price_eur", "line", "Цена в EUR"),
            ("old_eur", "line", "Старая цена в EUR"),
            ("label_usd", "line", "Кнопка валюты USD"),
            ("label_eur", "line", "Кнопка валюты EUR"),
            ("widget_usd", "widget", "Виджет lava.top для USD (вставь код iframe или ссылку)"),
            ("widget_eur", "widget", "Виджет lava.top для EUR"),
            ("widget_width", "int", "Ширина виджета, px"),
            ("widget_height", "int", "Высота виджета, px"),
            ("note", "line", "Мелкая подпись под виджетом"),
        ],
    },
    "faq": {
        "label": "Вопросы и ответы",
        "fields": [
            ("title", "line", "Заголовок"),
            ("items", "lines", "Вопросы, по одному на строку: Вопрос | Ответ"),
        ],
    },
    "quote": {
        "label": "Крупная цитата / фраза",
        "fields": [("text", "text", "Текст"), ("dark", "bool", "Тёмный фон секции")],
    },
    "text": {
        "label": "Текст (для любых страниц)",
        "fields": [
            ("title", "line", "Заголовок"),
            ("body", "text", "Текст. Пустая строка = новый абзац, **жирный**, *курсив*, [ссылка](https://...), строки с «- » = список"),
            ("dark", "bool", "Тёмный фон секции"),
        ],
    },
    "instagram": {
        "label": "Призыв подписаться на Instagram",
        "fields": [
            ("title", "line", "Заголовок"),
            ("text", "text", "Текст"),
            ("button_text", "line", "Текст кнопки"),
        ],
    },
    "html": {
        "label": "HTML-код (для опытных)",
        "fields": [("code", "text", "HTML, вставляется как есть")],
    },
}

BLOCK_DEFAULTS = {
    "hero": {"image_style": "none", "button_link": "#buy", "kicker": "", "title": "New page",
             "text": "", "button_text": "", "show_old_price": False, "image": ""},
    "cards": {"columns": 3, "numbered": False, "dark": False, "items": "", "title": "", "text": "", "kicker": ""},
    "image_text": {"image_style": "circle", "image_right": False, "dark": False},
    "pay": {"label_usd": "Pay in USD", "label_eur": "Pay in EUR", "widget_width": 250, "widget_height": 80},
    "faq": {"title": "Questions"},
    "quote": {"dark": False},
    "text": {"dark": False},
    "instagram": {"title": "Come say hi on Instagram", "button_text": "Follow"},
    "html": {},
}


def new_block(btype):
    b = {"type": btype}
    for name, ftype, _ in BLOCK_TYPES[btype]["fields"]:
        b[name] = False if ftype == "bool" else (0 if ftype == "int" else "")
    b.update(BLOCK_DEFAULTS.get(btype, {}))
    return b


WIDGET_RE = re.compile(r"^https://widget\.lava\.top/[A-Za-z0-9._~/?=&%-]+$")


def clean_widget(value):
    """Accept a pasted iframe snippet or a bare link; return a safe widget URL or ''."""
    value = (value or "").strip()
    if not value:
        return ""
    m = re.search(r'src\s*=\s*["\']([^"\']+)["\']', value)
    if m:
        value = m.group(1).strip()
    value = html.unescape(value)
    return value if WIDGET_RE.match(value) else None


def read_block(form, i, btype):
    b = {"type": btype}
    for name, ftype, _ in BLOCK_TYPES[btype]["fields"]:
        key = f"b{i}_{name}"
        if ftype == "bool":
            b[name] = form.get(key) == "on"
        elif ftype == "int":
            try:
                b[name] = int(form.get(key) or 0)
            except ValueError:
                b[name] = 0
        elif ftype.startswith("choice:"):
            opts = [o.split("=", 1)[0] for o in ftype[7:].split(",")]
            b[name] = form.get(key) if form.get(key) in opts else opts[0]
        else:
            b[name] = (form.get(key) or "").replace("\r\n", "\n").strip()
    return b


def choices(ftype):
    return [tuple(o.split("=", 1)) for o in ftype[7:].split(",")]


def split_items(text):
    out = []
    for line in (text or "").split("\n"):
        line = line.strip()
        if not line:
            continue
        if "|" in line:
            a, b = line.split("|", 1)
            out.append((a.strip(), b.strip()))
        else:
            out.append((line, ""))
    return out


def lines(text):
    return [x.strip() for x in (text or "").split("\n") if x.strip()]


_INLINE = [
    (re.compile(r"\*\*(.+?)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"\*(.+?)\*"), r'<em class="hl">\1</em>'),
    (re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+|/[^\s)]*|#[^\s)]*)\)"), r'<a href="\2">\1</a>'),
]


def inline(text):
    """Escape, then allow **bold**, *accent italic* and [links](url)."""
    s = html.escape(text or "", quote=True)
    for rx, rep in _INLINE:
        s = rx.sub(rep, s)
    return Markup(s)


def rich(text):
    """Paragraphs and '- ' lists on top of inline()."""
    out = []
    for para in re.split(r"\n\s*\n", (text or "").strip()):
        rows = [r for r in para.split("\n") if r.strip()]
        if not rows:
            continue
        if all(r.lstrip().startswith("- ") for r in rows):
            out.append("<ul>" + "".join(f"<li>{inline(r.lstrip()[2:])}</li>" for r in rows) + "</ul>")
        else:
            out.append("<p>" + "<br>".join(str(inline(r)) for r in rows) + "</p>")
    return Markup("".join(out))
