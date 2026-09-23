import os
import re
import sys
import json
import time
import random
import hashlib
import logging
import base64
import signal
from pathlib import Path
from urllib.parse import urlparse, unquote
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from config import (
    BASE_URL, OSS_URL, DOC_URL, DOC_ID, SYSTEM_TYPE,
    OUTPUT_DIR, COOKIES_FILE, USER_AGENT,
    DELAY_BETWEEN_PAGES, DELAY_TRANSLATE, TRANSLATE_TIMEOUT,
)


# ============================================================
# Логирование
# ============================================================

def setup_logger(out_root: Path) -> logging.Logger:
    logger = logging.getLogger("parser")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                            datefmt="%H:%M:%S")

    # Консоль
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # Файл
    fh = logging.FileHandler(out_root / "parser.log", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger


log = logging.getLogger("parser")


# ============================================================
# Утилиты
# ============================================================

def sanitize(name: str, max_len=100) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = name.strip().strip(".")
    return name[:max_len] or "untitled"


def load_cookies():
    with open(COOKIES_FILE, encoding="utf-8") as f:
        return json.load(f)


def guess_ext(url: str, content_type: str = "") -> str:
    path = urlparse(url).path
    ext = os.path.splitext(path)[1].lower()
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"):
        return ext
    mime_map = {
        "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
        "image/webp": ".webp", "image/bmp": ".bmp", "image/svg+xml": ".svg",
    }
    for mime, e in mime_map.items():
        if mime in content_type:
            return e
    return ".png"


def abs_url(src: str) -> str:
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("/"):
        return BASE_URL + src
    if src.startswith("http"):
        return src
    return BASE_URL + "/" + src


def rel_to_images(depth: int, filename: str) -> str:
    return "../" * depth + "images/" + filename


# ============================================================
# Progress tracker
# ============================================================

class Progress:
    """
    Хранит:
      - done_pages:   { nodeId: относительный путь к html }
      - name_cache:   { original_name: translated_name }
      - downloaded:   { url: filename }
    Сохраняется на диск после каждого действия.
    """

    def __init__(self, path: Path):
        self.path = path
        self.data = {
            "done_pages": {},
            "name_cache": {},
            "downloaded": {},
        }
        if path.exists():
            try:
                self.data.update(json.loads(path.read_text(encoding="utf-8")))
                log.info(f"📂 Загружен прогресс: "
                         f"{len(self.data['done_pages'])} страниц, "
                         f"{len(self.data['downloaded'])} картинок")
            except Exception as e:
                log.warning(f"Не удалось загрузить progress.json: {e}")

    def save(self):
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # --- страницы ---
    def is_page_done(self, node_id: str) -> bool:
        rel = self.data["done_pages"].get(node_id)
        if not rel:
            return False
        return (self.path.parent / rel).exists()

    def mark_page_done(self, node_id: str, rel_path: str):
        self.data["done_pages"][node_id] = rel_path
        self.save()

    # --- имена ---
    def get_name(self, original: str):
        return self.data["name_cache"].get(original)

    def set_name(self, original: str, translated: str):
        self.data["name_cache"][original] = translated
        self.save()

    # --- картинки ---
    def get_image(self, url: str):
        return self.data["downloaded"].get(url)

    def set_image(self, url: str, fname: str):
        self.data["downloaded"][url] = fname
        self.save()


# ============================================================
# Outline
# ============================================================

def fetch_outline(page) -> list:
    page.goto(DOC_URL, wait_until="networkidle")
    page.wait_for_selector("#outline", timeout=30000)

    outline_url = page.get_attribute("#outline", "data-outlineurl")
    if not outline_url:
        raise RuntimeError("Не найден data-outlineurl в #outline")

    full_url = f"{OSS_URL}/{outline_url}"
    log.info(f"📥 Outline: {full_url}")

    data = page.evaluate(
        """async (url) => {
            const r = await fetch(url, { credentials: 'include' });
            return await r.json();
        }""",
        full_url,
    )
    return data


# ============================================================
# Контент
# ============================================================

def fetch_content(page, node_id: str) -> str | None:
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
        log.warning(f"nodeId={node_id}: {data.get('Code')} {data.get('Msg')}")
        return None
    return data["Data"]


# ============================================================
# Картинки
# ============================================================

def download_image(page, url: str, images_dir: Path, progress: Progress) -> str | None:
    """Скачивает картинку (если ещё нет) и возвращает имя файла."""
    # Кэш прогресса
    cached = progress.get_image(url)
    if cached and (images_dir / cached).exists():
        return cached

    try:
        result = page.evaluate(
            """async (url) => {
                const r = await fetch(url, { credentials: 'include' });
                if (!r.ok) return null;
                const ct = r.headers.get('content-type') || '';
                const buf = await r.arrayBuffer();
                let binary = '';
                const bytes = new Uint8Array(buf);
                const chunk = 0x8000;
                for (let i = 0; i < bytes.length; i += chunk) {
                    binary += String.fromCharCode.apply(
                        null, bytes.subarray(i, i + chunk)
                    );
                }
                return { b64: btoa(binary), ct: ct };
            }""",
            url,
        )
        if not result:
            log.warning(f"Картинка не скачалась: {url}")
            return None

        raw = base64.b64decode(result["b64"])
        ext = guess_ext(url, result.get("ct", ""))

        h = hashlib.md5(url.encode("utf-8")).hexdigest()[:12]
        orig = os.path.splitext(os.path.basename(unquote(urlparse(url).path)))[0]
        orig = sanitize(orig, 40) or "img"
        fname = f"{orig}_{h}{ext}"

        fpath = images_dir / fname
        if not fpath.exists():
            fpath.write_bytes(raw)
            log.info(f"  🖼️  {fname} ({len(raw)//1024} KB)")

        progress.set_image(url, fname)
        return fname
    except Exception as e:
        log.error(f"Ошибка картинки {url}: {e}")
        return None


# ============================================================
# Перевод (в браузере)
# ============================================================

TRANSLATE_SCRIPT = Path("google_translate_helper.js").read_text(encoding="utf-8")


def inject_translator(page):
    page.evaluate(TRANSLATE_SCRIPT)


def ensure_translator_loaded(page, timeout=TRANSLATE_TIMEOUT):
    page.wait_for_function("() => window.__gt_ready === true",
                           timeout=timeout * 1000)


def translate_via_browser(page, text: str, progress: Progress) -> str:
    """С кэшем в progress.json."""
    text = text.strip()
    if not text:
        return text

    cached = progress.get_name(text)
    if cached:
        return cached

    try:
        translated = page.evaluate(
            """async (text) => {
                const url = 'https://translate.googleapis.com/translate_a/single'
                    + '?client=gtx&sl=zh-CN&tl=ru&dt=t&q=' + encodeURIComponent(text);
                const r = await fetch(url);
                const data = await r.json();
                return data[0].map(s => s[0]).join('');
            }""",
            text,
        )
        progress.set_name(text, translated)
        return translated
    except Exception as e:
        log.warning(f"Перевод '{text}': {e}")
        return text


# ============================================================
# Обработка HTML страницы
# ============================================================

def process_page_html(page, raw_html: str, images_dir: Path,
                      progress: Progress, depth: int) -> str:
    soup = BeautifulSoup(raw_html, "lxml")

    for img in soup.find_all("img"):
        src = img.get("data-original") or img.get("src")
        if not src:
            continue
        url = abs_url(src)

        fname = download_image(page, url, images_dir, progress)
        if fname:
            img["src"] = rel_to_images(depth, fname)
        else:
            img["src"] = url

        if img.has_attr("data-original"):
            del img["data-original"]

    return str(soup)


def translate_html_in_browser(page, html: str) -> str:
    page.evaluate(
        """(html) => {
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

    ok = page.evaluate("() => window.__translateToRussian()")
    if not ok:
        log.warning("Перевод не применился")

    time.sleep(DELAY_TRANSLATE)
    return page.evaluate(
        "() => document.getElementById('__parser_holder').innerHTML"
    )


# ============================================================
# Сохранение
# ============================================================

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{ max-width: 1200px; margin: 20px auto; padding: 20px;
          font-family: Arial, sans-serif; background: #fff; color: #222; }}
  img {{ max-width: 100%; height: auto; }}
  .goog-te-banner-frame, #goog-gt-tt, .goog-tooltip,
  .goog-te-balloon-frame, #google_translate_element {{ display: none !important; }}
  body {{ top: 0 !important; }}
</style>
</head>
<body>
{content}
</body>
</html>"""


def save_html(folder: Path, name: str, content: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    fpath = folder / f"{sanitize(name)}.html"
    fpath.write_text(
        HTML_TEMPLATE.format(title=name, content=content),
        encoding="utf-8",
    )
    return fpath


# ============================================================
# Парсер с деревом
# ============================================================

class Parser:
    def __init__(self, page, out_root: Path, progress: Progress, force: bool = False):
        self.page = page
        self.out_root = out_root
        self.images_dir = out_root / "images"
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.progress = progress
        self.force = force
        self.total = 0
        self.done = 0
        self.skipped = 0
        self.interrupted = False

    def count_pages(self, nodes) -> int:
        n = 0
        for node in nodes:
            if (node.get("id") or "").strip():
                n += 1
            if node.get("children"):
                n += self.count_pages(node["children"])
        return n

    def walk(self, node, current_dir: Path, depth: int):
        if self.interrupted:
            return

        name = (node.get("name") or "").strip()
        node_id = (node.get("id") or "").strip()
        children = node.get("children") or []

        if not node_id:
            # --- ПАПКА ---
            if name:
                folder_name = translate_via_browser(self.page, name, self.progress)
                new_dir = current_dir / sanitize(folder_name)
            else:
                new_dir = current_dir
            for child in children:
                self.walk(child, new_dir, depth + 1)
        else:
            # --- HTML ---
            self.done += 1
            prefix = f"[{self.done}/{self.total}]"

            # Пропуск готовых
            if not self.force and self.progress.is_page_done(node_id):
                self.skipped += 1
                log.info(f"{prefix} ⏭️  {name} (уже готово)")
                return

            log.info(f"{prefix} 🔄 {name}")

            try:
                raw_html = fetch_content(self.page, node_id)
                if not raw_html:
                    return

                processed = process_page_html(
                    self.page, raw_html, self.images_dir, self.progress, depth
                )
                translated = translate_html_in_browser(self.page, processed)

                file_name = translate_via_browser(self.page, name, self.progress) \
                            if name else node_id

                # Коллизия: если файл с таким именем уже есть в этом же dir
                # и это не тот же node_id — добавляем суффикс
                target = current_dir / f"{sanitize(file_name)}.html"
                if target.exists() and not self.force:
                    # проверяем, наш ли это файл
                    existing_rel = self.progress.data["done_pages"].get(node_id)
                    if not existing_rel or \
                       (self.out_root / existing_rel) != target:
                        file_name = f"{file_name}_{node_id[:6]}"

                saved_path = save_html(current_dir, file_name, translated)
                rel = saved_path.relative_to(self.out_root).as_posix()
                self.progress.mark_page_done(node_id, rel)
                log.info(f"   💾 {rel}")

            except Exception as e:
                log.error(f"Ошибка на '{name}': {e}", exc_info=True)

            time.sleep(random.uniform(*DELAY_BETWEEN_PAGES))


# ============================================================
# Main
# ============================================================

def main():
    # CLI
    force = "--force" in sys.argv
    only_node = None
    for arg in sys.argv[1:]:
        if arg.startswith("--node="):
            only_node = arg.split("=", 1)[1]

    out_root = Path(OUTPUT_DIR) / DOC_ID
    out_root.mkdir(parents=True, exist_ok=True)

    setup_logger(out_root)
    log.info(f"🚀 Старт. Force={force}, node={only_node}")

    progress = Progress(out_root / "progress.json")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--lang=ru-RU", "--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=USER_AGENT,
            locale="ru-RU",
            viewport={"width": 1400, "height": 900},
        )
        context.add_cookies(load_cookies())
        page = context.new_page()

        # Graceful shutdown по Ctrl+C
        parser_holder = {}

        def on_sigint(sig, frame):
            log.warning("\n⛔ Прерывание — сохраняем прогресс...")
            if "parser" in parser_holder:
                parser_holder["parser"].interrupted = True

        signal.signal(signal.SIGINT, on_sigint)

        try:
            # 1. Основная страница
            log.info("🌐 Открываем руководство...")
            page.goto(DOC_URL, wait_until="networkidle")
            page.wait_for_selector("#outline", timeout=30000)

            # 2. Outline
            outline = fetch_outline(page)
            (out_root / "outline.json").write_text(
                json.dumps(outline, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            # 3. Переводчик
            log.info("🔤 Инициализируем Google Translate...")
            inject_translator(page)
            ensure_translator_loaded(page)
            log.info("✅ Переводчик готов")

            # 4. Обход
            parser = Parser(page, out_root, progress, force=force)
            parser_holder["parser"] = parser
            parser.total = parser.count_pages(outline)
            log.info(f"📄 Всего страниц: {parser.total}")

            for top_node in outline:
                if parser.interrupted:
                    break
                if only_node and (top_node.get("id") or "") != only_node \
                   and only_node not in _collect_ids(top_node):
                    continue
                parser.walk(top_node, out_root, depth=0)

            log.info(f"\n✅ Готово. Обработано: {parser.done - parser.skipped}, "
                     f"пропущено: {parser.skipped}")

        finally:
            progress.save()
            log.info("💾 Прогресс сохранён")
            browser.close()


def _collect_ids(node) -> set:
    """Собирает все id в поддереве (для --node)."""
    ids = set()
    if (node.get("id") or "").strip():
        ids.add(node["id"])
    for c in node.get("children") or []:
        ids.update(_collect_ids(c))
    return ids


if __name__ == "__main__":
    main()