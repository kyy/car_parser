# build_index.py
"""
Генерирует index.html для просмотра переведённого руководства.
Слева — дерево, справа — iframe с контентом.
Кнопка переключает RU / ORIG.
Стили и скрипты просмотрщика (таблицы, картинки, lightbox)
подключаются к каждой странице отдельно — это работает и на file://.
"""
import json
import shutil
from pathlib import Path
from config import OUTPUT_DIR, DOC_ID


# ============================================================
# Утилиты
# ============================================================

def escape(s: str) -> str:
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;"))


def render_tree(nodes) -> str:
    if not nodes:
        return ""
    html = ['<ul class="tree">']
    for node in nodes:
        name = node.get("name_ru") or node.get("name_zh") or "?"
        is_page = node.get("is_page")
        children = node.get("children") or []
        if is_page:
            pid = node.get("id", "")
            html.append(
                f'<li class="page" data-id="{pid}">'
                f'<span class="label page-label" data-page="{pid}" '
                f'onclick="openPage(\'{pid}\')">{escape(name)}</span>'
                f'</li>'
            )
        else:
            html.append(
                f'<li class="folder">'
                f'<span class="label folder-label" onclick="toggleFolder(this)">'
                f'<span class="arrow">▸</span>{escape(name)}</span>'
            )
            if children:
                html.append(render_tree(children))
            html.append('</li>')
    html.append('</ul>')
    return "".join(html)


# ============================================================
# CSS и JS, вшиваемые в каждую страницу
# ============================================================

VIEWER_CSS = r"""
/* _viewer.css — стили контента для страниц руководства */
html, body {
    margin: 0 !important;
    padding: 0 !important;
    max-width: none !important;
    width: 100% !important;
    overflow-x: hidden !important;
}
body {
    padding: 24px 32px 48px 32px !important;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                 Roboto, "Helvetica Neue", Arial, sans-serif;
    font-size: 15px;
    line-height: 1.65;
    color: #1f2328;
    background: #fff;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    letter-spacing: 0.005em;
}

h1, h2, h3, h4, h5, h6 {
    font-weight: 600;
    line-height: 1.3;
    color: #0d1117;
    margin: 1.6em 0 0.6em 0;
}
h1 { font-size: 1.7em; border-bottom: 1px solid #eaecef; padding-bottom: .3em; }
h2 { font-size: 1.4em; border-bottom: 1px solid #eaecef; padding-bottom: .3em; }
h3 { font-size: 1.2em; }
h4 { font-size: 1.05em; }
h5, h6 { font-size: 1em; color: #57606a; }
h1:first-child, h2:first-child, h3:first-child { margin-top: 0; }

p { margin: .7em 0; }

a { color: #0969da; text-decoration: none; }
a:hover { text-decoration: underline; }

ul, ol { margin: .7em 0; padding-left: 1.6em; }
li { margin: .25em 0; }

blockquote {
    margin: 1em 0; padding: .4em 1em;
    border-left: 4px solid #d0d7de;
    background: #f6f8fa; color: #57606a;
    border-radius: 0 6px 6px 0;
}

hr { border: none; border-top: 1px solid #eaecef; margin: 1.6em 0; }

code {
    font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo,
                 Consolas, "Liberation Mono", monospace;
    font-size: .88em;
    background: #f6f8fa;
    padding: .15em .4em;
    border-radius: 4px;
}
pre {
    background: #f6f8fa;
    border: 1px solid #eaecef;
    border-radius: 6px;
    padding: 12px 16px;
    overflow-x: auto;
    line-height: 1.5;
}
pre code { background: transparent; padding: 0; border-radius: 0; font-size: .86em; }

/* ---------- Таблицы ---------- */
.__table_wrap {
    width: 100%;
    overflow-x: auto;
    margin: 1em 0;
    border: 1px solid #d0d7de;
    border-radius: 8px;
    background: #fff;
}
table {
    border-collapse: collapse;
    border-spacing: 0;
    width: 100%;
    font-size: .94em;
    text-align: left;
    background: #fff;
}
thead { background: #f6f8fa; }
th, td {
    text-align: left !important;
    vertical-align: top;
    padding: 8px 14px;
    border-bottom: 1px solid #eaecef;
    border-right: 1px solid #f0f2f4;
    word-wrap: break-word;
    overflow-wrap: anywhere;
}
th:last-child, td:last-child { border-right: none; }
tbody tr:last-child td { border-bottom: none; }
tbody tr:nth-child(even) { background: #fafbfc; }
tbody tr:hover { background: #f0f6ff; }
th { font-weight: 600; color: #0d1117; white-space: nowrap; }

/* ---------- Картинки ---------- */
img, svg, video {
    display: block;
    width: 100% !important;
    max-width: 100% !important;
    height: auto !important;
    margin: 14px 0;
    cursor: zoom-in;
    opacity: 0;
    transition: opacity .2s ease-in;
    border-radius: 6px;
}
img.loaded, svg.loaded, video.loaded { opacity: 1; }
img[data-small="1"] {
    width: auto !important;
    max-width: min(100%, 300px) !important;
    display: inline-block;
    vertical-align: middle;
}
img.__loading {
    background: #f0f0f0 url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='40' height='40' viewBox='0 0 40 40'><circle cx='20' cy='20' r='14' fill='none' stroke='%23ccc' stroke-width='3' stroke-dasharray='60 20'><animateTransform attributeName='transform' type='rotate' from='0 20 20' to='360 20 20' dur='1s' repeatCount='indefinite'/></circle></svg>") center center no-repeat;
    min-height: 80px;
}

/* ---------- Lightbox ---------- */
#__lightbox {
    position: fixed; inset: 0; background: rgba(0,0,0,.92);
    display: none; align-items: center; justify-content: center;
    z-index: 999999; cursor: zoom-out;
}
#__lightbox img {
    width: auto !important;
    max-width: 96vw !important;
    max-height: 96vh !important;
    box-shadow: 0 0 40px rgba(0,0,0,.6);
    background: #fff;
    opacity: 1 !important;
    cursor: zoom-out;
    transition: none;
    border-radius: 4px;
}
#__lightbox.open { display: flex; }

.goog-te-banner-frame, #goog-gt-tt, .goog-tooltip,
.goog-te-balloon-frame, #google_translate_element { display: none !important; }
body { top: 0 !important; }
"""

VIEWER_JS = r"""
/* _viewer.js — обёртка таблиц, lazy-loading, lightbox */
(function () {
    "use strict";

    function ready(fn) {
        if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", fn);
        } else {
            fn();
        }
    }

    ready(function () {
        // --- таблицы: обернуть в скроллящийся контейнер ---
        document.querySelectorAll("table").forEach(function (tbl) {
            if (tbl.parentElement &&
                tbl.parentElement.classList.contains("__table_wrap")) return;
            var wrap = document.createElement("div");
            wrap.className = "__table_wrap";
            tbl.parentNode.insertBefore(wrap, tbl);
            wrap.appendChild(tbl);
        });

        // --- lightbox ---
        var lb = document.createElement("div");
        lb.id = "__lightbox";
        lb.innerHTML = '<img id="__lightbox_img" alt="">';
        lb.addEventListener("click", function () {
            lb.classList.remove("open");
        });
        document.body.appendChild(lb);

        document.addEventListener("click", function (e) {
            var t = e.target;
            if (t.tagName !== "IMG" || t.id === "__lightbox_img") return;
            var orig = t.dataset.orig || t.src;
            var img = document.getElementById("__lightbox_img");
            img.src = orig;
            lb.classList.add("open");
        });
        document.addEventListener("keydown", function (e) {
            if (e.key === "Escape") lb.classList.remove("open");
        });

        // --- картинки: lazy + fade-in + мелкие ---
        var imgs = document.querySelectorAll("img");
        imgs.forEach(function (img) {
            if (!img.hasAttribute("loading")) img.setAttribute("loading", "lazy");
            img.setAttribute("decoding", "async");

            var w = parseInt(img.getAttribute("width") || "0", 10);
            var h = parseInt(img.getAttribute("height") || "0", 10);
            if ((w > 0 && w < 200) || (h > 0 && h < 100)) {
                img.dataset.small = "1";
            }
            img.removeAttribute("width");
            img.removeAttribute("height");

            var preview = img.getAttribute("src") || "";
            if (preview && !preview.startsWith("data:")) {
                img.dataset.realSrc = preview;
                img.removeAttribute("src");
                img.classList.add("__loading");
            } else {
                img.classList.add("loaded");
            }

            img.addEventListener("load", function () {
                img.classList.remove("__loading");
                img.classList.add("loaded");
            });
            img.addEventListener("error", function () {
                img.classList.remove("__loading");
                img.classList.add("loaded");
            });
        });

        if (imgs.length && "IntersectionObserver" in window) {
            var io = new IntersectionObserver(function (entries) {
                entries.forEach(function (entry) {
                    if (!entry.isIntersecting) return;
                    var img = entry.target;
                    if (img.dataset.realSrc) {
                        img.src = img.dataset.realSrc;
                        delete img.dataset.realSrc;
                    }
                    io.unobserve(img);
                });
            }, { rootMargin: "600px 0px", threshold: 0.01 });
            imgs.forEach(function (img) { io.observe(img); });
        } else {
            imgs.forEach(function (img) {
                if (img.dataset.realSrc) {
                    img.src = img.dataset.realSrc;
                    delete img.dataset.realSrc;
                }
            });
        }
    });
})();
"""


def inject_viewer_assets(out_root: Path) -> None:
    """Копирует _viewer.css и _viewer.js в out_root и подключает их
    ко всем страницам ru_pages/*.html и pages/*.html."""
    (out_root / "_viewer.css").write_text(VIEWER_CSS, encoding="utf-8")
    (out_root / "_viewer.js").write_text(VIEWER_JS, encoding="utf-8")

    link_tag = '<link rel="stylesheet" href="../_viewer.css">'
    script_tag = '<script src="../_viewer.js" defer></script>'

    for sub in ("ru_pages", "pages"):
        d = out_root / sub
        if not d.is_dir():
            continue
        for html in d.glob("*.html"):
            try:
                text = html.read_text(encoding="utf-8")
            except Exception:
                continue
            orig = text
            if "_viewer.css" not in text:
                if "</head>" in text:
                    text = text.replace("</head>", link_tag + "\n</head>", 1)
                else:
                    text = link_tag + "\n" + text
            if "_viewer.js" not in text:
                if "</body>" in text:
                    text = text.replace("</body>", script_tag + "\n</body>", 1)
                else:
                    text = text + "\n" + script_tag
            if text != orig:
                html.write_text(text, encoding="utf-8")


# ============================================================
# Шаблон index.html
# ============================================================

INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>__TITLE__</title>
<style>
  * { box-sizing: border-box; }
  html, body {
      margin: 0; padding: 0; height: 100%;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                   Roboto, "Helvetica Neue", Arial, sans-serif;
      font-size: 14px; color: #1f2328; background: #fafafa;
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
  }
  #layout { display: flex; height: 100vh; overflow: hidden; }

  /* ---------- Sidebar ---------- */
  #sidebar {
      width: 360px; min-width: 240px; max-width: 60vw;
      background: #fff; border-right: 1px solid #e6e8eb;
      display: flex; flex-direction: column;
      resize: horizontal; overflow: hidden; flex-shrink: 0;
  }
  #sidebar-header {
      padding: 12px 16px; border-bottom: 1px solid #e6e8eb;
      background: #f6f8fa;
      display: flex; align-items: center; justify-content: space-between; gap: 8px;
  }
  #doc-title {
      font-weight: 600; font-size: 14px;
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1;
  }
  #lang-toggle {
      border: 1px solid #ccc; background: #fff;
      padding: 4px 10px; border-radius: 6px; cursor: pointer;
      font-size: 12px; font-weight: 600; transition: all .15s; white-space: nowrap;
  }
  #lang-toggle:hover { background: #f0f0f0; }
  #lang-toggle.ru { background: #d4edda; border-color: #28a745; color: #155724; }
  #lang-toggle.orig { background: #fff3cd; border-color: #ffc107; color: #856404; }

  #search { padding: 8px 12px; border-bottom: 1px solid #eef0f2; }
  #search input {
      width: 100%; padding: 6px 10px;
      border: 1px solid #d0d7de; border-radius: 6px;
      font-size: 13px; outline: none;
      transition: border-color .15s, box-shadow .15s;
  }
  #search input:focus {
      border-color: #0969da;
      box-shadow: 0 0 0 3px rgba(9,105,218,.15);
  }
  #tree-container { flex: 1; overflow-y: auto; padding: 8px 0 24px 0; }

  /* ---------- Tree ---------- */
  ul.tree { list-style: none; margin: 0; padding: 0; }
  ul.tree ul.tree { padding-left: 16px; }
  li { margin: 0; }
  .label {
      display: block; padding: 4px 12px; cursor: pointer;
      border-radius: 4px; user-select: none;
      font-size: 13px; line-height: 1.4;
      white-space: normal; word-wrap: break-word;
  }
  .label:hover { background: #eef5ff; }
  .folder-label { font-weight: 600; color: #333; }
  .folder-label .arrow {
      display: inline-block; width: 14px;
      transition: transform .15s; color: #888; font-size: 11px;
  }
  li.folder.open > .folder-label .arrow { transform: rotate(90deg); }
  li.folder > ul.tree { display: none; }
  li.folder.open > ul.tree { display: block; }
  .page-label { color: #0969da; padding-left: 26px; }
  .page-label.active { background: #0969da; color: #fff; }
  li.hidden { display: none; }

  /* ---------- Main ---------- */
  #main {
      flex: 1; display: flex; flex-direction: column;
      overflow: hidden; background: #fff; min-width: 0;
  }
  #topbar {
      padding: 8px 16px; background: #fff;
      border-bottom: 1px solid #e6e8eb;
      display: flex; flex-direction: column; gap: 4px;
      flex-shrink: 0; min-height: 40px;
  }
  #topbar-row1 {
      display: flex; align-items: center;
      justify-content: space-between; gap: 12px; font-size: 13px;
  }
  #current-title {
      font-weight: 600; overflow: hidden; text-overflow: ellipsis;
      white-space: nowrap; flex: 1; color: #1f2328;
  }
  #open-external {
      color: #0969da; text-decoration: none; font-size: 12px;
      padding: 4px 8px; border-radius: 4px; white-space: nowrap;
  }
  #open-external:hover { background: #eef5ff; }
  #filepath-row {
      display: flex; align-items: center; gap: 8px;
      font-size: 12px; color: #57606a; min-width: 0;
  }
  #filepath {
      font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo,
                   Consolas, "Liberation Mono", monospace;
      background: #f6f8fa; border: 1px solid #d0d7de;
      border-radius: 6px; padding: 2px 8px; cursor: pointer;
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
      max-width: 100%; transition: background .15s;
  }
  #filepath:hover { background: #eef5ff; border-color: #0969da; }
  #filepath.copied { background: #d4edda; border-color: #28a745; color: #155724; }
  #open-folder {
      color: #0969da; text-decoration: none; font-size: 12px;
      padding: 2px 8px; border-radius: 4px; white-space: nowrap;
      border: 1px solid #d0d7de; background: #fff; cursor: pointer;
  }
  #open-folder:hover { background: #eef5ff; }

  #content-frame {
      flex: 1; width: 100%; border: none; background: #fff; display: block;
  }
  #welcome {
      padding: 60px 40px; text-align: center; color: #888;
      flex: 1; overflow: auto;
  }
  #welcome h1 { font-weight: 400; color: #333; }

  @media (max-width: 700px) {
      #sidebar { width: 100%; position: absolute; z-index: 10; height: 100%; }
  }
</style>
</head>
<body>

<div id="layout">
  <aside id="sidebar">
    <div id="sidebar-header">
      <div id="doc-title" title="__TITLE__">__TITLE__</div>
      <button id="lang-toggle" class="ru" onclick="toggleLang()"
              title="Переключить RU / ORIG">RU</button>
    </div>
    <div id="search">
      <input type="text" id="search-input"
             placeholder="Поиск по названию..." autocomplete="off">
    </div>
    <div id="tree-container">
      __TREE_HTML__
    </div>
  </aside>

  <main id="main">
    <div id="topbar">
      <div id="topbar-row1">
        <div id="current-title">—</div>
        <a id="open-external" href="#" target="_blank" style="display:none;">
          открыть в новой вкладке ↗
        </a>
      </div>
      <div id="filepath-row" style="display:none;">
        <span id="filepath" title="Кликните, чтобы скопировать путь"></span>
        <a id="open-folder" href="#" title="Открыть папку с файлом">открыть папку 📂</a>
      </div>
    </div>
    <iframe id="content-frame" src="about:blank" loading="lazy"></iframe>
    <div id="welcome">
      <h1>Выбери раздел слева</h1>
      <p>Контент откроется здесь. Кнопка <b>RU</b> переключает<br>
         переведённый и оригинальный контент.</p>
    </div>
  </main>
</div>

<script>
// ---------- Состояние ----------
let currentPageId = null;
let currentLang = "ru";

// ---------- Дерево ----------
function toggleFolder(el) {
    el.parentElement.classList.toggle("open");
}

function openPage(id) {
    currentPageId = id;
    const prev = document.querySelector(".page-label.active");
    if (prev) prev.classList.remove("active");
    const active = document.querySelector('.page[data-id="' + id + '"] .page-label');
    if (active) {
        active.classList.add("active");
        let p = active.closest("li.folder");
        while (p) { p.classList.add("open"); p = p.parentElement.closest("li.folder"); }
        active.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
    const name = active ? active.textContent.trim() : id;
    document.getElementById("current-title").textContent = name;
    loadPage();
}

function loadPage() {
    if (!currentPageId) return;
    const folder = currentLang === "ru" ? "ru_pages" : "pages";
    const src = folder + "/" + currentPageId + ".html";

    const frame = document.getElementById("content-frame");
    frame.src = src;
    document.getElementById("welcome").style.display = "none";
    frame.style.display = "block";

    const ext = document.getElementById("open-external");
    ext.href = src;
    ext.style.display = "inline-block";

    const fpRow = document.getElementById("filepath-row");
    const fp = document.getElementById("filepath");
    fp.textContent = src;
    fpRow.style.display = "flex";

    const of = document.getElementById("open-folder");
    of.href = folder + "/";
}

function copyPath() {
    const fp = document.getElementById("filepath");
    const text = fp.textContent;
    const done = () => {
        fp.classList.add("copied");
        const old = fp.textContent;
        fp.textContent = "✓ скопировано";
        setTimeout(() => { fp.classList.remove("copied"); fp.textContent = old; }, 1000);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, done);
    } else {
        const ta = document.createElement("textarea");
        ta.value = text; document.body.appendChild(ta); ta.select();
        try { document.execCommand("copy"); } catch (e) {}
        document.body.removeChild(ta); done();
    }
}

function toggleLang() {
    currentLang = currentLang === "ru" ? "orig" : "ru";
    const btn = document.getElementById("lang-toggle");
    btn.textContent = currentLang === "ru" ? "RU" : "ORIG";
    btn.className = currentLang === "ru" ? "ru" : "orig";
    if (currentPageId) loadPage();
}

// ============================================================
// Быстрый фильтр
// ============================================================
// Идея: собрать один раз плоский список страниц и папок.
// На каждый ввод — линейный проход, без querySelectorAll.

var PAGE_INDEX = [];     // { li, name }
var FOLDER_INDEX = [];   // { li, depth } — все папки дерева

function buildSearchIndex() {
    PAGE_INDEX.length = 0;
    FOLDER_INDEX.length = 0;

    document.querySelectorAll("#tree-container li.page").forEach(li => {
        const label = li.querySelector(".page-label");
        if (!label) return;
        PAGE_INDEX.push({
            li: li,
            name: label.textContent.trim().toLowerCase()
        });
    });
    document.querySelectorAll("#tree-container li.folder").forEach(li => {
        FOLDER_INDEX.push({ li: li });
    });
}

// Показать/скрыть поддерево: ставим/снимаем .hidden
function setHidden(el, hidden) {
    if (hidden) el.classList.add("hidden");
    else el.classList.remove("hidden");
}

function runSearch(q) {
    // 1. Сбросить все .hidden у страниц и папок
    for (let i = 0; i < PAGE_INDEX.length; i++) setHidden(PAGE_INDEX[i].li, false);
    for (let i = 0; i < FOLDER_INDEX.length; i++) setHidden(FOLDER_INDEX[i].li, false);

    if (!q) {
        // свернуть всё назад
        for (let i = 0; i < FOLDER_INDEX.length; i++) {
            FOLDER_INDEX[i].li.classList.remove("open");
        }
        // восстановить раскрытие вокруг активной страницы
        const active = document.querySelector(".page-label.active");
        if (active) {
            let p = active.closest("li.folder");
            while (p) { p.classList.add("open"); p = p.parentElement.closest("li.folder"); }
        }
        return;
    }

    // 2. Пометить, какие страницы совпали
    const matched = new Set();
    for (let i = 0; i < PAGE_INDEX.length; i++) {
        const p = PAGE_INDEX[i];
        if (p.name.indexOf(q) !== -1) matched.add(p.li);
    }

    // 3. Скрыть несовпавшие страницы
    for (let i = 0; i < PAGE_INDEX.length; i++) {
        const p = PAGE_INDEX[i];
        if (!matched.has(p.li)) setHidden(p.li, true);
    }

    // 4. Пройти по всем папкам снизу вверх: если под папкой нет
    //    ни одной видимой страницы — скрыть её; иначе оставить
    //    и раскрыть.
    //    (снизу вверх = обратный порядок DOM)
    for (let i = FOLDER_INDEX.length - 1; i >= 0; i--) {
        const f = FOLDER_INDEX[i].li;
        const visiblePages = f.querySelectorAll("li.page:not(.hidden)").length;
        if (visiblePages === 0) {
            setHidden(f, true);
            f.classList.remove("open");
        } else {
            setHidden(f, false);
            f.classList.add("open");
        }
    }
}

// Дебаунс, чтобы не дёргать фильтр на каждую букву
let searchTimer = null;
document.getElementById("search-input").addEventListener("input", function (e) {
    const q = e.target.value.trim().toLowerCase();
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(() => runSearch(q), 120);
});

// ---------- Кнопка копирования пути ----------
document.getElementById("filepath").addEventListener("click", copyPath);

// ---------- Автооткрытие первой страницы ----------
window.addEventListener("DOMContentLoaded", function () {
    buildSearchIndex();
    const first = document.querySelector("li.page .page-label");
    if (first) first.click();
});
</script>

</body>
</html>
"""


# ============================================================
# Main
# ============================================================

def main():
    out_root = Path(OUTPUT_DIR) / DOC_ID

    content_path = out_root / "content.ru.json"
    if not content_path.exists():
        content_path = out_root / "content.json"
    if not content_path.exists():
        raise SystemExit(f"❌ Не найден content.json в {out_root}")

    print(f"📂 Источник: {content_path}")
    data = json.loads(content_path.read_text(encoding="utf-8"))

    title = data.get("title_ru") or data.get("doc_title") or "Руководство"
    tree = data.get("tree", [])
    if not tree:
        raise SystemExit("❌ Пустое дерево в content.json")

    tree_html = render_tree(tree)

    # 1. Вшить стили/скрипты просмотрщика во все страницы
    inject_viewer_assets(out_root)
    print("✅ _viewer.css / _viewer.js вшиты в ru_pages/ и pages/")

    # 2. Собрать index.html
    html = (INDEX_TEMPLATE
            .replace("__TITLE__", escape(title))
            .replace("__TREE_HTML__", tree_html))

    index_path = out_root / "index.html"
    index_path.write_text(html, encoding="utf-8")
    print(f"✅ {index_path}")
    print(f"\nОткрой:")
    print(f"   file:///{index_path.resolve().as_posix()}")


if __name__ == "__main__":
    main()