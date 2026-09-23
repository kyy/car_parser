import os
import re
import json
import time
import random
from pathlib import Path
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from config import (BASE_URL, OSS_URL, DOC_URL, DOC_ID, SYSTEM_TYPE,
                    OUTPUT_DIR, COOKIES_FILE, USER_AGENT)


# ---------- Утилиты ----------

def sanitize(name: str, max_len=80) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = name.strip().strip(".")
    return name[:max_len] or "untitled"


def load_cookies():
    with open(COOKIES_FILE, encoding="utf-8") as f:
        return json.load(f)


# ---------- Outline ----------

def fetch_outline(page) -> list:
    """Скачиваем outline-JSON с OSS, используя браузер (credentials)."""
    page.goto(DOC_URL, wait_until="networkidle")
    page.wait_for_selector("#outline", timeout=30000)

    outline_url = page.get_attribute("#outline", "data-outlineurl")
    if not outline_url:
        raise RuntimeError("Не найден data-outlineurl в #outline")

    full_url = f"{OSS_URL}/{outline_url}"
    print(f"📥 Outline: {full_url}")

    # Забираем JSON через fetch прямо в браузере
    data = page.evaluate(
        """async (url) => {
            const r = await fetch(url, { credentials: 'include' });
            return await r.json();
        }""",
        full_url,
    )
    return data


# ---------- Обход дерева ----------

def flatten_outline(nodes, parent_path="", counter=None):
    """
    Плоский список страниц с непустым id.
    counter — список [N] для нумерации разделов.
    """
    if counter is None:
        counter = [0]

    result = []
    for node in nodes:
        name = (node.get("name") or "").strip()
        node_id = (node.get("id") or "").strip()

        # Каждому именованному узлу даём номер
        new_path = parent_path
        if name:
            counter[0] += 1
            # Имя переведём позже, после того как браузер сделает перевод
            new_path = f"{parent_path}/{counter[0]:03d}.{name}" if parent_path \
                       else f"{counter[0]:03d}.{name}"

        if node_id:
            result.append({
                "id": node_id,
                "name": name,
                "path": new_path,
            })

        children = node.get("children") or []
        if children:
            result.extend(flatten_outline(children, new_path, counter))

    return result


# ---------- Контент ----------

def fetch_content(page, node_id: str) -> str | None:
    """Дёргаем /webpage/getPage из браузера (куки + сессия)."""
    data = page.evaluate(
        """async ([docId, nodeId, systemType]) => {
            const r = await fetch(
              `/webpage/getPage?docId=${docId}&nodeId=${nodeId}&systemType=${systemType}`,
              { method: 'POST', credentials: 'include' }
            );
            return await r.json();
        }""",
        [DOC_ID, node_id, SYSTEM_TYPE],
    )
    if data.get("Code") != 200:
        print(f"⚠️  nodeId={node_id}: {data.get('Code')} {data.get('Msg')}")
        return None
    return data["Data"]


# ---------- Перевод через встроенный Google Element ----------

TRANSLATE_SCRIPT = Path("google_translate_helper.js").read_text(encoding="utf-8")


def inject_translator(page):
    """Внедряем хелпер один раз на страницу."""
    page.evaluate(TRANSLATE_SCRIPT)


def ensure_translator_loaded(page, timeout=30):
    """Ждём, пока элемент Google Translate будет готов."""
    page.wait_for_function("() => window.__gt_ready === true", timeout=timeout * 1000)


# ---------- Обработка HTML ----------

def fix_images(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for img in soup.find_all("img"):
        src = img.get("data-original") or img.get("src")
        if not src:
            continue
        if src.startswith("//"):
            src = "https:" + src
        elif src.startswith("/"):
            src = BASE_URL + src
        img["src"] = src
        if img.has_attr("data-original"):
            del img["data-original"]
    return str(soup)


def translate_text_in_browser(page, text: str) -> str:
    """
    Переводим произвольный текст через тот же Google-переводчик,
    но на отдельной скрытой странице-обёртке.
    (Только для имён папок.)
    """
    if not text.strip():
        return text
    result = page.evaluate(
        """async (text) => {
            const url = 'https://translate.googleapis.com/translate_a/single'
                + '?client=gtx&sl=zh-CN&tl=ru&dt=t&q=' + encodeURIComponent(text);
            const r = await fetch(url);
            const data = await r.json();
            return data[0].map(s => s[0]).join('');
        }""",
        text,
    )
    return result


# ---------- Сохранение ----------

def save_page(output_root: Path, item: dict, html: str):
    folder = output_root / sanitize(item["path"])
    folder.mkdir(parents=True, exist_ok=True)

    filename = sanitize(f"{item['name_ru'] or item['name']}.html")
    filepath = folder / filename

    full = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>{item.get('name_ru') or item['name']}</title>
<style>
  body {{ max-width: 1200px; margin: 20px auto; padding: 20px;
          font-family: Arial, sans-serif; background: #fff; color: #222; }}
  img {{ max-width: 100%; height: auto; }}
  /* Прячем артефакты Google Translate */
  .goog-te-banner-frame, #goog-gt-tt, .goog-tooltip,
  .goog-te-balloon-frame, #google_translate_element {{ display: none !important; }}
  body {{ top: 0 !important; }}
</style>
</head>
<body>
{html}
</body>
</html>"""
    filepath.write_text(full, encoding="utf-8")
    print(f"💾 {filepath}")


# ---------- Main ----------

def main():
    out_root = Path(OUTPUT_DIR) / DOC_ID
    out_root.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        # headless=False — чтобы Google Translate не блокировался
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--lang=ru-RU",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = browser.new_context(
            user_agent=USER_AGENT,
            locale="ru-RU",
            viewport={"width": 1400, "height": 900},
        )
        context.add_cookies(load_cookies())

        page = context.new_page()

        # 1. Заходим на основную ссылку
        print("🌐 Открываем руководство...")
        page.goto(DOC_URL, wait_until="networkidle")
        page.wait_for_selector("#outline", timeout=30000)

        # 2. Получаем структуру
        outline = fetch_outline(page)
        (out_root / "outline.json").write_text(
            json.dumps(outline, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        flat = flatten_outline(outline)
        print(f"📄 Найдено страниц: {len(flat)}")

        # 3. Внедряем переводчик ОДИН РАЗ для всей сессии
        print("🔤 Инициализируем Google Translate в браузере...")
        inject_translator(page)
        ensure_translator_loaded(page)
        print("✅ Переводчик готов")

        # 4. Перебираем страницы
        for i, item in enumerate(flat, 1):
            print(f"\n[{i}/{len(flat)}] {item['name']}")

            try:
                # 4.1. Получаем оригинальный HTML
                html = fetch_content(page, item["id"])
                if not html:
                    continue

                # 4.2. Чиним картинки
                html = fix_images(html)

                # 4.3. Кладём HTML во временный контейнер и переводим
                page.evaluate(
                    """(html) => {
                        // Прячем всё лишнее, оставляем только перевод
                        let holder = document.getElementById('__parser_holder');
                        if (!holder) {
                            holder = document.createElement('div');
                            holder.id = '__parser_holder';
                            holder.style.cssText =
                                'position:fixed;top:0;left:0;right:0;bottom:0;' +
                                'background:#fff;z-index:999999;overflow:auto;padding:20px;';
                            document.body.appendChild(holder);
                        }
                        holder.innerHTML = html;
                    }""",
                    html,
                )

                # 4.4. Переводим страницу целиком (переводчик сам найдёт #__parser_holder)
                ok = page.evaluate("() => window.__translateToRussian()")
                if not ok:
                    print("  ⚠️  Похоже, перевод не применился")

                time.sleep(0.5)

                # 4.5. Забираем переведённый HTML
                translated_html = page.evaluate(
                    "() => document.getElementById('__parser_holder').innerHTML"
                )

                # 4.6. Переводим имя для папки (через тот же браузер)
                name_ru = translate_text_in_browser(page, item["name"])
                item["name_ru"] = name_ru
                # Обновляем путь: заменяем последнее имя на переведённое
                parts = item["path"].split("/")
                prefix = "/".join(parts[:-1])
                item["path"] = f"{prefix}/{parts[-1]}_{name_ru}" if prefix \
                               else f"{parts[-1]}_{name_ru}"

                save_page(out_root, item, translated_html)

            except Exception as e:
                print(f"❌ Ошибка на {item['name']}: {e}")

            # имитируем человека
            time.sleep(random.uniform(2.0, 4.0))

        browser.close()

    print("\n🎉 Готово!")


if __name__ == "__main__":
    main()