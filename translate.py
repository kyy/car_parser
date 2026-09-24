# translate.py
"""
Перевод уже скачанных страниц и content.json.

- content.json и HTML-страницы переводятся через Google Translate Element
  в браузере (Playwright + Chromium).
- Ведётся translate_progress.json: { id: "ok" | "fail" }.

Запуск:
    python translate.py                  # всё: content.json + страницы
    python translate.py --content        # только content.json
    python translate.py --pages          # только страницы
    python translate.py --force-content  # перевести content.json заново
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

    def reset(self, key: str):
        if key in self.data:
            del self.data[key]
            self.save()

    def set(self, key: str, status: str):
        self.data[key] = status
        self.save()


# ============================================================
# Утилиты
# ============================================================

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
RU_RE = re.compile(r"[а-яА-Я]")

def _has_chinese(s: str) -> bool:
    return bool(s) and bool(CJK_RE.search(s))

def _has_russian(s: str) -> bool:
    return bool(s) and bool(RU_RE.search(s))


# ============================================================
# JS-хелпер Google Translate
# ============================================================

TRANSLATE_SCRIPT = r"""
(() => {
  if (window.__gt_ready) return;

  if (!document.getElementById('google_translate_element')) {
    const div = document.createElement('div');
    div.id = 'google_translate_element';
    div.style.display = 'none';
    document.body.appendChild(div);
  }

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

  const s = document.createElement('script');
  s.src = 'https://translate.google.com/translate_a/element.js?cb=googleTranslateElementInit';
  s.onerror = () => { window.__gt_error = 'script load failed'; };
  document.head.appendChild(s);

  const watch = setInterval(() => {
    if (document.querySelector('.goog-te-combo')) {
      window.__gt_ready = true;
      clearInterval(watch);
    }
  }, 200);

  window.__translateToRussian = () => new Promise((resolve) => {
    const combo = document.querySelector('.goog-te-combo');
    if (!combo) { resolve(false); return; }

    combo.value = 'ru';
    combo.dispatchEvent(new Event('change', { bubbles: true }));

    let lastRu = -1;
    let stable = 0;
    let ticks = 0;
    const MAX_TICKS = 240;
    const STABLE_NEEDED = 6;

    const checker = setInterval(() => {
      ticks++;
      const text = document.body.innerText || '';
      const ru = (text.match(/[а-яА-Я]/g) || []).length;

      if (ru > 0 && ru === lastRu) {
        stable++;
      } else {
        stable = 0;
      }
      lastRu = ru;

      if (stable >= STABLE_NEEDED || ticks >= MAX_TICKS) {
        clearInterval(checker);
        resolve(ru > 0);
      }
    }, 250);
  });
})();
"""


def ensure_translator(page, timeout=TRANSLATE_TIMEOUT):
    page.evaluate(TRANSLATE_SCRIPT)

    start = time.time()
    while time.time() - start < timeout:
        if page.evaluate("() => window.__gt_ready === true"):
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
        f"Google Translate Element не загрузился за {timeout} сек."
    )


def _put_html_into_holder(page, html: str):
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


def translate_html_in_browser(page, html: str) -> str:
    _put_html_into_holder(page, html)
    ok = page.evaluate("() => window.__translateToRussian()")
    if not ok:
        log.warning("   ⚠️  Похоже, перевод не применился")
    time.sleep(0.4)
    return page.evaluate(
        "() => document.getElementById('__translate_holder').innerHTML"
    )


# ============================================================
# Перевод одной HTML-страницы
# ============================================================

def translate_page_file(page, src_file: Path, dst_file: Path):
    html = src_file.read_text(encoding="utf-8")

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
# Перевод набора строк через Google (с якорями)
# ============================================================

def google_translate_strings(page, strings: list) -> list:
    """
    Переводит список строк через Google Translate Element.
    Использует якоря data-k, чтобы жёстко сопоставить вход и выход.
    Возвращает список той же длины; для непереведённых — оригинал.
    """
    if not strings:
        return []

    results = list(strings)
    BATCH = 40

    for i in range(0, len(strings), BATCH):
        chunk = strings[i:i + BATCH]
        # экранируем HTML-спецсимволы
        def esc(x):
            return (x.replace("&", "&amp;")
                     .replace("<", "&lt;")
                     .replace(">", "&gt;"))
        parts = [f'<p data-k="{j}">{esc(s)}</p>' for j, s in enumerate(chunk)]
        html = "<div id='__tr'>" + "".join(parts) + "</div>"

        _put_html_into_holder(page, html)
        page.evaluate("() => window.__translateToRussian()")
        time.sleep(0.4)

        translated = page.evaluate(
            """() => Array.from(
                document.querySelectorAll('#__tr p')
            ).map(p => ({k: p.getAttribute('data-k'),
                         t: p.textContent.trim()}))"""
        )

        # индекс -> перевод
        got = {}
        for item in translated:
            try:
                k = int(item["k"])
            except (TypeError, ValueError):
                continue
            got[k] = item["t"]

        for j, src in enumerate(chunk):
            ru = got.get(j, "").strip()
            if ru and _has_russian(ru):
                results[i + j] = ru
            else:
                # fallback: оставляем китайский, чтобы не потерять данные
                results[i + j] = src

        log.info(f"   🔤 [{min(i+BATCH, len(strings))}/{len(strings)}] переведено")

    return results


# ============================================================
# Перевод content.json
# ============================================================

def translate_content_json(page, src_json: Path, dst_json: Path):
    data = json.loads(src_json.read_text(encoding="utf-8"))

    # ---------- 1. Собираем ВСЕ китайские строки ----------
    # key -> китайский текст
    to_translate = {}
    order = []

    def add(key: str, text: str):
        text = (text or "").strip()
        if not text or not _has_chinese(text):
            return
        if key in to_translate:
            return
        to_translate[key] = text
        order.append(key)

    # --- имя руководства (doc_title и альтернативы) ---
    for field in ("doc_title", "title_zh", "title", "name_zh", "name"):
        v = data.get(field)
        if isinstance(v, str):
            add(f"__doc__.{field}", v)

    # --- дерево ---
    def collect_tree(node, path):
        for field in ("name_zh", "name", "title_zh", "title"):
            v = node.get(field)
            if isinstance(v, str):
                add(f"{path}.{field}", v)
        for idx, c in enumerate(node.get("children") or []):
            collect_tree(c, f"{path}.children[{idx}]")

    for idx, top in enumerate(data.get("tree", []) or []):
        collect_tree(top, f"tree[{idx}]")

    # --- flat_pages ---
    for pid, item in (data.get("flat_pages") or {}).items():
        if not isinstance(item, dict):
            continue
        for field in ("name_zh", "name", "title_zh", "title"):
            v = item.get(field)
            if isinstance(v, str):
                add(f"flat_pages[{pid}].{field}", v)

    log.info(f"   🔤 Уникальных китайских строк: {len(order)}")
    if not order:
        data["translated_at"] = datetime.now().isoformat(timespec="seconds")
        dst_json.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info(f"   💾 {dst_json} (нечего переводить)")
        return

    # ---------- 2. Переводим через Google ----------
    src_list = [to_translate[k] for k in order]
    ru_list = google_translate_strings(page, src_list)
    mapping = dict(zip(order, ru_list))

    # ---------- 3. Применяем ----------
    # doc_title
    for field in ("doc_title", "title_zh", "title", "name_zh", "name"):
        k = f"__doc__.{field}"
        if k in mapping:
            ru_field = "doc_title_ru" if field == "doc_title" else f"{field}_ru"
            data[ru_field] = mapping[k]
    # если в исходнике был doc_title — гарантируем doc_title_ru
    if isinstance(data.get("doc_title"), str) and "doc_title_ru" not in data:
        data["doc_title_ru"] = data["doc_title"]

    # tree
    def apply_tree(node, path):
        # name_ru — из name_zh или name
        for field in ("name_zh", "name", "title_zh", "title"):
            k = f"{path}.{field}"
            if k in mapping:
                node["name_ru"] = mapping[k]
                break
        else:
            node.setdefault(
                "name_ru",
                (node.get("name_zh") or node.get("name") or "").strip(),
            )
        for idx, c in enumerate(node.get("children") or []):
            apply_tree(c, f"{path}.children[{idx}]")

    for idx, top in enumerate(data.get("tree", []) or []):
        apply_tree(top, f"tree[{idx}]")

    # flat_pages
    for pid, item in (data.get("flat_pages") or {}).items():
        if not isinstance(item, dict):
            continue
        for field in ("name_zh", "name", "title_zh", "title"):
            k = f"flat_pages[{pid}].{field}"
            if k in mapping:
                item["name_ru"] = mapping[k]
                break
        else:
            item.setdefault(
                "name_ru",
                (item.get("name_zh") or item.get("name") or "").strip(),
            )

    data["translated_at"] = datetime.now().isoformat(timespec="seconds")
    data["translated_by"] = "google-translate-element"
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
    force_content = "--force-content" in sys.argv

    out_root = Path(OUTPUT_DIR) / DOC_ID
    setup_logger(out_root)

    pages_dir = out_root / "pages"
    ru_pages_dir = out_root / "ru_pages"
    ru_pages_dir.mkdir(parents=True, exist_ok=True)

    progress = TranslateProgress(out_root / "translate_progress.json")
    if force_content:
        progress.reset("__content__")

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
                if progress.is_ok("__content__") and dst_json.exists():
                    log.info("⏭️  content.json уже переведён")
                elif not src_json.exists():
                    log.warning("⚠️  content.json не найден — пропускаем")
                else:
                    log.info("📄 Переводим content.json через Google...")
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
                failed = 0
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
                        failed += 1

                    time.sleep(random.uniform(*DELAY_BETWEEN_PAGES))

                log.info(f"\n✅ Страниц переведено: {done}, ошибок: {failed}")

        finally:
            progress.save()
            log.info("💾 Прогресс сохранён")
            browser.close()


if __name__ == "__main__":
    main()