# ParserKolesa — Бот-продавец авточехлов AUTOCOVERS.KZ

Автоматическая система холодных продаж авточехлов через WhatsApp. Парсит объявления с Kolesa.kz, собирает номера телефонов покупателей автомобилей и автоматически ведёт диалог через AI (DeepSeek).

## Стек технологий

- **Backend:** Python 3.11, FastAPI, SQLite
- **Парсер:** Playwright (Chromium)
- **WhatsApp:** Green API (polling + webhook)
- **AI:** DeepSeek (диалог) + Groq Whisper (транскрибация аудио)
- **Frontend:** Vanilla JS, HTML/CSS
- **Деплой:** Ubuntu 24.04, Nginx, systemd

## Структура проекта

```
parskolesa/
├── main.py              # FastAPI сервер, все API endpoints
├── bot.py               # Логика бота (скрипты, AI диалог, LAER)
├── parser.py            # Playwright парсер Kolesa.kz
├── database.py          # SQLite база данных
├── whatsapp.py          # Green API клиент
├── ai_client.py         # AI клиент (DeepSeek/OpenAI)
├── auth.py              # JWT авторизация
├── catalog.py           # Прайс-лист и классификация авто
├── set_groq.py          # Утилита сохранения Groq API ключа
├── catalog/
│   ├── КАТАЛОГ_2025.pdf # Полный каталог продукции
│   └── photos/          # Фото работ (img-009, 011, 016, 019, 022.jpg)
├── public/
│   ├── index.html       # Панель управления
│   └── login.html       # Страница входа
├── .env                 # Credentials (не в git)
└── kolesa_session.json  # Сессия Kolesa.kz (не в git)
```

## Установка

### Локально (Windows)

```bash
# Клонировать репозиторий
git clone https://github.com/Nurblack/parserkolesa.git
cd parserkolesa

# Установить зависимости
py -3.11 -m pip install fastapi uvicorn playwright requests python-dotenv groq

# Установить браузер
py -3.11 -m playwright install chromium

# Запустить сервер
py -3.11 -m uvicorn main:app --port 8000
```

### На сервере (Ubuntu 24.04)

```bash
cd /var/www/kolesa.raycon.kz

# Установить зависимости
pip install fastapi uvicorn aiohttp python-dotenv requests playwright groq

# Установить браузер
playwright install chromium

# Системные библиотеки для Chromium
apt install -y libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
  libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
  libgbm1 libasound2t64
```

## Настройка API ключей

Все ключи хранятся в БД и настраиваются через панель управления (Настройки) или через терминал:

```bash
# DeepSeek API ключ (основной AI)
py -3.11 -c "from database import db; db.save_settings({'ai_api_key': 'sk-...', 'ai_provider': 'DeepSeek', 'ai_model': 'deepseek-chat'})"

# Groq API ключ (транскрибация голосовых)
py -3.11 set_groq.py

# Проверка ключей
py -3.11 -c "from database import db; s=db.get_settings(); print('AI:', s.get('ai_api_key','')[:10], 'Groq:', s.get('groq_api_key','')[:10])"
```

## Деплой на сервер

```bash
# Создать systemd сервис
cat > /etc/systemd/system/parskolesa.service << EOF
[Unit]
Description=ParserKolesa Bot
After=network.target

[Service]
User=root
WorkingDirectory=/var/www/kolesa.raycon.kz
ExecStart=/usr/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8001
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable parskolesa
systemctl start parskolesa
```

### Обновление с GitHub

```bash
cd /var/www/kolesa.raycon.kz
git fetch https://github.com/Nurblack/parserkolesa.git main
git reset --hard FETCH_HEAD
systemctl restart parskolesa
```

## Использование

### Панель управления

Открой `http://localhost:8000` (локально) или `https://kolesa.raycon.kz` (сервер).

**Логин:**
- Администратор: `admin` / `admin123`
- Пользователь: `user1` / `user123`

### Авторизация Kolesa.kz

1. Перейди в **Настройки → Аккаунт Kolesa.kz**
2. Нажми **"Войти вручную"**
3. В открывшемся браузере войди в аккаунт
4. Дождись сообщения "Сессия сохранена"

### Запуск парсера

1. Перейди в раздел **Парсер**
2. Введи URL категории Kolesa.kz:
   ```
   https://kolesa.kz/cars/astana/
   https://kolesa.kz/cars/almaty/
   ```
3. Укажи лимит объявлений (50-200)
4. Нажми **Запустить**

### Запуск бота

1. Перейди в раздел **Бот**
2. Нажми **Запустить бота**
3. Бот начнёт отправлять удочки новым номерам каждые 45 секунд

### Тестовый режим (Whitelist)

Чтобы бот писал только на определённые номера — укажи их в **Настройки → Тестовый режим (Whitelist)**:
```
77001234567
77009876543
```
Оставь пустым для обычного режима (пишет всем).

## Логика бота

```
Парсер → Номера NEW → Бот отправляет удочку (Pattern Interrupt)
                               ↓
                     Клиент отвечает
                               ↓
          photo/price → Каталог (5 фото + прайс + PDF) → CTA
          discount    → Ответ про ценность (установка + доставка бесплатно)
          маркетплейс → Challenger Sale (пошив vs универсал)
          гарантия    → 6 месяцев на швы
          доставка    → Сроки и регионы
          качество    → Турецкие материалы + фото
          аудио       → Транскрибация через Groq Whisper → обработка текста
          цитата      → Читает ответ клиента из quoted message
               ↓
          1-й отказ → LAER вопрос про причину
          2-й отказ → AI дожим (Challenger Sale)
          3-й отказ → Breakup + Instagram
               ↓
          Заказ → Подтверждение + Instagram → DONE
```

## Настройки бота

| Параметр | Описание | По умолчанию |
|----------|----------|--------------|
| `send_delay` | Пауза между циклами (сек) | 45 |
| `daily_hooks_limit` | Лимит удочек в день | 100 |
| `working_hours_start` | Начало рабочего дня | 9 |
| `working_hours_end` | Конец рабочего дня | 21 |
| `ai_provider` | Провайдер AI | DeepSeek |
| `ai_model` | Модель AI | deepseek-chat |
| `groq_api_key` | Ключ для Groq Whisper (аудио) | — |

## Green API

Сервис для работы с WhatsApp:
- Отправка сообщений с индикатором "печатает..." (`sendTyping`)
- Получение входящих через polling (каждые 45 сек)
- Отправка фото и PDF файлов
- Транскрибация голосовых через Groq Whisper

**Webhook URL** (для мгновенных ответов на продакшн):
```
https://kolesa.raycon.kz/api/webhook
```

**Instance ID:** `7700610961`

## Типы сообщений WhatsApp (поддерживаются)

| Тип | Описание |
|-----|----------|
| `textMessage` | Обычный текст |
| `quotedMessage` | Цитата — читает ответ клиента |
| `extendedTextMessage` | Текст со ссылкой |
| `audioMessage` | Голосовое → Groq Whisper → текст |
| `pttMessage` | Push-to-talk → Groq Whisper → текст |

## Каталог продукции

```
catalog/
├── КАТАЛОГ_2025.pdf     # Полный каталог (отправляется клиенту)
└── photos/
    ├── img-009.jpg      # Ромб серый (Toyota/Mazda)
    ├── img-011.jpg      # Ёлочка бежевый (Hyundai)
    ├── img-016.jpg      # Классика чёрная
    ├── img-019.jpg      # Соты чёрный
    └── img-022.jpg      # Тедди бежевый
```

**Прайс-лист (легковые):**
- Открытая спинка: Велюр 57к / Тедди 65к / Энигма 75к
- Закрытая спинка: Велюр 65-70к / Тедди 80-85к / Экокожа 65-70к

**Прайс-лист (кроссоверы):**
- Открытая спинка: от 57к
- Закрытая спинка: от 67к

## Права доступа

| Раздел | Админ | Юзер |
|--------|-------|------|
| Дашборд | ✅ | ✅ |
| Парсер | ✅ | ✅ |
| Бот | ✅ | ✅ |
| Диалоги | ✅ | ✅ |
| База номеров | ✅ | ❌ |
| Настройки | ✅ | ❌ |
| Логи | ✅ | ❌ |

## Сервер

- **IP:** 91.224.74.17
- **Домен:** kolesa.raycon.kz
- **ОС:** Ubuntu 24.04
- **Порт:** 8001 (за Nginx)

## Контакты

- **Instagram:** [@autocovers.kz](https://www.instagram.com/autocovers.kz?igsh=MW8zNzd5NzdrczYyYQ==)
- **GitHub:** [Nurblack/parserkolesa](https://github.com/Nurblack/parserkolesa)
