import asyncio
import re
import traceback
import threading
from playwright.sync_api import sync_playwright
from database import db


class KolesaParser:
    def __init__(self):
        self.is_running = False
        self.stats = {
            "total_found": 0,
            "new_added": 0,
            "pages_parsed": 0,
            "current_url": ""
        }
        self._thread = None

    def _get_instance(self):
        import os
        settings = db.get_settings()
        return settings.get("green_api_instance_id") or os.getenv("GREEN_API_INSTANCE_ID", "7700610961")

    def _get_token(self):
        import os
        settings = db.get_settings()
        return settings.get("green_api_token") or os.getenv("GREEN_API_TOKEN", "ec40236de3f943ffb076cea5b564af4f19610819453f41c8bf")

    def stop(self):
        self.is_running = False
        db.log("INFO", "PARSER", "Парсер остановлен")

    def start_in_thread(self, job_id: int, urls: list, max_ads: int = 50, delay_ms: int = 3000):
        """Запуск парсера в отдельном потоке (для совместимости с Windows + FastAPI)"""
        self._thread = threading.Thread(
            target=self._run_sync,
            args=(job_id, urls, max_ads, delay_ms),
            daemon=True
        )
        self._thread.start()

    def _run_sync(self, job_id: int, urls: list, max_ads: int, delay_ms: int):
        """Синхронный запуск через sync_playwright"""
        self.is_running = True
        self.stats = {"total_found": 0, "new_added": 0, "pages_parsed": 0, "current_url": ""}
        db.log("INFO", "PARSER", f"Парсер запущен. URLs: {len(urls)}, лимит: {max_ads}")

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled"
                    ]
                )

                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800}
                )

                for url in urls:
                    if not self.is_running:
                        break
                    if self.stats["total_found"] >= max_ads:
                        break
                    self._parse_page(context, url, job_id, max_ads, delay_ms)

                browser.close()

            db.update_parser_job(job_id, {
                "status": "COMPLETED",
                "new_added": self.stats["new_added"],
                "pages_parsed": self.stats["pages_parsed"]
            })
            db.log("INFO", "PARSER", f"✅ Готово. Новых номеров: {self.stats['new_added']}")

        except Exception as e:
            err = traceback.format_exc()
            db.log("ERROR", "PARSER", f"Критическая ошибка: {e} | {err[:300]}")
            db.update_parser_job(job_id, {"status": "FAILED"})
        finally:
            self.is_running = False

    def _parse_page(self, context, start_url: str, job_id: int, max_ads: int, delay_ms: int):
        page = context.new_page()
        try:
            self.stats["current_url"] = start_url
            db.log("INFO", "PARSER", f"Открываем: {start_url}")

            page.goto(start_url, wait_until="domcontentloaded", timeout=30000)
            import time
            time.sleep(3)

            page_num = 1
            while self.is_running and self.stats["total_found"] < max_ads:
                db.log("INFO", "PARSER", f"Страница {page_num}: {page.url}")
                self.stats["pages_parsed"] += 1

                # Ищем ссылки на объявления
                ad_links = page.eval_on_selector_all(
                    'a[href*="/a/show/"]',
                    'els => [...new Set(els.map(e => e.href))]'
                )

                if not ad_links:
                    ad_links = page.eval_on_selector_all(
                        'a[href*="kolesa.kz/a/"]',
                        'els => [...new Set(els.map(e => e.href))]'
                    )

                db.log("INFO", "PARSER", f"Найдено ссылок: {len(ad_links)}")

                if not ad_links:
                    page.screenshot(path="debug_parser.png")
                    db.log("WARN", "PARSER", "Нет ссылок — скриншот debug_parser.png")
                    break

                for link in ad_links:
                    if not self.is_running or self.stats["total_found"] >= max_ads:
                        break
                    self._parse_ad(context, link, job_id)
                    time.sleep(delay_ms / 1000)

                # Следующая страница
                next_btn = page.query_selector('.pager__next:not([disabled]), a[rel="next"]')
                if next_btn:
                    next_btn.click()
                    time.sleep(3)
                    page_num += 1
                else:
                    break

        except Exception as e:
            db.log("ERROR", "PARSER", f"Ошибка страницы: {e}")
        finally:
            page.close()

    def _parse_ad(self, context, url: str, job_id: int):
        page = context.new_page()
        try:
            import time
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            time.sleep(2)

            # Кнопка "Показать телефон"
            try:
                btn = page.locator('button:has-text("Показать телефон")').first
                if btn.count() > 0:
                    btn.click()
                    time.sleep(2)
            except:
                pass

            content = page.content()
            phones = self._extract_phones(content)

            if not phones:
                db.log("WARN", "PARSER", f"Нет телефона: {url}")
                return

            # Данные объявления
            title = ""
            price = ""
            city = ""

            try:
                title = page.inner_text('.offer__title')
            except:
                try:
                    title = page.title()
                except:
                    pass

            try:
                price = page.inner_text('.offer__price')
            except:
                pass

            try:
                city = page.inner_text('.offer__location')
            except:
                pass

            car_brand, car_model, year = self._parse_car(title)

            for phone in phones:
                # Проверяем есть ли WhatsApp перед сохранением
                import requests as req
                try:
                    check = req.post(
                        f"https://api.green-api.com/waInstance{self._get_instance()}/checkWhatsapp/{self._get_token()}",
                        json={"phoneNumber": phone},
                        timeout=10
                    ).json()
                    has_wa = check.get("existsWhatsapp", False)
                except:
                    has_wa = True  # если ошибка проверки — сохраняем

                if not has_wa:
                    db.log("INFO", "PARSER", f"⛔ Нет WhatsApp: +{phone}")
                    self.stats["total_found"] += 1
                    continue

                saved = db.save_listing({
                    "source_url": url,
                    "title": title.strip()[:200],
                    "price": price.strip()[:50],
                    "city": city.strip()[:100],
                    "car_brand": car_brand,
                    "car_model": car_model,
                    "year": year,
                    "phone": f"+{phone}",
                    "phone_clean": phone,
                    "parser_job_id": job_id
                })

                if saved:
                    self.stats["new_added"] += 1
                    db.log("INFO", "PARSER", f"✅ +{phone} WA — {car_brand} {car_model} {year or ''}")

                self.stats["total_found"] += 1

        except Exception as e:
            db.log("ERROR", "PARSER", f"Ошибка объявления: {e}")
        finally:
            page.close()

    def _extract_phones(self, html: str) -> list:
        clean = re.sub(r'<[^>]+>', ' ', html)
        found = set()
        patterns = [
            r'\+7[\s\-\(]?\d{3}[\s\-\)]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}',
            r'8[\s\-\(]?\d{3}[\s\-\)]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}',
            r'7\d{10}'
        ]
        for pattern in patterns:
            for m in re.findall(pattern, clean):
                digits = re.sub(r'\D', '', m)
                if digits.startswith('8') and len(digits) == 11:
                    digits = '7' + digits[1:]
                if len(digits) == 11 and digits.startswith('7'):
                    found.add(digits)
        return list(found)

    def _parse_car(self, title: str):
        year_match = re.search(r'\b(19[5-9]\d|20[0-2]\d)\b', title)
        year = int(year_match.group()) if year_match else None
        clean = re.sub(r'\b(19|20)\d{2}\b', '', title)
        clean = re.sub(r'[,\.\-\|]', ' ', clean).strip()
        parts = clean.split()
        brand = parts[0] if parts else ""
        model = " ".join(parts[1:3]) if len(parts) > 1 else ""
        return brand, model, year


parser = KolesaParser()
