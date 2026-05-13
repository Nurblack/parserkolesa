"""
Каталог товаров AUTOCOVERS.KZ
Универсальные авточехлы — цены зависят только от типа авто:
  - Легковые
  - Кроссоверы / внедорожники
"""

import os

INSTAGRAM_LINK = "https://www.instagram.com/autocovers.kz?igsh=MW8zNzd5NzdrczYyYQ=="
CATALOG_PDF_PATH = "catalog/КАТАЛОГ_2025.pdf"


# ── Классификация: кроссовер или легковой ──────────────────────────────────
# Если модель есть в этом списке → кроссовер/внедорожник, иначе → легковой

CROSSOVERS = {
    # Toyota
    'rav4', 'rav 4', 'highlander', 'land cruiser', 'landcruiser', 'prado',
    'fortuner', 'c-hr', 'chr', 'venza', 'rush', '4runner',
    # Hyundai
    'tucson', 'santa fe', 'santafe', 'creta', 'ix35', 'ix55', 'palisade',
    'venue', 'kona',
    # Kia
    'sportage', 'sorento', 'seltos', 'mohave', 'telluride', 'soul',
    'carnival', 'niro',
    # Nissan
    'x-trail', 'xtrail', 'qashqai', 'pathfinder', 'patrol', 'murano',
    'juke', 'terrano',
    # Mitsubishi
    'outlander', 'pajero', 'asx', 'eclipse cross', 'l200', 'montero',
    # Honda
    'cr-v', 'crv', 'hr-v', 'hrv', 'pilot', 'passport',
    # Mazda
    'cx-5', 'cx5', 'cx-7', 'cx7', 'cx-9', 'cx9', 'cx-3', 'cx3',
    'cx-30', 'cx30', 'cx-50', 'cx50',
    # Chevrolet
    'captiva', 'tracker', 'trailblazer', 'tahoe', 'equinox', 'traverse',
    # Volkswagen
    'tiguan', 'touareg', 'atlas', 'taos', 't-roc', 'troc',
    # BMW
    'x1', 'x2', 'x3', 'x4', 'x5', 'x6', 'x7',
    # Mercedes
    'gla', 'glb', 'glc', 'gle', 'gls', 'g-class',
    # Audi
    'q3', 'q5', 'q7', 'q8',
    # Lexus
    'rx', 'nx', 'ux', 'lx', 'gx',
    # Subaru
    'forester', 'outback', 'xv', 'crosstrek',
    # Renault
    'duster', 'kaptur', 'koleos', 'arkana',
    # Skoda
    'kodiaq', 'karoq',
    # Geely
    'atlas pro', 'monjaro', 'tugella',
    # Chery
    'tiggo', 'tiggo 4', 'tiggo 7', 'tiggo 8',
    # Haval
    'jolion', 'f7', 'h6', 'h9', 'dargo',
    # Ford
    'explorer', 'escape', 'kuga', 'bronco', 'everest',
    # Land Rover
    'defender', 'discovery', 'range rover', 'freelander', 'evoque',
    # Jeep
    'grand cherokee', 'cherokee', 'wrangler', 'compass', 'renegade',
    # Volvo
    'xc40', 'xc60', 'xc90',
}


def is_crossover(car_brand: str, car_model: str) -> bool:
    """Определяет тип авто по марке и модели"""
    check = f"{car_brand} {car_model}".lower().strip()
    for name in CROSSOVERS:
        if name in check:
            return True
    return False


# ── Прайс-лист ─────────────────────────────────────────────────────────────

PRICES = {
    "sedan": {
        "open": {  # Открытая спинка (галстуки)
            "Велюр": "57 000 тг",
            "Тедди": "65 000 тг",
            "Энигма": "75 000 тг",
        },
        "closed": {  # Закрытая спинка (полные чехлы)
            "Велюр": "65 000 / 70 000 тг",
            "Тедди": "80 000 / 85 000 тг",
            "Энигма": "90 000 / 95 000 тг",
            "Экокожа": "65 000 / 70 000 тг",
            "Анфора": "73 000 / 78 000 тг",
        }
    },
    "crossover": {
        "open": {
            "Велюр": "57 000 тг",
            "Тедди": "65 000 тг",
            "Энигма": "75 000 тг",
        },
        "closed": {
            "Велюр": "67 000 / 72 000 тг",
            "Тедди": "82 000 / 87 000 тг",
            "Энигма": "92 000 / 97 000 тг",
            "Экокожа": "67 000 / 72 000 тг",
            "Анфора": "75 000 / 80 000 тг",
        }
    }
}


def get_price_message(car_brand: str, car_model: str, year=None) -> str:
    """
    Формирует прайс-лист под тип авто клиента.
    Определяет легковой или кроссовер → показывает соответствующие цены.
    """
    crossover = is_crossover(car_brand, car_model)
    car_type = "crossover" if crossover else "sedan"
    car_type_label = "🚙 Кроссоверы / внедорожники" if crossover else "🚗 Легковые"

    car_name = " ".join(filter(None, [car_brand, car_model, str(year) if year else ""])).strip()

    prices_open = PRICES[car_type]["open"]
    prices_closed = PRICES[car_type]["closed"]

    msg = f"📋 *Прайс-лист AUTOCOVERS.KZ*\n"
    msg += f"{car_type_label}\n"
    if car_name:
        msg += f"Для вашего: {car_name}\n"
    msg += "\n"

    msg += "▸ *Открытая спинка (галстуки):*\n"
    for material, price in prices_open.items():
        msg += f"  • {material} — {price}\n"
    msg += "\n"

    msg += "▸ *Закрытая спинка (полные чехлы):*\n"
    for material, price in prices_closed.items():
        msg += f"  • {material} — {price}\n"
    msg += "\n"

    msg += "✨ 9 дизайнов: Ромб, Ёлочка, Соты, Бизон и др.\n\n"
    msg += "✅ Пошив 5-7 дней\n"
    msg += "✅ Бесплатная установка (2 часа)\n"
    msg += "✅ Бесплатная доставка\n"
    msg += "⚡ Экспресс пошив 2 дня (+5 000 тг)"

    return msg


def get_instagram_message() -> str:
    """Сообщение со ссылкой на Instagram"""
    return (
        f"📸 Больше примеров наших работ вы найдёте в нашем Instagram:\n"
        f"{INSTAGRAM_LINK}\n\n"
        f"Подписывайтесь! Там много фото готовых работ 🔥"
    )


def get_catalog_photos_dir() -> str:
    """Путь к папке с общими фото каталога"""
    return os.path.join(os.path.dirname(__file__), 'catalog', 'photos')


def get_sample_photos() -> list:
    """
    Возвращает общие фото разновидностей чехлов из catalog/photos/ (до 5 шт).
    Это фото дизайнов/материалов — одинаковые для всех клиентов.
    """
    photos_dir = get_catalog_photos_dir()
    if not os.path.exists(photos_dir):
        return []

    photos = [os.path.join(photos_dir, f) for f in sorted(os.listdir(photos_dir))
              if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
    return photos[:5]
