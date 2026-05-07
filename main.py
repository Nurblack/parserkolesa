import asyncio
import json
import os
from datetime import datetime
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import List, Optional
import uvicorn
from dotenv import load_dotenv

load_dotenv()

from database import db
from whatsapp import wa
from parser import parser
from bot import bot
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

# ─── Webhook ──────────────────────────────────────────────────────────────────

@app.post("/api/webhook")
async def webhook(data: dict, background_tasks: BackgroundTasks):
    background_tasks.add_task(bot.handle_webhook, data)
    return {"ok": True}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
