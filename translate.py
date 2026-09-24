# translate.py
"""
Перевод уже скачанных страниц и content.json через Google Translate Element.

Особенности:
- Переводятся в том числе текстовые узлы внутри SVG (<text>/<tspan>),
  которые Google Translate Element по умолчанию игнорирует — через
  постобработку: находим оставшиеся CJK, переводим отдельно, вставляем.
- Строка/страница считается переведённой ("ok") только если в ней
  НЕТ ни одного китайского иероглифа и есть буквы целевого языка.
- Незавершённые строки content.json помечаются "fail" в
  translate_progress.json -> "__content_items__" и доделываются
  при следующем запуске.

Запуск:
    python translate.py                       # всё: content.json + страницы (ru)
    python translate.py --content             # только content.json (ru)
    python translate.py --pages               # только страницы (ru)
    python translate.py --force-content       # сбросить прогресс content.json (ru)
    python translate.py --en                  # перевод на английский (en_pages, content.en.json)
    python translate.py --en --pages          # только страницы на английский
    python translate.py --en --content        # только content.json на английский
    python translate.py --en --force-content  # сбросить прогресс content.json (en)
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

def setup_logger(out_root: Path, suffix: str = "") -> logging.Logger:
    logger = logging.getLogger("translate")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                            datefmt="%H:%M:%S")
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    log_name = f"translate{suffix}.log"
    fh = logging.FileHandler(out_root / log_name, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger


log = logging.getLogger("translate")


# ============================================================
# Языковые профили
# ============================================================

class LangProfile:
    """
    Описывает целевой язык перевода:
      - code:         код языка для Google ('ru' / 'en')
      - letter_re:    регулярка "буквы целевого языка" (для проверки)
      - pages_dir:    имя каталога с переведёнными страницами
      - content_out:  имя итогового content-файла
      - progress:     имя файла прогресса
      - log_suffix:   суффикс для лог-файла
      - name_ru:      как называть язык в логах
    """
    def __init__(self, code, letter_re, pages_dir, content_out,
                 progress, log_suffix, name_ru):
        self.code = code
        self.letter_re = letter_re
        self.pages_dir = pages_dir
        self.content_out = content_out
        self.progress = progress
        self.log_suffix = log_suffix
        self.name_ru = name_ru


RU_PROFILE = LangProfile(
    code="ru",
    letter_re=re.compile(r"[а-яА-Я]"),
    pages_dir="ru_pages",
    content_out="content.ru.json",
    progress="translate_progress.json",
    log_suffix="",
    name_ru="русский",
)

EN_PROFILE = LangProfile(
    code="en",
    letter_re=re.compile(r"[a-zA-Z]"),
    pages_dir="en_pages",
    content_out="content.en.json",
    progress="translate_progress.en.json",
    log_suffix=".en",
    name_ru="английский",
)


# ============================================================
# Progress
# ============================================================

class TranslateProgress:
    """
    {
      "page_id": "ok" | "fail",
      "__content__": "ok" | "fail",
      "__content_items__": { "tree[0].name_zh": "ok" | "fail", ... }
    }
    """

    def __init__(self, path: Path):
        self.path = path
        self.data = {}
        if path.exists():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
                ok = sum(1 for v in self.data.values() if v == "ok")
                log.info(f"📂 Прогресс: {ok} ok / {len(self.data)} записей")
            except Exception as e:
                log.warning(f"Не загрузился {path.name}: {e}")

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

    def content_items(self) -> dict:
        v = self.data.get("__content_items__")
        if not isinstance(v, dict):
            v = {}
            self.data["__content_items__"] = v
        return v

    def content_item_is_ok(self, key: str) -> bool:
        return self.content_items().get(key) == "ok"

    def content_item_set(self, key: str, status: str):
        self.content_items()[key] = status

    def reset_content(self):
        self.data.pop("__content__", None)
        self.data.pop("__content_items__", None)
        self.save()


# ============================================================
# Утилиты
# ============================================================

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

# текст между тегами (не атрибуты)
TEXT_NODE_RE = re.compile(r">([^<>]*)<", re.S)

def _has_chinese(s: str) -> bool:
    return bool(s) and bool(CJK_RE.search(s))

def _has_russian(s: str) -> bool:
    return bool(s) and bool(RU_PROFILE.letter_re.search(s))

def _is_translated(s: str, profile: LangProfile) -> bool:
    if not s:
        return False
    if CJK_RE.search(s):
        return False
    return bool(profile.letter_re.search(s))


# ============================================================
# JS-хелпер Google Translate
# ============================================================

TRANSLATE_SCRIPT_TEMPLATE = r"""
(() => {
  if (window.__gt_ready) return;

  const TARGET_LANG = '__TARGET_LANG__';

  if (!document.getElementById('google_translate_element')) {
    const div = document.createElement('div');
    div.id = 'google_translate_element';
    div.style.display = 'none';
    document.body.appendChild(div);
  }

  window.googleTranslateElementInit = function () {
    try {
      new google.translate.TranslateElement(
        { pageLanguage: 'zh-CN', includedLanguages: TARGET_LANG, autoDisplay: false },
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

  window.__translateToTarget = () => new Promise((resolve) => {
    const combo = document.querySelector('.goog-te-combo');
    if (!combo) { resolve(false); return; }

    combo.value = TARGET_LANG;
    combo.dispatchEvent(new Event('change', { bubbles: true }));

    // счётчик "букв" целевого языка — для en это латиница,
    // но чтобы не путаться с исходным кодом страницы, считаем
    // по факту наличия перевода через API-атрибут.
    let lastCount = -1;
    let stable = 0;
    let ticks = 0;
    const MAX_TICKS = 240;
    const STABLE_NEEDED = 6;

    const checker = setInterval(() => {
      ticks++;
      const text = document.body.innerText || '';
      let count;
      if (TARGET_LANG === 'ru') {
        count = (text.match(/[а-яА-Я]/g) || []).length;
      } else {
        // для английского считаем латиницу, но отсекаем случай,
        // когда на странице вообще нет непустого текста
        count = (text.match(/[a-zA-Z]/g) || []).length;
      }

      if (count > 0 && count === lastCount) {
        stable++;
      } else {
        stable = 0;
      }
      lastCount = count;

      if (stable >= STABLE_NEEDED || ticks >= MAX_TICKS) {
        clearInterval(checker);
        resolve(count > 0);
      }
    }, 250);
  });
})();
"""

def _translate_script(target_lang: str) -> str:
    return TRANSLATE_SCRIPT_TEMPLATE.replace("__TARGET_LANG__", target_lang)


def ensure_translator(page, target_lang: str, timeout=TRANSLATE_TIMEOUT):
    page.evaluate(_translate_script(target_lang))

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
    ok = page.evaluate("() => window.__translateToTarget()")
    if not ok:
        log.warning("   ⚠️  Похоже, перевод не применился")
    time.sleep(0.4)
    return page.evaluate(
        "() => document.getElementById('__translate_holder').innerHTML"
    )


def _html_text(html: str) -> str:
    html = re.sub(r"(?is)<script.*?</script>", " ", html)
    html = re.sub(r"(?is)<style.*?</style>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    return text


def _page_translation_ok(html: str, profile: LangProfile) -> bool:
    text = _html_text(html)
    if not profile.letter_re.search(text):
        return False
    if CJK_RE.search(text):
        return False
    return True


# ============================================================
# Постобработка: перевод оставшихся CJK (например, в SVG <text>)
# ============================================================

def fix_leftover_cjk(page, html: str, profile: LangProfile,
                     max_rounds: int = 3) -> str:
    """
    Google Translate Element не трогает текст внутри SVG (<text>/<tspan>).
    Находим все текстовые узлы с CJK, переводим их отдельным запросом
    через тот же Google и подставляем обратно по индексам.

    Делаем до max_rounds раундов, потому что после подстановки могут
    обнаружиться новые (вложенные/смежные) узлы.
    """
    for round_no in range(1, max_rounds + 1):
        # прячем <script> и <style>, чтобы не зацепить их содержимое
        placeholders = {}
        def hide(m, _ph=placeholders):
            key = f"\x00H{len(_ph)}\x00"
            _ph[key] = m.group(0)
            return key

        protected = re.sub(r"(?is)<script.*?</script>", hide, html)
        protected = re.sub(r"(?is)<style.*?</style>", hide, protected)

        # находим текстовые узлы с CJK
        matches = []
        for m in TEXT_NODE_RE.finditer(protected):
            text = m.group(1)
            if _has_chinese(text):
                matches.append((m.start(1), m.end(1), text))

        if not matches:
            # вернём скрипты/стили
            for k, v in placeholders.items():
                protected = protected.replace(k, v)
            return protected

        log.info(f"   🧩 Раунд {round_no}: CJK-текстовых узлов: {len(matches)}")

        # переводим
        src_list = [t for _, _, t in matches]
        ru_list = google_translate_strings(page, src_list, profile)

        # собираем новый html справа налево, чтобы не сбить индексы
        result = protected
        for (start, end, orig), ru in reversed(list(zip(matches, ru_list))):
            if ru is None or not _is_translated(ru, profile):
                continue
            result = result[:start] + ru + result[end:]

        # вернём скрипты/стили
        for k, v in placeholders.items():
            result = result.replace(k, v)

        html = result

        # если CJK больше не осталось — выходим
        if not CJK_RE.search(_html_text(html)):
            return html

    return html


# ============================================================
# Перевод одной HTML-страницы
# ============================================================

def translate_page_file(page, src_file: Path, dst_file: Path,
                        profile: LangProfile) -> bool:
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
    translated = fix_leftover_cjk(page, translated, profile)

    dst_file.parent.mkdir(parents=True, exist_ok=True)
    dst_file.write_text(translated, encoding="utf-8")

    ok = _page_translation_ok(translated, profile)
    if not ok:
        leftover = CJK_RE.findall(_html_text(translated))
        log.warning(
            f"   ⚠️  Остались китайские символы: {len(leftover)} шт."
        )
    return ok


# ============================================================
# Перевод набора строк через Google (с якорями)
# ============================================================

def google_translate_strings(page, strings: list,
                             profile: LangProfile) -> list:
    """
    Переводит список строк через Google Translate Element.
    Возвращает список той же длины; для непереведённых — None,
    чтобы вызывающий код мог пометить "fail".
    """
    if not strings:
        return []

    results = [None] * len(strings)
    BATCH = 40

    def esc(x):
        return (x.replace("&", "&amp;")
                 .replace("<", "&lt;")
                 .replace(">", "&gt;"))

    for i in range(0, len(strings), BATCH):
        chunk = strings[i:i + BATCH]
        parts = [f'<p data-k="{j}">{esc(s)}</p>' for j, s in enumerate(chunk)]
        html = "<div id='__tr'>" + "".join(parts) + "</div>"

        _put_html_into_holder(page, html)
        page.evaluate("() => window.__translateToTarget()")
        time.sleep(0.4)

        translated = page.evaluate(
            """() => Array.from(
                document.querySelectorAll('#__tr p')
            ).map(p => ({k: p.getAttribute('data-k'),
                         t: p.textContent.trim()}))"""
        )

        got = {}
        for item in translated:
            try:
                k = int(item["k"])
            except (TypeError, ValueError):
                continue
            got[k] = item["t"]

        for j, src in enumerate(chunk):
            ru = (got.get(j) or "").strip()
            if _is_translated(ru, profile):
                results[i + j] = ru

        log.info(f"   🔤 [{min(i+BATCH, len(strings))}/{len(strings)}] обработано")

    return results


# ============================================================
# Перевод content.json
# ============================================================

def translate_content_json(page, src_json: Path, dst_json: Path,
                           progress: TranslateProgress,
                           profile: LangProfile):
    data = json.loads(src_json.read_text(encoding="utf-8"))

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

    for field in ("doc_title", "title_zh", "title", "name_zh", "name"):
        v = data.get(field)
        if isinstance(v, str):
            add(f"__doc__.{field}", v)

    def collect_tree(node, path):
        for field in ("name_zh", "name", "title_zh", "title"):
            v = node.get(field)
            if isinstance(v, str):
                add(f"{path}.{field}", v)
        for idx, c in enumerate(node.get("children") or []):
            collect_tree(c, f"{path}.children[{idx}]")

    for idx, top in enumerate(data.get("tree", []) or []):
        collect_tree(top, f"tree[{idx}]")

    for pid, item in (data.get("flat_pages") or {}).items():
        if not isinstance(item, dict):
            continue
        for field in ("name_zh", "name", "title_zh", "title"):
            v = item.get(field)
            if isinstance(v, str):
                add(f"flat_pages[{pid}].{field}", v)

    log.info(f"   🔤 Уникальных китайских строк: {len(order)}")

    existing_mapping = {}
    if dst_json.exists():
        try:
            prev = json.loads(dst_json.read_text(encoding="utf-8"))
            existing_mapping = prev.get("__translations__", {}) or {}
        except Exception as e:
            log.warning(f"Не удалось прочитать старый {dst_json.name}: {e}")

    pending_keys = []
    for k in order:
        if progress.content_item_is_ok(k) and _is_translated(existing_mapping.get(k, ""), profile):
            continue
        pending_keys.append(k)

    log.info(f"   🧩 К переводу сейчас: {len(pending_keys)} "
             f"(уже ok: {len(order) - len(pending_keys)})")

    if pending_keys:
        src_list = [to_translate[k] for k in pending_keys]
        ru_list = google_translate_strings(page, src_list, profile)

        for k, ru in zip(pending_keys, ru_list):
            if ru is not None and _is_translated(ru, profile):
                existing_mapping[k] = ru
                progress.content_item_set(k, "ok")
            else:
                existing_mapping[k] = to_translate[k]
                progress.content_item_set(k, "fail")
        progress.save()

    mapping = existing_mapping

    for field in ("doc_title", "title_zh", "title", "name_zh", "name"):
        k = f"__doc__.{field}"
        if k in mapping:
            ru_field = "doc_title_ru" if field == "doc_title" else f"{field}_ru"
            data[ru_field] = mapping[k]
    if isinstance(data.get("doc_title"), str) and "doc_title_ru" not in data:
        data["doc_title_ru"] = data["doc_title"]

    def apply_tree(node, path):
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

    data["__translations__"] = mapping
    data["translated_at"] = datetime.now().isoformat(timespec="seconds")
    data["translated_by"] = "google-translate-element"
    dst_json.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info(f"   💾 {dst_json}")

    fails = [k for k in order if not progress.content_item_is_ok(k)]
    log.info(f"   📊 content.json: ok={len(order)-len(fails)}, fail={len(fails)}")
    if fails:
        log.warning("   ⚠️  Не переведены (будут добиты при след. запуске):")
        for k in fails[:10]:
            log.warning(f"      • {k} = {to_translate[k][:60]!r}")
        if len(fails) > 10:
            log.warning(f"      ... и ещё {len(fails)-10}")

    progress.set("__content__", "ok" if not fails else "fail")


# ============================================================
# Main
# ============================================================

def main():
    only_content = "--content" in sys.argv
    only_pages = "--pages" in sys.argv
    force_content = "--force-content" in sys.argv
    to_english = "--en" in sys.argv

    profile = EN_PROFILE if to_english else RU_PROFILE

    out_root = Path(OUTPUT_DIR) / DOC_ID
    setup_logger(out_root, suffix=profile.log_suffix)

    pages_dir = out_root / "pages"
    ru_pages_dir = out_root / profile.pages_dir
    ru_pages_dir.mkdir(parents=True, exist_ok=True)

    progress = TranslateProgress(out_root / profile.progress)
    if force_content:
        progress.reset_content()

    log.info(f"🌐 Целевой язык: {profile.name_ru} ({profile.code})")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                f"--lang={profile.code}-{profile.code.upper()}",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = browser.new_context(
            user_agent=USER_AGENT,
            locale=f"{profile.code}-{profile.code.upper()}",
            viewport={"width": 1400, "height": 900},
        )
        page = context.new_page()

        log.info(f"🔤 Инициализируем Google Translate ({profile.code})...")
        page.goto("https://example.com", wait_until="domcontentloaded")
        ensure_translator(page, profile.code, timeout=60)
        log.info("✅ Переводчик готов")

        interrupted = {"v": False}

        def on_sigint(sig, frame):
            log.warning("\n⛔ Прерывание — сохраняем прогресс...")
            interrupted["v"] = True

        signal.signal(signal.SIGINT, on_sigint)

        try:
            if not only_pages:
                src_json = out_root / "content.json"
                dst_json = out_root / profile.content_out

                if progress.is_ok("__content__") and dst_json.exists():
                    log.info("⏭️  content.json уже переведён полностью")
                elif not src_json.exists():
                    log.warning("⚠️  content.json не найден — пропускаем")
                else:
                    log.info(f"📄 Переводим content.json на {profile.name_ru}...")
                    try:
                        translate_content_json(
                            page, src_json, dst_json, progress, profile
                        )
                    except Exception as e:
                        log.error(f"Ошибка перевода content.json: {e}",
                                  exc_info=True)
                        progress.set("__content__", "fail")

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
                        ok = translate_page_file(page, src, dst, profile)
                        if ok:
                            progress.set(pid, "ok")
                            done += 1
                        else:
                            progress.set(pid, "fail")
                            failed += 1
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