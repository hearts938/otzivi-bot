# Чеклист запуска: Timeweb VPS + домен REG.RU

Отмечайте выполненное: замените `[ ]` на `[x]`.

**Схема:** REG.RU (DNS) → IP VPS Timeweb → nginx (HTTPS) → `run_all.py` (бот + сайт + планировщик).

Замените в тексте:
- `ваш-домен.ru` — ваш домен на REG.RU
- `admin` — желаемый субдомен (получится `admin.ваш-домен.ru`)
- `ВАШ_IP_VPS` — внешний IPv4 из панели Timeweb Cloud

**Git (залить код и обновлять сервер):** подробно в [`deploy/GIT_SETUP.md`](GIT_SETUP.md).

---

## Фаза 0 — подготовка (до сервера)

- [ ] Токен бота от [@BotFather](https://t.me/BotFather) +
- [ ] Ваш Telegram ID (например [@userinfobot](https://t.me/userinfobot)) — для `ADMIN_IDS` +
- [ ] Домен зарегистрирован на REG.RU +
- [ ] Выбран субдомен для админки (например `admin`) - 
- [ ] Создан облачный VPS в Timeweb Cloud (Ubuntu 22.04 рекомендуется) +
- [ ] Записан **внешний IPv4** VPS из панели Timeweb +
- [ ] Есть доступ по SSH (логин/пароль или ключ из Timeweb) +

---

## Фаза 1 — локально на Windows (проверка)

- [ ] Python 3.11+ установлен (`py --version`) +
- [ ] Установлены зависимости:
  ```powershell
  cd c:\Users\korov\PycharmProjects\pythonboteng
  py -m pip install -r requirements.txt +
  ```
- [ ] Файл `.env` создан (скопирован из `.env.example`) +
- [ ] В `.env` указан реальный `BOT_TOKEN` +
- [ ] В `.env` указан `ADMIN_IDS` (ваш числовой ID) +
- [ ] В `.env` указан `DATABASE_URL=sqlite+aiosqlite:///./bot.db` +
- [ ] В `.env` задан `WEB_ADMIN_PASSWORD` (длинный пароль)
- [ ] В `.env` задан `WEB_SESSION_SECRET` (случайная строка 32+ символа)
- [ ] Локально: `WEB_HOST=0.0.0.0`, `WEB_PORT=8000`
- [ ] Первый запуск: `py main.py` или `py run_all.py`
- [ ] Бот отвечает в Telegram на `/start`
- [ ] Команда `/admin` открывает панель (с аккаунта из `ADMIN_IDS`)
- [ ] Сайт открывается: `http://127.0.0.1:8000` — вход по `WEB_ADMIN_PASSWORD`
- [ ] После запуска появился файл `bot.db` в папке проекта

---

## Фаза 1.5 — Git (репозиторий на GitHub / GitLab)

Подробные команды: [`deploy/GIT_SETUP.md`](GIT_SETUP.md).

- [ ] Установлен Git на Windows (`git --version`) или включён Git в PyCharm
- [ ] Создан **пустой** репозиторий на GitHub/GitLab (лучше **Private**)
- [ ] В проекте есть `.gitignore` (не коммитит `.env`, `bot.db`, `venv/`)
- [ ] Первый коммит и push с ПК:
  ```powershell
  cd c:\Users\korov\PycharmProjects\pythonboteng
  git init
  git add .
  git status
  git commit -m "Initial commit"
  git branch -M main
  git remote add origin https://github.com/ВАШ_ЛОГИН/pythonboteng.git
  git push -u origin main
  ```
- [ ] В `git status` перед push **нет** файла `.env`
- [ ] URL репозитория записан (для `git clone` на сервере)

---

## Фаза 2 — VPS Timeweb (базовая настройка)

### Панель Timeweb

- [ ] В панели найден и записан **публичный IPv4** сервера
- [ ] В файрволе / правилах безопасности открыт порт **22** (SSH)
- [ ] Открыты порты **80** и **443** (сайт и Let's Encrypt)
- [ ] Порт **8000** наружу **не** открыт (доступ только через nginx на localhost)

### Подключение по SSH

- [ ] Подключение с ПК успешно:
  ```powershell
  ssh root@ВАШ_IP_VPS
  ```
  (или пользователь из письма Timeweb)

### Пакеты на сервере

- [ ] Выполнено обновление и установка пакетов:
  ```bash
  apt update && apt upgrade -y
  apt install -y python3 python3-venv python3-pip git nginx certbot python3-certbot-nginx ufw
  ```
- [ ] Настроен UFW:
  ```bash
  ufw allow OpenSSH
  ufw allow 'Nginx Full'
  ufw enable
  ```
- [ ] Созданы каталоги:
  ```bash
  mkdir -p /opt/pythonboteng/data
  ```

### Код на сервере (из Git)

- [ ] Клонирован репозиторий:
  ```bash
  cd /opt
  git clone https://github.com/ВАШ_ЛОГИН/pythonboteng.git pythonboteng
  ```
  (приватный репо — SSH-ключ на VPS, см. `GIT_SETUP.md`)
- [ ] Создано виртуальное окружение и зависимости:
  ```bash
  cd /opt/pythonboteng
  python3 -m venv venv
  source venv/bin/activate
  pip install -r requirements.txt
  ```

---

## Фаза 3 — DNS на REG.RU

- [ ] Вход на [reg.ru](https://www.reg.ru) → **Домены** → ваш домен
- [ ] Открыто **управление DNS-зоной** (NS домена — REG.RU или зона редактируется там, где висят NS)
- [ ] Добавлена A-запись:

  | Тип | Имя / поддомен | Значение |
  |-----|----------------|----------|
  | A   | `admin`        | `ВАШ_IP_VPS` |

- [ ] Запись сохранена
- [ ] Подождали 15–60 минут (иногда до 24 ч)
- [ ] Проверка с ПК:
  ```powershell
  nslookup admin.ваш-домен.ru
  ```
  → в ответе IP Timeweb

---

## Фаза 4 — `.env` на сервере

- [ ] Создан файл `/opt/pythonboteng/.env`
- [ ] `BOT_TOKEN` — тот же, что локально
- [ ] `ADMIN_IDS` — ваш Telegram ID
- [ ] `DATABASE_URL=sqlite+aiosqlite:////opt/pythonboteng/data/bot.db`
- [ ] `WEB_ADMIN_PASSWORD` — сильный уникальный пароль
- [ ] `WEB_SESSION_SECRET` — сгенерирован (не пустой):
  ```bash
  python3 -c "import secrets; print(secrets.token_hex(32))"
  ```
- [ ] `WEB_HOST=127.0.0.1`
- [ ] `WEB_PORT=8000`
- [ ] `APP_TIMEZONE=Europe/Moscow`
- [ ] Права на `.env`: `chmod 600 /opt/pythonboteng/.env`
- [ ] Владелец каталога для сервиса (пример):
  ```bash
  chown -R www-data:www-data /opt/pythonboteng
  ```

---

## Фаза 5 — автозапуск (systemd)

- [ ] Создан unit `/etc/systemd/system/pythonboteng.service`:

  ```ini
  [Unit]
  Description=Review bot (Telegram + web admin)
  After=network.target

  [Service]
  Type=simple
  User=www-data
  Group=www-data
  WorkingDirectory=/opt/pythonboteng
  EnvironmentFile=/opt/pythonboteng/.env
  ExecStart=/opt/pythonboteng/venv/bin/python run_all.py
  Restart=always
  RestartSec=5

  [Install]
  WantedBy=multi-user.target
  ```

- [ ] Сервис включён и запущен:
  ```bash
  systemctl daemon-reload
  systemctl enable --now pythonboteng
  systemctl status pythonboteng
  ```
- [ ] В логах нет ошибок: `journalctl -u pythonboteng -f`
- [ ] Локально на VPS отвечает веб:
  ```bash
  curl -I http://127.0.0.1:8000/login
  ```
- [ ] Файл БД создан: `/opt/pythonboteng/data/bot.db`

---

## Фаза 6 — nginx + HTTPS (субдомен)

- [ ] Скопирован пример конфига:
  ```bash
  cp /opt/pythonboteng/deploy/nginx-admin.conf.example /etc/nginx/sites-available/admin.conf
  ```
- [ ] В `admin.conf` заменены все `admin.example.com` на `admin.ваш-домен.ru`
- [ ] Сайт включён:
  ```bash
  ln -s /etc/nginx/sites-available/admin.conf /etc/nginx/sites-enabled/
  nginx -t
  systemctl reload nginx
  ```
- [ ] Выпущен сертификат Let's Encrypt:
  ```bash
  certbot --nginx -d admin.ваш-домен.ru
  ```
- [ ] В браузере открывается `https://admin.ваш-домен.ru` (замок без предупреждений)
- [ ] Вход на сайт по `WEB_ADMIN_PASSWORD` работает

---

## Фаза 7 — финальная проверка

- [ ] DNS: `admin.ваш-домен.ru` → IP Timeweb
- [ ] HTTPS работает
- [ ] Разделы веб-админки открываются (пользователи, заказчики, финансы)
- [ ] Импорт Excel на сайте: `/import`
- [ ] Бот: `/start`, опрос (пол + ник), меню заданий
- [ ] Бот: `/admin` — все пункты панели
- [ ] Модерация отзывов (одобрение → баланс)
- [ ] Импорт Excel в боте (модерация / пул заказчика)
- [ ] Тексты с датой публикуются в 00:00 МСК (сервис `pythonboteng` с `run_all.py` запущен)

---

## Фаза 8 — эксплуатация

- [ ] Настроен бэкап `data/bot.db` (cron или бэкапы Timeweb)
- [ ] `.env` не попадает в Git
- [ ] Записана команда обновления после изменений кода:
  ```bash
  cd /opt/pythonboteng && git pull && source venv/bin/activate && pip install -r requirements.txt
  systemctl restart pythonboteng
  ```
- [ ] Знаю, где смотреть логи: `journalctl -u pythonboteng -n 100`

---

## Частые проблемы

| Симптом | Проверить |
|---------|-----------|
| Сайт не открывается | A-запись на REG.RU, IP, порты 80/443 в Timeweb |
| 502 Bad Gateway | `systemctl status pythonboteng`, `WEB_HOST=127.0.0.1` |
| Бот не отвечает | `BOT_TOKEN`, сервис запущен, `journalctl -u pythonboteng` |
| «Нет доступа» в `/admin` | `ADMIN_IDS` = ваш числовой ID |
| Certbot не выдаёт сертификат | DNS уже на VPS, порт 80 открыт |
| Сессия на сайте сбрасывается | `WEB_SESSION_SECRET` задан и не меняется при каждом рестарте |

---

## Справка: переменные `.env`

| Переменная | Локально | На сервере |
|------------|----------|------------|
| `DATABASE_URL` | `sqlite+aiosqlite:///./bot.db` | `sqlite+aiosqlite:////opt/pythonboteng/data/bot.db` |
| `WEB_HOST` | `0.0.0.0` | `127.0.0.1` |
| Запуск | `py run_all.py` | systemd → `run_all.py` |

---

## Порядок в одну строку

Локальный тест → **Git push** → VPS `git clone` → REG.RU A-запись → `.env` на сервере → systemd → nginx + certbot → проверка. Обновления: `git push` → на VPS `git pull` + restart.
