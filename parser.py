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
from datetime import datetime
from urllib.parse import urlparse, unquote
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from config import (
    BASE_URL, OSS_URL, DOC_URL, DOC_ID, SYSTEM_TYPE,
    OUTPUT_DIR, COOKIES_FILE, USER_AGENT,
    DELAY_BETWEEN_PAGES,
)
# Внутренняя ссылка = только [A-Za-z0-9_-], без пути/точки/схемы
PAGE_ID_RE = re.compile(r'^[A-Za-z0-9_\-]+$')

# Схемы и протоколы, которые не трогаем
SKIP_SCHEMES = ("http://", "https://", "//", "mailto:", "tel:",
                "javascript:", "data:", "#")

def fix_internal_links(html: str) -> str:
    """
    Превращает <a href="<id>"> в <a href="<id>.html">.
    Не трогает абсолютные ссылки, якоря, mailto и т.п.
    Работает и через BeautifulSoup, и напрямую regex'ом — здесь regex,
    чтобы не ломать форматирование (полезно для diff'а).
    """
    def replace(match):
        quote = match.group("quote")
        href = match.group("href").strip()

        # пустые / схемы / якоря — не трогаем
        if not href:
            return match.group(0)
        low = href.lower()
        if any(low.startswith(s) for s in SKIP_SCHEMES):
            return match.group(0)

        # есть точка (расширение), слэш, вопрос, пробел — не наш случай
        if any(c in href for c in ('.', '/', '?', '#', ' ', '\\')):
            return match.group(0)

        # не похоже на id
        if not PAGE_ID_RE.match(href):
            return match.group(0)

        # ок — добавляем .html
        return f'href={quote}{href}.html{quote}'

    pattern = re.compile(
        r'href=(?P<quote>["\'])(?P<href>[^"\']+)(?P=quote)',
        flags=re.IGNORECASE,
    )
    return pattern.sub(replace, html)

def ensure_meta_charset(html: str) -> str:
    """
    Гарантирует наличие <meta charset="utf-8"> в <head>.
    Если <head> пуст или мета отсутствует — добавляет.
    Если <head> вообще нет — создаёт минимальный.
    """
    # Уже есть?
    if re.search(r'<meta[^>]+charset\s*=', html, flags=re.IGNORECASE):
        return html

    meta = '<meta charset="utf-8">'

    # Есть <head ...> ... </head>?
    m = re.search(r'(<head\b[^>]*>)', html, flags=re.IGNORECASE)
    if m:
        # Вставляем сразу после открывающего <head>
        return html[:m.end()] + meta + html[m.end():]

    # Нет <head> — вставляем перед <body> или в начало
    m = re.search(r'(<body\b)', html, flags=re.IGNORECASE)
    if m:
        return html[:m.start()] + f'<head>{meta}</head>' + html[m.start():]

    # Совсем ничего — оборачиваем
    return f'<!DOCTYPE html><html><head>{meta}</head><body>{html}</body></html>'
# ============================================================
# Логирование
# ============================================================

def setup_logger(out_root: Path):
    logger = logging.getLogger("parser")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                            datefmt="%H:%M:%S")
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)
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


def guess_ext_from_url(url: str) -> str:
    path = urlparse(url).path
    ext = os.path.splitext(path)[1].lower()
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"):
        return ext
    return ".png"


def guess_ext_from_mime(mime: str) -> str:
    mime = (mime or "").lower()
    m = {
        "image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg",
        "image/gif": ".gif", "image/webp": ".webp", "image/bmp": ".bmp",
        "image/svg+xml": ".svg",
    }
    for k, v in m.items():
        if k in mime:
            return v
    return ".png"


def abs_url(src: str) -> str:
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("/"):
        return BASE_URL + src
    if src.startswith("http"):
        return src
    return BASE_URL + "/" + src


def md5(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def rel_to_images(depth: int, filename: str) -> str:
    """pages/ — html лежит в pages/, images/ на уровень выше."""
    # html: output/<docid>/pages/<nodeId>.html
    # images: output/<docid>/images/<file>
    # значит всегда один уровень вверх + images/
    return "../images/" + filename


# ============================================================
# Progress
# ============================================================

class Progress:
    def __init__(self, path: Path):
        self.path = path
        self.data = {
            "done_pages": {},   # nodeId -> True (страница собрана)
            "downloaded": {},   # url -> filename
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

    def is_page_done(self, node_id: str) -> bool:
        return node_id in self.data["done_pages"]

    def mark_page_done(self, node_id: str):
        self.data["done_pages"][node_id] = True
        self.save()

    def get_image(self, key: str):
        return self.data["downloaded"].get(key)

    def set_image(self, key: str, fname: str):
        self.data["downloaded"][key] = fname
        self.save()


# ============================================================
# Outline
# ============================================================

def fetch_outline(page) -> tuple[list, str]:
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
    return data, full_url


# ============================================================
# Контент
# ============================================================

def fetch_content(page, node_id: str, retries: int = 3) -> str | None:
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            data = page.evaluate(
                """async ([docId, nodeId, systemType]) => {
                    const r = await fetch(
                      `/webpage/getPage?docId=${docId}&nodeId=${nodeId}&systemType=${systemType}`,
                      { method: 'POST', credentials: 'include' }
                    );
                    const ct = r.headers.get('content-type') || '';
                    if (!r.ok) return { err: 'http ' + r.status };
                    if (!ct.includes('json')) {
                        const t = await r.text();
                        return { err: 'not json: ' + t.slice(0, 120) };
                    }
                    return await r.json();
                }""",
                [DOC_ID, node_id, SYSTEM_TYPE],
            )
            if not data:
                last_err = "empty"
            elif data.get("err"):
                last_err = data["err"]
            elif data.get("Code") != 200:
                last_err = f"{data.get('Code')} {data.get('Msg')}"
            else:
                html = data.get("Data") or ""
                if not html.strip():
                    last_err = "empty Data"
                else:
                    return html
        except Exception as e:
            last_err = str(e)

        if attempt < retries:
            time.sleep(0.6 * attempt)

    log.warning(f"nodeId={node_id}: контент не получен ({last_err})")
    return None


# ============================================================
# Картинки
# ============================================================

def download_image_from_url(page, url: str, images_dir: Path,
                            progress: Progress,
                            retries: int = 3) -> str | None:
    """Обычная http(s) картинка через браузер. С ретраями и валидацией."""
    cached = progress.get_image(url)
    if cached and (images_dir / cached).exists():
        return cached

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            result = page.evaluate(
                """async (url) => {
                    const r = await fetch(url, { credentials: 'include' });
                    if (!r.ok) return { err: 'http ' + r.status };
                    const ct = (r.headers.get('content-type') || '').toLowerCase();
                    const buf = await r.arrayBuffer();
                    const bytes = new Uint8Array(buf);
                    // первые байты: если HTML — вернём признак
                    let head = '';
                    for (let i = 0; i < Math.min(64, bytes.length); i++) {
                        head += String.fromCharCode(bytes[i]);
                    }
                    let binary = '';
                    const chunk = 0x8000;
                    for (let i = 0; i < bytes.length; i += chunk) {
                        binary += String.fromCharCode.apply(
                            null, bytes.subarray(i, i + chunk)
                        );
                    }
                    return { b64: btoa(binary), ct: ct, size: bytes.length, head: head };
                }""",
                url,
            )
            if not result:
                last_err = "empty result"
            elif result.get("err"):
                last_err = result["err"]
            elif result.get("size", 0) < 32:
                last_err = f"too small ({result.get('size')})"
            elif "text/html" in (result.get("ct") or ""):
                last_err = "content-type text/html"
            elif result.get("head", "").lstrip().lower().startswith(("<!doctype", "<html")):
                last_err = "body looks like html"
            else:
                raw = base64.b64decode(result["b64"])
                ext = guess_ext_from_url(url)
                if ext == ".png" and result.get("ct"):
                    ext = guess_ext_from_mime(result["ct"])

                h = md5(url)[:12]
                orig = os.path.splitext(
                    os.path.basename(unquote(urlparse(url).path))
                )[0]
                orig = sanitize(orig, 40) or "img"
                fname = f"{orig}_{h}{ext}"

                fpath = images_dir / fname
                if not fpath.exists():
                    fpath.write_bytes(raw)
                    log.info(f"  🖼️  {fname} ({len(raw)//1024} KB)")
                progress.set_image(url, fname)
                return fname
        except Exception as e:
            last_err = str(e)

        if attempt < retries:
            time.sleep(0.5 * attempt)  # экспоненциальная пауза

    log.warning(f"Картинка не скачалась ({last_err}): {url}")
    return None


def save_data_uri(data_uri: str, images_dir: Path,
                  progress: Progress) -> str | None:
    """
    Декодирует data:image/...;base64,... и сохраняет как файл.
    Возвращает имя файла.
    """
    # Кэш по хэшу содержимого
    key = "data-uri:" + md5(data_uri)
    cached = progress.get_image(key)
    if cached and (images_dir / cached).exists():
        return cached

    try:
        # data:image/png;base64,XXXX   или   data:image/png,XXXX
        header, _, payload = data_uri.partition(",")
        if not payload:
            return None

        # MIME
        mime = ""
        m = re.match(r"data:([^;,]+)", header)
        if m:
            mime = m.group(1)
        ext = guess_ext_from_mime(mime)

        # base64 или URL-encoded
        if ";base64" in header:
            raw = base64.b64decode(payload)
        else:
            from urllib.parse import unquote_to_bytes
            raw = unquote_to_bytes(payload)

        h = md5(data_uri)[:12]
        fname = f"inline_{h}{ext}"
        fpath = images_dir / fname
        if not fpath.exists():
            fpath.write_bytes(raw)
            log.info(f"  🖼️  {fname} ({len(raw)//1024} KB, inline)")

        progress.set_image(key, fname)
        return fname
    except Exception as e:
        log.error(f"Ошибка data-uri картинки: {e}")
        return None


def _extract_srcset_urls(srcset: str) -> list[str]:
    """Парсит srcset: 'a.png 1x, b.png 2x' -> ['a.png','b.png']."""
    urls = []
    for part in (srcset or "").split(","):
        part = part.strip()
        if not part:
            continue
        # первая «колонка» до пробела — это URL
        url = part.split()[0]
        if url:
            urls.append(url)
    return urls


def _collect_candidate_srcs(img) -> list[str]:
    """
    Возвращает список URL-кандидатов для <img> в порядке приоритета.
    Поддерживает: src, data-original, data-src, data-lazy-src,
    data-echo, data-url, srcset, data-srcset, <source> внутри <picture>.
    """
    cands = []

    # 1) одиночные атрибуты
    for attr in ("src", "data-original", "data-src", "data-lazy-src",
                 "data-echo", "data-url", "data-image"):
        v = (img.get(attr) or "").strip()
        if v:
            cands.append(v)

    # 2) srcset / data-srcset
    for attr in ("srcset", "data-srcset"):
        v = img.get(attr)
        if v:
            cands.extend(_extract_srcset_urls(v))

    # 3) <source srcset> внутри <picture>
    parent = img.parent
    if parent and getattr(parent, "name", None) == "picture":
        for source in parent.find_all("source"):
            v = source.get("srcset") or source.get("data-srcset")
            if v:
                cands.extend(_extract_srcset_urls(v))

    # 4) уникализируем, сохраняя порядок
    seen, out = set(), []
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def process_images(page, soup: BeautifulSoup, images_dir: Path,
                   progress: Progress) -> list[dict]:
    """
    Обходит все <img>, скачивает (или декодирует) первую УСПЕШНУЮ картинку
    из списка кандидатов (динамические src, srcset, data-*),
    заменяет src на относительный путь.
    """
    images_info = []

    for img in soup.find_all("img"):
        candidates = _collect_candidate_srcs(img)
        if not candidates:
            continue

        chosen_fname = None
        chosen_src_key = None

        # пробуем кандидатов по очереди — пока не скачаем
        for raw_src in candidates:
            if raw_src.startswith("data:"):
                fname = save_data_uri(raw_src, images_dir, progress)
                src_key = raw_src[:80]
            else:
                url = abs_url(raw_src)
                fname = download_image_from_url(page, url, images_dir, progress)
                src_key = url

            if fname:
                chosen_fname = fname
                chosen_src_key = src_key
                break

        if not chosen_fname:
            log.warning(f"  ⚠️  Не удалось скачать картинку: {candidates[:3]}")
            # не удаляем атрибуты — пусть останется как есть
            continue

        img["src"] = rel_to_images(0, chosen_fname)
        for attr in ("data-original", "data-src", "data-lazy-src",
                     "data-echo", "data-url", "data-image",
                     "srcset", "data-srcset"):
            if img.has_attr(attr):
                del img[attr]

        images_info.append({
            "source": chosen_src_key,
            "file": f"images/{chosen_fname}",
        })

    return images_info


# ============================================================
# Обработка страницы
# ============================================================

def validate_page_html(html_out: str, images_info: list[dict]) -> tuple[bool, str]:
    """
    Проверяет, что HTML пригоден:
    - не пустой / не заглушка
    - есть <body> и хоть какой-то контент
    - все <img> имеют src (локальный или внешний), либо их нет вовсе
    - каждая ожидаемая картинка из images_info реально упомянута в html
    Возвращает (ok, reason).
    """
    if not html_out or len(html_out.strip()) < 50:
        return False, "html слишком короткий"

    low = html_out.lower()
    if "<body" not in low and "<html" not in low:
        # API иногда отдаёт фрагмент — это нормально, но проверим что он не пуст
        if len(html_out.strip()) < 50:
            return False, "пустой фрагмент"

    # все img должны иметь src
    soup = BeautifulSoup(html_out, "lxml")
    bad_imgs = [img for img in soup.find_all("img")
                if not (img.get("src") or "").strip()]
    if bad_imgs:
        return False, f"{len(bad_imgs)} <img> без src"

    # каждая картинка из images_info должна присутствовать в html
    for info in images_info:
        fname = os.path.basename(info["file"])
        if fname not in html_out:
            return False, f"картинка {fname} не найдена в html"

    return True, "ok"


def collect_page(page, node_id: str, pages_dir: Path, images_dir: Path,
                 progress: Progress) -> dict | None:
    """
    Скачивает HTML, обрабатывает картинки, ПРОВЕРЯЕТ результат,
    сохраняет html и возвращает метаданные.
    Если проверка не прошла — возвращает None (страница НЕ помечается done).
    """
    raw_html = fetch_content(page, node_id)
    if not raw_html:
        return None

    soup = BeautifulSoup(raw_html, "lxml")

    # --- 1. Скачиваем картинки ---
    images = process_images(page, soup, images_dir, progress)

    # --- 2. Собираем итоговый HTML ---
    html_out = str(soup)
    html_out = ensure_meta_charset(html_out)
    html_out = fix_internal_links(html_out)

    # --- 3. Проверяем ДО сохранения ---
    ok, reason = validate_page_html(html_out, images)
    if not ok:
        log.warning(f"  ❌ nodeId={node_id} не прошёл проверку: {reason}")
        return None

    # --- 4. Атомарная запись (через .tmp) ---
    pages_dir.mkdir(parents=True, exist_ok=True)
    page_file = pages_dir / f"{node_id}.html"
    tmp_file = page_file.with_suffix(".html.tmp")
    tmp_file.write_text(html_out, encoding="utf-8")
    tmp_file.replace(page_file)

    # --- 5. Пост-проверка на диске ---
    if not page_file.exists() or page_file.stat().st_size < 50:
        log.error(f"  ❌ Файл {page_file} не записался")
        return None

    return {
        "id": node_id,
        "page_file": f"pages/{node_id}.html",
        "images": images,
    }


# ============================================================
# Обход дерева — только сбор
# ============================================================

class Collector:
    def __init__(self, page, out_root: Path, progress: Progress,
                 force: bool = False):
        self.page = page
        self.out_root = out_root
        self.pages_dir = out_root / "pages"
        self.images_dir = out_root / "images"
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.progress = progress
        self.force = force
        self.total = 0
        self.done = 0
        self.skipped = 0
        self.interrupted = False
        self.flat = {}          # nodeId -> {name_zh, path_names, page_file, images}

    def count_pages(self, nodes) -> int:
        n = 0
        for node in nodes:
            if (node.get("id") or "").strip():
                n += 1
            if node.get("children"):
                n += self.count_pages(node["children"])
        return n

    def walk(self, node, path_names: list[str]) -> dict:
        """Рекурсивно обходит узел, возвращает узел для content.json."""
        if self.interrupted:
            return None

        name = (node.get("name") or "").strip()
        node_id = (node.get("id") or "").strip()
        children_raw = node.get("children") or []

        new_path = path_names + ([name] if name else [])

        # --- Узел-страница ---
        if node_id:
            self.done += 1
            prefix = f"[{self.done}/{self.total}]"

            meta = None
            if not self.force and self.progress.is_page_done(node_id):
                self.skipped += 1
                log.info(f"{prefix} ⏭️  {name} (уже собрано)")
                page_file = self.pages_dir / f"{node_id}.html"
                if page_file.exists() and page_file.stat().st_size > 50:
                    soup = BeautifulSoup(
                        page_file.read_text(encoding="utf-8"), "lxml"
                    )
                    images = []
                    for img in soup.find_all("img"):
                        src = (img.get("src") or "").strip()
                        if not src:
                            continue
                        fname = os.path.basename(src)
                        # пробуем восстановить исходный url из progress
                        source = ""
                        for k, v in self.progress.data["downloaded"].items():
                            if v == fname:
                                source = k
                                break
                        images.append({
                            "source": source,
                            "file": f"images/{fname}",
                        })
                    meta = {
                        "id": node_id,
                        "page_file": f"pages/{node_id}.html",
                        "images": images,
                    }
                else:
                    # файла нет или он битый — пересоберём
                    log.warning(f"{prefix} ⚠️  html отсутствует, пересобираем")
                    meta = None
            else:
                log.info(f"{prefix} 🔄 {name}")
                try:
                    meta = collect_page(
                        self.page, node_id,
                        self.pages_dir, self.images_dir, self.progress,
                    )
                    if meta:
                        self.progress.mark_page_done(node_id)
                    else:
                        log.warning(f"{prefix} ⚠️  '{name}' не собрана, "
                                    f"повторим при следующем запуске")
                except Exception as e:
                    log.error(f"Ошибка на '{name}': {e}", exc_info=True)

                time.sleep(random.uniform(*DELAY_BETWEEN_PAGES))

            if meta:
                self.flat[node_id] = {
                    "name_zh": name,
                    "path_names": new_path,
                    "page_file": meta["page_file"],
                    "images": meta["images"],
                }

            # Если не удалось собрать — фиксируем как проблемный узел,
            # чтобы он не потерялся в дереве
            if meta is None:
                return {
                    "id": node_id,
                    "name_zh": name,
                    "is_page": True,
                    "page_file": None,
                    "images": [],
                    "error": "not collected",
                    "children": [],
                }

            return {
                "id": node_id,
                "name_zh": name,
                "is_page": True,
                "page_file": meta["page_file"],
                "images": meta["images"],
                "children": [],
            }

        # --- Узел-папка ---
        children_out = []
        for child in children_raw:
            c = self.walk(child, new_path)
            if c:
                children_out.append(c)

        return {
            "id": "",
            "name_zh": name,
            "is_page": False,
            "children": children_out,
        }


# ============================================================
# Main
# ============================================================

def main():
    force = "--force" in sys.argv

    out_root = Path(OUTPUT_DIR) / DOC_ID
    out_root.mkdir(parents=True, exist_ok=True)

    setup_logger(out_root)
    log.info(f"🚀 Сбор данных. Force={force}")

    progress = Progress(out_root / "progress.json")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--lang=ru-RU", "--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=USER_AGENT,
            locale="ru-RU",
            viewport={"width": 1400, "height": 900},
        )
        context.add_cookies(load_cookies())
        page = context.new_page()

        collector_holder = {}

        def on_sigint(sig, frame):
            log.warning("\n⛔ Прерывание — сохраняем прогресс...")
            if "c" in collector_holder:
                collector_holder["c"].interrupted = True

        signal.signal(signal.SIGINT, on_sigint)

        try:
            log.info("🌐 Открываем руководство...")
            page.goto(DOC_URL, wait_until="networkidle")
            page.wait_for_selector("#outline", timeout=30000)

            doc_title = page.title()

            outline, outline_url = fetch_outline(page)

            # Метаданные документа
            meta = {
                "doc_id": DOC_ID,
                "doc_title": doc_title,
                "source_url": DOC_URL,
                "outline_url": outline_url,
                "system_type": SYSTEM_TYPE,
                "collected_at": datetime.now().isoformat(timespec="seconds"),
                "images_dir": "images",
                "pages_dir": "pages",
                "tree": [],
                "flat_pages": {},
            }

            collector = Collector(page, out_root, progress, force=force)
            collector_holder["c"] = collector
            collector.total = collector.count_pages(outline)
            log.info(f"📄 Всего страниц: {collector.total}")

            for top_node in outline:
                if collector.interrupted:
                    break
                node_out = collector.walk(top_node, [])
                if node_out:
                    meta["tree"].append(node_out)

            meta["flat_pages"] = collector.flat

            # Сохраняем
            content_path = out_root / "content.json"
            content_path.write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            log.info(f"\n✅ Готово. Обработано: {collector.done - collector.skipped}, "
                     f"пропущено: {collector.skipped}")
            log.info(f"📦 content.json: {content_path}")

        finally:
            progress.save()
            log.info("💾 Прогресс сохранён")
            browser.close()


if __name__ == "__main__":
    main()