"""Hush&hold auto-replies: storage, Instagram API client and comment/DM logic.

Two connection modes:
- "facebook": Instagram API with Unified Login (graph.facebook.com, never-expiring system user
  token from the Facebook Login for Business dialog). The only option for apps created after ~Oct 2026.
- "instagram": Instagram API with Instagram Login (graph.instagram.com, 60-day token).
Flow per rule: comment with keyword -> public reply under the comment ->
private reply in DM. If the rule requires a follow, the DM carries a button;
when the person taps it we check is_user_follow_business and send the reward
(promo code + link) or ask them to follow first.
"""
import datetime as dt
import hashlib
import hmac
import json
import logging
import os
import queue
import random
import re
import sqlite3
import threading
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
log = logging.getLogger("autoreply")


# ---------- config ----------

KNOWN_KEYS = {"DOMAIN", "ADMIN_PASSWORD", "SECRET_KEY", "VERIFY_TOKEN", "GRAPH_VERSION", "TIMEZONE",
              "BRAND_NAME", "CONTACT_EMAIL", "DB_PATH", "HTTPS"}


def load_env(path=os.path.join(HERE, "config.env")):
    cfg = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip().strip('"')
    for k, v in os.environ.items():
        if k in cfg or k in KNOWN_KEYS or k.startswith(("IG_", "META_")):
            cfg[k] = v
    return cfg


CFG = load_env()
IG_GRAPH = "https://graph.instagram.com/" + CFG.get("GRAPH_VERSION", "v23.0")
FB_VERSION = CFG.get("FB_GRAPH_VERSION", "v25.0")
FB_GRAPH = "https://graph.facebook.com/" + FB_VERSION
DB_PATH = CFG.get("DB_PATH") or os.path.join(HERE, "data.db")


# ---------- storage ----------

SCHEMA = """
create table if not exists kv(k text primary key, v text);
create table if not exists rules(
  id integer primary key autoincrement,
  name text, enabled integer default 1,
  keywords text, match_mode text default 'word',
  media_ids text default '',
  public_replies text, dm_text text,
  require_follow integer default 1, button_title text,
  reward_text text, not_following_text text, recheck_title text);
create table if not exists events(
  id integer primary key autoincrement, at real, kind text, rule_id integer,
  user_id text, username text, media_id text, comment_id text, text text,
  status text, detail text);
create index if not exists events_at on events(at);
create table if not exists handled(key text primary key, at real);
"""

DEFAULT_RULE = dict(
    name="SLEEP → promo code",
    enabled=1,
    keywords="sleep",
    match_mode="word",
    media_ids="",
    public_replies="\n".join([
        "Just sent it to your DMs! 🌙",
        "Check your messages, it's there 💛",
        "Sent! Look in your DMs (or message requests) ✨",
        "Done, check your inbox 🌙",
    ]),
    dm_text=("Hi! So glad you're here 💛 Your personal discount for the gentle sleep guide "
             "(babies 0–3, no cry-it-out) is ready. Tap the button below to get your code 👇"),
    require_follow=1,
    button_title="Get my code 💛",
    reward_text=("Here it is! 🌙 Promo code: MOMSHELP\n"
                 "It's a limited-time personal discount, so don't wait too long.\n"
                 "👉 https://app.lava.top/products/0657f576-a3d7-406f-a6d2-c390e7bf918b\n"
                 "Questions? Just reply here 💛"),
    not_following_text=("The discount is just for my followers 💛 Follow @hush_hold, "
                        "then tap the button below and I'll send your code right away."),
    recheck_title="I followed ✅",
)


def db():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = db()
    con.executescript(SCHEMA)
    if not con.execute("select 1 from rules limit 1").fetchone():
        cols = ",".join(DEFAULT_RULE)
        con.execute(f"insert into rules({cols}) values({','.join('?' * len(DEFAULT_RULE))})",
                    list(DEFAULT_RULE.values()))
    con.commit()
    con.close()
    if not kv_get("token") and CFG.get("IG_ACCESS_TOKEN"):
        kv_set("token", CFG["IG_ACCESS_TOKEN"])
        kv_set("token_refreshed_at", time.time())


def kv_get(k, default=None):
    con = db()
    row = con.execute("select v from kv where k=?", (k,)).fetchone()
    con.close()
    return row[0] if row else default


def kv_set(k, v):
    con = db()
    con.execute("insert or replace into kv(k, v) values(?, ?)", (k, str(v)))
    con.commit()
    con.close()


def add_event(kind, status, rule_id=None, user_id="", username="", media_id="",
              comment_id="", text="", detail=""):
    con = db()
    con.execute("insert into events(at, kind, rule_id, user_id, username, media_id, comment_id,"
                " text, status, detail) values(?,?,?,?,?,?,?,?,?,?)",
                (time.time(), kind, rule_id, user_id, username, media_id, comment_id,
                 (text or "")[:500], status, str(detail)[:1000]))
    con.commit()
    con.close()


def first_time(key):
    """True the first time a key is seen (dedupe webhooks that Meta retries)."""
    con = db()
    try:
        con.execute("insert into handled(key, at) values(?, ?)", (key, time.time()))
        con.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        con.close()


def get_rules(enabled_only=False):
    con = db()
    sql = "select * from rules" + (" where enabled=1" if enabled_only else "") + " order by id"
    rows = [dict(r) for r in con.execute(sql)]
    con.close()
    return rows


def get_rule(rule_id):
    con = db()
    row = con.execute("select * from rules where id=?", (rule_id,)).fetchone()
    con.close()
    return dict(row) if row else None


def save_rule(data, rule_id=None):
    fields = [k for k in DEFAULT_RULE if k in data]
    con = db()
    if rule_id:
        con.execute(f"update rules set {','.join(f + '=?' for f in fields)} where id=?",
                    [data[f] for f in fields] + [rule_id])
    else:
        cur = con.execute(f"insert into rules({','.join(fields)}) values({','.join('?' * len(fields))})",
                          [data[f] for f in fields])
        rule_id = cur.lastrowid
    con.commit()
    con.close()
    return rule_id


def delete_rule(rule_id):
    con = db()
    con.execute("delete from rules where id=?", (rule_id,))
    con.commit()
    con.close()


def recent_events(limit=100, kind=None):
    con = db()
    if kind:
        rows = con.execute("select * from events where kind=? order by id desc limit ?", (kind, limit))
    else:
        rows = con.execute("select * from events order by id desc limit ?", (limit,))
    out = [dict(r) for r in rows]
    con.close()
    return out


def stats(since):
    con = db()
    rows = con.execute("select kind, status, count(*) n from events where at>=? group by kind, status",
                       (since,)).fetchall()
    con.close()
    return {f"{r['kind']}:{r['status']}": r["n"] for r in rows}


def settings():
    return {
        "paused": kv_get("paused", "0") == "1",
        "test_mode": kv_get("test_mode", "0") == "1",
        "test_usernames": kv_get("test_usernames", ""),
        "replies_per_hour": int(kv_get("replies_per_hour", "150")),
        "polling": kv_get("polling", "1") == "1",
        "last_poll_at": kv_get("last_poll_at"),
        "last_poll_error": (kv_get("last_poll_error", "") + " " + (("директ: " + kv_get("last_dm_poll_error", "")) if kv_get("last_dm_poll_error") else "")).strip(),
    }


# ---------- Instagram API ----------

class ApiError(Exception):
    pass


def token():
    return kv_get("token", "")


def mode():
    return kv_get("api_mode", "instagram")


def meta(k):
    """Meta app settings: saved in the panel (kv) or in config.env (META_APP_ID, META_APP_SECRET, META_CONFIG_ID)."""
    return kv_get("meta_" + k) or CFG.get("META_" + k.upper(), "")


def acct():
    """Path segment for the own account: 'me' with Instagram Login, the IG account id with Unified Login."""
    return "me" if mode() == "instagram" else kv_get("ig_id", "")


def api(method, path, params=None, body=None, tok=None, base=None):
    params = dict(params or {})
    params["access_token"] = tok or token()
    base = base or (IG_GRAPH if mode() == "instagram" else FB_GRAPH)
    r = requests.request(method, f"{base}/{path}", params=params, json=body, timeout=30)
    try:
        data = r.json()
    except ValueError:
        raise ApiError(f"HTTP {r.status_code}: {r.text[:200]}")
    if isinstance(data, dict) and "error" in data:
        e = data["error"]
        raise ApiError(f"{e.get('message')} (code {e.get('code')}/{e.get('error_subcode', '-')})")
    return data


def me(force=False):
    """Own account: user_id (the id webhooks use) and username. Cached."""
    cached = kv_get("me")
    if cached and not force:
        return json.loads(cached)
    if mode() == "instagram":
        data = api("GET", "me", {"fields": "user_id,username,name,followers_count,profile_picture_url"})
    else:
        if not kv_get("ig_id"):
            raise ApiError("не найден ID аккаунта Instagram, подключи заново")
        data = api("GET", kv_get("ig_id"), {"fields": "id,username,name,followers_count,profile_picture_url"})
        data["user_id"] = data.get("id")
    kv_set("me", json.dumps(data))
    return data


FIELDS = "comments,messages,messaging_postbacks"


def subscribe_webhooks():
    out = api("POST", f"{acct()}/subscribed_apps", {"subscribed_fields": FIELDS})
    pid, ptok = page()
    if pid:  # Page-level subscription carries Instagram messaging webhooks on the classic route
        try:
            api("POST", f"{pid}/subscribed_apps", {"subscribed_fields": "messages,messaging_postbacks"}, tok=ptok)
        except ApiError as e:
            add_event("webhook", "page_subscribe_error", detail=e)
    if mode() == "facebook" and meta("app_id") and meta("app_secret") and CFG.get("DOMAIN"):
        # app-level subscription: same as filling "Configure webhooks" in the dashboard by hand
        api("POST", f"{meta('app_id')}/subscriptions",
            {"object": "instagram", "callback_url": f"https://{CFG['DOMAIN']}/webhook",
             "verify_token": CFG.get("VERIFY_TOKEN", ""), "fields": FIELDS, "include_values": "true"},
            tok=f"{meta('app_id')}|{meta('app_secret')}", base=FB_GRAPH)
    return out


def login_url(redirect_uri, state):
    from urllib.parse import urlencode
    q = {"client_id": meta("app_id"), "config_id": meta("config_id"), "redirect_uri": redirect_uri,
         "response_type": "code", "override_default_response_type": "true", "state": state}
    return f"https://www.facebook.com/{FB_VERSION}/dialog/oauth?" + urlencode(q)


def connect_with_code(code, redirect_uri):
    """Unified Login: exchange the dialog code for a system user token, find the IG account, subscribe."""
    r = requests.get(f"{FB_GRAPH}/oauth/access_token",
                     params={"client_id": meta("app_id"), "client_secret": meta("app_secret"),
                             "redirect_uri": redirect_uri, "code": code}, timeout=30)
    data = r.json()
    if "access_token" not in data:
        raise ApiError(str(data.get("error", data))[:300])
    return use_fb_token(data["access_token"], data.get("expires_in"))


def _try(fn, notes, label):
    try:
        return fn()
    except Exception as e:
        notes.append(f"{label}: {e}")
        return None


def find_ig_accounts(tok, notes):
    """Find the Instagram account a Meta token can act for. Tries several routes, because which one
    works depends on the token type and the permissions Meta actually granted."""
    g = lambda path, params=None: api("GET", path, params or {}, tok=tok, base=FB_GRAPH)
    found = {}
    data = _try(lambda: g("me/assigned_instagram_accounts", {"fields": "id,username"}), notes, "assigned")
    for a in (data or {}).get("data", []):
        found[a["id"]] = a.get("username", "")
    if not found:
        data = _try(lambda: g("me/accounts", {"fields": "id,name,instagram_business_account{id,username}"}), notes, "pages")
        for p in (data or {}).get("data", []):
            a = p.get("instagram_business_account")
            if a:
                found[a["id"]] = a.get("username", "")
    if not found and meta("app_id") and meta("app_secret"):
        dbg = _try(lambda: api("GET", "debug_token", {"input_token": tok},
                               tok=f"{meta('app_id')}|{meta('app_secret')}", base=FB_GRAPH), notes, "debug")
        d = (dbg or {}).get("data", {})
        notes.append("type=%s scopes=%s" % (d.get("type"), ",".join(d.get("scopes", []))))
        for sc in d.get("granular_scopes", []):
            if sc.get("scope", "").startswith("instagram"):
                for tid in sc.get("target_ids", []):
                    found.setdefault(tid, "")
    manual = kv_get("ig_id_manual") or CFG.get("IG_USER_ID", "")
    if manual:
        found = {manual: found.get(manual, "")} | found
    out = []
    for ig_id, uname in found.items():
        info = _try(lambda: g(ig_id, {"fields": "id,username"}), notes, f"check {ig_id}")
        if info:
            out.append({"id": ig_id, "username": info.get("username", uname)})
    return out


def use_fb_token(tok, expires_in=None):
    notes = []
    accounts = find_ig_accounts(tok, notes)
    if not accounts:
        detail = " | ".join(notes)[:700]
        add_event("connect", "error", detail=detail)
        raise ApiError("токен получен, но аккаунт Instagram через него недоступен. Подробности в журнале "
                       "(событие connect): " + detail[:300])
    want = CFG.get("IG_USERNAME", "").lstrip("@").lower()
    acc = next((a for a in accounts if a.get("username", "").lower() == want), accounts[0])
    kv_set("api_mode", "facebook")
    kv_set("token", tok)
    kv_set("ig_id", acc["id"])
    kv_set("token_refreshed_at", time.time())
    kv_set("token_expires_at", time.time() + int(expires_in) if expires_in else "")
    find_page(tok, acc["id"], notes)
    add_event("connect", "ok", username=acc.get("username", ""), detail=" | ".join(notes)[:700])
    return acc


def find_page(tok, ig_id, notes):
    """Find the Facebook Page linked to the IG account and keep its Page token. Needed for the
    follower check (and DMs on the classic route). Tries the manual Page ID first, then /me/accounts."""
    kv_set("page_id", "")
    kv_set("page_token", "")
    g = lambda path, params: api("GET", path, params, tok=tok, base=FB_GRAPH)
    candidates = []
    manual = kv_get("page_id_manual", "")
    if manual:
        p = _try(lambda: g(manual, {"fields": "id,name,access_token,instagram_business_account"}), notes, "page manual")
        if p:
            candidates.append(p)
    data = _try(lambda: g("me/accounts", {"fields": "id,name,access_token,instagram_business_account"}), notes, "pages")
    candidates += (data or {}).get("data", [])
    with_token = [p for p in candidates if p.get("access_token")]
    notes.append("pages seen: " + ", ".join(f"{p.get('name')}({p.get('id')}, ig={(p.get('instagram_business_account') or {}).get('id', '-')}, token={'yes' if p.get('access_token') else 'no'})" for p in candidates))
    pick = next((p for p in with_token if (p.get("instagram_business_account") or {}).get("id") == ig_id), None)
    if not pick and len(with_token) == 1:
        pick = with_token[0]  # one Page only: assume it is the linked one
    if pick:
        kv_set("page_id", pick["id"])
        kv_set("page_token", pick["access_token"])
        notes.append(f"page {pick.get('name')} ({pick['id']}) linked")
        return pick
    notes.append("page not found")
    return None


def page():
    pid, ptok = kv_get("page_id", ""), kv_get("page_token", "")
    return (pid, ptok) if mode() == "facebook" and pid and ptok else (None, None)


def refresh_token():
    """Long-lived Instagram tokens live 60 days; refreshing gives another 60."""
    r = requests.get("https://graph.instagram.com/refresh_access_token",
                     params={"grant_type": "ig_refresh_token", "access_token": token()}, timeout=30)
    data = r.json()
    if "access_token" not in data:
        raise ApiError(str(data.get("error", data))[:300])
    kv_set("token", data["access_token"])
    kv_set("token_refreshed_at", time.time())
    kv_set("token_expires_at", time.time() + int(data.get("expires_in", 5184000)))
    return data


def connection_info():
    return {"mode": mode(), "app_id": meta("app_id"), "config_id": meta("config_id"),
            "has_secret": bool(meta("app_secret")), "ig_id": kv_get("ig_id", ""),
            "ig_id_manual": kv_get("ig_id_manual", ""),
            "page_id_manual": kv_get("page_id_manual", ""), "page_id": kv_get("page_id", "")}


def set_new_token(tok):
    """Store a pasted token. A short-lived one (1 hour, e.g. from an OAuth redirect) is exchanged
    for a long-lived 60-day token; a token from the dashboard "Generate token" is already long-lived."""
    tok = tok.strip()
    try:  # a Unified Login / system user (graph.facebook.com) token?
        acc = use_fb_token(tok)
        return f"бессрочный токен Meta, аккаунт @{acc.get('username')}"
    except Exception:
        if tok.startswith("EAA"):  # Facebook-type token: show the real reason instead of guessing further
            raise
    kv_set("api_mode", "instagram")
    note = "долгий токен (60 дней)"
    secret = CFG.get("IG_APP_SECRET")
    expires_in = 60 * 86400
    if secret:
        r = requests.get("https://graph.instagram.com/access_token",
                         params={"grant_type": "ig_exchange_token", "client_secret": secret,
                                 "access_token": tok}, timeout=30)
        data = r.json()
        if "access_token" in data:
            tok, expires_in = data["access_token"], int(data.get("expires_in", expires_in))
            note = "короткий токен обменян на долгий (60 дней)"
    kv_set("token", tok)
    kv_set("token_refreshed_at", time.time())
    kv_set("token_expires_at", time.time() + expires_in)
    return note


def reply_comment(comment_id, text):
    return api("POST", f"{comment_id}/replies", {"message": text})


def send_dm(recipient, message):
    """recipient: {"id": igsid} or {"comment_id": id} (private reply, once per comment, 7 days)."""
    body = {"recipient": recipient, "message": message}
    pid, ptok = page()
    routes = [lambda: api("POST", f"{acct()}/messages", body=body)]
    if pid:
        via_page = lambda: api("POST", f"{pid}/messages", body=body, tok=ptok)
        routes = routes + [via_page]  # the IG-account route is proven; the Page route is only a fallback
    err = None
    for r in routes:
        try:
            return r()
        except ApiError as e:
            err = e
    raise err


def user_profile(igsid):
    pid, ptok = page()
    return api("GET", igsid, {"fields": "username,name,is_user_follow_business,is_business_follow_user"},
               tok=ptok or None)


def media_list(limit=25):
    return api("GET", f"{acct()}/media", {"fields": "id,caption,media_type,media_product_type,permalink,timestamp,thumbnail_url,media_url",
                                   "limit": limit}).get("data", [])


# ---------- logic ----------

def verify_signature(raw_body, header):
    """Meta signs webhooks with HMAC-SHA256 of the raw body. For Instagram Login apps the key is the
    Instagram app secret; for Facebook Login apps it is the Meta app secret. Either is accepted."""
    if not header or not header.startswith("sha256="):
        return False
    sent = header.split("=", 1)[1]
    for secret in (CFG.get("IG_APP_SECRET"), meta("app_secret")):
        if secret:
            good = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
            if hmac.compare_digest(good, sent):
                return True
    return False


def norm(text):
    return (text or "").lower().strip()


def matches(rule, text):
    t = norm(text)
    for kw in [k.strip().lower() for k in (rule["keywords"] or "").split(",") if k.strip()]:
        if rule.get("match_mode") == "contains":
            if kw in t:
                return True
        elif re.search(r"(?<![\w])" + re.escape(kw) + r"(?![\w])", t):
            return True
    return False


def media_ok(rule, media_id):
    ids = [x.strip() for x in (rule.get("media_ids") or "").replace("\n", ",").split(",") if x.strip()]
    return not ids or media_id in ids


def pick_reply(rule):
    lines = [x.strip() for x in (rule["public_replies"] or "").splitlines() if x.strip()]
    return random.choice(lines) if lines else ""


def button(title, rule_id):
    return [{"content_type": "text", "title": title[:20], "payload": f"RULE:{rule_id}"}]


def sent_last_hour():
    con = db()
    n = con.execute("select count(*) from events where kind='public_reply' and status='ok' and at>=?",
                    (time.time() - 3600,)).fetchone()[0]
    con.close()
    return n


def handle_comment(value, own_id):
    s = settings()
    frm = value.get("from") or {}
    user_id, username = frm.get("id", ""), frm.get("username", "")
    comment_id, text = value.get("id", ""), value.get("text", "")
    media_id = (value.get("media") or {}).get("id", "")
    if not comment_id or user_id == own_id or (own_id and username == me().get("username")):
        return
    if not first_time(f"comment:{comment_id}"):
        return
    rule = next((r for r in get_rules(True) if matches(r, text) and media_ok(r, media_id)), None)
    if not rule:
        add_event("comment", "no_match", None, user_id, username, media_id, comment_id, text)
        return
    ev = dict(rule_id=rule["id"], user_id=user_id, username=username, media_id=media_id,
              comment_id=comment_id, text=text)
    if s["paused"]:
        add_event("comment", "paused", **ev)
        return
    if s["test_usernames"]:
        allowed = [u.strip().lstrip("@").lower() for u in s["test_usernames"].split(",") if u.strip()]
        if username.lower() not in allowed:
            add_event("comment", "skipped_not_tester", **ev)
            return
    if not first_time(f"user_media_rule:{user_id}:{media_id}:{rule['id']}"):
        add_event("comment", "duplicate_user", **ev)
        return
    add_event("comment", "matched", **ev)
    dry = s["test_mode"]

    reply = pick_reply(rule)
    if reply:
        if sent_last_hour() >= s["replies_per_hour"]:
            add_event("public_reply", "rate_limited", **ev)
        elif dry:
            add_event("public_reply", "dry_run", detail=reply, **ev)
        else:
            try:
                reply_comment(comment_id, reply)
                add_event("public_reply", "ok", detail=reply, **ev)
            except Exception as e:
                add_event("public_reply", "error", detail=e, **ev)

    if rule["require_follow"]:
        msg = {"text": rule["dm_text"], "quick_replies": button(rule["button_title"] or "Get my code", rule["id"])}
    else:
        msg = {"text": rule["reward_text"]}
    if dry:
        add_event("dm", "dry_run", detail=json.dumps(msg, ensure_ascii=False), **ev)
        return
    try:
        send_dm({"comment_id": comment_id}, msg)
        add_event("dm", "ok", detail="private reply" + (" + button" if rule["require_follow"] else " (reward)"), **ev)
        if not rule["require_follow"]:
            add_event("reward", "ok", **ev)
    except ApiError as e:
        if "quick_replies" in msg:  # fall back to plain text if buttons are refused in private replies
            try:
                fallback = dict(text=rule["dm_text"] + "\n\nReply \"" + (rule["keywords"].split(",")[0].strip().upper()) +
                                "\" here to get your code.")
                send_dm({"comment_id": comment_id}, fallback)
                add_event("dm", "ok", detail=f"private reply, plain text fallback ({e})", **ev)
                return
            except Exception as e2:
                e = e2
        add_event("dm", "error", detail=e, **ev)


def deliver_reward(rule, igsid, username, source):
    ev = dict(rule_id=rule["id"], user_id=igsid, username=username)
    if settings()["test_mode"]:
        add_event("reward", "dry_run", detail=source, **ev)
        return
    following = True
    if rule["require_follow"]:
        try:
            prof = user_profile(igsid)
            username = prof.get("username", username)
            ev["username"] = username
            following = bool(prof.get("is_user_follow_business"))
        except Exception as e:
            add_event("follow_check", "error", detail=e, **ev)
            following = True  # do not punish the person for an API hiccup
    if following:
        con = db()
        recent = con.execute("select 1 from events where kind='reward' and status='ok' and user_id=? and rule_id=?"
                             " and at>=?", (igsid, rule["id"], time.time() - 600)).fetchone()
        con.close()
        if recent:  # double tap on the button: one code is enough
            add_event("reward", "duplicate_tap", detail=source, **ev)
            return
    try:
        if following:
            send_dm({"id": igsid}, {"text": rule["reward_text"]})
            add_event("reward", "ok", detail=source, **ev)
        else:
            con = db()
            n = con.execute("select count(*) from events where kind='reward' and status='not_following' and user_id=?"
                            " and rule_id=? and at>=?", (igsid, rule["id"], time.time() - 86400)).fetchone()[0]
            con.close()
            if n >= 3:  # no more than 3 "please follow" messages per person per day
                add_event("reward", "not_following_limit", detail=source, **ev)
                return
            send_dm({"id": igsid}, {"text": rule["not_following_text"],
                                    "quick_replies": button(rule["recheck_title"] or "I followed", rule["id"])})
            add_event("reward", "not_following", detail=source, **ev)
    except Exception as e:
        add_event("reward", "error", detail=e, **ev)


def handle_message(m, own_id):
    sender = (m.get("sender") or {}).get("id", "")
    if not sender or sender == own_id:
        return
    msg = m.get("message") or {}
    if msg.get("is_echo") or msg.get("is_deleted"):
        return
    mid = msg.get("mid") or (m.get("postback") or {}).get("mid") or f"{sender}:{m.get('timestamp')}"
    if not first_time(f"msg:{mid}"):
        return
    s = settings()
    payload = (msg.get("quick_reply") or {}).get("payload") or (m.get("postback") or {}).get("payload") or ""
    text = msg.get("text", "")
    if norm(text) == "delete":
        forget_user(sender)
        try:
            send_dm({"id": sender}, {"text": "Done 💛 We deleted everything we stored about you."})
        except Exception as e:
            log.warning("delete confirm failed: %s", e)
        return
    rule = None
    if payload.startswith("RULE:"):
        rule = get_rule(int(payload.split(":", 1)[1] or 0))
    elif text:
        # a button tap read back through the API arrives as plain text equal to the button title
        rule = next((r for r in get_rules(True)
                     if norm(text) in (norm(r["button_title"]), norm(r["recheck_title"]))), None)
        if rule:
            payload = f"RULE:{rule['id']}"
        else:
            rule = next((r for r in get_rules(True) if matches(r, text)), None)
    if not rule or not rule["enabled"]:
        add_event("message", "no_match", user_id=sender, text=text or payload)
        return
    if s["paused"]:
        add_event("message", "paused", rule_id=rule["id"], user_id=sender, text=text or payload)
        return
    add_event("message", "matched", rule_id=rule["id"], user_id=sender, text=text or payload)
    deliver_reward(rule, sender, "", "button" if payload else "dm keyword")


def forget_user(user_id):
    con = db()
    con.execute("delete from events where user_id=?", (user_id,))
    con.execute("delete from handled where key like ?", (f"user_media_rule:{user_id}:%",))
    con.commit()
    con.close()
    add_event("privacy", "deleted", detail="user data deleted on request")


def process(payload):
    try:
        own_id = str(me().get("user_id", ""))
    except Exception as e:
        own_id = ""
        log.warning("me() failed: %s", e)
    try:
        kinds = []
        for entry in payload.get("entry", []):
            kinds += [ch.get("field", "?") for ch in entry.get("changes", [])]
            kinds += ["messaging:" + ",".join(k for k in m if k not in ("sender", "recipient", "timestamp"))
                      for m in entry.get("messaging", [])]
        add_event("webhook", "received", detail=f"{payload.get('object')} {' '.join(kinds)} | {json.dumps(payload, ensure_ascii=False)[:600]}")
    except Exception:
        pass
    for entry in payload.get("entry", []):
        for ch in entry.get("changes", []):
            if ch.get("field") == "comments":
                handle_comment(ch.get("value") or {}, own_id)
        for m in entry.get("messaging", []):
            handle_message(m, own_id)


# ---------- background worker ----------

JOBS = queue.Queue()


def worker():
    while True:
        payload = JOBS.get()
        try:
            process(payload)
        except Exception:
            log.exception("processing failed")
            add_event("error", "exception", detail=json.dumps(payload)[:900])


def parse_ts(iso):
    try:
        return dt.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%S%z").timestamp()
    except (TypeError, ValueError):
        return 0


def poll_comments(since):
    """Fallback for webhooks: read fresh comments on recent posts through the API.
    Handles the same way as a webhook; first_time() keeps webhook + poll from answering twice."""
    own_id = str(me().get("user_id", ""))
    found = 0
    for m in media_list(int(kv_get("poll_media", "8"))):
        url, pages = f"{m['id']}/comments", 0
        params = {"fields": "id,text,timestamp,from,username", "limit": 50}
        while url and pages < 4:
            data = api("GET", url, params)
            pages += 1
            for c in data.get("data", []):
                if parse_ts(c.get("timestamp")) < since:
                    continue
                frm = c.get("from") or {"id": "", "username": c.get("username", "")}
                found += 1
                handle_comment({"id": c["id"], "text": c.get("text", ""), "from": frm,
                                "media": {"id": m["id"]}}, own_id)
            nxt = (data.get("paging") or {}).get("cursors", {}).get("after")
            url = url if nxt and (data.get("paging") or {}).get("next") else None
            params = dict(params, after=nxt) if nxt else params
    return found


def poll_messages(since):
    """Fallback for messaging webhooks: read recent DMs through the Conversations API."""
    if mode() != "facebook":
        return 0
    own_id = str(me().get("user_id", ""))
    fields = "id,updated_time,messages.limit(5){id,created_time,from,message}"
    ptok = None  # the IG-account route is proven to work for reading DMs; the Page route is the fallback
    try:
        data = api("GET", f"{acct()}/conversations", {"platform": "instagram", "fields": fields, "limit": 20})
    except ApiError:
        pid, ptok = page()
        if not pid:
            raise
        data = api("GET", f"{pid}/conversations", {"platform": "instagram", "fields": fields, "limit": 20}, tok=ptok)
    found = 0
    for conv in data.get("data", []):
        if parse_ts(conv.get("updated_time")) < since:
            continue
        for m in (conv.get("messages") or {}).get("data", []):
            if parse_ts(m.get("created_time")) < since:
                continue
            if "message" not in m or "from" not in m:
                m = api("GET", m["id"], {"fields": "id,created_time,from,message"}, tok=ptok or None)
            frm = (m.get("from") or {}).get("id", "")
            if not frm or frm == own_id:
                continue
            found += 1
            handle_message({"sender": {"id": frm}, "message": {"mid": m["id"], "text": m.get("message", "")}},
                           own_id)
    return found


def debug_dump():
    """Raw answers from Meta for troubleshooting DMs (shown in the panel)."""
    out = {}
    def call(label, method, path, params=None):
        try:
            out[label] = api(method, path, params)
        except Exception as e:
            out[label] = {"error": str(e)}
    a = acct()
    call("conversations", "GET", f"{a}/conversations", {"platform": "instagram", "fields": "id,updated_time,participants", "limit": 10})
    call("conversations+messages", "GET", f"{a}/conversations",
         {"platform": "instagram", "fields": "id,updated_time,messages.limit(5){id,created_time,from,message}", "limit": 5})
    convs = (out.get("conversations") or {}).get("data") or []
    if convs:
        call("first conversation messages", "GET", convs[0]["id"], {"fields": "messages.limit(5){id,created_time,from,to,message}"})
    call("subscribed_apps", "GET", f"{a}/subscribed_apps")
    pid, ptok = page()
    out["page"] = {"page_id": pid or "не найдена"}
    if pid:
        try:
            out["page conversations"] = api("GET", f"{pid}/conversations",
                                            {"platform": "instagram", "fields": "id,updated_time", "limit": 5}, tok=ptok)
            out["page subscribed_apps"] = api("GET", f"{pid}/subscribed_apps", tok=ptok)
        except Exception as e:
            out["page error"] = str(e)
    if meta("app_id") and meta("app_secret"):
        try:
            out["app subscriptions"] = api("GET", f"{meta('app_id')}/subscriptions", {},
                                           tok=f"{meta('app_id')}|{meta('app_secret')}", base=FB_GRAPH)
        except Exception as e:
            out["app subscriptions"] = {"error": str(e)}
    return out


def poller():
    if not kv_get("poll_since"):
        kv_set("poll_since", time.time())
    while True:
        time.sleep(int(kv_get("poll_every", "60")))
        if not token() or kv_get("polling", "1") != "1":
            continue
        started = time.time()
        try:
            since = max(float(kv_get("poll_since")), float(kv_get("last_poll_at") or 0) - 600)
            poll_comments(since)
            try:
                poll_messages(since)
                kv_set("last_dm_poll_error", "")
            except Exception as e:
                kv_set("last_dm_poll_error", str(e)[:300])
            kv_set("last_poll_at", started)
            kv_set("last_poll_error", "")
        except Exception as e:
            kv_set("last_poll_error", str(e)[:300])
            log.warning("poll failed: %s", e)
            if "blocked" in str(e).lower() or "(code 4/" in str(e) or "(code 32/" in str(e):
                time.sleep(1800)  # Meta blocked or rate-limited the app: back off instead of hammering


def maintenance():
    """Refresh the token every 7 days so it never reaches its 60-day expiry."""
    while True:
        try:
            last = float(kv_get("token_refreshed_at", "0") or 0)
            if token() and mode() == "instagram" and time.time() - last > 7 * 86400:
                refresh_token()
                add_event("token", "refreshed")
        except Exception as e:
            add_event("token", "error", detail=e)
        try:
            con = db()
            con.execute("delete from handled where at < ?", (time.time() - 30 * 86400,))
            con.execute("delete from events where at < ?", (time.time() - 180 * 86400,))
            con.commit()
            con.close()
        except Exception:
            log.exception("cleanup failed")
        time.sleep(6 * 3600)


_started = False


def start_background():
    global _started
    if _started:
        return
    _started = True
    init_db()
    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=maintenance, daemon=True).start()
    threading.Thread(target=poller, daemon=True).start()


def fmt_time(ts):
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(CFG.get("TIMEZONE", "Europe/Madrid"))
    return dt.datetime.fromtimestamp(float(ts), tz).strftime("%d.%m %H:%M")
