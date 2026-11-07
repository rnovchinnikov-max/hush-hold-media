"""Web part: Meta webhook endpoint, control panel, privacy/data-deletion pages.

Run locally:  python app.py   (http://127.0.0.1:8000)
On server:    gunicorn -w 1 --threads 8 -b 127.0.0.1:8000 app:app   (see install.sh)
Keep ONE worker: the background queue lives inside the process.
"""
import hmac
import json
import logging
import secrets
import time
from functools import wraps

from flask import (Flask, abort, flash, redirect, render_template, request, session, url_for)

import core

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
app = Flask(__name__)
app.secret_key = core.CFG.get("SECRET_KEY") or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=core.CFG.get("HTTPS", "true") == "true",
                  PERMANENT_SESSION_LIFETIME=30 * 86400)
app.jinja_env.filters["t"] = core.fmt_time
core.start_background()

BRAND = core.CFG.get("BRAND_NAME", "Hush&hold")
CONTACT = core.CFG.get("CONTACT_EMAIL", "")


@app.context_processor
def inject():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return {"brand": BRAND, "contact": CONTACT, "csrf": session["csrf"]}


# ---------- webhook ----------

@app.get("/webhook")
def webhook_verify():
    if (request.args.get("hub.mode") == "subscribe"
            and hmac.compare_digest(request.args.get("hub.verify_token", ""), core.CFG.get("VERIFY_TOKEN", "-"))):
        return request.args.get("hub.challenge", ""), 200
    return "forbidden", 403


@app.post("/webhook")
def webhook_receive():
    raw = request.get_data()
    if not core.verify_signature(raw, request.headers.get("X-Hub-Signature-256")):
        core.add_event("webhook", "bad_signature", detail=raw[:300].decode("utf-8", "replace"))
        return "bad signature", 403
    core.kv_set("last_webhook_at", time.time())
    try:
        payload = json.loads(raw)
    except ValueError:
        return "bad json", 400
    core.JOBS.put(payload)  # answer Meta fast, work in the background
    return "ok", 200


# ---------- public pages (needed for Meta app settings / review) ----------

@app.get("/")
def home():
    return render_template("public.html", page="home")


@app.get("/privacy")
def privacy():
    return render_template("public.html", page="privacy")


@app.get("/data-deletion")
def data_deletion():
    return render_template("public.html", page="deletion")


@app.get("/healthz")
def healthz():
    return {"ok": True, "queue": core.JOBS.qsize()}


# ---------- control panel ----------

def login_required(f):
    @wraps(f)
    def wrap(*a, **kw):
        if not session.get("auth"):
            return redirect(url_for("login", next=request.path))
        if request.method == "POST" and request.form.get("csrf") != session.get("csrf"):
            abort(400)
        return f(*a, **kw)
    return wrap


_fails = {}


@app.route("/admin/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        ip = request.headers.get("X-Real-IP", request.remote_addr)
        n, first = _fails.get(ip, (0, time.time()))
        if n >= 10 and time.time() - first < 900:
            flash("Слишком много попыток, подожди 15 минут.")
            return render_template("login.html"), 429
        pw = core.CFG.get("ADMIN_PASSWORD", "")
        if pw and hmac.compare_digest(request.form.get("password", ""), pw):
            session.clear()
            session.permanent = True
            session["auth"] = True
            _fails.pop(ip, None)
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/admin") else url_for("dashboard"))
        _fails[ip] = (n + 1, first if n else time.time())
        flash("Неверный пароль.")
    return render_template("login.html")


@app.get("/admin/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/admin")
@login_required
def dashboard():
    now = time.time()
    account, account_err = None, None
    if core.token():
        try:
            account = core.me()
        except Exception as e:
            account_err = str(e)
    exp = core.kv_get("token_expires_at")
    return render_template(
        "dashboard.html", account=account, account_err=account_err,
        today=core.stats(now - 86400), week=core.stats(now - 7 * 86400),
        events=core.recent_events(40), s=core.settings(),
        last_webhook=core.kv_get("last_webhook_at"), token_refreshed=core.kv_get("token_refreshed_at"),
        token_days_left=int((float(exp) - now) / 86400) if exp else None,
        rules=core.get_rules(), conn=core.connection_info(),
        redirect_uri=redirect_uri())


@app.get("/admin/log")
@login_required
def log_page():
    return render_template("log.html", events=core.recent_events(500, request.args.get("kind") or None),
                           kind=request.args.get("kind", ""))


@app.route("/admin/rules/<int:rule_id>", methods=["GET", "POST"])
@app.route("/admin/rules/new", methods=["GET", "POST"])
@login_required
def rule_edit(rule_id=None):
    rule = core.get_rule(rule_id) if rule_id else dict(core.DEFAULT_RULE, name="New rule", keywords="", enabled=0)
    if rule_id and not rule:
        abort(404)
    if request.method == "POST":
        if request.form.get("delete") and rule_id:
            core.delete_rule(rule_id)
            flash("Правило удалено.")
            return redirect(url_for("dashboard"))
        data = {k: request.form.get(k, "").strip() for k in core.DEFAULT_RULE}
        data["enabled"] = 1 if request.form.get("enabled") else 0
        data["require_follow"] = 1 if request.form.get("require_follow") else 0
        if not data["keywords"]:
            flash("Укажи хотя бы одно ключевое слово.")
            return render_template("rule.html", rule=data, rule_id=rule_id, media=[])
        new_id = core.save_rule(data, rule_id)
        flash("Сохранено.")
        return redirect(url_for("rule_edit", rule_id=new_id))
    media = []
    try:
        media = core.media_list(30) if core.token() else []
    except Exception as e:
        flash(f"Не удалось загрузить посты: {e}")
    return render_template("rule.html", rule=rule, rule_id=rule_id, media=media)


def redirect_uri():
    return f"https://{core.CFG.get('DOMAIN') or request.host}/auth/callback"


@app.post("/admin/meta-app")
@login_required
def save_meta_app():
    if request.form.get("page_id_manual") is not None:
        core.kv_set("page_id_manual", request.form.get("page_id_manual", "").strip())
    if request.form.get("ig_id_manual") is not None:
        core.kv_set("ig_id_manual", request.form.get("ig_id_manual", "").strip())
    for k in ("app_id", "app_secret", "config_id"):
        v = request.form.get(k, "").strip()
        if v:
            core.kv_set("meta_" + k, v)
    flash("Данные приложения Meta сохранены.")
    return redirect(url_for("dashboard"))


@app.get("/admin/connect")
@login_required
def connect():
    if not (core.meta("app_id") and core.meta("app_secret") and core.meta("config_id")):
        flash("Сначала заполни App ID, App Secret и Configuration ID.")
        return redirect(url_for("dashboard"))
    session["oauth_state"] = secrets.token_urlsafe(16)
    return redirect(core.login_url(redirect_uri(), session["oauth_state"]))


@app.get("/auth/callback")
def oauth_callback():
    if not session.get("auth"):
        return redirect(url_for("login"))
    if request.args.get("error") or not request.args.get("code"):
        flash("Вход отменён: " + (request.args.get("error_description") or request.args.get("error") or "нет кода"))
        return redirect(url_for("dashboard"))
    if not hmac.compare_digest(request.args.get("state", ""), session.pop("oauth_state", "-")):
        abort(400)
    try:
        acc = core.connect_with_code(request.args["code"], redirect_uri())
        core.me(force=True)
        msg = f"Подключено: @{acc.get('username')}."
        try:
            core.subscribe_webhooks()
            msg += " Вебхуки подписаны."
        except Exception as e:
            msg += f" Вебхуки подписать не удалось: {e}"
        flash(msg)
    except Exception as e:
        flash(f"Ошибка подключения: {e}")
    return redirect(url_for("dashboard"))


@app.post("/admin/settings")
@login_required
def save_settings():
    core.kv_set("paused", "1" if request.form.get("paused") else "0")
    core.kv_set("test_mode", "1" if request.form.get("test_mode") else "0")
    core.kv_set("polling", "1" if request.form.get("polling") else "0")
    core.kv_set("test_usernames", request.form.get("test_usernames", "").strip())
    try:
        core.kv_set("replies_per_hour", max(1, int(request.form.get("replies_per_hour", "150"))))
    except ValueError:
        pass
    flash("Настройки сохранены.")
    return redirect(url_for("dashboard"))


@app.post("/admin/token")
@login_required
def save_token():
    action = request.form.get("action")
    try:
        if action == "save":
            tok = request.form.get("token", "").strip()
            if not tok:
                raise core.ApiError("пустой токен")
            note = core.set_new_token(tok)
            acc = core.me(force=True)
            core.subscribe_webhooks()
            flash(f"Токен сохранён ({note}), аккаунт @{acc.get('username')}, вебхуки подписаны.")
        elif action == "refresh":
            if core.mode() == "facebook":
                flash("Токен Unified Login бессрочный, продлевать не нужно.")
            else:
                core.refresh_token()
                flash("Токен продлён на 60 дней.")
        elif action == "subscribe":
            if core.mode() == "facebook":
                notes = []
                core.find_page(core.token(), core.kv_get("ig_id", ""), notes)
                flash("Страница Facebook: " + " | ".join(notes)[-200:])
            core.subscribe_webhooks()
            core.me(force=True)
            flash("Аккаунт подписан на вебхуки (comments, messages, messaging_postbacks).")
    except Exception as e:
        flash(f"Ошибка: {e}")
    return redirect(url_for("dashboard"))


@app.get("/admin/debug")
@login_required
def debug_page():
    from markupsafe import escape
    def clean(x):  # drop paging links: Meta puts the access token inside them
        if isinstance(x, dict):
            return {k: clean(v) for k, v in x.items() if k != "paging"}
        if isinstance(x, list):
            return [clean(v) for v in x]
        if isinstance(x, str) and "access_token=" in x:
            return "[скрыто]"
        return x
    body = json.dumps(clean(core.debug_dump()), ensure_ascii=False, indent=1)
    return f"<pre style='white-space:pre-wrap;font-size:12px'>{escape(body)}</pre>"


@app.post("/admin/catch-up")
@login_required
def catch_up():
    hours = max(1, min(168, int(request.form.get("hours", "24") or 24)))
    try:
        core.reopen_skipped(time.time() - hours * 3600)
        n = core.poll_comments(time.time() - hours * 3600)
        try:
            d = core.poll_messages(time.time() - hours * 3600)
        except Exception as e:
            d = f"ошибка ({e})"
        flash(f"За {hours} ч проверено комментариев: {n}, сообщений в директе: {d}. Подходящие обработаны, смотри журнал.")
    except Exception as e:
        flash(f"Ошибка: {e}")
    return redirect(url_for("dashboard"))


@app.post("/admin/test-dm")
@login_required
def test_dm():
    """Simulate a comment through the whole pipeline without Instagram (test mode forced)."""
    text = request.form.get("text", "sleep")
    was = core.kv_get("test_mode", "0")
    core.kv_set("test_mode", "1")
    try:
        core.handle_comment({"id": f"sim-{time.time()}", "text": text,
                             "from": {"id": f"sim-user-{int(time.time())}", "username": "simulated_user"},
                             "media": {"id": "sim-media"}}, own_id="")
    finally:
        core.kv_set("test_mode", was)
    flash("Симуляция выполнена, смотри журнал ниже (статус dry_run).")
    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    app.config["SESSION_COOKIE_SECURE"] = False
    app.run(host="127.0.0.1", port=8000, debug=False)
