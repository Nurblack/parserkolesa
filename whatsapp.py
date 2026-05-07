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

    async def send_message(self, phone: str, text: str) -> bool:
        clean = phone.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        if clean.startswith("8") and len(clean) == 11:
            clean = "7" + clean[1:]
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
        text = msg_data.get("textMessageData", {}).get("textMessage", "")
        phone = sender.get("chatId", "").replace("@c.us", "")
        if not phone or not text:
            return {}
        return {
            "phone": phone,
            "text": text,
            "sender_name": sender.get("senderName", ""),
            "receipt_id": notification.get("receiptId")
        }

    def get_qr_link(self) -> str:
        instance_id, token = self._get_credentials()
        return f"https://qr.green-api.com/waInstance{instance_id}/{token}"


wa = WhatsAppClient()
