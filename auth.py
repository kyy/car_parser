# auth.py
from playwright.sync_api import sync_playwright
import json

def save_cookies():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://dongcheyun.com/")

        print("🔐 Залогинься вручную в открывшемся браузере.")
        input("👉 Когда закончишь — нажми Enter здесь...")

        cookies = context.cookies()
        with open("cookies.json", "w", encoding="utf-8") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)

        print(f"✅ Сохранено {len(cookies)} куки в cookies.json")
        browser.close()

if __name__ == "__main__":
    save_cookies()