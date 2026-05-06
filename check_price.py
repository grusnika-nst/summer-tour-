import asyncio
import json
import os
import re
import requests
from datetime import datetime
from playwright.async_api import async_playwright

# Настройки из GitHub Secrets
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TOUR_URL = "https://alatantour.by/#tvtourid=6847006619"
PRICE_FILE = "prices.json"


async def get_tour_price():
    """Открывает страницу и парсит цену"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()

        print(f"Открываю: {TOUR_URL}")
        await page.goto(TOUR_URL, timeout=60000)

        # Ждём загрузки виджета TourVisor
        print("Жду загрузки виджета...")
        await page.wait_for_timeout(15000)

        # Скриншот для отладки
        await page.screenshot(path="screenshot.png", full_page=True)
        print("Скриншот сохранён")

        # Получаем весь текст страницы
        content = await page.content()

        # Сохраняем HTML для отладки
        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(content)

        # Ищем цену — пробуем разные селекторы TourVisor
        price = None

        # Способ 1: селекторы
        selectors = [
            "[class*='price'] [class*='val']",
            "[class*='price']",
            "[class*='Price']",
            "[class*='cost']",
            "[class*='sum']",
            ".tv-tour-price",
            ".tour_price",
            "[class*='tour'] [class*='price']",
        ]

        for selector in selectors:
            try:
                elements = await page.query_selector_all(selector)
                for el in elements:
                    text = await el.text_content()
                    if text:
                        digits = re.sub(r'\D', '', text.strip())
                        if digits and 100 < int(digits) < 100000:
                            price = int(digits)
                            print(f"Цена найдена селектором "
                                  f"'{selector}': {price}")
                            break
            except Exception:
                continue
            if price:
                break

        # Способ 2: регулярные выражения по HTML
        if not price:
            patterns = [
                r'(\d[\d\s]{2,8}\d)\s*(?:USD|usd|\$|долл)',
                r'(\d[\d\s]{2,8}\d)\s*(?:BYN|byn|руб|р\.)',
                r'(?:цена|price|стоимость)[^\d]{0,30}(\d[\d\s]{2,8}\d)',
                r'(?:от\s*)(\d[\d\s]{2,8}\d)',
            ]
            for pattern in patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    digits = re.sub(r'\D', '', match.group(1))
                    if digits and 100 < int(digits) < 100000:
                        price = int(digits)
                        print(f"Цена найдена регулярным "
                              f"выражением: {price}")
                        break

        await browser.close()
        return price


def send_telegram(message):
    """Отправка сообщения в Telegram"""
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram не настроен!")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    resp = requests.post(url, json={
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    })
    print(f"Telegram ответ: {resp.status_code}")


def send_telegram_photo(photo_path, caption=""):
    """Отправка фото в Telegram"""
    if not BOT_TOKEN or not CHAT_ID:
        return
    if not os.path.exists(photo_path):
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    with open(photo_path, "rb") as photo:
        requests.post(url, data={
            "chat_id": CHAT_ID,
            "caption": caption,
            "parse_mode": "HTML"
        }, files={"photo": photo})


def load_prices():
    """Загрузка истории цен"""
    if os.path.exists(PRICE_FILE):
        with open(PRICE_FILE, "r") as f:
            return json.load(f)
    return {"prices": []}


def save_prices(data):
    """Сохранение истории цен"""
    with open(PRICE_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


async def main():
    print(f"\n{'='*50}")
    print(f"Проверка цены: {datetime.now()}")
    print(f"{'='*50}\n")

    # Получаем текущую цену
    try:
        current_price = await get_tour_price()
    except Exception as e:
        print(f"ОШИБКА: {e}")
        send_telegram(f"⚠️ Ошибка мониторинга:\n\n{str(e)[:200]}")
        return

    if current_price is None:
        print("Цена не найдена!")
        send_telegram(
            "⚠️ Не удалось найти цену на странице.\n"
            "Возможно, сайт изменился или тур недоступен.\n\n"
            f"🔗 {TOUR_URL}"
        )
        send_telegram_photo("screenshot.png", "Скриншот страницы")
        return

    # Загружаем историю
    history = load_prices()

    if history["prices"]:
        last_entry = history["prices"][-1]
        last_price = last_entry["price"]
        diff = current_price - last_price

        if diff != 0:
            if diff < 0:
                emoji = "📉🔥"
                status = "ПОДЕШЕВЕЛО!"
            else:
                emoji = "📈"
                status = "Подорожало"

            message = (
                f"{emoji} <b>{status}</b>\n\n"
                f"🏨 Тур на alatantour.by\n"
                f"━━━━━━━━━━━━━━━\n"
                f"Было: {last_price:,}\n"
                f"Стало: <b>{current_price:,}</b>\n"
                f"Разница: <b>{diff:+,}</b>\n"
                f"━━━━━━━━━━━━━━━\n\n"
                f"🔗 <a href='{TOUR_URL}'>Открыть тур</a>"
            )
            send_telegram(message)
            print(f"Цена изменилась: {last_price} → {current_price}")
        else:
            print(f"Цена не изменилась: {current_price}")
    else:
        # Первый запуск
        message = (
            f"✅ Мониторинг запущен!\n\n"
            f"🏨 Тур на alatantour.by\n"
            f"Текущая цена: <b>{current_price:,}</b>\n\n"
            f"Буду проверять каждые 30 минут "
            f"и сообщу если изменится.\n\n"
            f"🔗 <a href='{TOUR_URL}'>Открыть тур</a>"
        )
        send_telegram(message)
        send_telegram_photo("screenshot.png",
                           "📸 Так выглядит страница")
        print(f"Первый запуск. Цена: {current_price}")

    # Сохраняем
    history["prices"].append({
        "price": current_price,
        "timestamp": datetime.now().isoformat()
    })
    history["prices"] = history["prices"][-500:]
    save_prices(history)

    print("Готово!")


if __name__ == "__main__":
    asyncio.run(main())
