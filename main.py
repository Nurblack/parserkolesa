import asyncio
import json
import os
import logging
from datetime import datetime
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import List, Optional
import uvicorn
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

from database import db
from whatsapp import wa
from parser import parser
from bot import bot, run_self_test
from auth import login, verify_token

app = FastAPI(title="ParserKolesa")
app.mount("/static", StaticFiles(directory="public"), name="static")

# ─── Auth helpers ─────────────────────────────────────────────────────────────

def get_current_user(request: Request) -> dict:
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    if not token:
        token = request.cookies.get('token', '')
    user = verify_token(token)
    if not user:
        raise HTTPException(401, 'Не авторизован')
    return user

def require_admin(request: Request) -> dict:
    user = get_current_user(request)
    if user.get('role') != 'admin':
        raise HTTPException(403, 'Нет доступа')
    return user

# ─── Root ─────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return FileResponse("public/index.html")

@app.get("/login")
async def login_page():
    return FileResponse("public/login.html")

# ─── Auth ─────────────────────────────────────────────────────────────────────

class LoginModel(BaseModel):
    username: str
    password: str

@app.post("/api/auth/login")
async def auth_login(data: LoginModel):
    result = login(data.username, data.password)
    if not result:
        raise HTTPException(401, 'Неверный логин или пароль')
    return result

@app.get("/api/auth/me")
async def auth_me(request: Request):
    user = get_current_user(request)
    return user

# ─── Settings ─────────────────────────────────────────────────────────────────

class SettingsModel(BaseModel):
    green_api_instance_id: str = ""
    green_api_token: str = ""
    ai_provider: str = "openai"
    ai_api_key: str = ""
    ai_model: str = "gpt-4o"
    ai_prompt: str = ""
    groq_api_key: str = ""
    first_message: str = ""
    form_message: str = ""
    send_delay: int = 45
    daily_hooks_limit: int = 100
    daily_outbound_limit: int = 100
    working_hours_start: int = 9
    working_hours_end: int = 21
    conversation_script: list = []
    whitelist: list = []

@app.get("/api/settings")
async def get_settings(request: Request):
    get_current_user(request)
    return {"settings": db.get_settings()}

@app.put("/api/settings")
async def save_settings(data: SettingsModel, request: Request):
    require_admin(request)
    db.save_settings(data.dict())
    return {"success": True}

# ─── WhatsApp ─────────────────────────────────────────────────────────────────

@app.get("/api/whatsapp/status")
async def whatsapp_status(request: Request):
    get_current_user(request)
    status = await wa.get_status()
    return {"status": status}

@app.get("/api/whatsapp/qr")
async def whatsapp_qr(request: Request):
    require_admin(request)
    return {"qr_link": wa.get_qr_link()}

@app.post("/api/whatsapp/test")
async def whatsapp_test(data: dict, request: Request):
    require_admin(request)
    phone = data.get("phone", "").replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not phone:
        raise HTTPException(400, "Номер обязателен")
    result = await wa.send_message(phone, "🤖 Тест от ParserKolesa Bot")
    return {"success": result}

# ─── Parser ───────────────────────────────────────────────────────────────────

class ParserStartModel(BaseModel):
    urls: List[str]
    max_ads: int = 50
    delay_ms: int = 3000

@app.post("/api/parser/start")
async def parser_start(data: ParserStartModel, request: Request):
    get_current_user(request)
    if parser.is_running:
        raise HTTPException(400, "Парсер уже запущен")
    job_id = db.create_parser_job({"urls": data.urls, "max_ads": data.max_ads})
    parser.start_in_thread(job_id, data.urls, data.max_ads, data.delay_ms)
    return {"success": True, "job_id": job_id}

@app.post("/api/parser/stop")
async def parser_stop(request: Request):
    get_current_user(request)
    parser.stop()
    return {"success": True}

@app.get("/api/parser/status")
async def parser_status(request: Request):
    get_current_user(request)
    return {"is_running": parser.is_running, "stats": parser.stats}

# ─── Listings ─────────────────────────────────────────────────────────────────

@app.get("/api/listings")
async def get_listings(request: Request, status: str = "", limit: int = 200):
    require_admin(request)
    return {"listings": db.get_listings(status=status, limit=limit)}

@app.get("/api/listings/stats")
async def get_listing_stats(request: Request):
    get_current_user(request)
    return {"stats": db.get_listing_stats()}

@app.delete("/api/listings/{listing_id}")
async def delete_listing(listing_id: int, request: Request):
    require_admin(request)
    listing = db.get_listing_by_id(listing_id)
    if not listing:
        raise HTTPException(404, 'Номер не найден')
    with db.conn() as c:
        c.execute('DELETE FROM conversations WHERE listing_id=?', (listing_id,))
        c.execute('DELETE FROM listings WHERE id=?', (listing_id,))
    db.log('INFO', 'BOT', f'Номер удалён: {listing["phone"]}')
    return {'success': True}

@app.post('/api/listings/send-now')
async def send_now(data: dict, background_tasks: BackgroundTasks, request: Request):
    require_admin(request)
    listing_id = data.get('listing_id')
    if not listing_id:
        raise HTTPException(400, 'listing_id обязателен')
    listing = db.get_listing_by_id(listing_id)
    if not listing:
        raise HTTPException(404, 'Номер не найден')
    if listing['status'] != 'NEW':
        raise HTTPException(400, f'Статус: {listing["status"]}')
    settings = db.get_settings()
    background_tasks.add_task(bot._send_hook, listing, settings)
    return {'success': True}

class ManualListingModel(BaseModel):
    phone: str
    car_brand: str = ''
    car_model: str = ''
    year: Optional[int] = None
    city: str = ''
    price: str = ''

@app.post('/api/listings/add')
async def add_listing_manual(data: ManualListingModel, request: Request):
    require_admin(request)
    clean = data.phone.replace('+','').replace(' ','').replace('-','').replace('(','').replace(')','')
    if clean.startswith('8') and len(clean) == 11:
        clean = '7' + clean[1:]
    if not clean.startswith('7') or len(clean) != 11:
        raise HTTPException(400, 'Неверный формат номера')
    listing_id = db.save_listing({
        'source_url': 'manual',
        'title': ' '.join(filter(None, [data.car_brand, data.car_model, str(data.year or '')])),
        'price': data.price,
        'city': data.city,
        'car_brand': data.car_brand,
        'car_model': data.car_model,
        'year': data.year,
        'phone': f'+{clean}',
        'phone_clean': clean,
        'parser_job_id': None
    })
    if listing_id is None:
        raise HTTPException(400, 'Этот номер уже есть в базе')
    db.log('INFO', 'BOT', f'Номер добавлен вручную: +{clean}')
    return {'success': True, 'id': listing_id}

# ─── Bot ──────────────────────────────────────────────────────────────────────

@app.post("/api/bot/start")
async def bot_start(background_tasks: BackgroundTasks, request: Request):
    get_current_user(request)
    if bot.is_running:
        raise HTTPException(400, "Бот уже запущен")
    background_tasks.add_task(bot.start)
    return {"success": True}

@app.post("/api/bot/stop")
async def bot_stop(request: Request):
    get_current_user(request)
    bot.stop()
    return {"success": True}

@app.get("/api/bot/status")
async def bot_status(request: Request):
    get_current_user(request)
    return {"is_running": bot.is_running, "stats": bot.stats}

@app.post("/api/bot/self-test")
async def bot_self_test(request: Request):
    """Запускает режим самотестирования — бот разговаривает сам с собой."""
    require_admin(request)
    try:
        history = await run_self_test(bot)
        return {
            "success": True,
            "turns": len(history),
            "conversation": [{"role": r, "message": m} for r, m in history]
        }
    except Exception as e:
        raise HTTPException(500, f"Ошибка самотестирования: {e}")

# ─── Manual Test (Пользователь сам пишет боту) ─────────────────────────────────

from typing import Dict
import uuid

# Хранилище активных ручных тестов в памяти
manual_tests: Dict[str, dict] = {}

class ManualTestStart(BaseModel):
    car_brand: str = "Toyota"
    car_model: str = "Camry"
    year: int = 2023

@app.post("/api/bot/manual-test/start")
async def manual_test_start(data: ManualTestStart, request: Request):
    """Начать ручной тест — пользователь сам пишет боту."""
    require_admin(request)
    import traceback
    from bot import get_hook_message

    test_id = str(uuid.uuid4())[:8]
    phone = f"test_{test_id}"
    listing_id = f'manual_test_{test_id}'

    test_listing = {
        'id': listing_id,
        'phone': phone,
        'phone_clean': phone,
        'car_brand': data.car_brand,
        'car_model': data.car_model,
        'year': data.year,
        'status': 'NEW',
        'script_step': 0,
        'followup_count': 0,
    }

    # Сохраняем в БД
    try:
        db.save_listing(test_listing)
    except Exception as e:
        logger.warning(f"Could not save listing: {e}")

    # Создаем первое сообщение бота
    first_message = get_hook_message(data.car_brand, data.car_model, data.year)

    # Сохраняем сообщение в БД
    try:
        db.save_message(listing_id, 'out', first_message)
    except Exception as e:
        logger.warning(f"Could not save message: {e}")

    # Сохраняем тест
    manual_tests[test_id] = {
        'listing': test_listing,
        'history': [{'role': 'bot', 'message': first_message}],
        'created_at': datetime.now().isoformat()
    }

    return {"success": True, "test_id": test_id, "first_message": first_message}

class ManualTestMessage(BaseModel):
    test_id: str
    message: str

@app.post("/api/bot/manual-test/message")
async def manual_test_message(data: ManualTestMessage, request: Request):
    """Отправить сообщение боту в ручном тесте."""
    import traceback

    # Auth
    try:
        require_admin(request)
    except HTTPException as e:
        raise e

    if data.test_id not in manual_tests:
        raise HTTPException(404, "Тест не найден. Начните новый тест.")

    test = manual_tests[data.test_id]
    listing = test['listing']
    phone = listing['phone_clean']

    # Сохраняем сообщение пользователя
    test['history'].append({'role': 'user', 'message': data.message})

    # Перехватываем все исходящие сообщения бота
    captured_responses = []

    async def capture_send(phone_num, text):
        if text and text.strip():
            captured_responses.append(text)
        return True

    async def capture_upload(phone_num, path, caption=""):
        label = caption or "файл"
        captured_responses.append(f"📎 [{label}]")
        return True

    # Патчим wa напрямую (не через bot.wa property)
    original_send = wa.send_message
    original_upload = wa.send_file_by_upload
    wa.send_message = capture_send
    wa.send_file_by_upload = capture_upload

    error_info = None
    try:
        await bot.handle_incoming(phone, data.message, listing)
    except Exception as e:
        err = traceback.format_exc()
        logger.error(f"Manual test bot error:\n{err}")
        error_info = f"⚠️ {type(e).__name__}: {str(e)}"
    finally:
        # Всегда восстанавливаем оригиналы
        wa.send_message = original_send
        wa.send_file_by_upload = original_upload

    # Добавляем ответы бота в историю
    for resp in captured_responses:
        test['history'].append({'role': 'bot', 'message': resp})

    # Если была ошибка и бот ничего не отправил — показываем её в чате
    if error_info and not captured_responses:
        test['history'].append({'role': 'bot', 'message': error_info})

    # Обновляем script_step в listing в памяти (не в БД)
    curr = listing.get('script_step', 0)
    listing['script_step'] = curr + 1

    return {"success": True, "history": test['history']}

@app.get("/api/bot/manual-test/{test_id}")
async def manual_test_get(test_id: str, request: Request):
    """Получить историю ручного теста."""
    require_admin(request)

    if test_id not in manual_tests:
        raise HTTPException(404, "Тест не найден")

    return {"success": True, "history": manual_tests[test_id]['history']}

@app.delete("/api/bot/manual-test/{test_id}")
async def manual_test_delete(test_id: str, request: Request):
    """Удалить ручной тест."""
    require_admin(request)

    if test_id in manual_tests:
        del manual_tests[test_id]

    return {"success": True}

# ─── Conversations ────────────────────────────────────────────────────────────

@app.get("/api/conversations")
async def get_conversations(request: Request, limit: int = 50):
    get_current_user(request)
    return {"conversations": db.get_conversations(limit=limit)}

@app.get("/api/conversations/{conv_id}/messages")
async def get_messages(conv_id: int, request: Request):
    get_current_user(request)
    return {"messages": db.get_messages(conv_id)}

# ─── Logs ─────────────────────────────────────────────────────────────────────

@app.get("/api/logs")
async def get_logs(request: Request, limit: int = 200, source: str = ""):
    require_admin(request)
    return {"logs": db.get_logs(limit=limit, source=source)}

# ─── Kolesa.kz Auth ──────────────────────────────────────────────────────────

@app.get('/api/kolesa/status')
async def kolesa_status(request: Request):
    get_current_user(request)
    import os, json as _json
    if not os.path.exists('kolesa_session.json'):
        return {'authorized': False, 'cookies': 0}
    try:
        with open('kolesa_session.json') as f:
            cookies = _json.load(f)
        # Проверяем есть ли auth cookies (klssid, kumd)
        auth_cookies = [c for c in cookies if c.get('name') in ('klssid', 'kumd', 'ssid')]
        return {'authorized': len(auth_cookies) > 0, 'cookies': len(cookies), 'auth_cookies': len(auth_cookies)}
    except:
        return {'authorized': False, 'cookies': 0}

@app.post('/api/kolesa/login')
async def kolesa_login(data: dict, request: Request):
    require_admin(request)
    login = data.get('login', '')
    password = data.get('password', '')
    if not login or not password:
        raise HTTPException(400, 'Логин и пароль обязательны')
    
    # Save credentials to settings
    db.save_settings({'kolesa_login': login, 'kolesa_password': password})
    
    # Run login in thread
    import threading
    result = {'success': False, 'error': ''}
    
    def do_login():
        try:
            from playwright.sync_api import sync_playwright
            import time, json as _json
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                page = context.new_page()
                
                # Step 1: open login page
                page.goto('https://id.kolesa.kz/login/', wait_until='domcontentloaded', timeout=30000)
                time.sleep(2)
                
                # Step 2: enter phone number
                page.fill('input[type="tel"], input[placeholder*="телефон"], input[name="phone"]', login)
                page.click('button:has-text("Продолжить"), button[type="submit"]')
                time.sleep(3)
                
                # Step 3: enter password if field appears
                try:
                    page.fill('input[type="password"]', password)
                    page.click('button:has-text("Войти"), button[type="submit"]')
                    time.sleep(3)
                except Exception:
                    pass
                
                # Save cookies regardless - check if login successful
                current_url = page.url
                cookies = context.cookies()
                db.log('INFO', 'PARSER', f'URL после входа: {current_url}')
                
                if 'login' not in current_url or len(cookies) > 3:
                    with open('kolesa_session.json', 'w') as f:
                        _json.dump(cookies, f)
                    result['success'] = True
                    db.log('INFO', 'PARSER', f'Авторизация Kolesa.kz выполнена. Cookies: {len(cookies)}')
                else:
                    result['error'] = 'Неверный логин или пароль'
                    db.log('ERROR', 'PARSER', f'Ошибка авторизации. URL: {current_url}')
                
                browser.close()
        except Exception as e:
            result['error'] = str(e)
            db.log('ERROR', 'PARSER', f'Ошибка входа Kolesa.kz: {e}')
    
    t = threading.Thread(target=do_login)
    t.start()
    t.join(timeout=45)
    
    return result

@app.post('/api/kolesa/manual-login')
async def kolesa_manual_login(request: Request):
    require_admin(request)
    result = {'success': False, 'error': ''}
    
    def do_manual():
        try:
            from playwright.sync_api import sync_playwright
            import time, json as _json
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = context.new_page()
                page.goto('https://id.kolesa.kz/login/')
                
                db.log('INFO', 'PARSER', 'Откройте браузер и войдите в Kolesa.kz вручную')
                
                # Ждём пока пользователь залогинится (до 120 сек)
                for i in range(60):
                    time.sleep(2)
                    current_url = page.url
                    if 'login' not in current_url:
                        break
                
                # Сохраняем все cookies включая httpOnly
                cookies = context.cookies()
                with open('kolesa_session.json', 'w') as f:
                    _json.dump(cookies, f)
                
                result['success'] = True
                db.log('INFO', 'PARSER', f'Сессия сохранена: {len(cookies)} cookies')
                browser.close()
        except Exception as e:
            result['error'] = str(e)
            db.log('ERROR', 'PARSER', f'Ошибка: {e}')
    
    import threading
    t = threading.Thread(target=do_manual)
    t.start()
    t.join(timeout=130)
    
    return result

# ─── Webhook ──────────────────────────────────────────────────────────────────

@app.post("/api/webhook")
async def webhook(data: dict, background_tasks: BackgroundTasks):
    background_tasks.add_task(bot.handle_webhook, data)
    return {"ok": True}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
