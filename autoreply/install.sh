#!/usr/bin/env bash
# Hush&hold autoreply: install or update on Ubuntu 22.04/24.04.
# Usage (as root):
#   bash <(curl -fsSL https://raw.githubusercontent.com/rnovchinnikov-max/hush-hold-media/claude/project-thread-jbu733/autoreply/install.sh)
# Re-run the same command to update: config.env and the database are kept.
set -euo pipefail
DOMAIN="${DOMAIN:-hushhold.uk}"
REPO="${REPO:-https://github.com/rnovchinnikov-max/hush-hold-media.git}"
BRANCH="${BRANCH:-claude/project-thread-jbu733}"
APP=/opt/hush-autoreply
DATA=/var/lib/hush-autoreply
SRC=/opt/hush-src

[ "$(id -u)" = 0 ] || { echo "Запусти от root"; exit 1; }
echo "==> Пакеты"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git nginx certbot python3-certbot-nginx python3-venv python3-pip openssl dnsutils >/dev/null

echo "==> Код"
if [ -d "$SRC/.git" ]; then
  git -C "$SRC" fetch -q --depth 1 origin "$BRANCH" && git -C "$SRC" reset -q --hard FETCH_HEAD
else
  git clone -q --depth 1 -b "$BRANCH" "$REPO" "$SRC"
fi
id hush >/dev/null 2>&1 || useradd --system --home "$APP" --shell /usr/sbin/nologin hush
mkdir -p "$APP" "$DATA"
cp -r "$SRC/autoreply/." "$APP/"
python3 -m venv "$APP/.venv"
"$APP/.venv/bin/pip" install -q --upgrade pip >/dev/null
"$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt"

FIRST=0
if [ ! -f "$APP/config.env" ]; then
  FIRST=1
  sed -e "s|^DOMAIN=.*|DOMAIN=$DOMAIN|" \
      -e "s|^ADMIN_PASSWORD=.*|ADMIN_PASSWORD=$(openssl rand -base64 12 | tr -d '/+=')|" \
      -e "s|^SECRET_KEY=.*|SECRET_KEY=$(openssl rand -hex 32)|" \
      -e "s|^VERIFY_TOKEN=.*|VERIFY_TOKEN=hush-$(openssl rand -hex 8)|" \
      "$APP/config.example.env" > "$APP/config.env"
fi
chown -R hush:hush "$APP" "$DATA"
chmod 600 "$APP/config.env"

echo "==> Служба"
cat > /etc/systemd/system/hush-autoreply.service <<UNIT
[Unit]
Description=Hush&hold Instagram autoreply
After=network-online.target
Wants=network-online.target

[Service]
User=hush
WorkingDirectory=$APP
ExecStart=$APP/.venv/bin/gunicorn -w 1 --threads 8 -b 127.0.0.1:8000 --access-logfile - app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable -q hush-autoreply
systemctl restart hush-autoreply

echo "==> nginx"
SITE=/etc/nginx/sites-available/hush-autoreply
if [ ! -f "$SITE" ]; then
cat > /etc/nginx/sites-available/hush-autoreply <<NGINX
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN www.$DOMAIN;
    client_max_body_size 2m;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
NGINX
fi
ln -sf /etc/nginx/sites-available/hush-autoreply /etc/nginx/sites-enabled/hush-autoreply
rm -f /etc/nginx/sites-enabled/default
nginx -t -q && systemctl reload nginx

if ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw allow OpenSSH >/dev/null; ufw allow 'Nginx Full' >/dev/null
fi

echo "==> HTTPS"
MYIP=$(curl -fsS4 https://api.ipify.org || true)
DNSIP=$(dig +short A "$DOMAIN" @1.1.1.1 | tail -1)
if [ ! -d "/etc/letsencrypt/live/$DOMAIN" ]; then
  if [ -n "$MYIP" ] && [ "$MYIP" != "$DNSIP" ]; then
    echo "!! $DOMAIN указывает на '$DNSIP', а у сервера IP $MYIP."
    echo "!! Проверь A-запись в Cloudflare (серое облачко, DNS only) и запусти скрипт ещё раз."
  else
    WWW=""; [ -n "$(dig +short A "www.$DOMAIN" @1.1.1.1)" ] && WWW="-d www.$DOMAIN"
    certbot --nginx -n --agree-tos --register-unsafely-without-email --redirect -d "$DOMAIN" $WWW
  fi
else
  echo "Сертификат уже есть, продлевается автоматически."
fi

sleep 2
echo
if curl -fsS "http://127.0.0.1:8000/healthz" >/dev/null; then echo "✅ Приложение работает"; else echo "❌ Приложение не отвечает: journalctl -u hush-autoreply -n 50"; fi
set +u; . <(grep -E '^(ADMIN_PASSWORD|VERIFY_TOKEN)=' "$APP/config.env"); set -u
echo
echo "Панель:          https://$DOMAIN/admin"
echo "Пароль панели:   $ADMIN_PASSWORD"
echo "Callback URL:    https://$DOMAIN/webhook"
echo "Verify token:    $VERIFY_TOKEN"
echo "Privacy policy:  https://$DOMAIN/privacy"
echo "Data deletion:   https://$DOMAIN/data-deletion"
[ $FIRST = 1 ] && echo && echo "Сохрани пароль. Настройки: nano $APP/config.env, потом: systemctl restart hush-autoreply"
