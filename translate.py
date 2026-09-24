# translate.py
"""
Перевод уже скачанных страниц и content.json.
Читает pages/*.html, переводит через Google Translate Element в браузере,
сохраняет в ru_pages/*.html.
Ведёт translate_progress.json: { id: "ok" | "fail" }.

Запуск:
    python translate.py             # всё: content.json + страницы
    python translate.py --content   # только content.json
    python translate.py --pages     # только страницы
"""
import re
import sys
import json
import time
import random
import logging
import signal
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright

from config import (
    OUTPUT_DIR, DOC_ID, USER_AGENT,
    DELAY_BETWEEN_PAGES, TRANSLATE_TIMEOUT,
)


# ============================================================
# Логирование
# ============================================================

def setup_logger(out_root: Path) -> logging.Logger:
    logger = logging.getLogger("translate")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                            datefmt="%H:%M:%S")
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    fh = logging.FileHandler(out_root / "translate.log", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger


log = logging.getLogger("translate")


# ============================================================
# Progress
# ============================================================

class TranslateProgress:
    """{ "page_id": "ok" | "fail", "__content__": "ok" | "fail" }"""

    def __init__(self, path: Path):
        self.path = path
        self.data = {}
        if path.exists():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
                ok = sum(1 for v in self.data.values() if v == "ok")
                log.info(f"📂 Прогресс: {ok} ok / {len(self.data)} записей")
            except Exception as e:
                log.warning(f"Не загрузился translate_progress.json: {e}")

    def save(self):
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def is_ok(self, key: str) -> bool:
        return self.data.get(key) == "ok"

    def set(self, key: str, status: str):
        self.data[key] = status
        self.save()


# ============================================================
# JS-хелпер для перевода (ИСПРАВЛЕННЫЙ)
# ============================================================

TRANSLATE_SCRIPT = r"""
(() => {
  if (window.__gt_ready) return;

  // 1. Сначала создаём контейнер — ДО загрузки скрипта Google
  if (!document.getElementById('google_translate_element')) {
    const div = document.createElement('div');
    div.id = 'google_translate_element';
    div.style.display = 'none';
    document.body.appendChild(div);
  }

  // 2. Колбэк, который вызовет Google после загрузки element.js
  window.googleTranslateElementInit = function () {
    try {
      new google.translate.TranslateElement(
        { pageLanguage: 'zh-CN', includedLanguages: 'ru', autoDisplay: false },
        'google_translate_element'
      );
    } catch (e) {
      window.__gt_error = String(e);
    }
  };

  // 3. Подгружаем сам скрипт Google
  const s = document.createElement('script');
  s.src = 'https://translate.google.com/translate_a/element.js?cb=googleTranslateElementInit';
  s.onerror = () => { window.__gt_error = 'script load failed'; };
  document.head.appendChild(s);

  // 4. Флаг готовности — только когда реально появился .goog-te-combo
  const watch = setInterval(() => {
    if (document.querySelector('.goog-te-combo')) {
      window.__gt_ready = true;
      clearInterval(watch);
    }
  }, 200);

  // 5. Хелпер перевода
  window.__translateToRussian = () => new Promise((resolve) => {
    const trySelect = () => {
      const combo = document.querySelector('.goog-te-combo');
      if (!combo) { setTimeout(trySelect, 300); return; }
      combo.value = 'ru';
      combo.dispatchEvent(new Event('change', { bubbles: true }));

      let tries = 0;
      const checker = setInterval(() => {
        tries++;
        const text = document.body.innerText;
        const hasRussian = /[а-яА-Я]/.test(text);
        if (hasRussian || tries > 60) {
          clearInterval(checker);
          resolve(hasRussian);
        }
      }, 250);
    };
    trySelect();
  });
})();
"""


# ============================================================
# Инициализация переводчика
# ============================================================

def ensure_translator(page, timeout=TRANSLATE_TIMEOUT):
    page.evaluate(TRANSLATE_SCRIPT)

    start = time.time()
    while time.time() - start < timeout:
        ready = page.evaluate("() => window.__gt_ready === true")
        if ready:
            return

        state = page.evaluate(
            """() => ({
                hasInit: typeof window.googleTranslateElementInit === 'function',
                hasGoogle: typeof window.google !== 'undefined',
                hasTranslate: !!(window.google && window.google.translate),
                comboExists: !!document.querySelector('.goog-te-combo'),
                err: window.__gt_error || null,
            })"""
        )
        time.sleep(2)
        log.info(f"   ⏳ ждём... {state}")

    raise RuntimeError(
        f"Google Translate Element не загрузился за {timeout} сек. "
        f"Смотри translate.log"
    )


def translate_html_in_browser(page, html: str) -> str:
    """Кладём HTML в скрытый контейнер, переводим, забираем обратно."""
    page.evaluate(
        """(html) => {
            let holder = document.getElementById('__translate_holder');
            if (!holder) {
                holder = document.createElement('div');
                holder.id = '__translate_holder';
                holder.style.cssText =
                    'position:fixed;top:0;left:0;right:0;bottom:0;' +
                    'background:#fff;z-index:999999;overflow:auto;padding:20px;';
                document.body.appendChild(holder);
            }
            holder.innerHTML = html;
        }""",
        html,
    )

    ok = page.evaluate("() => window.__translateToRussian()")
    if not ok:
        log.warning("   ⚠️  Похоже, перевод не применился")

    time.sleep(0.4)
    return page.evaluate(
        "() => document.getElementById('__translate_holder').innerHTML"
    )


# ============================================================
# Перевод одной страницы
# ============================================================

def translate_page_file(page, src_file: Path, dst_file: Path):
    html = src_file.read_text(encoding="utf-8")

    # Скрываем баннер Google Translate и верхний отступ
    hide_css = (
        "<style>"
        ".goog-te-banner-frame,#goog-gt-tt,.goog-tooltip,"
        ".goog-te-balloon-frame,#google_translate_element"
        "{display:none!important}"
        "body{top:0!important}"
        "</style>"
    )
    if "</head>" in html:
        html = html.replace("</head>", hide_css + "</head>", 1)
    else:
        html = hide_css + html

    translated = translate_html_in_browser(page, html)

    dst_file.parent.mkdir(parents=True, exist_ok=True)
    dst_file.write_text(translated, encoding="utf-8")


# ============================================================
# Перевод content.json (только name_zh → name_ru)
# ============================================================

def translate_content_json(page, src_json: Path, dst_json: Path):
    data = json.loads(src_json.read_text(encoding="utf-8"))

    # 1. Собираем уникальные имена
    names = set()

    def collect(node):
        n = (node.get("name_zh") or "").strip()
        if n:
            names.add(n)
        for c in node.get("children") or []:
            collect(c)

    for top in data.get("tree", []):
        collect(top)
    for _, item in (data.get("flat_pages") or {}).items():
        n = (item.get("name_zh") or "").strip()
        if n:
            names.add(n)

    names = sorted(names)
    log.info(f"   🔤 Уникальных имён: {len(names)}")

    # 2. Переводим батчами
    mapping = {}
    BATCH = 50

    for i in range(0, len(names), BATCH):
        chunk = names[i:i + BATCH]
        html_parts = [f'<p data-k="{idx}">{name}</p>' for idx, name in enumerate(chunk)]
        html = "<div id='__tr'>" + "".join(html_parts) + "</div>"

        page.evaluate(
            """(html) => {
                let h = document.getElementById('__translate_holder');
                if (!h) {
                    h = document.createElement('div');
                    h.id = '__translate_holder';
                    h.style.cssText =
                        'position:fixed;top:0;left:0;right:0;bottom:0;' +
                        'background:#fff;z-index:999999;overflow:auto;padding:20px;';
                    document.body.appendChild(h);
                }
                h.innerHTML = html;
            }""",
            html,
        )
        page.evaluate("() => window.__translateToRussian()")
        time.sleep(0.3)

        translated_items = page.evaluate(
            """() => Array.from(
                document.querySelectorAll('#__tr p')
            ).map(p => p.textContent.trim())"""
        )

        for idx, name in enumerate(chunk):
            ru = translated_items[idx] if idx < len(translated_items) else name
            mapping[name] = ru

        log.info(f"   🔤 [{min(i+BATCH, len(names))}/{len(names)}] переведено")

    # 3. Подставляем name_ru
    def apply(node):
        n = (node.get("name_zh") or "").strip()
        node["name_ru"] = mapping.get(n, n) if n else ""
        for c in node.get("children") or []:
            apply(c)

    for top in data.get("tree", []):
        apply(top)
    for _, item in (data.get("flat_pages") or {}).items():
        n = (item.get("name_zh") or "").strip()
        item["name_ru"] = mapping.get(n, n) if n else ""

    data["translated_at"] = datetime.now().isoformat(timespec="seconds")
    dst_json.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info(f"   💾 {dst_json}")


# ============================================================
# Main
# ============================================================

def main():
    only_content = "--content" in sys.argv
    only_pages = "--pages" in sys.argv

    out_root = Path(OUTPUT_DIR) / DOC_ID
    setup_logger(out_root)

    pages_dir = out_root / "pages"
    ru_pages_dir = out_root / "ru_pages"
    ru_pages_dir.mkdir(parents=True, exist_ok=True)

    progress = TranslateProgress(out_root / "translate_progress.json")

    with sync_playwright() as p:
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
        page = context.new_page()

        # Рабочий стол — нормальная страница, чтобы Google Element
        # корректно инициализировался. data:URL тоже работает,
        # но надёжнее обычная страница.
        log.info("🔤 Инициализируем Google Translate...")
        page.goto("https://example.com", wait_until="domcontentloaded")
        ensure_translator(page, timeout=60)
        log.info("✅ Переводчик готов")

        interrupted = {"v": False}

        def on_sigint(sig, frame):
            log.warning("\n⛔ Прерывание — сохраняем прогресс...")
            interrupted["v"] = True

        signal.signal(signal.SIGINT, on_sigint)

        try:
            # ---------- 1. content.json ----------
            if not only_pages:
                src_json = out_root / "content.json"
                dst_json = out_root / "content.ru.json"
                if progress.is_ok("__content__"):
                    log.info("⏭️  content.json уже переведён")
                elif not src_json.exists():
                    log.warning("⚠️  content.json не найден — пропускаем")
                else:
                    log.info("📄 Переводим content.json...")
                    try:
                        translate_content_json(page, src_json, dst_json)
                        progress.set("__content__", "ok")
                    except Exception as e:
                        log.error(f"Ошибка перевода content.json: {e}",
                                  exc_info=True)
                        progress.set("__content__", "fail")

            # ---------- 2. страницы ----------
            if not only_content:
                page_files = sorted(pages_dir.glob("*.html"))
                total = len(page_files)
                log.info(f"📚 Страниц к переводу: {total}")

                done = 0
                for i, src in enumerate(page_files, 1):
                    if interrupted["v"]:
                        break

                    pid = src.stem
                    dst = ru_pages_dir / f"{pid}.html"

                    if progress.is_ok(pid) and dst.exists():
                        log.info(f"[{i}/{total}] ⏭️  {pid}")
                        continue

                    log.info(f"[{i}/{total}] 🔄 {pid}")
                    try:
                        translate_page_file(page, src, dst)
                        progress.set(pid, "ok")
                        done += 1
                    except Exception as e:
                        log.error(f"Ошибка {pid}: {e}", exc_info=True)
                        progress.set(pid, "fail")

                    time.sleep(random.uniform(*DELAY_BETWEEN_PAGES))

                log.info(f"\n✅ Страниц переведено: {done}")

        finally:
            progress.save()
            log.info("💾 Прогресс сохранён")
            browser.close()


if __name__ == "__main__":
    main()