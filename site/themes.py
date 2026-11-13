"""Style presets for the site. The admin can pick a preset and then tweak any value."""

# Every theme has the same keys. Colors are hex, fonts are Google Fonts family names.
THEME_KEYS = [
    ("bg", "Фон страницы"),
    ("bg2", "Фон второстепенных секций"),
    ("surface", "Фон карточек"),
    ("border", "Рамки"),
    ("text", "Основной текст"),
    ("muted", "Второстепенный текст"),
    ("accent", "Акцент (кнопки, выделения)"),
    ("accent_text", "Текст на кнопках"),
    ("kicker", "Мелкие заголовки (надписи над заголовками)"),
]

FONT_KEYS = [("font_heading", "Шрифт заголовков"), ("font_body", "Шрифт текста")]

# Google Fonts css2 spec per family (only weights the family really has, else Google returns 400).
FONT_SPECS = {
    "DM Serif Display": "ital@0;1",
    "Cormorant Garamond": "ital,wght@0,500;0,600;0,700;1,500;1,600",
    "Fraunces": "ital,wght@0,300;0,500;0,700;1,300;1,500",
    "Playfair Display": "ital,wght@0,400;0,600;0,700;1,400;1,600",
    "Lora": "ital,wght@0,400;0,600;0,700;1,400;1,600",
    "Libre Baskerville": "ital,wght@0,400;0,700;1,400",
    "EB Garamond": "ital,wght@0,400;0,600;0,700;1,400;1,600",
    "Nunito": "ital,wght@0,400;0,600;0,700;0,800;1,400",
    "Nunito Sans": "ital,wght@0,400;0,600;0,700;0,800;1,400",
    "Karla": "ital,wght@0,400;0,500;0,700;0,800;1,400",
    "Inter": "wght@400;600;700;800",
    "Manrope": "wght@400;600;700;800",
    "Mulish": "ital,wght@0,400;0,600;0,700;0,800;1,400",
    "Work Sans": "ital,wght@0,400;0,600;0,700;0,800;1,400",
    "Lato": "ital,wght@0,400;0,700;0,900;1,400",
    "Montserrat": "ital,wght@0,400;0,600;0,700;0,800;1,400",
    "Raleway": "ital,wght@0,400;0,600;0,700;0,800;1,400",
    "Quicksand": "wght@400;600;700",
}
FONTS = list(FONT_SPECS)

PRESETS = {
    "night": {
        "label": "Ночная сказка (тёмный)",
        "bg": "#1E1A2B", "bg2": "#15121F", "surface": "#2A2440", "border": "#3B3456",
        "text": "#F4ECE6", "muted": "#C9BFCF", "accent": "#F2C9BE", "accent_text": "#1E1A2B",
        "kicker": "#E58E7E", "font_heading": "DM Serif Display", "font_body": "Nunito",
        "stars": True, "dark": True, "radius": 22,
    },
    "instagram": {
        "label": "Instagram-лента (светлый, пудровый)",
        "bg": "#FBF6F2", "bg2": "#F6E3DD", "surface": "#FFFFFF", "border": "#EBC9C0",
        "text": "#3E2C29", "muted": "#7A625D", "accent": "#B5584B", "accent_text": "#FBF6F2",
        "kicker": "#4F6B4B", "font_heading": "Cormorant Garamond", "font_body": "Nunito Sans",
        "stars": False, "dark": False, "radius": 22,
    },
    "editorial": {
        "label": "Мягкий журнал (шалфей)",
        "bg": "#F3F1EC", "bg2": "#DCE3D6", "surface": "#FFFFFF", "border": "#C9CFC4",
        "text": "#26302A", "muted": "#5B675E", "accent": "#3F5A44", "accent_text": "#F3F1EC",
        "kicker": "#B5584B", "font_heading": "Fraunces", "font_body": "Karla",
        "stars": False, "dark": False, "radius": 14,
    },
}

DEFAULT_PRESET = "night"


def preset(name):
    p = dict(PRESETS.get(name) or PRESETS[DEFAULT_PRESET])
    p.pop("label", None)
    p["preset"] = name if name in PRESETS else DEFAULT_PRESET
    return p


def google_fonts_url(theme):
    fams = []
    for key in ("font_heading", "font_body"):
        f = theme.get(key)
        if f and f not in fams:
            fams.append(f)
    parts = []
    for f in fams:
        if f not in FONT_SPECS:
            continue
        parts.append("family=" + f.replace(" ", "+") + ":" + FONT_SPECS[f])
    if not parts:
        return ""
    return "https://fonts.googleapis.com/css2?" + "&".join(parts) + "&display=swap"
