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
    tour_data = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        # Перехватываем ВСЕ ответы от сервера
        async def handle_response(response):
            url = response.url
            if "tourvisor" in url or "tour" in url.lower():
                try:
                    if "json" in (response.headers.get("content-type", "") or ""):
                        body = await response.json()
                        tour_data[url] = body
                        print(f"Перехвачен JSON: {url[:100]}")
                    else:
                        text = await response.text()
                        if "price" in text.lower() or "cost" in text.lower():
                            tour_data[url] = text[:2000]
                            print(f"Перехвачен ответ: {url[:100]}")
                except Exception:
                    pass

        page.on("response", handle_response)

        print(f"Открываю: {TOUR_URL}")
        await page.goto(TOUR_URL, wait_until="domcontentloaded", timeout=60000)

        print("Жду загрузки...")
        await page.wait_for_timeout(5000)

        # Пробуем активировать виджет
        await page.evaluate("window.location.hash = 'tvtourid=6847006619'; window.dispatchEvent(new HashChangeEvent('hashchange'));")

        print("Жду API-ответов...")
        await page.wait_for_timeout(20000)

        await page.screenshot(path="screenshot.png", full_page=True)

        # Сохраняем все перехваченные данные
        with open("api_responses.json", "w", encoding="utf-8") as f:
            json.dump(tour_data, f, indent=2, ensure_ascii=False, default=str)

        print(f"\nПерехвачено ответов: {len(tour_data)}")

        # Ищем цену в перехваченных данных
        price = None
        for url, data in tour_data.items():
            data_str = json.dumps(data) if isinstance(data, dict) else str(data)
            print(f"\nURL: {url[:100]}")
            print(f"Данные (фрагмент): {data_str[:300]}")

            # Ищем цену в JSON
            price_patterns = [
                r'"price"\s*:\s*"?(\d+)"?',
                r'"cost"\s*:\s*"?(\d+)"?',
                r'"total"\s*:\s*"?(\d+)"?',
                r'"priceUsd"\s*:\s*"?(\d+)"?',
                r'"priceByn"\s*:\s*"?(\d+)"?',
                r'"amount"\s*:\s*"?(\d+)"?',
            ]
            for pattern in price_patterns:
                match = re.search(pattern, data_str, re.IGNORECASE)
                if match:
                    found = int(match.group(1))
                    if 200 < found < 500000:
                        price = found
                        print(f"ЦЕНА НАЙДЕНА: {price} (из {url[:60]})")
                        break
            if price:
                break

        # Если в API не нашли — ищем на странице
        if not price:
            print("\nВ API не нашли, ищем на странице...")
            content = await page.content()

            # Ищем элементы с ценой в открытой карточке
            all_text = await page.evaluate("document.body.innerText")
            print(f"Текст страницы (фрагмент): {all_text[:500]}")

            # Ищем паттерн цены
            patterns = [
                r'(\d[\d\s]{2,8}\d)\s*(?:USD|usd|\$)',
                r'(\d[\d\s]{2,8}\d)\s*(?:BYN|byn)',
            ]
            for pattern in patterns:
                matches = re.findall(pattern, all_text)
                for match in matches:
                    digits = re.sub(r'\D', '', match)
                    if digits and 500 < int(digits) < 500000:
                        price = int(digits)
                        print(f"Найдено на странице: {price}")
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
        send_telegram("⚠️ Не удалось найти цену тура.\nНи в API, ни на странице.")
        send_telegram_photo("screenshot.png", "Скриншот")
        return

    history = load_prices()

    # Сбрасываем историю (т.к. раньше была неправильная цена)
    if history["prices"] and history["prices"][-1]["price"] == 2900:
        history["prices"] = []

    if history["prices"]:
        last_price = history["prices"][-1]["price"]
        diff = current_price - last_price
        if diff != 0:
            emoji = "📉🔥 ПОДЕШЕВЕЛО!" if diff < 0 else "📈 Подорожало"
            send_telegram(f"{emoji}\n\nБыло: {last_price:,}\nСтало: {current_price:,}\nРазница: {diff:+,}\n\n🔗 <a href='{TOUR_URL}'>Открыть тур</a>")
        else:
            print(f"Цена та же: {current_price}")
    else:
        send_telegram(f"✅ Мониторинг запущен!\n\nЦена тура: {current_price:,}\n\n🔗 <a href='{TOUR_URL}'>Открыть тур</a>")
        send_telegram_photo("screenshot.png", "📸 Страница")

    history["prices"].append({"price": current_price, "timestamp": datetime.now().isoformat()})
    history["prices"] = history["prices"][-500:]
    save_prices(history)
    print("Готово!")


if __name__ == "__main__":
    asyncio.run(main())
