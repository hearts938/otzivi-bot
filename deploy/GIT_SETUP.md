# Git: залить код и обновлять сервер с репозитория

## 1. Установить Git на Windows (если ещё нет)

- Скачать: https://git-scm.com/download/win
- Установить с настройками по умолчанию
- Перезапустить терминал / Cursor
- Проверка: `git --version`

Либо использовать **Git в PyCharm**: VCS → Enable Version Control Integration → Git.

---

## 2. Создать пустой репозиторий на GitHub / GitLab

**GitHub:**

1. https://github.com/new
2. Имя, например: `pythonboteng`
3. **Private** (рекомендуется — там бизнес-логика бота)
4. **Не** ставить галочки «Add README» / «Add .gitignore» — репозиторий должен быть пустым
5. Скопировать URL, например: `https://github.com/ВАШ_ЛОГИН/pythonboteng.git`

**GitLab:** аналогично — New project → Create blank project.

---

## 3. Первый push с компьютера

В PowerShell (из папки проекта):

```powershell
cd c:\Users\korov\PycharmProjects\pythonboteng

git init
git add .
git status
```

Убедитесь, что в списке **нет** `.env` и `bot.db` (они в `.gitignore`).

```powershell
git commit -m "Initial commit: Telegram bot + web admin"

git branch -M main
git remote add origin https://github.com/ВАШ_ЛОГИН/pythonboteng.git
git push -u origin main
```

При первом push GitHub попросит войти (браузер или Personal Access Token).

### Personal Access Token (если пароль не принимается)

1. GitHub → Settings → Developer settings → Personal access tokens
2. Создать token с правом `repo`
3. При `git push` логин = ваш GitHub, пароль = **token**

---

## 4. Клонировать на сервер Timeweb (первый раз)

По SSH на VPS:

```bash
# если каталог пустой или только data:
cd /opt
sudo rm -rf pythonboteng   # только если там ещё нет важной bot.db!
sudo git clone https://github.com/ВАШ_ЛОГИН/pythonboteng.git pythonboteng
cd /opt/pythonboteng

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

mkdir -p data
cp deploy/env.production.example .env
nano .env   # заполнить BOT_TOKEN, ADMIN_IDS, пароли

chmod 600 .env
sudo chown -R www-data:www-data /opt/pythonboteng
```

Дальше — systemd и nginx по `CHECKLIST_TIMEWEB_REGRU.md`.

### Приватный репозиторий на сервере

**Вариант A — SSH-ключ на VPS (удобно):**

```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519_github
cat ~/.ssh/id_ed25519_github.pub
```

Публичный ключ добавить в GitHub → Settings → SSH keys.  
Клонировать: `git clone git@github.com:ВАШ_ЛОГИН/pythonboteng.git`

**Вариант B — HTTPS + token** при `git pull` (логин + token как пароль).

---

## 5. Обновление кода на сервере (каждый раз после правок)

На **компьютере** после изменений:

```powershell
cd c:\Users\korov\PycharmProjects\pythonboteng
git add .
git commit -m "Описание изменений"
git push
```

На **сервере**:

```bash
cd /opt/pythonboteng
sudo -u www-data git pull
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart pythonboteng
```

Проверка: `journalctl -u pythonboteng -n 30`

---

## 6. Что никогда не коммитить

| Файл | Где хранить |
|------|-------------|
| `.env` | Только локально и на сервере |
| `bot.db` / `data/*.db` | Только на сервере (бэкап отдельно) |
| `venv/` | Создаётся на каждой машине |

В репозитории есть `.env.example` и `deploy/env.production.example` — без секретов.

---

## 7. PyCharm (без командной строки)

1. VCS → Enable Version Control Integration → Git  
2. Git → Commit (выбрать файлы, сообщение)  
3. Git → Push — указать remote при первом разе  
4. На сервере всё равно `git pull` по SSH

---

## Краткая схема

```text
ПК: правки → git commit → git push
         ↓
GitHub/GitLab (private)
         ↓
VPS: git pull → pip install → systemctl restart
```
