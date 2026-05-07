import hashlib
import hmac
import json
import time
import base64
from database import db

# Users config
USERS = {
    'admin': {
        'password': hashlib.sha256('admin123'.encode()).hexdigest(),
        'role': 'admin'
    },
    'user1': {
        'password': hashlib.sha256('user123'.encode()).hexdigest(),
        'role': 'user'
    }
}

SECRET_KEY = 'parskolesa_secret_key_2026'
TOKEN_EXPIRE = 86400  # 24 hours


def create_token(username: str, role: str) -> str:
    payload = {
        'username': username,
        'role': role,
        'exp': int(time.time()) + TOKEN_EXPIRE
    }
    data = base64.b64encode(json.dumps(payload).encode()).decode()
    sig = hmac.new(SECRET_KEY.encode(), data.encode(), hashlib.sha256).hexdigest()
    return f"{data}.{sig}"


def verify_token(token: str) -> dict:
    try:
        parts = token.split('.')
        if len(parts) != 2:
            return {}
        data, sig = parts
        expected_sig = hmac.new(SECRET_KEY.encode(), data.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return {}
        payload = json.loads(base64.b64decode(data).decode())
        if payload.get('exp', 0) < time.time():
            return {}
        return payload
    except Exception:
        return {}


def login(username: str, password: str) -> dict:
    user = USERS.get(username)
    if not user:
        return {}
    hashed = hashlib.sha256(password.encode()).hexdigest()
    if not hmac.compare_digest(hashed, user['password']):
        return {}
    token = create_token(username, user['role'])
    return {'token': token, 'role': user['role'], 'username': username}
