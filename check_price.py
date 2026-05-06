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
    """Открывает страницу и ждёт загрузки виджета тура"""
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
               await page.goto(TOUR_URL, wait_until="domcontentloaded",
                        timeout=60000)

        # Ждём загрузки основной страницы
        print("Жду загрузки страницы...")
        await page.wait_for_timeout(5000)

        # Принудительно обрабатываем хэш — TourVisor виджет
        # Иногда нужно заново установить хэш
        await page.evaluate("""
            window.location.hash = 'tvtourid=6847006619';
            window.dispatchEvent(new HashChangeEvent('hashchange'));
        """)

        # Ждём появления всплывающего окна тура
        print("Жду открытия карточки тура...")
        await page.wait_for_timeout(20000)

        # Скриншот
        await page.screenshot(path="screenshot.png", full_page=True)
        print("Скриншот сохранён")

        # Получаем HTML
        content = await page.content()
        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(content)

        # Ищем цену в модальном окне / оверлее тура
        price = None

        # Способ 1: ищем во всплывающем окне TourVisor
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
            ".tv-cost",
            "[class*='tv-'] [class*='price']",
            "[class*='tv-'] [class*='cost']",
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
                            print(f"Найдено '{selector}': "
                                  f"{text.strip()} → {price}")
                            break
            except Exception:
                continue
            if price:
                break

        # Способ 2: ищем все элементы с ценой на странице
        if not price:
            print("Селекторы не помогли, ищу по всем элементам...")
            all_elements = await page.query_selector_all("*")
            for el in all_elements[:500]:
                try:
                    text = await el.text_content()
                    if text and re.search(
                        r'\d[\d\s]*\d\s*(?:USD|BYN|\$|€)',
                        text.strip()[:50]
                    ):
                        digits = re.sub(r'\D', '', text.strip()[:20])
                        if digits and 200 < int(digits) < 500000:
                            price = int(digits)
                            print(f"Найдено в тексте: {text.strip()[:50]} → {price}")
                            break
                except Exception:
                    continue

        # Способ 3: регулярные выражения по HTML
        if not price:
            print("Ищу по HTML регулярными выражениями...")
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
                        print(f"Регулярное выражение: {price}")
                        break
                if price:
                    break

        # Способ 4: ищем в сетевых запросах (API TourVisor)
        if not price:
            print("Цена не найдена на странице")

        await browser.close()
        return price


def send_telegram(message):
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
    print(f"Telegram: {resp.status_code}")


def send_telegram_photo(photo_path, caption=""):
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
    if os.path.exists(PRICE_FILE):
        with open(PRICE_FILE, "r") as f:
            return json.load(f)
    return {"prices": []}


def save_prices(data):
    with open(PRICE_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


async def main():
    print(f"\n{'='*50}")
    print(f"Проверка: {datetime.now()}")
    print(f"{'='*50}\n")

    try:
        current_price = await get_tour_price()
    except Exception as e:
        print(f"ОШИБКА: {e}")
        send_telegram(f"⚠️ Ошибка:\n{str(e)[:300]}")
        return

    if current_price is None:
        send_telegram(
            "⚠️ Не удалось найти цену тура.\n"
            "Карточка тура не загрузилась.\n\n"
            f"🔗 {TOUR_URL}"
        )
        send_telegram_photo("screenshot.png",
                           "Скриншот — карточка тура не открылась")
        return

    history = load_prices()

    if history["prices"]:
        last_price = history["prices"][-1]["price"]
        diff = current_price - last_price

        if diff != 0:
            emoji = "📉🔥 ПОДЕШЕВЕЛО!" if diff < 0 \
                else "📈 Подорожало"
            message = (
                f"{emoji}\n\n"
                f"🏨 Тур на alatantour.by\n"
                f"Было: {last_price:,}\n"
                f"Стало: <b>{current_price:,}</b>\n"
                f"Разница: <b>{diff:+,}</b>\n\n"
                f"🔗 <a href='{TOUR_URL}'>Открыть тур</a>"
            )
            send_telegram(message)
        else:
            print(f"Цена та же: {current_price}")
    else:
        message = (
            f"✅ Мониторинг запущен!\n\n"
            f"🏨 Тур на alatantour.by\n"
            f"Текущая цена: <b>{current_price:,}</b>\n\n"
            f"Проверяю каждые 30 минут.\n\n"
            f"🔗 <a href='{TOUR_URL}'>Открыть тур</a>"
        )
        send_telegram(message)
        send_telegram_photo("screenshot.png", "📸 Страница тура")

    history["prices"].append({
        "price": current_price,
        "timestamp": datetime.now().isoformat()
    })
    history["prices"] = history["prices"][-500:]
    save_prices(history)
    print("Готово!")


if __name__ == "__main__":
    asyncio.run(main())
