"""Hush & Hold website: public pages built from blocks + admin panel at /studio."""
import hmac
import os
import re
import secrets
import time
import uuid
from functools import wraps

from flask import (Flask, abort, flash, redirect, render_template, request, send_from_directory, session,
                   url_for)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename

import blocks as B
import db
from themes import FONTS, FONT_KEYS, PRESETS, THEME_KEYS, google_fonts_url, preset

BASE = os.path.dirname(os.path.abspath(__file__))
UPLOADS = os.environ.get("SITE_UPLOADS", os.path.join(BASE, "data", "uploads"))
ADMIN_PASSWORD = os.environ.get("SITE_ADMIN_PASSWORD", "")
ADMIN_PREFIX = "/studio"
IMG_EXT = {"jpg", "jpeg", "png", "webp", "gif", "svg"}
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}$")
RESERVED = {"studio", "static", "uploads", "admin", "webhook", "auth", "privacy", "data-deletion", "healthz"}

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.secret_key = os.environ.get("SITE_SECRET_KEY") or secrets.token_hex(32)
app.config.update(MAX_CONTENT_LENGTH=10 * 1024 * 1024, SESSION_COOKIE_HTTPONLY=True,
                  SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=os.environ.get("SITE_COOKIE_SECURE", "1") == "1",
                  SESSION_COOKIE_NAME="hush_site")
os.makedirs(UPLOADS, exist_ok=True)
db.init()

app.jinja_env.filters["inline"] = B.inline
app.jinja_env.filters["rich"] = B.rich
app.jinja_env.globals.update(split_items=B.split_items, lines=B.lines, choices=B.choices)


CSP_COMMON = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
              "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
              "frame-src https://widget.lava.top; object-src 'none'; base-uri 'self'; form-action 'self'; "
              "upgrade-insecure-requests; ")


@app.after_request
def security_headers(resp):
    h = resp.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    h.setdefault("Permissions-Policy",
                 'camera=(), microphone=(), geolocation=(), usb=(), payment=(self "https://widget.lava.top")')
    if request.is_secure:
        h.setdefault("Strict-Transport-Security", "max-age=31536000")
    if request.path.startswith(ADMIN_PREFIX):
        h["X-Frame-Options"] = "DENY"
        h["Cache-Control"] = "no-store"
        h.setdefault("Content-Security-Policy", CSP_COMMON + "frame-ancestors 'none'")
    else:
        h.setdefault("X-Frame-Options", "SAMEORIGIN")
        h.setdefault("Content-Security-Policy", CSP_COMMON + "frame-ancestors 'self'")
    return resp


def needs_currency(page):
    return any(b.get("type") == "pay" and not b.get("single_widget") for b in page["blocks"])


def page_price(page):
    for b in page["blocks"]:
        if b.get("type") == "pay" and (b.get("price_usd") or b.get("price_eur")):
            return b
    return None


@app.context_processor
def inject():
    s = db.get_settings()
    return {"S": s, "T": s["theme"], "fonts_url": google_fonts_url(s["theme"]), "nav": db.nav_pages(),
            "ADMIN": ADMIN_PREFIX, "csrf": csrf_token()}


# ---------------- public ----------------
@app.get("/")
def home():
    page = db.home_page()
    if not page:
        abort(404)
    return render_template("page.html", page=page, price=page_price(page), is_home=True,
                           show_cur=needs_currency(page))


@app.get("/<slug>")
@app.get("/<slug>/")
def page(slug):
    p = db.get_page(slug=slug)
    if not p or (not p["published"] and not session.get("admin")):
        abort(404)
    if p["is_home"]:
        return redirect(url_for("home"), 301)
    return render_template("page.html", page=p, price=page_price(p), is_home=False,
                           show_cur=needs_currency(p))


@app.get("/uploads/<path:name>")
def uploads(name):
    resp = send_from_directory(UPLOADS, name, max_age=7 * 86400)
    if name.lower().endswith(".svg"):
        resp.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'"
    return resp


@app.get("/site-health")
def health():
    return "ok"


@app.errorhandler(404)
def not_found(_):
    return render_template("404.html"), 404


# ---------------- admin helpers ----------------
def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


def login_required(fn):
    @wraps(fn)
    def wrap(*a, **kw):
        if not session.get("admin"):
            return redirect(url_for("login", next=request.path))
        if request.method == "POST" and not hmac.compare_digest(request.form.get("csrf", ""), session.get("csrf", "")):
            abort(400, "Форма устарела, обнови страницу.")
        return fn(*a, **kw)
    return wrap


def upload_list():
    files = []
    for n in sorted(os.listdir(UPLOADS), key=lambda x: -os.path.getmtime(os.path.join(UPLOADS, x))):
        if n.rsplit(".", 1)[-1].lower() in IMG_EXT:
            files.append("/uploads/" + n)
    return files + ["/static/img/guide-cover.jpg", "/static/img/mom-baby.jpg", "/static/img/moon.svg"]


# ---------------- admin ----------------
@app.route(ADMIN_PREFIX + "/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if ADMIN_PASSWORD and hmac.compare_digest(request.form.get("password", ""), ADMIN_PASSWORD):
            session.clear()
            session["admin"] = True
            session.permanent = True
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith(ADMIN_PREFIX) else url_for("admin_pages"))
        time.sleep(1.5)
        flash("Неверный пароль")
    return render_template("admin/login.html", no_password=not ADMIN_PASSWORD)


@app.get(ADMIN_PREFIX + "/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get(ADMIN_PREFIX)
@app.get(ADMIN_PREFIX + "/")
@login_required
def admin_pages():
    return render_template("admin/pages.html", pages=db.list_pages())


@app.post(ADMIN_PREFIX + "/pages/order")
@login_required
def admin_pages_order():
    order = []
    for p in db.list_pages():
        try:
            order.append((p["id"], int(request.form.get(f"priority_{p['id']}", p["priority"]))))
        except ValueError:
            pass
    db.set_priorities(order)
    home_id = request.form.get("home")
    if home_id and home_id.isdigit():
        db.set_home(int(home_id))
    flash("Порядок и главная страница сохранены")
    return redirect(url_for("admin_pages"))


@app.post(ADMIN_PREFIX + "/pages/new")
@login_required
def admin_page_new():
    title = (request.form.get("title") or "New page").strip()[:120]
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50] or "page"
    slug, n = base, 2
    while db.get_page(slug=slug) or slug in RESERVED:
        slug, n = f"{base}-{n}", n + 1
    template = request.form.get("template", "blank")
    if template == "copy" and request.form.get("copy_from", "").isdigit():
        src = db.get_page(int(request.form["copy_from"]))
        blocks = src["blocks"] if src else []
    else:
        blocks = [dict(B.new_block("hero"), title=title, image_style="none", button_text=""),
                  B.new_block("text")]
    pages = db.list_pages()
    pid = db.save_page({"slug": slug, "title": title, "nav_label": title, "description": "", "is_home": False,
                        "priority": max([p["priority"] for p in pages] + [0]) + 1, "show_in_nav": True,
                        "published": False, "blocks": blocks})
    flash("Страница создана. Она пока скрыта: отметь «Опубликована», когда будет готова.")
    return redirect(url_for("admin_page_edit", page_id=pid))


@app.route(ADMIN_PREFIX + "/pages/<int:page_id>", methods=["GET", "POST"])
@login_required
def admin_page_edit(page_id):
    p = db.get_page(page_id)
    if not p:
        abort(404)
    if request.method == "POST":
        f = request.form
        errors = []
        count = int(f.get("block_count", 0))
        new_blocks = []
        for i in range(count):
            bt = f.get(f"b{i}_type")
            if bt not in B.BLOCK_TYPES:
                continue
            blk = B.read_block(f, i, bt)
            if bt == "pay":
                for k in ("widget_usd", "widget_eur"):
                    w = B.clean_widget(blk[k])
                    if w is None:
                        errors.append(f"Блок {i + 1}: виджет должен быть ссылкой https://widget.lava.top/... "
                                      "или кодом iframe из lava.top")
                        w = p["blocks"][i].get(k, "") if i < len(p["blocks"]) else ""
                    blk[k] = w
            new_blocks.append(blk)
        action = f.get("action", "save")
        m = re.match(r"^(up|down|del|dup):(\d+)$", action)
        if m:
            op, i = m.group(1), int(m.group(2))
            if 0 <= i < len(new_blocks):
                if op == "up" and i > 0:
                    new_blocks[i - 1], new_blocks[i] = new_blocks[i], new_blocks[i - 1]
                elif op == "down" and i < len(new_blocks) - 1:
                    new_blocks[i + 1], new_blocks[i] = new_blocks[i], new_blocks[i + 1]
                elif op == "del":
                    new_blocks.pop(i)
                elif op == "dup":
                    new_blocks.insert(i + 1, dict(new_blocks[i]))
        elif action.startswith("add:") and action[4:] in B.BLOCK_TYPES:
            new_blocks.append(B.new_block(action[4:]))

        slug = (f.get("slug") or "").strip().lower()
        if not SLUG_RE.match(slug) or slug in RESERVED:
            errors.append("Адрес страницы: только латиница, цифры и дефис, например about-me")
            slug = p["slug"]
        other = db.get_page(slug=slug)
        if other and other["id"] != p["id"]:
            errors.append("Такой адрес уже занят другой страницей")
            slug = p["slug"]
        try:
            priority = int(f.get("priority") or p["priority"])
        except ValueError:
            priority = p["priority"]
        p.update(slug=slug, title=(f.get("title") or p["title"]).strip()[:160],
                 nav_label=(f.get("nav_label") or "").strip()[:60], description=(f.get("description") or "").strip()[:300],
                 priority=priority, show_in_nav=f.get("show_in_nav") == "on",
                 published=f.get("published") == "on" or bool(p["is_home"]), blocks=new_blocks)
        if f.get("is_home") == "on":
            p["is_home"] = True
            p["published"] = True
        db.save_page(p)
        for e in errors:
            flash(e, "error")
        if not errors and action == "save":
            flash("Сохранено")
        anchor = ""
        if m:
            anchor = "#block-" + str(max(0, min(len(new_blocks) - 1, int(m.group(2)) - (1 if m.group(1) == "up" else 0))))
        elif action.startswith("add:"):
            anchor = "#block-" + str(len(new_blocks) - 1)
        return redirect(url_for("admin_page_edit", page_id=page_id) + anchor)
    return render_template("admin/page_edit.html", p=p, types=B.BLOCK_TYPES, images=upload_list())


@app.post(ADMIN_PREFIX + "/pages/<int:page_id>/delete")
@login_required
def admin_page_delete(page_id):
    p = db.get_page(page_id)
    if p and p["is_home"]:
        flash("Главную страницу удалить нельзя. Сначала сделай главной другую.", "error")
    else:
        db.delete_page(page_id)
        flash("Страница удалена")
    return redirect(url_for("admin_pages"))


@app.route(ADMIN_PREFIX + "/style", methods=["GET", "POST"])
@login_required
def admin_style():
    s = db.get_settings()
    if request.method == "POST":
        f = request.form
        if f.get("action", "").startswith("preset:"):
            name = f["action"][7:]
            if name in PRESETS:
                db.set_settings({"theme": preset(name)})
                flash("Стиль «" + PRESETS[name]["label"] + "» применён")
            return redirect(url_for("admin_style"))
        theme = dict(s["theme"])
        for key, _ in THEME_KEYS:
            v = (f.get(key) or "").strip()
            if re.match(r"^#[0-9a-fA-F]{6}$", v):
                theme[key] = v
        for key, _ in FONT_KEYS:
            if f.get(key) in FONTS:
                theme[key] = f.get(key)
        theme["stars"] = f.get("stars") == "on"
        theme["dark"] = f.get("dark") == "on"
        try:
            theme["radius"] = max(0, min(40, int(f.get("radius") or 22)))
        except ValueError:
            pass
        db.set_settings({"theme": theme})
        flash("Стиль сохранён")
        return redirect(url_for("admin_style"))
    return render_template("admin/style.html", theme=s["theme"], keys=THEME_KEYS, font_keys=FONT_KEYS,
                           fonts=FONTS, presets=PRESETS)


@app.route(ADMIN_PREFIX + "/settings", methods=["GET", "POST"])
@login_required
def admin_settings():
    if request.method == "POST":
        f = request.form
        ig = (f.get("instagram_url") or "").strip()
        if ig and not ig.startswith("https://"):
            ig = "https://" + ig.lstrip("/")
        db.set_settings({
            "brand_name": (f.get("brand_name") or "Hush & Hold").strip()[:60],
            "instagram_url": ig,
            "instagram_handle": (f.get("instagram_handle") or "").strip()[:40],
            "default_currency": "EUR" if f.get("default_currency") == "EUR" else "USD",
            "footer_text": (f.get("footer_text") or "").strip()[:1000],
        })
        flash("Настройки сохранены")
        return redirect(url_for("admin_settings"))
    return render_template("admin/settings.html")


@app.route(ADMIN_PREFIX + "/files", methods=["GET", "POST"])
@login_required
def admin_files():
    if request.method == "POST":
        if request.form.get("delete"):
            name = secure_filename(request.form["delete"].rsplit("/", 1)[-1])
            path = os.path.join(UPLOADS, name)
            if name and os.path.isfile(path):
                os.remove(path)
                flash("Файл удалён")
            return redirect(url_for("admin_files"))
        for file in request.files.getlist("files"):
            ext = (file.filename or "").rsplit(".", 1)[-1].lower()
            if ext not in IMG_EXT:
                flash(f"{file.filename}: можно только картинки ({', '.join(sorted(IMG_EXT))})", "error")
                continue
            stem = secure_filename(file.filename.rsplit(".", 1)[0])[:40] or "image"
            name = f"{stem}-{uuid.uuid4().hex[:6]}.{ext}"
            file.save(os.path.join(UPLOADS, name))
            flash(f"Загружено: /uploads/{name}")
        return redirect(url_for("admin_files"))
    return render_template("admin/files.html", files=upload_list())


if __name__ == "__main__":
    app.run(debug=True, port=8010)
