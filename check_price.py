import asyncio
import json
import os
import re
import requests
from datetime import datetime
from playwright.async_api import async_playwright

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TOUR_URL = "https://alatantour.by/#tvtourid=6847006619"
PRICE_FILE = "prices.json"


async def get_tour_price():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        print(f"Открываю: {TOUR_URL}")
        await page.goto(TOUR_URL, wait_until="domcontentloaded", timeout=60000)

        print("Жду загрузки...")
        await page.wait_for_timeout(5000)

        await page.evaluate("window.location.hash = 'tvtourid=6847006619'; window.dispatchEvent(new HashChangeEvent('hashchange'));")

        print("Жду карточку тура...")
        await page.wait_for_timeout(20000)

        await page.screenshot(path="screenshot.png", full_page=True)
        print("Скриншот сохранён")

        content = await page.content()
        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(content)

        price = None

        selectors = [
            ".tv-tour-page-price",
            ".tv-tour-info-price",
            ".tv-modal [class*='price']",
            ".tv-popup [class*='price']",
            "[class*='tvtour'] [class*='price']",
            "[class*='tour-card'] [class*='price']",
            "[class*='overlay'] [class*='price']",
            "[class*='modal'] [class*='price']",
            "[class*='popup'] [class*='price']",
            "[class*='tv-'] [class*='price']",
            "[class*='tv-'] [class*='cost']",
            "[class*='price']",
        ]

        for selector in selectors:
            try:
                elements = await page.query_selector_all(selector)
                for el in elements:
                    text = await el.text_content()
                    if text:
                        digits = re.sub(r'\D', '', text.strip())
                        if digits and 200 < int(digits) < 500000:
                            price = int(digits)
                            print(f"Найдено '{selector}': {text.strip()} = {price}")
                            break
            except Exception:
                continue
            if price:
                break

        if not price:
            patterns = [
                r'(\d[\d\s]{2,8}\d)\s*(?:USD|usd|\$)',
                r'(\d[\d\s]{2,8}\d)\s*(?:BYN|byn)',
                r'(?:итого|total|цена|price)[^\d]{0,50}(\d[\d\s]{2,8}\d)',
            ]
            for pattern in patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                for match in matches:
                    digits = re.sub(r'\D', '', match)
                    if digits and 200 < int(digits) < 500000:
                        price = int(digits)
                        print(f"Regex: {price}")
                        break
                if price:
                    break

        await browser.close()
        return price


def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True})


def send_telegram_photo(photo_path, caption=""):
    if not BOT_TOKEN or not CHAT_ID:
        return
    if not os.path.exists(photo_path):
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    with open(photo_path, "rb") as photo:
        requests.post(url, data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML"}, files={"photo": photo})


def load_prices():
    if os.path.exists(PRICE_FILE):
        with open(PRICE_FILE, "r") as f:
            return json.load(f)
    return {"prices": []}


def save_prices(data):
    with open(PRICE_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


async def main():
    print(f"Проверка: {datetime.now()}")

    try:
        current_price = await get_tour_price()
    except Exception as e:
        print(f"ОШИБКА: {e}")
        send_telegram(f"⚠️ Ошибка:\n{str(e)[:300]}")
        return

    if current_price is None:
        send_telegram("⚠️ Не удалось найти цену тура. Карточка не загрузилась.")
        send_telegram_photo("screenshot.png", "Скриншот страницы")
        return

    history = load_prices()

    if history["prices"]:
        last_price = history["prices"][-1]["price"]
        diff = current_price - last_price
        if diff != 0:
            emoji = "📉🔥 ПОДЕШЕВЕЛО!" if diff < 0 else "📈 Подорожало"
            message = f"{emoji}\n\nБыло: {last_price:,}\nСтало: {current_price:,}\nРазница: {diff:+,}\n\n🔗 <a href='{TOUR_URL}'>Открыть тур</a>"
            send_telegram(message)
        else:
            print(f"Цена та же: {current_price}")
    else:
        send_telegram(f"✅ Мониторинг запущен!\n\nЦена: {current_price:,}\n\n🔗 <a href='{TOUR_URL}'>Открыть тур</a>")
        send_telegram_photo("screenshot.png", "📸 Страница")

    history["prices"].append({"price": current_price, "timestamp": datetime.now().isoformat()})
    history["prices"] = history["prices"][-500:]
    save_prices(history)
    print("Готово!")


if __name__ == "__main__":
    asyncio.run(main())
