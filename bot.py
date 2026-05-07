import asyncio
import json
import re
from datetime import datetime
from database import db
from whatsapp import wa

POSITIVE_SIGNALS = [
    'да', 'интересно', 'хочу', 'давай', 'ок', 'окей', 'конечно',
    'сколько', 'цена', 'стоимость', 'расскажи', 'подробнее',
    'можно', 'нужно', 'надо', 'хорошо', 'отлично', 'супер',
    'заказ', 'купить', 'взять', 'какие', 'есть', 'покажи'
]

# Только эти слова означают готовность купить — триггер для отправки формы
BUY_SIGNALS = [
    'оформить', 'заказать', 'беру', 'покупаю', 'оплатить',
    'хочу заказать', 'давай оформим', 'согласен', 'договорились',
    'ок оформляем', 'да оформляй', 'куплю', 'берем'
]

NEGATIVE_SIGNALS = [
    'нет', 'не интересно', 'не надо', 'не нужно', 'отказ',
    'не хочу', 'не буду', 'стоп', 'хватит', 'уберите',
    'отстаньте', 'не беспокойте', 'не особо', 'неособо',
    'не очень', 'неочень', 'не нужны', 'не хочу', 'пока не',
    'спасибо нет', 'спс нет', 'не сейчас', 'не актуально',
    'говорю что', 'уже есть', 'не нужны коврики'
]

UNCERTAIN_SIGNALS = [
    'подумаю', 'может быть', 'посмотрим',
    'посоветуюсь', 'потом', 'позже', 'не срочно'
]


def is_positive(text: str) -> bool:
    t = text.lower()
    return any(s in t for s in POSITIVE_SIGNALS)

def is_negative(text: str) -> bool:
    t = text.lower()
    return any(s in t for s in NEGATIVE_SIGNALS)

def is_uncertain(text: str) -> bool:
    t = text.lower()
    return any(s in t for s in UNCERTAIN_SIGNALS)

def extract_name(text: str) -> str:
    m = re.search(r'меня зовут ([А-ЯЁа-яёa-zA-Z]+)', text, re.IGNORECASE)
    if m: return m.group(1)
    m = re.match(r'^([А-ЯЁа-яё][а-яё]{1,14})$', text.strip())
    if m: return m.group(1)
    return ''

def build_message(template: str, vars: dict) -> str:
    result = template
    for key, value in vars.items():
        result = result.replace('{' + key + '}', str(value or ''))
    return result

def get_car_str(listing: dict) -> str:
    parts = [listing.get('car_brand',''), listing.get('car_model','')]
    if listing.get('year'):
        parts.append(str(listing['year']))
    return ' '.join(filter(None, parts)) or 'автомобиля'


# Permanently blocked message IDs (stuck in Green API queue)
BLOCKED_MESSAGE_IDS = {
    'AC255DDB5CE0865607A8E8A12B5D502F',
}

class Bot:
    def __init__(self):
        self.is_running = False
        self.stats = {'sent_today': 0, 'replies_today': 0}
        self._processed_receipts = set()
        self._processed_messages = set()  # Track by idMessage

    def stop(self):
        self.is_running = False
        db.log('INFO', 'BOT', 'Бот остановлен')

    async def start(self):
        self.is_running = True
        self._processed_receipts = set()
        self._processed_messages = set()  # Track by idMessage
        db.log('INFO', 'BOT', 'Бот запущен')

        while self.is_running:
            try:
                settings = db.get_settings()

                hour = datetime.now().hour
                start_h = settings.get('working_hours_start', 9)
                end_h = settings.get('working_hours_end', 21)
                if hour < start_h or hour >= end_h:
                    await asyncio.sleep(60)
                    continue

                hooks_limit = settings.get('daily_hooks_limit', 100)
                if db.get_daily_sent_count() >= hooks_limit:
                    await asyncio.sleep(300)
                    continue

                # Отправка удочек
                whitelist = settings.get('whitelist', [])
                clean_wl = [w.replace('+','').replace(' ','') for w in whitelist]

                if clean_wl:
                    listings = [l for l in db.get_all_new_listings() if l['phone_clean'] in clean_wl]
                else:
                    listings = db.get_pending_listings()

                for listing in listings:
                    if not self.is_running:
                        break
                    await self._send_hook(listing, settings)
                    await asyncio.sleep(settings.get('send_delay', 45))

                # Получение входящих
                await self._poll_messages()

                await asyncio.sleep(30)

            except Exception as e:
                db.log('ERROR', 'BOT', f'Ошибка цикла: {e}')
                await asyncio.sleep(10)

    async def _send_hook(self, listing: dict, settings: dict):
        try:
            phone = listing['phone_clean']
            car = get_car_str(listing)

            whitelist = settings.get('whitelist', [])
            clean_wl = [w.replace('+','').replace(' ','') for w in whitelist]
            if clean_wl and phone not in clean_wl:
                db.log('INFO', 'BOT', f'Пропуск (не в whitelist): +{phone}')
                return

            script = settings.get('conversation_script', [])
            if script:
                first_step = sorted(script, key=lambda x: x.get('order', 0))[0]
                template = first_step.get('message', '')
            else:
                template = settings.get('first_message', '')

            if not template:
                template = 'Здравствуйте! 👋 Увидел ваше объявление на Kolesa.kz. Хотел предложить качественные автомобильные коврики для вашего {car}. Интересно?'

            msg = build_message(template, {'car': car, 'name': '', 'formLink': ''})

            success = await wa.send_message(phone, msg)
            if success:
                conv = db.get_or_create_conversation(listing['id'], phone)
                db.save_message(conv['id'], msg, 'OUTGOING', is_ai=True)
                db.update_listing_status(listing['id'], 'SENT')
                db.update_conversation(conv['id'], {'current_step': 1, 'status': 'ACTIVE'})
                db.log('INFO', 'BOT', f'🪝 Удочка: {phone} ({car})')
                self.stats['sent_today'] += 1
            else:
                db.update_listing_status(listing['id'], 'ERROR')

        except Exception as e:
            db.log('ERROR', 'BOT', f'Ошибка удочки: {e}')

    async def _poll_messages(self):
        try:
            for _ in range(5):
                notification = await wa.receive_notification()
                if not notification:
                    break

                receipt_id = notification.get('receiptId')
                body = notification.get('body', {})
                msg_id = body.get('idMessage', '') if body else ''

                # Удаляем уведомление СРАЗУ
                if receipt_id:
                    try:
                        await wa.delete_notification(receipt_id)
                    except Exception:
                        pass

                # Пропускаем заблокированные и уже обработанные
                if msg_id and (msg_id in BLOCKED_MESSAGE_IDS or msg_id in self._processed_messages):
                    continue

                if msg_id:
                    self._processed_messages.add(msg_id)
                    if len(self._processed_messages) > 2000:
                        self._processed_messages.clear()

                # Обрабатываем
                msg = wa.parse_incoming(notification)
                if msg:
                    await self._handle_incoming(msg)

        except Exception as e:
            db.log('ERROR', 'BOT', f'Ошибка polling: {e}')

    async def _handle_incoming(self, msg: dict):
        phone = msg['phone']
        text = msg['text']

        # Проверяем whitelist для входящих
        settings = db.get_settings()
        whitelist = settings.get('whitelist', [])
        clean_wl = [w.replace('+','').replace(' ','') for w in whitelist]
        if clean_wl and phone not in clean_wl:
            db.log('INFO', 'BOT', f'Входящее от {phone} — не в whitelist, пропуск')
            return

        db.log('INFO', 'BOT', f'📨 Входящее от {phone}: {text[:60]}')

        conv = db.get_conversation_by_phone(phone)
        if not conv:
            db.log('WARN', 'BOT', f'Диалог не найден: {phone}')
            return

        # Закрытые диалоги — не отвечаем
        if conv['status'] in ('FORM_SENT', 'COMPLETED', 'CLOSED'):
            db.log('INFO', 'BOT', f'Диалог закрыт ({conv["status"]}), пропуск')
            return

        db.save_message(conv['id'], text, 'INCOMING')
        self.stats['replies_today'] += 1

        settings = db.get_settings()

        outbound_limit = settings.get('daily_outbound_limit', 100)
        if db.get_daily_sent_count() >= outbound_limit:
            db.log('WARN', 'BOT', 'Лимит ответов достигнут')
            return

        positive = is_positive(text)
        negative = is_negative(text)
        uncertain = is_uncertain(text)

        db.log('INFO', 'BOT', f'Настроение: {"✅ позитив" if positive else "❌ отказ" if negative else "🤔 неуверен" if uncertain else "🔵 нейтрал"}')

        script = settings.get('conversation_script', [])
        if script:
            await self._process_script(conv, text, script, settings, positive, negative, uncertain)
        elif settings.get('ai_api_key'):
            await self._process_ai(conv, text, settings)
        else:
            db.log('WARN', 'BOT', 'Нет скрипта и AI ключа')

    async def _process_script(self, conv, text, script, settings, positive, negative, uncertain):
        try:
            sorted_script = sorted(script, key=lambda x: x.get('order', 0))
            current_step = conv.get('current_step', 0)
            ctx = json.loads(conv.get('ai_context') or '{}')
            name = extract_name(text) or ctx.get('name', '')
            if name:
                ctx['name'] = name

            listing = db.get_listing_by_id(conv['listing_id'])
            car = get_car_str(listing) if listing else 'автомобиля'
            form_link = f"http://localhost:8000/form/{conv['listing_id']}"
            vars = {'car': car, 'name': name, 'formLink': form_link}

            if negative:
                reply = await self._handle_rejection(conv, sorted_script, vars, settings, ctx)
                if reply:
                    await self._send_reply(conv, reply)
                    return

            if uncertain:
                reply = await self._handle_uncertainty(conv, vars, settings)
                if reply:
                    await self._send_reply(conv, reply)
                    return

            next_idx = current_step
            if next_idx < len(sorted_script):
                next_step = sorted_script[next_idx]
                msg = build_message(next_step.get('message', ''), vars)

                if msg.strip():
                    await self._send_reply(conv, msg)
                    update = {'current_step': current_step + 1}

                    if next_step.get('type') == 'form':
                        # После отправки формы — закрываем диалог
                        update['status'] = 'FORM_SENT'
                        db.update_listing_status(conv['listing_id'], 'FORM_SENT')
                        db.log('INFO', 'BOT', f'Форма отправлена, диалог закрыт: {conv["phone"]}')

                    if name:
                        update['ai_context'] = json.dumps(ctx)
                    db.update_conversation(conv['id'], update)
            else:
                if settings.get('ai_api_key'):
                    await self._process_ai(conv, text, settings)

        except Exception as e:
            db.log('ERROR', 'BOT', f'Ошибка скрипта: {e}')

    async def _handle_rejection(self, conv, script, vars, settings, ctx) -> str:
        objection_steps = [s for s in script if s.get('type') == 'objection']
        if objection_steps:
            step = objection_steps[0]
            if ctx.get('objection_used'):
                reply = step.get('objection_reply', '')
            else:
                reply = step.get('message', '')
                ctx['objection_used'] = True
            if reply:
                return build_message(reply, vars)

        if settings.get('ai_api_key'):
            history = db.get_message_history(conv['id'], 6)
            extra = '\n\nВАЖНО: Клиент отказывается. Предложи скидку или альтернативу. Будь настойчивым но вежливым. Ответь ОДНИМ коротким сообщением.'
            return await self._call_ai(settings, history, extra)
        return ''

    async def _handle_uncertainty(self, conv, vars, settings) -> str:
        if settings.get('ai_api_key'):
            history = db.get_message_history(conv['id'], 6)
            extra = '\n\nВАЖНО: Клиент сомневается. Развей сомнения коротко. Ответь ОДНИМ коротким сообщением.'
            return await self._call_ai(settings, history, extra)
        return build_message('Понимаю! 😊 Кстати, сейчас скидка 10% при заказе сегодня. Что скажете?', vars)

    async def _process_ai(self, conv, text, settings):
        try:
            history = db.get_message_history(conv['id'], 10)
            user_msgs = [m for m in history if m['direction'] == 'INCOMING']

            # Отправляем форму только при явном желании купить
            text_lower = text.lower()
            wants_to_buy = any(s in text_lower for s in BUY_SIGNALS)
            if len(user_msgs) >= 2 and wants_to_buy:
                form_link = f"http://localhost:8000/form/{conv['listing_id']}"
                form_msg = settings.get('form_message', 'Отлично! Заполните форму: {formLink}')
                form_msg = build_message(form_msg, {'formLink': form_link})
                await self._send_reply(conv, form_msg)
                db.update_conversation(conv['id'], {'status': 'FORM_SENT'})
                db.update_listing_status(conv['listing_id'], 'FORM_SENT')
                db.log('INFO', 'BOT', f'Форма отправлена AI, диалог закрыт: {conv["phone"]}')
                return

            reply = await self._call_ai(settings, history, '')
            if reply:
                await self._send_reply(conv, reply)

        except Exception as e:
            db.log('ERROR', 'BOT', f'Ошибка AI диалога: {e}')

    async def _call_ai(self, settings, history, extra_prompt) -> str:
        import requests as req
        api_key = settings.get('ai_api_key', '')
        provider = settings.get('ai_provider', 'openai')
        model = settings.get('ai_model', 'gpt-4o')
        system_prompt = settings.get('ai_prompt', 'Ты — менеджер по продажам автомобильных ковриков. Будь дружелюбным, отвечай коротко.') + extra_prompt

        messages = [{'role': 'system', 'content': system_prompt}]
        for m in history:
            role = 'user' if m['direction'] == 'INCOMING' else 'assistant'
            messages.append({'role': role, 'content': m['content']})

        try:
            if provider in ('openai', 'deepseek'):
                base_url = 'https://api.openai.com/v1' if provider == 'openai' else 'https://api.deepseek.com/v1'
                r = req.post(
                    f'{base_url}/chat/completions',
                    headers={'Authorization': f'Bearer {api_key}'},
                    json={'model': model, 'messages': messages, 'max_tokens': 200, 'temperature': 0.7},
                    timeout=15
                )
                return r.json().get('choices', [{}])[0].get('message', {}).get('content', '')

            elif provider == 'gemini':
                prompt = system_prompt + '\n\n'
                for m in history:
                    role = 'Клиент' if m['direction'] == 'INCOMING' else 'Менеджер'
                    prompt += f'{role}: {m["content"]}\n'
                prompt += 'Менеджер:'
                r = req.post(
                    f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}',
                    json={'contents': [{'parts': [{'text': prompt}]}]},
                    timeout=15
                )
                return r.json().get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')

        except Exception as e:
            db.log('ERROR', 'BOT', f'Ошибка AI: {e}')
        return ''

    async def _send_reply(self, conv, text):
        if not text.strip():
            return
        success = await wa.send_message(conv['phone'], text)
        if success:
            db.save_message(conv['id'], text, 'OUTGOING', is_ai=True)
            db.log('INFO', 'BOT', f'💬 Ответ: {conv["phone"]}')

    async def handle_webhook(self, data):
        msg = wa.parse_incoming({'body': data})
        if msg:
            await self._handle_incoming(msg)


bot = Bot()
