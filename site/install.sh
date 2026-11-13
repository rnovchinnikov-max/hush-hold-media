#!/usr/bin/env bash
# Hush & Hold website: install or update on Ubuntu 22.04/24.04.
# Usage (as root):
#   bash <(curl -fsSL https://raw.githubusercontent.com/rnovchinnikov-max/hush-hold-media/claude/project-thread-knhep3/site/install.sh)
# Re-run the same command to update the code: config.env, pages, styles and pictures are kept.
#
# If the autoreply bot (hush-autoreply) already runs on this server, the site takes the main
# address (https://DOMAIN/) and the bot keeps /admin, /webhook, /auth, /privacy, /data-deletion.
# The site's own admin panel is https://DOMAIN/studio
set -euo pipefail
DOMAIN="${DOMAIN:-hushhold.uk}"
REPO="${REPO:-https://github.com/rnovchinnikov-max/hush-hold-media.git}"
BRANCH="${BRANCH:-claude/project-thread-knhep3}"
APP=/opt/hush-site
DATA=/var/lib/hush-site
SRC=/opt/hush-site-src
PORT=8010
BOT_SITE=/etc/nginx/sites-available/hush-autoreply

[ "$(id -u)" = 0 ] || { echo "Запусти от root"; exit 1; }

export DEBIAN_FRONTEND=noninteractive
if ! command -v nginx >/dev/null 2>&1; then
  echo "==> Проверка портов 80/443"
  BUSY=$(ss -Htlpn '( sport = :80 or sport = :443 )' 2>/dev/null || true)
  if [ -n "$BUSY" ]; then
    echo "!! Порт 80 или 443 занят другой программой:"; echo "$BUSY"
    echo "!! Ничего не изменено. Пришли этот вывод."; exit 1
  fi
fi
echo "==> Пакеты"
apt-get update -qq
apt-get install -y -qq git nginx certbot python3-certbot-nginx python3-venv python3-pip openssl dnsutils curl >/dev/null

echo "==> Код (ветка $BRANCH)"
if [ -d "$SRC/.git" ]; then
  git -C "$SRC" fetch -q --depth 1 origin "$BRANCH" && git -C "$SRC" reset -q --hard FETCH_HEAD
else
  git clone -q --depth 1 -b "$BRANCH" "$REPO" "$SRC"
fi
id hush >/dev/null 2>&1 || useradd --system --home "$APP" --shell /usr/sbin/nologin hush
mkdir -p "$APP" "$DATA/uploads"
rsync -a --delete --exclude config.env --exclude .venv --exclude data "$SRC/site/" "$APP/" 2>/dev/null || {
  apt-get install -y -qq rsync >/dev/null
  rsync -a --delete --exclude config.env --exclude .venv --exclude data "$SRC/site/" "$APP/"
}
[ -d "$APP/.venv" ] || python3 -m venv "$APP/.venv"
"$APP/.venv/bin/pip" install -q --upgrade pip >/dev/null
"$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt"

FIRST=0
if [ ! -f "$APP/config.env" ]; then
  FIRST=1
  sed -e "s|^SITE_ADMIN_PASSWORD=.*|SITE_ADMIN_PASSWORD=$(openssl rand -base64 12 | tr -d '/+=')|" \
      -e "s|^SITE_SECRET_KEY=.*|SITE_SECRET_KEY=$(openssl rand -hex 32)|" \
      "$APP/config.example.env" > "$APP/config.env"
fi
chown -R hush:hush "$APP" "$DATA"
chmod 600 "$APP/config.env"

echo "==> Служба hush-site"
cat > /etc/systemd/system/hush-site.service <<UNIT
[Unit]
Description=Hush & Hold website
After=network-online.target
Wants=network-online.target

[Service]
User=hush
WorkingDirectory=$APP
EnvironmentFile=$APP/config.env
ExecStart=$APP/.venv/bin/gunicorn -w 2 --threads 4 -b 127.0.0.1:$PORT --access-logfile - app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable -q hush-site
systemctl restart hush-site

echo "==> nginx"
mkdir -p /etc/nginx/snippets
if [ -f "$BOT_SITE" ]; then
  # the autoreply bot is here: its paths stay with it, everything else goes to the site
  cat > /etc/nginx/snippets/hush-autoreply-paths.conf <<'NGINX'
location ~ ^/(admin|webhook|auth|privacy|data-deletion|healthz)(/|$) {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
NGINX
  cp "$BOT_SITE" "/root/hush-autoreply.nginx.bak"
  python3 "$APP/nginx_patch.py" "$BOT_SITE"
  if ! nginx -t -q; then
    echo "!! nginx не принял настройки, возвращаю как было"
    cp /root/hush-autoreply.nginx.bak "$BOT_SITE"; nginx -t -q && systemctl reload nginx; exit 1
  fi
  systemctl reload nginx
else
  SITE=/etc/nginx/sites-available/hush-site
  if [ ! -f "$SITE" ]; then
  cat > "$SITE" <<NGINX
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN www.$DOMAIN;
    client_max_body_size 12m;
    location / {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
NGINX
  fi
  ln -sf "$SITE" /etc/nginx/sites-enabled/hush-site
  rm -f /etc/nginx/sites-enabled/default
  nginx -t -q && systemctl reload nginx
  if ufw status 2>/dev/null | grep -q "Status: active"; then
    ufw allow OpenSSH >/dev/null; ufw allow 'Nginx Full' >/dev/null
  fi
  echo "==> HTTPS"
  if [ ! -d "/etc/letsencrypt/live/$DOMAIN" ]; then
    MYIP=$(curl -fsS4 https://api.ipify.org || true)
    DNSIP=$(dig +short A "$DOMAIN" @1.1.1.1 | tail -1)
    if [ -n "$MYIP" ] && [ "$MYIP" != "$DNSIP" ]; then
      echo "!! $DOMAIN указывает на '$DNSIP', а у сервера IP $MYIP. Поправь A-запись (Cloudflare: серое облачко) и запусти скрипт ещё раз."
    else
      WWW=""; [ -n "$(dig +short A "www.$DOMAIN" @1.1.1.1)" ] && WWW="-d www.$DOMAIN"
      certbot --nginx -n --agree-tos --register-unsafely-without-email --redirect -d "$DOMAIN" $WWW
    fi
  fi
fi

sleep 2
echo
if curl -fsS "http://127.0.0.1:$PORT/site-health" >/dev/null; then echo "✅ Сайт работает"; else echo "❌ Сайт не отвечает: journalctl -u hush-site -n 50"; fi
set +u; . <(grep -E '^SITE_ADMIN_PASSWORD=' "$APP/config.env"); set -u
echo
echo "Сайт:            https://$DOMAIN/"
echo "Студия (админка): https://$DOMAIN/studio"
echo "Пароль студии:   $SITE_ADMIN_PASSWORD"
[ -f "$BOT_SITE" ] && echo "Бот автоответов: https://$DOMAIN/admin (без изменений)"
[ $FIRST = 1 ] && echo && echo "Сохрани пароль. Поменять: nano $APP/config.env, потом systemctl restart hush-site"
exit 0
