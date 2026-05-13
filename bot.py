"""
ParserKolesa — Bot логика продаж AUTOCOVERS.KZ
Техники холодных продаж встроены по энциклопедии 2025-2026:
- AIDA framework (холодный первый контакт)
- Pattern Interrupt (вовлечение)
- LAER Framework (обработка возражений)
- Permission-Based Selling (уважение к клиенту)
- Straight Line Persuasion (Need / Capacity / Authority)
- Challenger Sale (обучаем клиента)
- Техника Shut Up (CTA без болтовни)
- Breakup Message (финальное закрытие)
"""

import asyncio
import logging
import re
import random
import os
from datetime import datetime
from catalog import (
    get_price_message, get_instagram_message, get_sample_photos,
    is_crossover, CATALOG_PDF_PATH
)

logger = logging.getLogger(__name__)

# Импортируем зависимости как в оригинальном боте
try:
    from database import db as _db
    from whatsapp import wa as _wa
except ImportError:
    _db = None
    _wa = None

# ── AI системный промт с техниками продаж ──────────────────────────────────

AI_SYSTEM_PROMPT = """Ты — менеджер по продажам автоателье AUTOCOVERS.KZ (Астана, с 2017 года). Зовут Алия.
Пишешь в WhatsApp клиенту который недавно купил или продаёт автомобиль.

═══ ГЛАВНОЕ ПРАВИЛО ═══
НИКОГДА не сдавайся при первом отказе. Первый "нет" — это не отказ, это запрос на дополнительную ценность.
Breakup только на 3-й явный отказ подряд.

═══ КАК РАБОТАТЬ С ОТКАЗАМИ (LAER) ═══

Клиент: "Не интересует" / "Не надо" / "Передумал брать"
→ НЕ ПИШИ: "Понимаю, если надумаете — пишите" (это сдача)
→ ПИШИ по схеме:
  1. Acknowledge: коротко признай ("Понял 👍")
  2. Explore: задай ОДИН вопрос про причину ("Что остановило — цена или что-то другое?")
  3. После ответа — Respond с конкретной ценностью

Примеры правильных ответов на отказ:
- "Понял 🤝 А что остановило — цена не подошла или просто пока не время?"
- "Окей! Кстати, вы сказали велюр — это хороший выбор. Что именно смутило в конце?"
- "Понял. Последний вопрос — чехлы нужны срочно или есть время подождать 5-7 дней?"

═══ ТЕХНИКИ ПРОДАЖ ═══

1. AIDA в каждом сообщении:
   Attention (конкретика про ЕГО авто) → Interest (вопрос) → Desire (выгода) → Action (CTA)

2. Challenger Sale — указывай на проблему сам:
   "Заводская обивка на {авто} начинает протираться через 2-3 года..."
   "Большинство берут чехлы ДО того как салон потеряет вид, потом сложнее"

3. So What? — каждое предложение отвечает "и что мне с этого?":
   ❌ "У нас турецкий материал и 9 дизайнов"
   ✅ "Тедди не скользит и не потеет в жару — самый популярный для Казахстана"

4. Shut Up — задал вопрос → СТОП. Жди ответ. Не добавляй ничего.

5. CTA всегда конкретный:
   ❌ "Интересно ли вам?"
   ✅ "Велюр или Тедди — что ближе по стилю?"
   ✅ "В будни или выходные удобнее забрать?"

═══ ПРАВИЛА ФОРМАТА ═══
- 2-3 предложения максимум
- Разговорный стиль, без канцелярита
- 1-2 эмодзи максимум
- Не называй себя ботом
- Не используй слова: "бесплатно", "акция", "уникальный"
- После CTA — молчи, жди ответ

═══ О ПРОДУКТЕ ═══
- Авточехлы ручной пошивки под конкретное авто
- Материалы: Велюр (8 цветов), Тедди — бестселлер (42 цвета), Энигма, Экокожа (45+ цветов), Анфора
- Дизайны: Ромб, Ёлочка, Соты, Бизон, Пальма, Трансформер 1/2, Классика (9 вариантов)
- Срок пошива: 5-7 дней, экспресс 2 дня (+5 000 тг)
- Установка: 2 часа, бесплатно
- Доставка: бесплатно
- Цены легковые: от 57 000 тг (открытая спинка) / от 65 000 тг (полные чехлы)
- Цены кроссоверы: от 57 000 тг / от 67 000 тг

ЦЕЛЬ: довести до выбора материала → подтверждения заказа → Instagram для оформления."""


# ── Скрипты первого контакта (AIDA + Pattern Interrupt) ────────────────────

def get_hook_message(car_brand: str, car_model: str, car_year=None) -> str:
    """
    Первое сообщение — "удочка".
    Применяем: AIDA (Attention через сигнал — конкретное авто клиента)
    + Pattern Interrupt (не стандартный оффер, а вопрос-наблюдение)
    Коротко. Без слова "бесплатно", "акция", "скидка".
    """
    car = f"{car_brand} {car_model}".strip()
    year_str = f" {car_year}" if car_year else ""

    hooks = [
        # Паттерн 1: наблюдение про ЕГО авто (Challenger Sale)
        f"Добрый день! Вижу взяли {car}{year_str} 🎉\n\n"
        f"Сиденья на {car} — первое что «убивают» через полгода активной езды. "
        f"Уже думали о чехлах или пока руки не дошли?",

        # Паттерн 2: Permission-Based + AIDA Attention
        f"Привет! Займу 20 секунд.\n\n"
        f"Занимаемся пошивом авточехлов под {car}{year_str} — шьём точно под форму сидений. "
        f"Актуально сейчас или не сезон?",

        # Паттерн 3: конкретный вопрос (не «интересует ли вас»)
        f"Здравствуйте! Поздравляю с покупкой {car}{year_str} 🚗\n\n"
        f"Сразу вопрос — планируете защищать салон или оставить штатную обивку?",
    ]
    return random.choice(hooks)


def get_followup_message(car_brand: str, car_model: str, attempt: int) -> str:
    """
    Повторные касания если клиент не ответил.
    Применяем: Эффект Эха (ссылаемся на тот же сигнал) + новый угол атаки.
    Максимум 3 попытки, потом Breakup.
    """
    car = f"{car_brand} {car_model}".strip()

    followups = {
        1: (
            f"Ещё раз, коротко 🙂\n\n"
            f"Большинство владельцев {car} берут чехлы в первые 1-3 месяца — "
            f"пока сиденья ещё новые. Потом сложнее сохранить товарный вид.\n\n"
            f"Хотите — пришлю фото и цены под ваш тип авто?"
        ),
        2: (
            f"Последний раз напишу, не хочу надоедать 😊\n\n"
            f"Если {car} — для семьи или работы, чехлы окупаются за первый год. "
            f"Дети, грязь, солнце — это всё убивает родную обивку быстро.\n\n"
            f"Если не актуально — скажите, больше не потревожу."
        ),
        3: get_breakup_message(car_brand, car_model),
    }
    return followups.get(attempt, get_breakup_message(car_brand, car_model))


def get_breakup_message(car_brand: str, car_model: str) -> str:
    """
    Breakup message — финальное закрытие цикла с сохранением лица.
    Классика холодных продаж: оставляем дверь открытой.
    """
    car = f"{car_brand} {car_model}".strip()
    return (
        f"Понял, {car} — не мой звонок 😊\n\n"
        f"Закрываю тему. Если когда-нибудь встанет вопрос с чехлами — "
        f"я в AUTOCOVERS.KZ, пишите в любой момент.\n\n"
        f"Удачи с новым авто! 🚗"
    )


# ── Скрипты продажи (после позитивного ответа) ─────────────────────────────

SALES_SCRIPT = [
    # Единственный шаг — квалификация и сразу каталог
    # Если клиент ответил позитивно — сразу шлём каталог без доп вопросов
]
# Скрипт пустой — любой позитивный ответ сразу ведёт к каталогу


def get_objection_response(objection_type: str, car_brand: str, car_model: str) -> str:
    """
    Конкретные ответы на каждый тип возражения.
    Принцип: Listen → Acknowledge → конкретный факт → прямой CTA
    """
    car = f"{car_brand} {car_model}".strip() or "ваше авто"

    responses = {
        "quality_doubt": (
            f"Разница простая 🎯\n\n"
            f"Маркетплейс — универсальные накидки, сидят криво, съезжают. "
            f"Мы шьём точно под форму сидений {car} — как родные, без складок.\n\n"
            f"Материалы турецкие (Egida, Velur) — не китайский ворс. "
            f"Сейчас пришлю фото — сами увидите разницу."
        ),
        "vs_marketplace": (
            f"Смотрите в чём фишка 👇\n\n"
            f"За 15-30к на маркетплейсе — универсал. Болтается, съезжает, выглядит дёшево.\n\n"
            f"Наши шьются конкретно под {car} — другой крой, другой материал, другой результат. "
            f"Стоимость от 65 000 тг, зато стоят 3-5 лет."
        ),
        "guarantee": (
            "Гарантия 6 месяцев на швы и материал 🛡\n\n"
            "Если что-то разошлось по нашей вине — переделаем бесплатно. "
            "За 7 лет работы таких случаев единицы — шьём плотно.\n\n"
            "Какой материал рассматриваете?"
        ),
        "delivery": (
            "Да, работаем по всему Казахстану 🇰🇿\n\n"
            "Пошив: 5-7 дней, экспресс 2 дня (+5 000 тг)\n"
            "Установка бесплатно — 2 часа\n"
            "Доставка по Астане бесплатная, в регионы — Казпочта или СДЭК\n\n"
            "Откуда вы?"
        ),
        "think": (
            "Без проблем, не тороплю 🙂\n\n"
            "Просто имейте в виду — пошив занимает 5-7 дней. "
            "Если надумаете, напишите — за день согласуем детали и запустим в работу."
        ),
        "not_interested": (
            "Понял 👍 Если надумаете — пишите, подберём."
        ),
        "negative_1": (
            f"Понял 🤝 Можно спросить — что смущает? Цена, сроки или что-то другое?\n\n"
            f"Спрашиваю потому что под {car} можем подобрать вариант в любой бюджет — "
            f"есть от 57 000 тг с бесплатной установкой."
        ),
        "negative_2": (
            f"Ок, не настаиваю 🙂\n\n"
            f"Последнее — многие берут чехлы именно перед продажей авто: "
            f"салон выглядит как новый и цену можно поднять на 100-200 тыс. "
            f"Если вдруг будет актуально — я здесь."
        ),
        "already_have": (
            "О, отлично что позаботились о салоне 👍\n\n"
            "Если захотите обновить или что-то износится — обращайтесь. "
            "Сделаем лучше."
        ),
        "price": (
            "Понимаю, давайте по конкретике 👍\n\n"
            f"Велюр на {car} — от 65 000 тг\n"
            "Тедди (самый популярный) — от 80 000 тг\n"
            "Экокожа — от 65 000 тг\n\n"
            "Всё с установкой и доставкой. Что ближе по бюджету?"
        ),
        "later": (
            "Понял 👍 Когда будет время — напишите, подберём под ваш запрос."
        ),
    }
    return responses.get(objection_type, responses["think"])


# ── Классификация входящих сообщений ───────────────────────────────────────

POSITIVE_KEYWORDS = [
    'да', 'интересно', 'расскажи', 'хочу', 'сколько', 'цена', 'прайс',
    'давай', 'окей', 'ок', 'хорошо', 'пришли', 'покажи', 'фото', 'можно',
    'конечно', 'почему нет', 'присылай', 'расскажите', 'покажите',
    'интересует', 'подходит', 'подойдёт', 'подойдет', 'напишите', 'пишите',
    'согласен', 'согласна', 'годится', 'ладно',
]

PRICE_KEYWORDS = [
    'сколько стоит', 'сколько стоят', 'какая цена', 'какие цены',
    'прайс', 'расценки', 'почём', 'почем', 'стоимость',
    'сколько будет стоить', 'прейскурант', 'прайс-лист',
    'пришли цены', 'пришлите цены', 'скиньте цены', 'скинь цены',
]

PHOTO_KEYWORDS = [
    'фото', 'фотки', 'покажи', 'покажите', 'посмотреть', 'пример', 'примеры',
    'образцы', 'как выглядит', 'видео', 'галерею', 'пришли фото', 'пришлите фото',
    'прислать фото', 'посмотрю', 'хочу видеть', 'хочу посмотреть',
]

NEGATIVE_KEYWORDS = [
    'нет', 'не надо', 'не интересно', 'не интересует', 'спасибо нет',
    'не нужно', 'не хочу', 'отстань', 'отвяжись', 'не беспокой',
    'стоп', 'хватит', 'не актуально', 'уже есть',
    'уже купил', 'уже купила',
]

THINK_KEYWORDS = [
    'подумаю', 'подумать', 'позже', 'потом', 'не сейчас', 'посмотрим',
    'может быть', 'возможно', 'не знаю', 'надо подумать',
]

DELIVERY_KEYWORDS = [
    'сроки', 'срок', 'как долго', 'доставка', 'установка', 'быстро',
    'когда будет', 'сколько дней', 'в регион', 'в другой город',
]

QUALITY_KEYWORDS = [
    'качество', 'надёжно', 'надежно', 'износ', 'прочность', 'отзывы',
]

MARKETPLACE_KEYWORDS = [
    'маркетплейс', 'aliexpress', 'wildberries', 'kaspi', 'ozon',
    'чем лучше', 'чем отличаете', 'чем принципиально', 'зачем дороже',
    'чем хуже', 'чем дороже', 'за 15 тысяч', 'за 30 тысяч', 'за 40 тысяч',
    'что даёте сверх', 'дешёвый', 'дешевый',
]

GUARANTEE_KEYWORDS = [
    'гарантия', 'гарантию', 'вернуть', 'возврат', 'брак', 'разойдутся',
    'порвётся', 'порвется', 'швы', 'качество швов',
]

DISCOUNT_KEYWORDS = [
    'скидка', 'скидку', 'дешевле', 'акция', 'промокод',
    'снизить цену', 'поторгуемся', 'скинете', 'скиньте цену',
    'дорого', 'дороговато', 'дороговато', 'большая цена',
    'высокая цена', 'цена высокая', 'цена дорогая', 'дорогая цена',
    'много стоит', 'слишком дорого',
]


def classify_message(text: str) -> str:
    """
    Классификация входящего сообщения.
    Приоритет: фото > цена > скидка > маркетплейс > гарантия > доставка > негатив > сомнение > качество > позитив
    """
    text_lower = text.lower().strip()

    if any(kw in text_lower for kw in PHOTO_KEYWORDS):
        return 'photo_request'
    if any(kw in text_lower for kw in PRICE_KEYWORDS):
        return 'price_request'
    if any(kw in text_lower for kw in DISCOUNT_KEYWORDS):
        return 'discount'
    if any(kw in text_lower for kw in MARKETPLACE_KEYWORDS):
        return 'vs_marketplace'
    if any(kw in text_lower for kw in GUARANTEE_KEYWORDS):
        return 'guarantee'
    if any(kw in text_lower for kw in DELIVERY_KEYWORDS):
        return 'delivery'
    if any(kw in text_lower for kw in NEGATIVE_KEYWORDS):
        return 'negative'
    if any(kw in text_lower for kw in THINK_KEYWORDS):
        return 'think'
    if any(kw in text_lower for kw in QUALITY_KEYWORDS):
        return 'quality_doubt'
    if any(kw in text_lower for kw in POSITIVE_KEYWORDS):
        return 'positive'
    return 'unknown'


# ── Основной класс бота ─────────────────────────────────────────────────────

class SalesBot:
    """
    Бот-продавец AUTOCOVERS.KZ.
    Интерфейс совместим с main.py:
      - bot.is_running / bot.stats
      - bot.start() / bot.stop()
      - bot._send_hook(listing, settings)
      - bot.handle_webhook(data)

    Стадии диалога в БД (поле status в listings):
      NEW           — собран парсером, ещё не контактировали
      HOOK_SENT     — отправили удочку, ждём ответа
      IN_SCRIPT     — клиент ответил, ведём по скрипту
      CATALOG_SENT  — отправили каталог/прайс
      FORM_SENT     — отправили форму заказа
      DONE          — сделка закрыта (won)
      REJECTED      — клиент отказался (Breakup)
    """

    def __init__(self):
        self.is_running = False
        self.stats = {
            'hooks_sent': 0,
            'replies_received': 0,
            'catalogs_sent': 0,
            'forms_sent': 0,
            'deals_closed': 0,
        }
        self._task = None
        self._processing = set()  # Номера которые сейчас обрабатываются

    # ── Свойства для доступа к зависимостям ───────────────────────────────
    # Берём глобальные синглтоны из database.py и whatsapp.py
    # чтобы не требовать передачи в конструктор

    @property
    def db(self):
        from database import db
        return db

    @property
    def wa(self):
        from whatsapp import wa
        return wa

    def _get_ai_client(self):
        """Возвращает AI-клиент на основе настроек."""
        try:
            settings = self.db.get_settings()
            provider = settings.get('ai_provider', 'openai')
            api_key = settings.get('ai_api_key', '')
            model = settings.get('ai_model', 'gpt-4o')
            if not api_key:
                return None
            from ai_client import AIClient
            return AIClient(provider=provider, api_key=api_key, model=model)
        except Exception:
            return None

    # ── Запуск / остановка ─────────────────────────────────────────────────

    async def start(self):
        self.is_running = True
        logger.info("SalesBot started (AUTOCOVERS.KZ cold sales)")
        while self.is_running:
            try:
                settings = self.db.get_settings()
                hour = datetime.now().hour
                start_h = settings.get('working_hours_start', 9)
                end_h = settings.get('working_hours_end', 21)
                if start_h <= hour < end_h:
                    await self._process_new_numbers(settings)
                    await self._process_followups(settings)
                else:
                    logger.debug(f"Outside working hours ({hour}h), skipping")

                # Читаем входящие ВСЕГДА (не только в рабочие часы)
                await self._poll_messages()

            except Exception as e:
                logger.error(f"Bot loop error: {e}")
            delay = settings.get('send_delay', 45) if 'settings' in dir() else 45
            await asyncio.sleep(delay)

    def stop(self):
        self.is_running = False
        logger.info("SalesBot stopped")

    # ── Обработка новых номеров (первый контакт — AIDA) ───────────────────

    async def _process_new_numbers(self, settings: dict):
        """Отправляем удочки по AIDA новым номерам."""
        limit = settings.get('daily_hooks_limit', 100)
        listings = self.db.get_listings(status='NEW', limit=min(limit, 5))

        # Фильтруем по whitelist если он задан
        whitelist = settings.get('whitelist', [])
        if whitelist:
            # Нормализуем whitelist — только цифры
            clean_wl = set()
            for w in whitelist:
                digits = ''.join(c for c in str(w) if c.isdigit())
                if digits:
                    # Поддерживаем оба формата: 77001234567 и 7001234567
                    clean_wl.add(digits)
                    if digits.startswith('7') and len(digits) == 11:
                        clean_wl.add(digits[1:])  # без первой 7
                    elif len(digits) == 10:
                        clean_wl.add('7' + digits)  # с 7

            filtered = []
            for listing in listings:
                phone_clean = listing.get('phone_clean', '')
                digits = ''.join(c for c in phone_clean if c.isdigit())
                if digits in clean_wl:
                    filtered.append(listing)
                else:
                    logger.debug(f"Whitelist skip: {phone_clean}")
            listings = filtered

        if not listings:
            logger.debug("No new listings to process (whitelist active or empty queue)")
            return

        for listing in listings:
            await self._send_hook(listing, settings)
            await asyncio.sleep(random.uniform(15, 45))

    async def _send_hook(self, listing: dict, settings: dict = None):
        """
        Первое сообщение — "удочка" по AIDA + Pattern Interrupt.
        listing: dict с полями phone, car_brand, car_model, year
        settings: dict настроек (опционально)
        """
        phone = listing.get('phone', '')
        # Очищаем номер для Green API (формат: 77001234567)
        phone_clean = listing.get('phone_clean') or phone.replace('+', '').replace(' ', '')

        car_brand = listing.get('car_brand', '')
        car_model = listing.get('car_model', '')
        car_year = listing.get('year')

        # Если задан кастомный first_message в настройках — используем его
        # иначе генерируем по AIDA
        if settings:
            custom_first = settings.get('first_message', '').strip()
        else:
            custom_first = ''

        if custom_first:
            car_full = f"{car_brand} {car_model}".strip()
            year_str = str(car_year) if car_year else ""
            message = (custom_first
                .replace('{brand}', car_brand)
                .replace('{model}', car_model)
                .replace('{car}', car_full)
                .replace('{year}', year_str))
        else:
            message = get_hook_message(car_brand, car_model, car_year)

        success = await self.wa.send_message(phone_clean, message)
        if success:
            self.db.update_listing_status(phone_clean, 'HOOK_SENT')
            # Обновляем last_contact чтобы followup не ушёл сразу
            self.db.update_last_contact(phone_clean)
            # Создаём conversation чтобы диалог был виден в разделе Диалоги
            conv = self.db.get_or_create_conversation(listing['id'], phone_clean)
            self.db.save_message(conv['id'], message, 'OUTGOING', is_ai=True)
            self.stats['hooks_sent'] += 1
            logger.info(f"✅ Hook sent → {phone_clean} ({car_brand} {car_model})")
        else:
            logger.error(f"❌ Hook failed → {phone_clean}")

    # ── Повторные касания — Эффект Эха ────────────────────────────────────

    async def _process_followups(self, settings: dict):
        """
        Повторные касания для тех кто не ответил.
        Максимум 3 попытки. После — Breakup.
        """
        listings = self.db.get_listings_for_followup(
            status='HOOK_SENT',
            hours_since_last=24,
            max_followups=3
        )
        for listing in listings:
            await self._send_followup(listing)
            await asyncio.sleep(random.uniform(20, 60))

    async def _send_followup(self, listing: dict):
        attempt = listing.get('followup_count', 0) + 1
        phone_clean = listing.get('phone_clean') or listing.get('phone', '').replace('+', '')
        car_brand = listing.get('car_brand', '')
        car_model = listing.get('car_model', '')

        message = get_followup_message(car_brand, car_model, attempt)
        success = await self.wa.send_message(phone_clean, message)

        if success:
            self.db.increment_followup_count(phone_clean)
            self.db.update_last_contact(phone_clean)
            conv = self.db.get_or_create_conversation(listing['id'], phone_clean)
            self.db.save_message(conv['id'], message, 'OUTGOING', is_ai=True)

            if attempt >= 3:
                self.db.update_listing_status(phone_clean, 'REJECTED')

    # ── Webhook от Green API ───────────────────────────────────────────────

    async def _poll_messages(self):
        """Читает входящие сообщения из Green API (polling режим)."""
        try:
            for _ in range(10):  # До 10 сообщений за цикл
                notification = await self.wa.receive_notification()
                if not notification:
                    break
                receipt_id = notification.get('receiptId')
                body = notification.get('body', {})

                # Удаляем уведомление из очереди
                if receipt_id:
                    await self.wa.delete_notification(receipt_id)

                if body:
                    await self.handle_webhook(body)

        except Exception as e:
            logger.error(f"Poll messages error: {e}")

    async def handle_webhook(self, data: dict):
        """
        Обработка входящего вебхука от Green API.
        Формат: {"typeWebhook": "incomingMessageReceived", "senderData": {...}, "messageData": {...}}
        """
        try:
            webhook_type = data.get('typeWebhook', '')

            # Обрабатываем только входящие текстовые сообщения
            if webhook_type != 'incomingMessageReceived':
                return

            sender_data = data.get('senderData', {})
            message_data = data.get('messageData', {})
            type_msg = message_data.get('typeMessage', '')

            # Достаём номер телефона
            chat_id = sender_data.get('chatId', '')
            phone_clean = chat_id.replace('@c.us', '').replace('@g.us', '')

            # Игнорируем групповые чаты
            if '@g.us' in chat_id:
                return

            # ── Извлекаем текст в зависимости от типа сообщения ──
            text = ''

            if type_msg == 'textMessage':
                text = message_data.get('textMessageData', {}).get('textMessage', '').strip()

            elif type_msg == 'quotedMessage':
                # Клиент цитирует сообщение бота и пишет ответ
                ext = message_data.get('extendedTextMessageData', {})
                text = ext.get('text', '').strip()

            elif type_msg == 'extendedTextMessage':
                text = message_data.get('extendedTextMessageData', {}).get('text', '').strip()

            elif type_msg in ('audioMessage', 'pttMessage'):
                # Голосовое сообщение — транскрибируем через Groq (бесплатно) или OpenAI
                file_data = message_data.get('fileMessageData', {})
                download_url = file_data.get('downloadUrl', '')
                if download_url:
                    settings = self.db.get_settings()
                    # Приоритет: AssemblyAI → Groq → OpenAI
                    if settings.get('assemblyai_api_key'):
                        whisper_key = settings['assemblyai_api_key']
                        whisper_provider = 'assemblyai'
                    elif settings.get('groq_api_key'):
                        whisper_key = settings['groq_api_key']
                        whisper_provider = 'groq'
                    else:
                        whisper_key = settings.get('ai_api_key', '')
                        whisper_provider = settings.get('ai_provider', 'openai')

                    if whisper_key:
                        logger.info(f"🎤 Аудио от {phone_clean} — транскрибируем через {whisper_provider}...")
                        text = await self.wa.transcribe_audio(download_url, whisper_key, whisper_provider)
                        if text:
                            logger.info(f"🎤 Транскрипция: {text[:80]}")
                        else:
                            await self.wa.send_message(phone_clean,
                                "Не удалось распознать голосовое, напишите текстом 🙏")
                            return
                    else:
                        await self.wa.send_message(phone_clean,
                            "Голосовые сообщения пока не поддерживаются, напишите текстом 🙏")
                        return

            if not text:
                return

            self.stats['replies_received'] += 1
            logger.info(f"📩 Incoming from {phone_clean}: {text[:60]}")

            # Проверяем whitelist
            settings = self.db.get_settings()
            whitelist = settings.get('whitelist', [])
            if whitelist:
                clean_wl = set()
                for w in whitelist:
                    digits = ''.join(c for c in str(w) if c.isdigit())
                    if digits:
                        clean_wl.add(digits)
                        if digits.startswith('7') and len(digits) == 11:
                            clean_wl.add(digits[1:])
                        elif len(digits) == 10:
                            clean_wl.add('7' + digits)
                phone_digits = ''.join(c for c in phone_clean if c.isdigit())
                if phone_digits not in clean_wl:
                    logger.debug(f"Whitelist: ignoring incoming from {phone_clean}")
                    return

            # Ищем листинг в БД по номеру
            listing = self.db.get_listing_by_phone(phone_clean)
            if not listing:
                logger.debug(f"Unknown number: {phone_clean}, ignoring")
                return

            # Защита от дублей — если уже обрабатываем этот номер, пропускаем
            if phone_clean in self._processing:
                logger.debug(f"Already processing {phone_clean}, skipping duplicate")
                return
            self._processing.add(phone_clean)

            await self.handle_incoming(phone_clean, text, listing)

        except Exception as e:
            logger.error(f"Webhook processing error: {e}")
        finally:
            self._processing.discard(phone_clean)

    # ── Обработка входящих сообщений ──────────────────────────────────────

    async def handle_incoming(self, phone_clean: str, text: str, listing: dict):
        """
        Главная логика ответа на сообщение клиента.
        LAER для возражений, скрипт для позитива, Shut Up после CTA.
        """
        # Получаем/создаём conversation для этого листинга
        conv = self.db.get_or_create_conversation(listing['id'], phone_clean)
        self.db.save_message(conv['id'], text, 'INCOMING', is_ai=False)

        car_brand = listing.get('car_brand', '')
        car_model = listing.get('car_model', '')
        status = listing.get('status', 'NEW')
        classification = classify_message(text)

        logger.info(f"[{phone_clean}] status={status} class={classification}")

        # Фото или цена → каталог (только если ещё не отправляли)
        if classification in ('photo_request', 'price_request'):
            if status == 'CATALOG_SENT':
                # Каталог уже отправлен — AI отвечает контекстно
                await self._ai_reply(phone_clean, listing, text)
            else:
                await self._send_catalog(phone_clean, listing)
            return

        # Скидка — конкретный ответ с ценностью
        if classification == 'discount':
            resp = (
                f"Скидок не делаем — и так включаем установку (2 часа) и доставку бесплатно 🙏\n\n"
                f"Это уже экономия 5-8 тыс тг по рынку.\n\n"
                f"Велюр на {car_brand} {car_model} — от 65 000 тг всё включено. Оформим?"
            )
            await self._send(phone_clean, listing.get('id'), resp)
            return

        # Сравнение с маркетплейсом — Challenger Sale
        if classification == 'vs_marketplace':
            resp = get_objection_response('vs_marketplace', car_brand, car_model)
            await self._send(phone_clean, listing.get('id'), resp)
            return

        # Гарантия
        if classification == 'guarantee':
            resp = get_objection_response('guarantee', car_brand, car_model)
            await self._send(phone_clean, listing.get('id'), resp)
            return

        # Доставка/сроки
        if classification == 'delivery':
            resp = get_objection_response('delivery', car_brand, car_model)
            await self._send(phone_clean, listing.get('id'), resp)
            return

        # Качество
        if classification == 'quality_doubt':
            resp = get_objection_response('quality_doubt', car_brand, car_model)
            await self._send(phone_clean, listing.get('id'), resp)
            return

        # "Подумаю"
        if classification == 'think':
            resp = get_objection_response('think', car_brand, car_model)
            await self._send(phone_clean, listing.get('id'), resp)
            return

        # Явный отказ — применяем LAER, breakup только на 3-й раз
        if classification == 'negative':
            ai_attempts = listing.get('ai_attempts', 0)

            if ai_attempts == 0:
                # 1-й отказ — LAER: выясняем причину, предлагаем ценность
                resp = get_objection_response('negative_1', car_brand, car_model)
                await self._send(phone_clean, listing.get('id'), resp)
                self.db.update_listing_ai_attempts(phone_clean, 1)

            elif ai_attempts == 1:
                # 2-й отказ — AI дожим с историей диалога
                if status == 'CATALOG_SENT':
                    await self._ai_push(phone_clean, listing)
                else:
                    resp = get_objection_response('negative_2', car_brand, car_model)
                    await self._send(phone_clean, listing.get('id'), resp)
                    self.db.update_listing_ai_attempts(phone_clean, 2)

            else:
                # 3-й отказ — Breakup с достоинством
                msg = get_breakup_message(car_brand, car_model)
                await self._send(phone_clean, listing.get('id'), msg)
                await self._send(phone_clean, listing.get('id'), get_instagram_message())
                self.db.update_listing_status(phone_clean, 'REJECTED')
            return

        # Позитив / неизвестно → двигаем по скрипту или AI отвечает
        if status == 'CATALOG_SENT':
            # Каталог уже был отправлен — AI отвечает контекстно
            await self._ai_reply(phone_clean, listing, text)
        else:
            await self._advance_script(phone_clean, listing, text)

    async def _advance_script(self, phone_clean: str, listing: dict, client_text: str):
        """Продвижение по скрипту. Когда скрипт пройден → каталог."""
        script_step = listing.get('script_step', 0)

        if script_step < len(SALES_SCRIPT):
            message = SALES_SCRIPT[script_step]
            await self._send(phone_clean, listing.get('id'), message)
            # Обновляем и в БД и в объекте listing в памяти
            new_step = script_step + 1
            self.db.update_listing_script_step(phone_clean, new_step)
            listing['script_step'] = new_step
            self.db.update_listing_status(phone_clean, 'IN_SCRIPT')
        else:
            # Скрипт пройден — отправляем каталог
            await self._send_catalog(phone_clean, listing)

    async def _send_catalog(self, phone_clean: str, listing: dict):
        """
        Отправляем персонализированный каталог:
        1. Фото работ (общие)
        2. Прайс под тип авто
        3. PDF каталог
        4. CTA — конкретный вопрос (Shut Up техника)
        Instagram — только в конце сделки или при breakup
        """
        listing_id = listing.get('id')
        car_brand = listing.get('car_brand', '')
        car_model = listing.get('car_model', '')
        car_year = listing.get('year')

        # 1. Фото работ
        photos = get_sample_photos()
        if photos:
            for photo_path in photos[:5]:
                await self.wa.send_file_by_upload(phone_clean, photo_path, "Наши работы 🎨")

        # 2. Прайс под тип авто
        price_msg = get_price_message(car_brand, car_model, car_year)
        await self._send(phone_clean, listing_id, price_msg)

        # 3. PDF каталог
        if os.path.exists(CATALOG_PDF_PATH):
            await self.wa.send_file_by_upload(
                phone_clean, CATALOG_PDF_PATH,
                "📄 Полный каталог AUTOCOVERS.KZ 2025"
            )

        # 4. CTA — предлагаем выбор и МОЛЧИМ (Shut Up)
        crossover = is_crossover(car_brand, car_model)
        car_type = "кроссовер/внедорожник" if crossover else "легковой"
        cta = (
            f"Выбрали что-нибудь? 🙂\n\n"
            f"Для вашего {car_brand} {car_model} ({car_type}) — "
            f"что интереснее: Велюр, Тедди или Экокожа?"
        )
        await self._send(phone_clean, listing_id, cta)

        self.db.update_listing_status(phone_clean, 'CATALOG_SENT')
        self.stats['catalogs_sent'] += 1

    async def _handle_negative(self, phone_clean: str, listing: dict):
        """
        Клиент отказал. AI-дожим если ещё не пробовали, потом Breakup.
        """
        status = listing.get('status', '')
        ai_attempts = listing.get('ai_attempts', 0)

        if status == 'CATALOG_SENT' and ai_attempts < 2:
            await self._ai_push(phone_clean, listing)
        else:
            message = get_breakup_message(
                listing.get('car_brand', ''),
                listing.get('car_model', '')
            )
            await self._send(phone_clean, listing.get('id'), message)
            await self._send(phone_clean, listing.get('id'), get_instagram_message())
            self.db.update_listing_status(phone_clean, 'REJECTED')

    async def _ai_push(self, phone_clean: str, listing: dict):
        """AI-дожим через LAER. Не более 2 раз."""
        listing_id = listing.get('id')
        ai_attempts = listing.get('ai_attempts', 0)
        settings = self.db.get_settings()

        # Берём system prompt из настроек или встроенный
        system_prompt = settings.get('ai_system_prompt', '').strip() or AI_SYSTEM_PROMPT

        # История диалога из conversations
        conv = self.db.get_conversation_by_phone(phone_clean)
        history = self.db.get_message_history(conv['id'], 10) if conv else []

        car = f"{listing.get('car_brand','')} {listing.get('car_model','')}".strip()
        user_prompt = (
            f"Авто клиента: {car}\n"
            f"Ситуация: клиент получил каталог с фото и ценами, вёл диалог, "
            f"и теперь говорит что передумал или не хочет (попытка #{ai_attempts + 1}).\n\n"
            f"ЗАДАЧА: НЕ сдавайся. Применяй LAER:\n"
            f"- Acknowledge: коротко признай\n"
            f"- Explore: задай ОДИН вопрос чтобы понять реальную причину\n"
            f"(Цена? Сроки? Жена не разрешила? Уже купил где-то?)\n\n"
            f"2-3 предложения. После вопроса — СТОП."
        )

        ai = self._get_ai_client()
        try:
            if ai:
                response = await ai.complete(system_prompt, user_prompt, history)
            else:
                response = None

            if response and response.strip():
                await self._send(phone_clean, listing_id, response.strip())
                self.db.update_listing_ai_attempts(phone_clean, ai_attempts + 1)
            else:
                raise ValueError("Empty AI response")
        except Exception as e:
            logger.error(f"AI push failed: {e}")
            msg = get_breakup_message(listing.get('car_brand', ''), listing.get('car_model', ''))
            await self._send(phone_clean, listing_id, msg)
            self.db.update_listing_status(phone_clean, 'REJECTED')

    async def _ai_reply(self, phone_clean: str, listing: dict, client_text: str):
        """AI-ответ на нейтральное/непонятное сообщение после каталога."""
        listing_id = listing.get('id')
        settings = self.db.get_settings()
        system_prompt = settings.get('ai_system_prompt', '').strip() or AI_SYSTEM_PROMPT

        conv = self.db.get_conversation_by_phone(phone_clean)
        history = self.db.get_message_history(conv['id'], 8) if conv else []

        car = f"{listing.get('car_brand','')} {listing.get('car_model','')}".strip()
        user_prompt = (
            f"Авто клиента: {car}\n"
            f"Сообщение: {client_text}\n\n"
            f"Ответь по делу, 1-3 предложения. Продвигай к выбору материала или оформлению."
        )

        ai = self._get_ai_client()
        try:
            if ai:
                response = await ai.complete(system_prompt, user_prompt, history)
                if response and response.strip():
                    await self._send(phone_clean, listing_id, response.strip())
                    return
        except Exception as e:
            logger.error(f"AI reply failed: {e}")

        # Fallback без AI
        await self._send(phone_clean, listing_id,
            "Подскажите что интереснее — Велюр, Тедди или Экокожа? Подберём под ваш вкус 👍"
        )

    async def handle_form_submitted(self, phone_clean: str, form_data: dict):
        """Клиент заполнил форму — подтверждение + Instagram."""
        listing = self.db.get_listing_by_phone(phone_clean)
        listing_id = listing.get('id') if listing else None

        confirm = (
            "🎉 Отлично! Заявка принята!\n\n"
            "Наш менеджер свяжется с вами для уточнения деталей.\n\n"
            "Пошив: 5-7 дней (экспресс 2 дня +5 000 тг)\n"
            "Установка: 2 часа, бесплатно\n"
            "Доставка: бесплатно\n\n"
            "Спасибо что выбрали AUTOCOVERS.KZ! 🚗✨"
        )
        await self._send(phone_clean, listing_id, confirm)
        await self._send(phone_clean, listing_id, get_instagram_message())

        self.db.update_listing_status(phone_clean, 'DONE')
        self.stats['deals_closed'] += 1

    # ── Вспомогательные методы ─────────────────────────────────────────────

    async def _send(self, phone_clean: str, listing_id, text: str):
        """Отправка сообщения с индикатором печатания + сохранение в БД."""
        # Показываем "печатает..." пропорционально длине текста (1-4 сек)
        typing_time = min(max(len(text) // 60, 1), 4)
        await self.wa.send_typing(phone_clean, typing_time)

        success = await self.wa.send_message(phone_clean, text)
        if success:
            if listing_id and not str(listing_id).startswith('test_'):
                conv = self.db.get_or_create_conversation(listing_id, phone_clean)
                self.db.save_message(conv['id'], text, 'OUTGOING', is_ai=True)
        else:
            logger.error(f"Send failed → {phone_clean}")
        return success


# ── Режим самотестирования (обкатка бота) ──────────────────────────────────

class SelfTestConversation:
    """
    Симуляция диалога бота с самим собой для обкатки и тестирования.
    Бот играет роль клиента через AI, отвечая на свои же сообщения.
    """

    def __init__(self, bot_instance: SalesBot, listing: dict):
        self.bot = bot_instance
        self.listing = listing
        self.phone = listing.get('phone_clean') or listing.get('phone', '').replace('+', '')
        self.history: list[tuple[str, str]] = []  # [(role, message), ...]
        self.max_turns = 20
        self.turn = 0
        self._captured_bot_messages: list[str] = []
        self._original_send = None
        self._original_send_hook = None
        self._original_wa_send = None

    def _patch_bot_methods(self):
        """Патчим методы бота чтобы перехватывать исходящие сообщения."""
        # Сохраняем оригиналы
        self._original_send = self.bot._send
        self._original_send_hook = self.bot._send_hook
        self._original_wa_send = self.bot.wa.send_message

        listing_id = self.listing.get('id')

        # Патчим _send
        async def patched_send(phone_clean, lid, text):
            self._captured_bot_messages.append(text)
            # Сохраняем в БД напрямую чтобы _get_last_bot_message тоже работал
            if lid:
                self.bot.db.save_message(lid, 'out', text)
            return True
        self.bot._send = patched_send

        # Патчим wa.send_message чтобы перехватывать все сообщения
        async def patched_wa_send(phone, message):
            self._captured_bot_messages.append(message)
            # Сохраняем в БД
            self.bot.db.save_message(listing_id, 'out', message)
            return True
        self.bot.wa.send_message = patched_wa_send

        # Патчим _send_hook
        async def patched_send_hook(listing, settings):
            phone = listing.get('phone', '')
            phone_clean = listing.get('phone_clean') or phone.replace('+', '').replace(' ', '')
            car_brand = listing.get('car_brand', '')
            car_model = listing.get('car_model', '')
            car_year = listing.get('year')

            if settings:
                custom_first = settings.get('first_message', '').strip()
            else:
                custom_first = ''

            if custom_first:
                car_full = f"{car_brand} {car_model}".strip()
                year_str = str(car_year) if car_year else ""
                message = (custom_first
                    .replace('{brand}', car_brand)
                    .replace('{model}', car_model)
                    .replace('{car}', car_full)
                    .replace('{year}', year_str))
            else:
                message = get_hook_message(car_brand, car_model, car_year)

            # Сохраняем и в список, и в БД
            self._captured_bot_messages.append(message)
            self.bot.db.save_message(listing.get('id'), 'out', message)
            self.bot.db.update_listing_status(phone_clean, 'HOOK_SENT')
            self.bot.stats['hooks_sent'] += 1
            logger.info(f"✅ Hook sent → {phone_clean} ({car_brand} {car_model})")
            return True
        self.bot._send_hook = patched_send_hook

    def _unpatch_bot_methods(self):
        """Восстанавливаем оригинальные методы."""
        if self._original_send:
            self.bot._send = self._original_send
        if self._original_send_hook:
            self.bot._send_hook = self._original_send_hook
        if self._original_wa_send:
            self.bot.wa.send_message = self._original_wa_send

    def _get_last_captured_message(self) -> str:
        """Получаем последнее перехваченное сообщение бота."""
        if self._captured_bot_messages:
            return self._captured_bot_messages[-1]
        return "(нет сообщения)"

    async def run(self):
        """Запускает самотестирование — бот разговаривает сам с собой."""
        logger.info(f"🎭 Self-test started for {self.phone}")

        # Патчим методы бота
        self._patch_bot_methods()

        try:
            # Начинаем с отправки удочки
            await self.bot._send_hook(self.listing, {})
            hook_msg = self._get_last_captured_message()
            self.history.append(('bot', hook_msg))
            logger.info(f"🎭 [Start] Bot hook: {hook_msg[:80]}...")

            for i in range(self.max_turns):
                self.turn = i + 1

                # AI играет роль клиента и отвечает на последнее сообщение бота
                client_response = await self._simulate_client_response()
                if not client_response:
                    break
                self.history.append(('client', client_response))
                logger.info(f"🎭 [Turn {self.turn}] Client: {client_response[:80]}...")

                # Бот обрабатывает ответ клиента
                await self.bot.handle_incoming(self.phone, client_response, self.listing)
                bot_response = self._get_last_captured_message()
                self.history.append(('bot', bot_response))
                logger.info(f"🎭 [Turn {self.turn}] Bot: {bot_response[:80]}...")

                # Проверяем условия завершения
                if self._should_end_conversation():
                    logger.info(f"🎭 Self-test ended at turn {self.turn}")
                    break

                await asyncio.sleep(1)

        finally:
            # Восстанавливаем оригинальные методы
            self._unpatch_bot_methods()

        return self.history

    async def _simulate_client_response(self) -> str | None:
        """AI симулирует ответ типичного клиента на основе истории."""
        ai = self.bot._get_ai_client()
        if not ai:
            # Заглушка если AI не настроен
            responses = [
                "Интересно, сколько стоит?",
                "Какие материалы есть?",
                "Подумаю, напишу позже",
                "Нет, не нужно",
                "Пришлите фото",
            ]
            return random.choice(responses)

        car = f"{self.listing.get('car_brand', '')} {self.listing.get('car_model', '')}".strip()

        # Полная история для памяти
        full_history = "\n".join([
            f"{'Менеджер' if r == 'bot' else 'Клиент'}: {m}"
            for r, m in self.history
        ])
        # Последние 6 для контекста
        recent = "\n".join([
            f"{'Менеджер' if r == 'bot' else 'Клиент'}: {m}"
            for r, m in self.history[-6:]
        ])

        # Уже заданные клиентом вопросы — для памяти
        client_questions = [m for r, m in self.history if r == 'client']
        asked_topics = []
        if any('фото' in q.lower() or 'покажи' in q.lower() for q in client_questions):
            asked_topics.append('фото')
        if any('скидк' in q.lower() for q in client_questions):
            asked_topics.append('скидка')
        if any('сколько' in q.lower() or 'цена' in q.lower() for q in client_questions):
            asked_topics.append('цена')
        if any('доставк' in q.lower() or 'сроки' in q.lower() for q in client_questions):
            asked_topics.append('доставка')

        stage = "начало"
        if len(self.history) > 6:
            stage = "середина"
        if len(self.history) > 14:
            stage = "финал"

        prompt = f"""Ты — реальный покупатель авточехлов для {car}. Ведёшь переписку в WhatsApp.

Стадия диалога: {stage} ({len(self.history)} сообщений)

Последние сообщения:
{recent}

Темы которые ты УЖЕ спрашивал (НЕ повторяй): {', '.join(asked_topics) if asked_topics else 'ничего'}

ПРАВИЛА поведения:
- Пиши коротко (1-2 предложения), разговорный стиль без лишних слов
- НЕ повторяй вопросы которые уже задавал
- Реагируй на последнее сообщение бота — отвечай именно на него
- Если бот прислал цены — прокомментируй конкретно ("Велюр за 65к — норм, а Тедди чем лучше?")
- Если бот прислал фото — оцени ("Неплохо смотрится! А в чёрном есть?")
- Если бот задал вопрос — ответь на него, потом можешь добавить свой

Варианты тем (выбери незаданную, соответствующую стадии):
- {stage == "начало"}: "Покажите фото на похожей модели" / "А цены у вас какие?" / "Какой материал популярнее?"
- {stage == "середина"}: "Хорошо, берём Тедди — как заказать?" / "А гарантия есть?" / "Вы только в Астане?"  
- {stage == "финал"}: "Ладно, давайте оформим" / "Можно сначала посмотреть живьём?" / "Ок, пришлите реквизиты"

Ответ клиента (только текст, без кавычек):"""

        try:
            response = await ai.complete(
                "Ты реалистичный казахстанский покупатель авточехлов. Отвечаешь коротко и по делу.",
                prompt
            )
            return response.strip() if response else "Ладно, пришлите цены"
        except Exception as e:
            logger.error(f"AI client simulation failed: {e}")
            # Умная заглушка с учётом истории
            fallbacks = [q for q in [
                "Ладно, пришлите прайс" if 'цена' not in asked_topics else None,
                "А фото есть?" if 'фото' not in asked_topics else None,
                "Хорошо, как заказать?",
                "И сколько по времени делаете?",
                "Ок, давайте попробуем",
            ] if q]
            return fallbacks[0] if fallbacks else "Интересно, расскажите подробнее"

    def _get_last_bot_message(self) -> str:
        """Получает последнее сообщение бота из БД."""
        messages = self.bot.db.get_messages(self.listing.get('id')) or []
        for m in reversed(messages):
            if m.get('direction') == 'out':
                return m.get('text', '')
        return ""

    def _should_end_conversation(self) -> bool:
        """Проверяет условия завершения диалога."""
        last_client = self.history[-2][1] if len(self.history) >= 2 else ""
        last_bot = self.history[-1][1] if self.history else ""

        # Не завершаем рано — минимум 8 сообщений
        if len(self.history) < 8:
            return False

        # Клиент отказал категорично (только на поздних этапах)
        if len(self.history) > 12:
            hard_no = ['не нужно', 'не интересно', 'отстань', 'не пишите']
            if any(kw in last_client.lower() for kw in hard_no):
                return True

        # Бот сказал прощаться
        if any(kw in last_bot.lower() for kw in ['удачи с авто', 'всего доброго', 'до свидания']):
            return True

        # Статус завершён
        status = self.listing.get('status', '')
        if status in ('DONE', 'REJECTED'):
            return True

        # Достигнут лимит ходов
        if self.turn >= self.max_turns:
            return True

        return False


async def run_self_test(bot_instance: SalesBot, test_listing: dict | None = None):
    """
    Запускает режим обкатки — бот разговаривает сам с собой.
    Если test_listing не передан — создаёт фиктивный листинг.
    """
    if test_listing is None:
        test_listing = {
            'id': 'self_test_001',
            'phone': '77000000000',
            'phone_clean': '77000000000',
            'car_brand': 'Toyota',
            'car_model': 'Camry',
            'year': 2023,
            'status': 'NEW',
            'script_step': 0,
            'followup_count': 0,
        }
        # Сохраняем в БД для полноты симуляции
        try:
            bot_instance.db.save_listing(test_listing)
        except Exception:
            pass

    conversation = SelfTestConversation(bot_instance, test_listing)
    history = await conversation.run()

    # Выводим итог
    print("\n" + "="*60)
    print("🎭 САМОТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
    print("="*60)
    for role, msg in history:
        role_label = "🤖 БОТ" if role == 'bot' else "👤 КЛИЕНТ"
        print(f"\n{role_label}:\n{msg}")
    print("\n" + "="*60)

    return history


# ── Глобальный синглтон — именно его импортирует main.py ───────────────────
bot = SalesBot()
