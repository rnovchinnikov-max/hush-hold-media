"""SQLite storage: settings (key -> JSON) and pages (with blocks as JSON)."""
import json
import os
import sqlite3
import threading

from themes import preset, DEFAULT_PRESET

DB_PATH = os.environ.get("SITE_DB", os.path.join(os.path.dirname(__file__), "data", "site.db"))
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    nav_label TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    is_home INTEGER NOT NULL DEFAULT 0,
    priority INTEGER NOT NULL DEFAULT 10,
    show_in_nav INTEGER NOT NULL DEFAULT 1,
    published INTEGER NOT NULL DEFAULT 1,
    blocks TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init():
    with _lock, connect() as con:
        con.executescript(SCHEMA)
        if not con.execute("SELECT 1 FROM settings LIMIT 1").fetchone():
            for k, v in DEFAULT_SETTINGS.items():
                con.execute("INSERT INTO settings(key, value) VALUES (?, ?)", (k, json.dumps(v)))
        if not con.execute("SELECT 1 FROM pages LIMIT 1").fetchone():
            for p in SEED_PAGES:
                con.execute(
                    "INSERT INTO pages(slug,title,nav_label,description,is_home,priority,show_in_nav,published,blocks)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (p["slug"], p["title"], p["nav_label"], p["description"], p["is_home"], p["priority"],
                     1, 1, json.dumps(p["blocks"], ensure_ascii=False)),
                )


# ---------- settings ----------
def get_settings():
    with connect() as con:
        rows = con.execute("SELECT key, value FROM settings").fetchall()
    s = dict(DEFAULT_SETTINGS)
    s.update({r["key"]: json.loads(r["value"]) for r in rows})
    theme = preset(DEFAULT_PRESET)
    theme.update(s.get("theme") or {})
    s["theme"] = theme
    return s


def set_settings(values):
    with _lock, connect() as con:
        for k, v in values.items():
            con.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (k, json.dumps(v, ensure_ascii=False)))


# ---------- pages ----------
def _page(row):
    if not row:
        return None
    p = dict(row)
    p["blocks"] = json.loads(p["blocks"] or "[]")
    return p


def list_pages():
    with connect() as con:
        rows = con.execute("SELECT * FROM pages ORDER BY is_home DESC, priority ASC, id ASC").fetchall()
    return [_page(r) for r in rows]


def nav_pages():
    return [p for p in list_pages() if p["published"] and p["show_in_nav"]]


def get_page(page_id=None, slug=None):
    with connect() as con:
        if page_id is not None:
            row = con.execute("SELECT * FROM pages WHERE id=?", (page_id,)).fetchone()
        else:
            row = con.execute("SELECT * FROM pages WHERE slug=?", (slug,)).fetchone()
    return _page(row)


def home_page():
    with connect() as con:
        row = con.execute("SELECT * FROM pages WHERE is_home=1 AND published=1 LIMIT 1").fetchone()
        if not row:
            row = con.execute("SELECT * FROM pages WHERE published=1 ORDER BY priority, id LIMIT 1").fetchone()
    return _page(row)


def save_page(p):
    blocks = json.dumps(p.get("blocks", []), ensure_ascii=False)
    with _lock, connect() as con:
        if p.get("is_home"):
            con.execute("UPDATE pages SET is_home=0")
        if p.get("id"):
            con.execute(
                "UPDATE pages SET slug=?,title=?,nav_label=?,description=?,is_home=?,priority=?,show_in_nav=?,"
                "published=?,blocks=?,updated_at=datetime('now') WHERE id=?",
                (p["slug"], p["title"], p["nav_label"], p["description"], int(bool(p["is_home"])), p["priority"],
                 int(bool(p["show_in_nav"])), int(bool(p["published"])), blocks, p["id"]))
            return p["id"]
        cur = con.execute(
            "INSERT INTO pages(slug,title,nav_label,description,is_home,priority,show_in_nav,published,blocks)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (p["slug"], p["title"], p["nav_label"], p["description"], int(bool(p["is_home"])), p["priority"],
             int(bool(p["show_in_nav"])), int(bool(p["published"])), blocks))
        return cur.lastrowid


def set_home(page_id):
    with _lock, connect() as con:
        con.execute("UPDATE pages SET is_home=0")
        con.execute("UPDATE pages SET is_home=1, published=1 WHERE id=?", (page_id,))


def set_priorities(order):
    """order: list of (page_id, priority)."""
    with _lock, connect() as con:
        for pid, pr in order:
            con.execute("UPDATE pages SET priority=? WHERE id=?", (pr, pid))


def delete_page(page_id):
    with _lock, connect() as con:
        con.execute("DELETE FROM pages WHERE id=? AND is_home=0", (page_id,))


# ---------- first-run content ----------
DISCLAIMER = ("This guide shares general information about baby and toddler sleep. It is not medical advice. "
              "Talk to your pediatrician about your child's health, feeding and sleep.")

DEFAULT_SETTINGS = {
    "brand_name": "Hush & Hold",
    "instagram_url": "https://www.instagram.com/hush_hold/",
    "instagram_handle": "@hush_hold",
    "default_currency": "USD",
    "footer_text": DISCLAIMER,
    "theme": preset(DEFAULT_PRESET),
}

GUIDE_BLOCKS = [
    {"type": "hero", "image": "/static/img/guide-cover.jpg", "image_style": "cover",
     "kicker": "For babies and toddlers 0 to 3",
     "title": "From an hour of rocking to *goodnight* in 15 minutes.",
     "text": "A gentle, step-by-step plan to help your little one fall asleep on their own. "
             "No crying it out, and you stay close the whole time.",
     "button_text": "Get the guide · {price}", "button_link": "#buy", "show_old_price": True},
    {"type": "cards", "kicker": "", "title": "One calm evening, nine chapters",
     "text": "Short enough to read tonight. Clear enough to start tomorrow.",
     "items": "How baby sleep works | Sleep cycles and why naps stop at 40 minutes.\n"
              "The right daily rhythm | Wake windows by month and a bedtime formula.\n"
              "A safe, cozy sleep space | Safe sleep checklist, light, noise, temperature.\n"
              "Bedtime routine by age | Steps from birth to 3, plus the sleepy phrase.\n"
              "Why isn't my baby sleeping? | Associations, leaps and night wakings.\n"
              "Night feeds | When to reduce them, with your pediatrician.\n"
              "Co-sleeping and room-sharing | What experts recommend for safety.\n"
              "4 gentle methods | Pick up / put down, fading, the chair, agreements.\n"
              "Your calm | A calm parent makes a calmer baby.",
     "numbered": True, "columns": 3, "dark": True},
    {"type": "image_text", "image": "/static/img/mom-baby.jpg", "image_style": "circle",
     "kicker": "Written by a mom of two",
     "title": "I've had the 40-minute naps and the 2 a.m. wake-ups too.",
     "text": "These are the tips that worked for my two, put in order so you don't have to guess. "
             "Safe sleep is built into every page: baby on their back, a firm flat surface, nothing loose in the crib.",
     "bullets": "No cry-it-out, ever\nFoundations first, methods second\nA whole chapter on your own calm",
     "image_right": False, "dark": False},
    {"type": "pay", "title": "Tonight could be the first calm bedtime",
     "text": "Full guide · wake window and sleep tables · printable sleep log",
     "price_usd": "$27", "old_usd": "$47", "price_eur": "€25", "old_eur": "€45",
     "label_usd": "Pay in USD", "label_eur": "Pay in EUR",
     "widget_usd": "https://widget.lava.top/456d50cb-0755-46c5-b894-11750cccc7f4",
     "widget_eur": "https://widget.lava.top/a2142d47-8dda-4d5a-b199-10c91b1d7dfe",
     "widget_width": 250, "widget_height": 80, "note": "Instant download after payment"},
    {"type": "faq", "title": "Questions",
     "items": "Will my baby have to cry it out? | No. Every method keeps you close while your baby learns.\n"
              "We co-sleep. Is this still for us? | Yes. There is a chapter on co-sleeping and room-sharing, with expert safety advice.\n"
              "How fast will it work? | Start the basics tonight. Gentle methods often take a few weeks, and every baby is different.\n"
              "How do I get it? | A download link arrives right after payment. Read it on your phone or print it."},
    {"type": "instagram", "title": "More free tips every week",
     "text": "Carousels, reels and answers to your questions. Come say hi.", "button_text": "Follow on Instagram"},
]

SUPPORT_BLOCKS = [
    {"type": "hero", "image": "/static/img/mom-baby.jpg", "image_style": "circle",
     "kicker": "Support a new mom blogger",
     "title": "Did a tip of mine buy you a *quieter night?*",
     "text": "I'm a mom of two little angels and just starting out as a blogger. If you like my content, "
             "my tips or the guide, you can say thanks here. Every donation helps me keep Hush & Hold going "
             "and the free tips coming.",
     "button_text": "", "button_link": "#buy", "show_old_price": False},
    {"type": "pay", "title": "Send a little thank-you", "text": "Any amount means a lot to me.",
     "price_usd": "", "old_usd": "", "price_eur": "", "old_eur": "",
     "label_usd": "Donate in USD", "label_eur": "Donate in EUR",
     "widget_usd": "", "widget_eur": "", "widget_width": 250, "widget_height": 80,
     "note": "Secure payment through lava.top"},
    {"type": "cards", "kicker": "", "title": "Where your support goes", "text": "",
     "items": "More free posts | Weekly carousels and reels for tired parents.\n"
              "Safe, checked tips | Every tip checked against safe sleep guidance.\n"
              "Time for your DMs | More time to answer your questions.",
     "numbered": False, "columns": 3, "dark": True},
    {"type": "instagram", "title": "Follow along on Instagram",
     "text": "New sleep tips every week, and the easiest way to say hi.", "button_text": "Follow"},
    {"type": "quote", "text": "Thank you. Sleep well tonight.", "dark": True},
]

SEED_PAGES = [
    {"slug": "guide", "title": "Sleep Tight, Little One", "nav_label": "The guide",
     "description": "A gentle step-by-step guide to help babies 0-3 fall asleep on their own. No cry-it-out.",
     "is_home": 1, "priority": 1, "blocks": GUIDE_BLOCKS},
    {"slug": "support", "title": "Support Hush & Hold", "nav_label": "Support me",
     "description": "Support a new mom blogger and the free sleep tips on Hush & Hold.",
     "is_home": 0, "priority": 2, "blocks": SUPPORT_BLOCKS},
]
