# Автоответы Hush&hold (своя замена ManyChat)

Что делает: человек пишет под постом или рилсом ключевое слово (например, SLEEP) →
приложение отвечает под комментарием (случайный вариант из списка) → шлёт в директ
сообщение с кнопкой → человек жмёт кнопку → приложение проверяет подписку на @hush_hold →
подписчику отправляет промокод и ссылку, неподписанному предлагает подписаться и нажать
«I followed ✅». Если человек сам пишет ключевое слово в директ, срабатывает то же правило.
Всё настраивается в панели https://hushhold.uk/admin: правила, тексты, посты, пауза, тестовый режим, журнал.

## Шаг 3–4. Домен, сервер, HTTPS

1. Cloudflare → hushhold.uk → DNS → Records: две записи **A** (`@` и `www`) на IP сервера,
   облачко **серое (DNS only)**.
2. На сервере (`ssh root@IP`) одна команда, она же потом обновляет приложение:
   ```
   bash <(curl -fsSL https://raw.githubusercontent.com/rnovchinnikov-max/hush-hold-media/claude/project-thread-jbu733/autoreply/install.sh)
   ```
   Скрипт ставит nginx, сертификат Let's Encrypt (продлевается сам), Python-приложение как службу.
   В конце печатает **пароль панели**, **Callback URL** и **Verify token**. Сохрани их.
3. Проверка: https://hushhold.uk открывается с замочком, https://hushhold.uk/admin просит пароль.

## Шаг 5. Приложение Meta и токен

1. [developers.facebook.com/apps](https://developers.facebook.com/apps) → **Create app**.
   Имя, например `Hush Hold Replies`. Сценарий (use case): **Manage messaging & content on Instagram**.
   Бизнес-портфолио можно не выбирать.
2. В приложении: Use cases → Instagram → **API setup with Instagram login**.
3. Наверху страницы видны **Instagram app ID** и **Instagram app secret**. Секрет впиши на сервере:
   `nano /opt/hush-autoreply/config.env` → строка `IG_APP_SECRET=...` → Ctrl+O, Enter, Ctrl+X →
   `systemctl restart hush-autoreply`.
4. Блок **Generate access tokens** → Add account → войди в @hush_hold → **Generate token** → скопируй.
   Вставь в панели: Аккаунт → «Токен и вебхуки» → Сохранить токен. Панель сама подпишет аккаунт
   на события и дальше будет продлевать токен (живёт 60 дней, продлевается раз в 7).
5. Блок **Configure webhooks**: Callback URL `https://hushhold.uk/webhook`, Verify token из вывода
   скрипта → **Verify and save**. Ниже включи поля **comments**, **messages**, **messaging_postbacks**.
6. App settings → Basic: Privacy Policy URL `https://hushhold.uk/privacy`,
   User data deletion `https://hushhold.uk/data-deletion`, категория, иконка → Save.
   (Почту для этих страниц можно указать в config.env, строка CONTACT_EMAIL.)
7. В Instagram на телефоне: Настройки → Сообщения и ответы на истории → Управление сообщениями →
   Подключённые инструменты → **Разрешить доступ к сообщениям** (у тебя уже включено для ManyChat).

## Шаг 6–7. Обработчик и панель

Уже готовы, это и есть это приложение (`core.py` логика, `app.py` вебхук и панель).
В панели по умолчанию есть правило «SLEEP → promo code» с промокодом MOMSHELP и ссылкой на гайд.

## Шаг 8. Проверка и запуск

Пока приложение в режиме разработки, Meta шлёт события только по аккаунтам с ролью в приложении.
1. App roles → Roles → **Add people → Instagram Tester** → ник второго (тестового) аккаунта.
   В тестовом аккаунте прими приглашение: Настройки → Разрешения сайтов / Apps and websites → Tester invites.
2. В панели: «Отвечать только этим аккаунтам» → ник тестового аккаунта. Так ManyChat и новое
   приложение не будут отвечать одним и тем же людям.
3. С тестового аккаунта напиши SLEEP под постом. В журнале панели должны появиться
   `comment matched`, `public_reply ok`, `dm ok`; нажми кнопку в директе → `reward ok` или `not_following`.
4. Чтобы работало для всех: App Review → запросить **Advanced Access** для
   `instagram_business_basic`, `instagram_business_manage_comments`, `instagram_business_manage_messages`
   (нужны описание и короткая запись экрана; тексты помогу написать). Возможно, Meta попросит
   подтвердить бизнес (Business verification). После одобрения переключи приложение в **Live**.
5. В панели очисти «Отвечать только этим аккаунтам», а в ManyChat выключи автоматизацию SLEEP.

## Полезные команды на сервере

- логи: `journalctl -u hush-autoreply -f`
- перезапуск после правки config.env: `systemctl restart hush-autoreply`
- обновить приложение: снова команда установки из шага 3–4
- база (правила, журнал): `/var/lib/hush-autoreply/data.db`

## Ограничения Instagram

- Ответ в директ на комментарий (private reply) можно отправить один раз на комментарий и в течение 7 дней.
- После того как человек нажал кнопку или написал в директ, 24 часа можно писать ему свободно.
- Повторный комментарий того же человека под тем же постом игнорируется, чтобы не спамить.
