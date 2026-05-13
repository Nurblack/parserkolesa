import asyncio
import requests
import os
from database import db

DEFAULT_INSTANCE_ID = os.getenv("GREEN_API_INSTANCE_ID", "7700610961")
DEFAULT_API_TOKEN = os.getenv("GREEN_API_TOKEN", "ec40236de3f943ffb076cea5b564af4f19610819453f41c8bf")


class WhatsAppClient:

    def _get_credentials(self):
        settings = db.get_settings()
        instance_id = settings.get("green_api_instance_id") or DEFAULT_INSTANCE_ID
        api_token = settings.get("green_api_token") or DEFAULT_API_TOKEN
        return instance_id, api_token

    def _base_url(self):
        instance_id, _ = self._get_credentials()
        return f"https://api.green-api.com/waInstance{instance_id}"

    def _token(self):
        _, token = self._get_credentials()
        return token

    def _get(self, endpoint: str) -> dict:
        url = f"{self._base_url()}/{endpoint}/{self._token()}"
        try:
            resp = requests.get(url, timeout=15)
            if not resp.text or resp.text == 'null':
                return {}
            return resp.json()
        except Exception as e:
            db.log("ERROR", "WHATSAPP", f"GET error: {e}")
            return {}

    def _post(self, endpoint: str, data: dict) -> dict:
        url = f"{self._base_url()}/{endpoint}/{self._token()}"
        try:
            resp = requests.post(url, json=data, timeout=15)
            if not resp.text:
                return {}
            return resp.json()
        except Exception as e:
            db.log("ERROR", "WHATSAPP", f"POST error: {e}")
            return {}

    def _delete(self, receipt_id: int) -> bool:
        # Правильный порядок: токен ПЕРЕД receipt_id
        url = f"{self._base_url()}/deleteNotification/{self._token()}/{receipt_id}"
        try:
            resp = requests.delete(url, timeout=15)
            if not resp.text:
                return True  # считаем успехом если нет ответа
            data = resp.json()
            return data.get("result", True)
        except Exception as e:
            db.log("ERROR", "WHATSAPP", f"DELETE error: {e}")
            return False

    async def get_status(self) -> str:
        result = self._get("getStateInstance")
        return result.get("stateInstance", "unknown")

    async def send_typing(self, phone: str, duration_seconds: int = 3) -> None:
        """Показывает статус 'печатает...' через Green API (sendTyping)."""
        clean = phone.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        if clean.startswith("8") and len(clean) == 11:
            clean = "7" + clean[1:]
        if not clean.isdigit() or len(clean) < 10:
            await asyncio.sleep(duration_seconds)
            return
        chat_id = f"{clean}@c.us"
        typing_ms = min(duration_seconds * 1000, 5000)  # max 5 секунд
        self._post("sendTyping", {"chatId": chat_id, "typingTime": typing_ms})
        await asyncio.sleep(duration_seconds)

    async def send_message(self, phone: str, text: str) -> bool:
        clean = phone.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        if clean.startswith("8") and len(clean) == 11:
            clean = "7" + clean[1:]

        # Тестовые номера — не отправляем в реальный API
        if not clean.isdigit() or len(clean) < 10:
            db.log("INFO", "WHATSAPP", f"[TEST] Перехват сообщения: {clean[:20]} → {text[:50]}")
            return True

        chat_id = f"{clean}@c.us"
        result = self._post("sendMessage", {"chatId": chat_id, "message": text})
        if result.get("idMessage"):
            db.log("INFO", "WHATSAPP", f"Отправлено: +{clean}")
            return True
        else:
            db.log("ERROR", "WHATSAPP", f"Ошибка +{clean}: {result}")
            return False

    async def receive_notification(self) -> dict:
        result = self._get("receiveNotification")
        return result if result else {}

    async def delete_notification(self, receipt_id: int) -> bool:
        return self._delete(receipt_id)

    def parse_incoming(self, notification: dict) -> dict:
        body = notification.get("body", {})
        if not body:
            body = notification
        if body.get("typeWebhook") != "incomingMessageReceived":
            return {}

        sender = body.get("senderData", {})
        msg_data = body.get("messageData", {})
        type_msg = msg_data.get("typeMessage", "")

        phone = sender.get("chatId", "").replace("@c.us", "")
        if not phone:
            return {}

        text = ""

        # Обычное текстовое сообщение
        if type_msg == "textMessage":
            text = msg_data.get("textMessageData", {}).get("textMessage", "")

        # Цитируемое сообщение (quoted) — берём текст ответа клиента
        elif type_msg == "quotedMessage":
            ext = msg_data.get("extendedTextMessageData", {})
            text = ext.get("text", "")
            # Дополнительно прикладываем цитату для контекста
            quoted = msg_data.get("quotedMessage", {})
            quoted_text = quoted.get("textMessage", "")
            if quoted_text and text:
                text = f"{text}"  # Берём только ответ, без цитаты (бот и так знает историю)

        # Расширенное текстовое (ссылки, forwarded)
        elif type_msg == "extendedTextMessage":
            text = msg_data.get("extendedTextMessageData", {}).get("text", "")

        # Аудио сообщение — возвращаем специальный маркер с URL для транскрибации
        elif type_msg in ("audioMessage", "pttMessage"):
            file_data = msg_data.get("fileMessageData", {})
            download_url = file_data.get("downloadUrl", "")
            if download_url:
                text = f"__AUDIO__:{download_url}"
            else:
                return {}  # Нет URL — пропускаем

        if not text:
            return {}

        return {
            "phone": phone,
            "text": text,
            "sender_name": sender.get("senderName", ""),
            "receipt_id": notification.get("receiptId"),
            "type": type_msg,
        }

    async def transcribe_audio(self, download_url: str, api_key: str, provider: str = "groq") -> str:
        """
        Скачивает аудио и транскрибирует.
        Поддерживает: assemblyai (бесплатно $50), groq, openai.
        """
        import tempfile
        import os as _os
        import time

        try:
            db.log("INFO", "WHATSAPP", f"🎤 Скачиваем аудио...")
            resp = requests.get(download_url, timeout=30)
            if not resp.ok:
                db.log("ERROR", "WHATSAPP", f"Не удалось скачать аудио: {resp.status_code}")
                return ""

            size_kb = len(resp.content) // 1024
            content_type_header = resp.headers.get('content-type', '')
            db.log("INFO", "WHATSAPP", f"🎤 Аудио: {size_kb} KB, тип: {content_type_header}, провайдер: {provider}")

            if len(resp.content) < 500:
                db.log("ERROR", "WHATSAPP", f"🎤 Файл слишком маленький: {len(resp.content)} байт")
                return ""

            # ── AssemblyAI ──────────────────────────────────────────────────
            if provider.lower() == "assemblyai":
                headers = {"authorization": api_key, "content-type": "application/json"}

                # 1. Загружаем файл на AssemblyAI
                upload_resp = requests.post(
                    "https://api.assemblyai.com/v2/upload",
                    headers={"authorization": api_key},
                    data=resp.content,
                    timeout=30
                )
                if not upload_resp.ok:
                    db.log("ERROR", "WHATSAPP", f"AssemblyAI upload error: {upload_resp.status_code} {upload_resp.text[:100]}")
                    return ""

                audio_url = upload_resp.json().get("upload_url", "")
                db.log("INFO", "WHATSAPP", f"🎤 AssemblyAI: файл загружен")

                # 2. Запускаем транскрибацию
                transcript_resp = requests.post(
                    "https://api.assemblyai.com/v2/transcript",
                    headers=headers,
                    json={"audio_url": audio_url, "language_code": "ru"},
                    timeout=15
                )
                if not transcript_resp.ok:
                    db.log("ERROR", "WHATSAPP", f"AssemblyAI transcript error: {transcript_resp.text[:100]}")
                    return ""

                transcript_id = transcript_resp.json().get("id", "")
                db.log("INFO", "WHATSAPP", f"🎤 AssemblyAI: транскрибация запущена ({transcript_id})")

                # 3. Ждём результат (polling до 30 секунд)
                for _ in range(15):
                    await asyncio.sleep(2)
                    result_resp = requests.get(
                        f"https://api.assemblyai.com/v2/transcript/{transcript_id}",
                        headers=headers,
                        timeout=10
                    )
                    result = result_resp.json()
                    status = result.get("status", "")
                    if status == "completed":
                        text = result.get("text", "")
                        db.log("INFO", "WHATSAPP", f"🎤 Транскрипция: {text[:80]}")
                        return text
                    elif status == "error":
                        db.log("ERROR", "WHATSAPP", f"AssemblyAI error: {result.get('error', '')}")
                        return ""

                db.log("ERROR", "WHATSAPP", "AssemblyAI: timeout")
                return ""

            # ── Groq SDK (официальный) ──────────────────────────────────────
            if provider.lower() == "groq":
                import tempfile, os as _os
                suffix = ".ogg"
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                    tmp.write(resp.content)
                    tmp_path = tmp.name
                try:
                    from groq import Groq
                    client = Groq(api_key=api_key)
                    with open(tmp_path, "rb") as f:
                        result = client.audio.transcriptions.create(
                            model="whisper-large-v3-turbo",
                            file=f,
                            language="ru",
                            response_format="text"
                        )
                    text = result if isinstance(result, str) else getattr(result, 'text', str(result))
                    db.log("INFO", "WHATSAPP", f"🎤 Groq транскрипция: {text[:80]}")
                    return text.strip()
                except Exception as e:
                    db.log("ERROR", "WHATSAPP", f"Groq SDK error: {e}")
                    return ""
                finally:
                    _os.unlink(tmp_path)

        except Exception as e:
            db.log("ERROR", "WHATSAPP", f"Ошибка транскрибации аудио: {e}")
            return ""

    async def send_file_by_upload(self, phone: str, file_path: str, caption: str = "") -> bool:
        """Отправка файла с диска через Green API"""
        import os as _os
        clean = phone.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        if clean.startswith("8") and len(clean) == 11:
            clean = "7" + clean[1:]

        # Тестовые номера — не отправляем в реальный API
        if not clean.isdigit() or len(clean) < 10:
            filename = _os.path.basename(file_path)
            db.log("INFO", "WHATSAPP", f"[TEST] Перехват файла: {filename} → {clean[:20]}")
            return True

        chat_id = f"{clean}@c.us"
        url = f"{self._base_url()}/sendFileByUpload/{self._token()}"
        try:
            filename = _os.path.basename(file_path)
            with open(file_path, 'rb') as f:
                files = {'file': (filename, f)}
                data = {'chatId': chat_id, 'caption': caption}
                resp = requests.post(url, data=data, files=files, timeout=30)
                result = resp.json() if resp.text else {}
            if result.get("idMessage"):
                db.log("INFO", "WHATSAPP", f"Файл отправлен: +{clean} ({filename})")
                return True
            else:
                db.log("ERROR", "WHATSAPP", f"Ошибка файла +{clean}: {result}")
                return False
        except Exception as e:
            db.log("ERROR", "WHATSAPP", f"Ошибка отправки файла: {e}")
            return False

    async def send_file_by_url(self, phone: str, file_url: str, filename: str, caption: str = "") -> bool:
        """Отправка файла по URL через Green API"""
        clean = phone.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        if clean.startswith("8") and len(clean) == 11:
            clean = "7" + clean[1:]
        chat_id = f"{clean}@c.us"
        result = self._post("sendFileByUrl", {
            "chatId": chat_id,
            "urlFile": file_url,
            "fileName": filename,
            "caption": caption
        })
        if result.get("idMessage"):
            db.log("INFO", "WHATSAPP", f"Файл по URL отправлен: +{clean}")
            return True
        else:
            db.log("ERROR", "WHATSAPP", f"Ошибка файла URL +{clean}: {result}")
            return False

    def get_qr_link(self) -> str:
        instance_id, token = self._get_credentials()
        return f"https://qr.green-api.com/waInstance{instance_id}/{token}"


wa = WhatsAppClient()
