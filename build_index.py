# build_index.py
"""
Генерирует index.html для просмотра переведённого руководства.
Слева — дерево, справа — iframe с контентом.
Кнопка переключает RU / ORIG / EN (папки ru_pages / pages / en_pages).
Стили и скрипты просмотрщика (таблицы, картинки, lightbox)
подключаются к каждой странице отдельно — это работает и на file://.

Возможности:
  - _listing.html — листинг страниц папки с колонкой Title и поиском.
  - Закладки (localStorage) с комментариями, экспорт / импорт JSON.
  - Кнопка «Отблагодарить автора» (заглушка: методы оплаты и контакты).
"""
import json
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


def capitalize_first(s: str) -> str:
    """Делает первую букву заглавной, остальное не трогает."""
    if not s:
        return s
    return s[0].upper() + s[1:]


def render_tree(nodes) -> str:
    if not nodes:
        return ""
    html = ['<ul class="tree">']
    for node in nodes:
        raw_name = node.get("name_ru") or node.get("name_zh") or "?"
        name = capitalize_first(raw_name)
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


def collect_pages(nodes, acc=None):
    """Плоский список страниц: {id, title} — для листинга папки."""
    if acc is None:
        acc = []
    for n in nodes:
        if n.get("is_page") and n.get("id"):
            raw = n.get("name_ru") or n.get("name_zh") or n["id"]
            acc.append({
                "id": n["id"],
                "title": capitalize_first(raw),
            })
        collect_pages(n.get("children") or [], acc)
    return acc


# ============================================================
# CSS и JS, вшиваемые в каждую страницу контента
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

/* ---------- Картинки (в контенте) ---------- */
img, svg, video {
    display: block;
    width: auto !important;
    max-width: 100% !important;
    height: auto !important;
    margin: 14px auto;
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
    margin: 14px 4px;
}
img.__loading {
    background: #f0f0f0 url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='40' height='40' viewBox='0 0 40 40'><circle cx='20' cy='20' r='14' fill='none' stroke='%23ccc' stroke-width='3' stroke-dasharray='60 20'><animateTransform attributeName='transform' type='rotate' from='0 20 20' to='360 20 20' dur='1s' repeatCount='indefinite'/></circle></svg>") center center no-repeat;
    min-height: 80px;
}

/* ---------- Lightbox (реальный размер + зум + панорама) ---------- */
#__lightbox {
    position: fixed; inset: 0; background: rgba(0,0,0,.92);
    display: none; align-items: center; justify-content: center;
    z-index: 999999;
    overflow: hidden;
    cursor: grab;
}
#__lightbox.open { display: flex; }
#__lightbox.dragging { cursor: grabbing; }
#__lightbox img {
    width: auto !important;
    max-width: none !important;
    max-height: none !important;
    box-shadow: 0 0 40px rgba(0,0,0,.6);
    background: #fff;
    opacity: 1 !important;
    cursor: grab;
    transition: none;
    border-radius: 4px;
    user-select: none;
    -webkit-user-drag: none;
    will-change: transform;
    transform-origin: center center;
    margin: 0;
}
#__lightbox.dragging img { cursor: grabbing; }

#__lightbox_hint {
    position: fixed; bottom: 16px; left: 50%; transform: translateX(-50%);
    color: #fff; background: rgba(0,0,0,.55);
    padding: 6px 14px; border-radius: 20px;
    font-size: 12px; font-family: sans-serif;
    pointer-events: none; white-space: nowrap;
    opacity: .85;
}

.goog-te-banner-frame, #goog-gt-tt, .goog-tooltip,
.goog-te-balloon-frame, #google_translate_element { display: none !important; }
body { top: 0 !important; }
"""

VIEWER_JS = r"""
/* _viewer.js — обёртка таблиц, lazy-loading, lightbox с зумом и панорамой */
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

        // ============================================================
        // Lightbox: реальный размер, колесо — зум к курсору,
        // перетаскивание — панорама, dblclick — сброс, Esc — закрыть.
        // ============================================================
        var lb = document.createElement("div");
        lb.id = "__lightbox";
        lb.innerHTML =
            '<img id="__lightbox_img" alt="" draggable="false">' +
            '<div id="__lightbox_hint">колесо — зум · перетаскивание — панорама · 2×клик — сброс · Esc — закрыть</div>';
        document.body.appendChild(lb);

        var lbImg = lb.querySelector("#__lightbox_img");

        var tx = 0, ty = 0, scale = 1;
        var dragging = false, startX = 0, startY = 0, startTx = 0, startTy = 0;

        function applyTransform() {
            lbImg.style.transform =
                "translate(" + tx + "px," + ty + "px) scale(" + scale + ")";
        }
        function resetTransform() {
            tx = 0; ty = 0; scale = 1;
            applyTransform();
        }
        function closeLightbox() {
            lb.classList.remove("open", "dragging");
            dragging = false;
            resetTransform();
        }

        document.addEventListener("click", function (e) {
            var t = e.target;
            if (t.tagName !== "IMG" || t.id === "__lightbox_img") return;
            var orig = t.dataset.orig || t.src;
            lbImg.src = orig;
            resetTransform();
            lb.classList.add("open");
        });

        lb.addEventListener("click", function (e) {
            if (e.target === lb) closeLightbox();
        });
        document.addEventListener("keydown", function (e) {
            if (e.key === "Escape") closeLightbox();
        });

        lb.addEventListener("wheel", function (e) {
            if (!lb.classList.contains("open")) return;
            e.preventDefault();

            var rect = lbImg.getBoundingClientRect();
            var cx = e.clientX - (rect.left + rect.width / 2);
            var cy = e.clientY - (rect.top + rect.height / 2);

            var factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
            var newScale = Math.min(20, Math.max(0.1, scale * factor));
            var k = newScale / scale;

            tx = cx - k * (cx - tx);
            ty = cy - k * (cy - ty);
            scale = newScale;

            applyTransform();
        }, { passive: false });

        function onDown(e) {
            if (!lb.classList.contains("open")) return;
            if (e.target !== lbImg && e.target !== lb) return;
            dragging = true;
            lb.classList.add("dragging");
            var p = e.touches ? e.touches[0] : e;
            startX = p.clientX; startY = p.clientY;
            startTx = tx; startTy = ty;
            e.preventDefault();
        }
        function onMove(e) {
            if (!dragging) return;
            var p = e.touches ? e.touches[0] : e;
            tx = startTx + (p.clientX - startX);
            ty = startTy + (p.clientY - startY);
            applyTransform();
            e.preventDefault();
        }
        function onUp() {
            if (!dragging) return;
            dragging = false;
            lb.classList.remove("dragging");
        }

        lb.addEventListener("mousedown", onDown);
        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);

        lb.addEventListener("touchstart", onDown, { passive: false });
        window.addEventListener("touchmove", onMove, { passive: false });
        window.addEventListener("touchend", onUp);
        window.addEventListener("touchcancel", onUp);

        lbImg.addEventListener("dblclick", function (e) {
            e.stopPropagation();
            resetTransform();
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
    ко всем страницам ru_pages/*.html, pages/*.html и en_pages/*.html."""
    (out_root / "_viewer.css").write_text(VIEWER_CSS, encoding="utf-8")
    (out_root / "_viewer.js").write_text(VIEWER_JS, encoding="utf-8")

    link_tag = '<link rel="stylesheet" href="../_viewer.css">'
    script_tag = '<script src="../_viewer.js" defer></script>'

    for sub in ("ru_pages", "pages", "en_pages"):
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

INDEX_TEMPLATE = r"""<!DOCTYPE html>
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
      padding: 10px 12px; border-bottom: 1px solid #e6e8eb;
      background: #f6f8fa;
      display: flex; align-items: center; gap: 6px;
  }
  #doc-title {
      font-weight: 600; font-size: 14px;
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1;
      min-width: 0;
  }
  #lang-toggle {
      border: 1px solid #ccc; background: #fff;
      padding: 4px 10px; border-radius: 6px; cursor: pointer;
      font-size: 12px; font-weight: 600; transition: all .15s; white-space: nowrap;
      min-width: 54px; text-align: center;
  }
  #lang-toggle:hover { background: #f0f0f0; }
  #lang-toggle.ru   { background: #d4edda; border-color: #28a745; color: #155724; }
  #lang-toggle.orig { background: #fff3cd; border-color: #ffc107; color: #856404; }
  #lang-toggle.en   { background: #dbeafe; border-color: #0969da; color: #0a3069; }

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
      justify-content: space-between; gap: 8px; font-size: 13px;
      flex-wrap: wrap;
  }
  #current-title {
      font-weight: 600; overflow: hidden; text-overflow: ellipsis;
      white-space: nowrap; flex: 1; color: #1f2328; min-width: 120px;
  }
  #topbar-actions { display: flex; gap: 6px; flex-wrap: wrap; }
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

  /* ---------- Кнопки topbar ---------- */
  .tb-btn {
      border: 1px solid #d0d7de; background: #fff;
      color: #1f2328; font-size: 12px;
      padding: 4px 10px; border-radius: 6px; cursor: pointer;
      white-space: nowrap; transition: background .15s, border-color .15s;
      display: inline-flex; align-items: center; gap: 5px;
      font-family: inherit; text-decoration: none;
  }
  .tb-btn:hover { background: #eef5ff; border-color: #0969da; }
  .tb-btn.active {
      background: #fff8e1; border-color: #ffc107; color: #856404;
  }
  .tb-btn .count {
      background: #0969da; color: #fff;
      border-radius: 10px; padding: 1px 7px;
      font-size: 11px; font-weight: 600;
  }
  .tb-btn.active .count { background: #ffc107; color: #856404; }

  /* ---------- Модалки ---------- */
  .modal-back {
      position: fixed; inset: 0; background: rgba(0,0,0,.45);
      display: none; align-items: center; justify-content: center;
      z-index: 10000;
  }
  .modal-back.open { display: flex; }
  .modal {
      background: #fff; border-radius: 10px;
      box-shadow: 0 20px 60px rgba(0,0,0,.35);
      max-width: 92vw; max-height: 90vh;
      display: flex; flex-direction: column;
      overflow: hidden;
  }
  .modal.bookmarks { width: 680px; }
  .modal.donate { width: 480px; }
  .modal-head {
      padding: 12px 18px; background: #f6f8fa;
      border-bottom: 1px solid #e6e8eb;
      display: flex; align-items: center; justify-content: space-between;
      flex-shrink: 0;
  }
  .modal-head h2 {
      margin: 0; font-size: 15px; font-weight: 600;
  }
  .modal-body { padding: 16px 18px; overflow: auto; flex: 1; }
  .modal-foot {
      padding: 10px 18px; border-top: 1px solid #e6e8eb;
      background: #fafbfc;
      display: flex; gap: 8px; justify-content: flex-end;
      flex-wrap: wrap;
      flex-shrink: 0;
  }
  .modal-foot .left { margin-right: auto; display: flex; gap: 6px; }
  .modal-x {
      border: none; background: transparent; cursor: pointer;
      font-size: 22px; line-height: 1; color: #57606a; padding: 0 4px;
      font-family: inherit;
  }
  .modal-x:hover { color: #1f2328; }

  /* bookmark list */
  .bm-list { display: flex; flex-direction: column; gap: 8px; }
  .bm-item {
      border: 1px solid #e6e8eb; border-radius: 8px;
      padding: 10px 12px; background: #fff;
      display: flex; gap: 10px; align-items: flex-start;
  }
  .bm-item:hover { background: #f6f8fa; }
  .bm-item .bm-main { flex: 1; min-width: 0; }
  .bm-item .bm-title {
      font-weight: 600; font-size: 13px;
      color: #0969da; cursor: pointer;
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .bm-item .bm-title:hover { text-decoration: underline; }
  .bm-item .bm-id {
      font-family: ui-monospace, Menlo, Consolas, monospace;
      font-size: 11px; color: #8b949e; margin-top: 2px;
  }
  .bm-item .bm-comment {
      font-size: 12.5px; color: #24292f; margin-top: 6px;
      white-space: pre-wrap; word-wrap: break-word;
  }
  .bm-item .bm-comment.empty { color: #8b949e; font-style: italic; }
  .bm-item .bm-actions { display: flex; gap: 4px; flex-shrink: 0; }
  .bm-icon-btn {
      border: 1px solid #d0d7de; background: #fff; cursor: pointer;
      border-radius: 6px; padding: 3px 7px; font-size: 12px;
      color: #57606a; font-family: inherit;
  }
  .bm-icon-btn:hover { background: #eef5ff; border-color: #0969da; color: #0969da; }
  .bm-icon-btn.danger:hover { background: #ffe9e9; border-color: #d1242f; color: #d1242f; }

  .bm-empty {
      padding: 40px 20px; text-align: center;
      color: #8b949e; font-size: 13px;
  }

  /* comment edit dialog */
  .bm-edit-dialog { width: 480px; }
  .bm-edit-dialog textarea {
      width: 100%; min-height: 100px; resize: vertical;
      padding: 8px 10px; font-family: inherit; font-size: 13px;
      border: 1px solid #d0d7de; border-radius: 6px;
      outline: none;
  }
  .bm-edit-dialog textarea:focus {
      border-color: #0969da;
      box-shadow: 0 0 0 3px rgba(9,105,218,.15);
  }
  .bm-edit-dialog .label {
      font-size: 12px; color: #57606a; margin-bottom: 6px;
  }
  .bm-edit-dialog .pg-name {
      font-weight: 600; margin-bottom: 10px; font-size: 14px;
  }

  .btn-primary {
      background: #0969da; border-color: #0969da; color: #fff;
  }
  .btn-primary:hover { background: #0860c4; border-color: #0860c4; color: #fff; }
  .btn-danger {
      background: #fff; border-color: #d1242f; color: #d1242f;
  }
  .btn-danger:hover { background: #ffe9e9; }

  /* small note inside modal */
  .hint {
      font-size: 12px; color: #57606a;
      background: #f6f8fa; border: 1px solid #e6e8eb;
      border-radius: 6px; padding: 8px 12px; margin-top: 10px;
      line-height: 1.5;
  }
  .hint code {
      background: #fff; border: 1px solid #e6e8eb;
      padding: 1px 5px; border-radius: 4px; font-size: 11.5px;
  }

  /* donate placeholder */
  .donate-body {
      text-align: center; padding: 30px 20px; color: #57606a;
  }
  .donate-body .icon { font-size: 42px; margin-bottom: 10px; }
  .donate-body .msg { font-size: 14px; line-height: 1.6; }

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
      <button id="btn-bm-list" class="tb-btn" onclick="openBookmarks()"
              title="Список закладок">
        📑 <span id="bm-count" class="count">0</span>
      </button>
      <button id="lang-toggle" class="ru" onclick="toggleLang()"
              title="Переключить RU / ORIG / EN">RU</button>
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
        <div id="topbar-actions" style="display:none;">
          <button id="btn-bookmark" class="tb-btn"
                  onclick="toggleBookmark()"
                  title="Добавить / изменить закладку">
            <span id="bm-star">☆</span><span id="bm-label">В закладку</span>
          </button>
          <button class="tb-btn" onclick="openDonate()"
                  title="Отблагодарить автора">
            ❤️ Отблагодарить
          </button>
          <a id="open-external" href="#" target="_blank">
            открыть в новой вкладке ↗
          </a>
        </div>
      </div>
      <div id="filepath-row" style="display:none;">
        <span id="filepath" title="Кликните, чтобы скопировать путь"></span>
        <a id="open-folder" href="#" target="_blank"
           title="Список страниц с заголовками">открыть папку 📂</a>
      </div>
    </div>
    <iframe id="content-frame" src="about:blank" loading="lazy"></iframe>
    <div id="welcome">
      <h1>Выбери раздел слева</h1>
      <p>Контент откроется здесь. Кнопка <b>RU</b> переключает<br>
         языки: RU → ORIG → EN → RU.</p>
    </div>
  </main>
</div>

<!-- ============ Модалка: список закладок ============ -->
<div class="modal-back" id="bm-modal">
  <div class="modal bookmarks">
    <div class="modal-head">
      <h2>📑 Закладки</h2>
      <button class="modal-x" onclick="closeModal('bm-modal')">×</button>
    </div>
    <div class="modal-body">
      <div class="bm-list" id="bm-list"></div>
      <div class="bm-empty" id="bm-empty" style="display:none;">
        Пока нет закладок.<br>
        Открой страницу и нажми ☆ «В закладку».
      </div>
      <div class="hint">
        <b>Формат файла закладок:</b> JSON с расширением
        <code>.notes.json</code>.<br>
        Структура:
        <code>{ "version":1, "doc":"&lt;DOC_ID&gt;", "saved":"&lt;ISO&gt;",
        "bookmarks": { "&lt;page-id&gt;": {"comment":"…","ts":1234567890} } }</code>
      </div>
    </div>
    <div class="modal-foot">
      <div class="left">
        <button class="tb-btn" onclick="exportBookmarks()"
                title="Скачать закладки в .notes.json">⬇ Экспорт</button>
        <button class="tb-btn" onclick="importBookmarks()"
                title="Загрузить закладки из .notes.json">⬆ Импорт</button>
        <button class="tb-btn btn-danger" onclick="clearAllBookmarks()">
          Очистить всё
        </button>
      </div>
      <button class="tb-btn" onclick="closeModal('bm-modal')">Закрыть</button>
    </div>
  </div>
</div>

<!-- ============ Модалка: редактирование закладки ============ -->
<div class="modal-back" id="bm-edit-modal">
  <div class="modal bm-edit-dialog">
    <div class="modal-head">
      <h2 id="bm-edit-title">Закладка</h2>
      <button class="modal-x" onclick="closeModal('bm-edit-modal')">×</button>
    </div>
    <div class="modal-body">
      <div class="pg-name" id="bm-edit-pgname"></div>
      <div class="label">Комментарий (необязательно)</div>
      <textarea id="bm-edit-comment"
                placeholder="Например: важно, вернуться позже..."></textarea>
    </div>
    <div class="modal-foot">
      <button class="tb-btn btn-danger" id="bm-edit-remove"
              onclick="removeBookmarkFromDialog()">Удалить</button>
      <button class="tb-btn" onclick="closeModal('bm-edit-modal')">Отмена</button>
      <button class="tb-btn btn-primary" onclick="saveBookmarkFromDialog()">
        Сохранить
      </button>
    </div>
  </div>
</div>

<!-- ============ Модалка: отблагодарить автора (заглушка) ============ -->
<div class="modal-back" id="donate-modal">
  <div class="modal donate">
    <div class="modal-head">
      <h2>❤️ Отблагодарить автора</h2>
      <button class="modal-x" onclick="closeModal('donate-modal')">×</button>
    </div>
    <div class="modal-body">
      <div class="donate-body">
        <div class="icon">💳</div>
        <div class="msg">
          Тут методы оплаты и контакты.
        </div>
      </div>
    </div>
    <div class="modal-foot">
      <button class="tb-btn" onclick="closeModal('donate-modal')">Закрыть</button>
    </div>
  </div>
</div>

<script>
/* ============================================================
   Константы
   ============================================================ */
var BM_KEY = "bm:__DOC_ID__";
var DOC_ID = "__DOC_ID__";
var DOC_TITLE = "__TITLE__";

/* ============================================================
   Состояние
   ============================================================ */
var currentPageId = null;
var currentLang = "ru";   // "ru" | "orig" | "en"
var bookmarks = {};

/* ============================================================
   Дерево
   ============================================================ */
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

function langFolder(lang) {
    if (lang === "ru") return "ru_pages";
    if (lang === "en") return "en_pages";
    return "pages"; // orig
}

function loadPage() {
    if (!currentPageId) return;
    const folder = langFolder(currentLang);
    const src = folder + "/" + currentPageId + ".html";

    const frame = document.getElementById("content-frame");
    frame.src = src;
    document.getElementById("welcome").style.display = "none";
    frame.style.display = "block";

    const ext = document.getElementById("open-external");
    ext.href = src;

    const fpRow = document.getElementById("filepath-row");
    const fp = document.getElementById("filepath");
    fp.textContent = src;
    fpRow.style.display = "flex";

    const of = document.getElementById("open-folder");
    of.href = "_listing.html?folder=" + folder;

    document.getElementById("topbar-actions").style.display = "flex";

    updateBookmarkUI();
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
    // Цикл: ru → orig → en → ru
    if (currentLang === "ru") currentLang = "orig";
    else if (currentLang === "orig") currentLang = "en";
    else currentLang = "ru";

    const btn = document.getElementById("lang-toggle");
    if (currentLang === "ru") {
        btn.textContent = "RU";
        btn.className = "ru";
    } else if (currentLang === "en") {
        btn.textContent = "EN";
        btn.className = "en";
    } else {
        btn.textContent = "ORIG";
        btn.className = "orig";
    }
    if (currentPageId) loadPage();
}

/* ============================================================
   Быстрый фильтр дерева
   ============================================================ */
var PAGE_INDEX = [];
var FOLDER_INDEX = [];

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

function setHidden(el, hidden) {
    if (hidden) el.classList.add("hidden");
    else el.classList.remove("hidden");
}

function runSearch(q) {
    for (let i = 0; i < PAGE_INDEX.length; i++) setHidden(PAGE_INDEX[i].li, false);
    for (let i = 0; i < FOLDER_INDEX.length; i++) setHidden(FOLDER_INDEX[i].li, false);

    if (!q) {
        for (let i = 0; i < FOLDER_INDEX.length; i++) {
            FOLDER_INDEX[i].li.classList.remove("open");
        }
        const active = document.querySelector(".page-label.active");
        if (active) {
            let p = active.closest("li.folder");
            while (p) { p.classList.add("open"); p = p.parentElement.closest("li.folder"); }
        }
        return;
    }

    const matched = new Set();
    for (let i = 0; i < PAGE_INDEX.length; i++) {
        const p = PAGE_INDEX[i];
        if (p.name.indexOf(q) !== -1) matched.add(p.li);
    }

    for (let i = 0; i < PAGE_INDEX.length; i++) {
        const p = PAGE_INDEX[i];
        if (!matched.has(p.li)) setHidden(p.li, true);
    }

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

/* ============================================================
   Закладки
   ============================================================ */
function loadBookmarks() {
    try {
        bookmarks = JSON.parse(localStorage.getItem(BM_KEY) || "{}") || {};
    } catch (e) { bookmarks = {}; }
}

function saveBookmarks() {
    try {
        localStorage.setItem(BM_KEY, JSON.stringify(bookmarks));
    } catch (e) { /* quota */ }
    updateBookmarkUI();
}

function updateBookmarkUI() {
    const ids = Object.keys(bookmarks);
    const cnt = document.getElementById("bm-count");
    if (cnt) cnt.textContent = ids.length;

    const btn = document.getElementById("btn-bookmark");
    if (btn && currentPageId) {
        const isBm = !!bookmarks[currentPageId];
        btn.classList.toggle("active", isBm);
        document.getElementById("bm-star").textContent = isBm ? "★" : "☆";
        document.getElementById("bm-label").textContent =
            isBm ? "В закладках" : "В закладку";
    }
}

function toggleBookmark() {
    if (!currentPageId) return;
    if (bookmarks[currentPageId]) {
        openBookmarkDialog(currentPageId);
    } else {
        bookmarks[currentPageId] = { comment: "", ts: Date.now() };
        saveBookmarks();
        openBookmarkDialog(currentPageId);
    }
}

var bmDialogPageId = null;

function openBookmarkDialog(pid) {
    bmDialogPageId = pid;
    var el = document.querySelector('.page[data-id="' + pid + '"] .page-label');
    var name = el ? el.textContent.trim() : pid;
    document.getElementById("bm-edit-pgname").textContent = name;
    var bm = bookmarks[pid] || {};
    document.getElementById("bm-edit-comment").value = bm.comment || "";
    document.getElementById("bm-edit-title").textContent =
        bookmarks[pid] ? "Редактировать закладку" : "Новая закладка";
    openModal("bm-edit-modal");
    setTimeout(function () {
        var t = document.getElementById("bm-edit-comment");
        t.focus();
        t.setSelectionRange(t.value.length, t.value.length);
    }, 50);
}

function saveBookmarkFromDialog() {
    if (!bmDialogPageId) return;
    var c = document.getElementById("bm-edit-comment").value;
    if (!bookmarks[bmDialogPageId]) {
        bookmarks[bmDialogPageId] = { ts: Date.now() };
    }
    bookmarks[bmDialogPageId].comment = c;
    bookmarks[bmDialogPageId].ts = Date.now();
    saveBookmarks();
    closeModal("bm-edit-modal");
    refreshBookmarksList();
}

function removeBookmarkFromDialog() {
    if (!bmDialogPageId) return;
    delete bookmarks[bmDialogPageId];
    saveBookmarks();
    closeModal("bm-edit-modal");
    refreshBookmarksList();
}

function removeBookmark(pid) {
    delete bookmarks[pid];
    saveBookmarks();
    refreshBookmarksList();
}

function clearAllBookmarks() {
    if (Object.keys(bookmarks).length === 0) return;
    if (!confirm("Удалить все закладки?")) return;
    bookmarks = {};
    saveBookmarks();
    refreshBookmarksList();
}

function refreshBookmarksList() {
    var listEl = document.getElementById("bm-list");
    var emptyEl = document.getElementById("bm-empty");
    if (!listEl) return;
    listEl.innerHTML = "";

    var ids = Object.keys(bookmarks).sort(function (a, b) {
        return (bookmarks[b].ts || 0) - (bookmarks[a].ts || 0);
    });

    if (ids.length === 0) {
        emptyEl.style.display = "block";
        return;
    }
    emptyEl.style.display = "none";

    ids.forEach(function (pid) {
        var bm = bookmarks[pid];
        var el = document.querySelector('.page[data-id="' + pid + '"] .page-label');
        var title = el ? el.textContent.trim() : pid;

        var item = document.createElement("div");
        item.className = "bm-item";

        var main = document.createElement("div");
        main.className = "bm-main";

        var t = document.createElement("div");
        t.className = "bm-title";
        t.textContent = title;
        t.title = "Открыть страницу";
        t.addEventListener("click", function () {
            openPage(pid);
            closeModal("bm-modal");
        });
        main.appendChild(t);

        var idEl = document.createElement("div");
        idEl.className = "bm-id";
        idEl.textContent = pid;
        main.appendChild(idEl);

        var cm = document.createElement("div");
        cm.className = "bm-comment" + (bm.comment ? "" : " empty");
        cm.textContent = bm.comment || "(без комментария)";
        main.appendChild(cm);

        var actions = document.createElement("div");
        actions.className = "bm-actions";

        var editBtn = document.createElement("button");
        editBtn.className = "bm-icon-btn";
        editBtn.title = "Редактировать комментарий";
        editBtn.textContent = "✏️";
        editBtn.addEventListener("click", function () {
            openBookmarkDialog(pid);
        });

        var delBtn = document.createElement("button");
        delBtn.className = "bm-icon-btn danger";
        delBtn.title = "Удалить";
        delBtn.textContent = "🗑";
        delBtn.addEventListener("click", function () {
            removeBookmark(pid);
        });

        actions.appendChild(editBtn);
        actions.appendChild(delBtn);

        item.appendChild(main);
        item.appendChild(actions);
        listEl.appendChild(item);
    });
}

function openBookmarks() {
    refreshBookmarksList();
    openModal("bm-modal");
}

/* ---------- Экспорт / импорт закладок ---------- */

function exportBookmarks() {
    var payload = {
        version: 1,
        doc: DOC_ID,
        doc_title: DOC_TITLE,
        saved: new Date().toISOString(),
        bookmarks: bookmarks
    };
    var json = JSON.stringify(payload, null, 2);
    var blob = new Blob([json], { type: "application/json;charset=utf-8" });

    var stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
    var filename = "notes-" + sanitizeFilename(DOC_ID) + "-" + stamp + ".notes.json";

    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
}

function sanitizeFilename(s) {
    return String(s).replace(/[^\w\-\.]+/g, "_").slice(0, 80) || "doc";
}

function importBookmarks() {
    var inp = document.createElement("input");
    inp.type = "file";
    inp.accept = ".json,.notes.json,application/json";
    inp.style.display = "none";
    inp.addEventListener("change", function () {
        var f = inp.files && inp.files[0];
        if (!f) return;
        var reader = new FileReader();
        reader.onload = function () {
            try {
                var data = JSON.parse(reader.result);
                applyImportedBookmarks(data);
            } catch (e) {
                alert("Не удалось прочитать файл: " + e.message);
            }
        };
        reader.onerror = function () {
            alert("Ошибка чтения файла.");
        };
        reader.readAsText(f, "utf-8");
    });
    document.body.appendChild(inp);
    inp.click();
    setTimeout(function () { document.body.removeChild(inp); }, 5000);
}

function applyImportedBookmarks(data) {
    if (!data || typeof data !== "object") {
        alert("Некорректный формат файла.");
        return;
    }
    var incoming = data.bookmarks;
    if (!incoming || typeof incoming !== "object") {
        alert("В файле нет объекта bookmarks.");
        return;
    }

    // Нормализуем записи
    var normalized = {};
    var count = 0;
    Object.keys(incoming).forEach(function (pid) {
        var v = incoming[pid];
        if (typeof v === "string") {
            // допускаем простой формат: { "id": "комментарий" }
            normalized[pid] = { comment: v, ts: Date.now() };
        } else if (v && typeof v === "object") {
            normalized[pid] = {
                comment: String(v.comment || ""),
                ts: Number(v.ts) || Date.now()
            };
        } else {
            return;
        }
        count++;
    });

    if (count === 0) {
        alert("Не найдено ни одной закладки.");
        return;
    }

    var mode = prompt(
        "Найдено закладок: " + count + ".\n\n" +
        "Введите режим импорта:\n" +
        "  merge  — добавить к текущим (совпадения перезапишутся)\n" +
        "  replace — заменить всё текущее\n\n" +
        "По умолчанию: merge",
        "merge"
    );
    if (mode === null) return;  // отмена
    mode = (mode || "merge").trim().toLowerCase();

    if (mode === "replace") {
        if (!confirm("Точно заменить все текущие закладки (" +
                     Object.keys(bookmarks).length + " шт.)?")) return;
        bookmarks = normalized;
    } else {
        Object.keys(normalized).forEach(function (pid) {
            bookmarks[pid] = normalized[pid];
        });
    }

    saveBookmarks();
    refreshBookmarksList();
    alert("Импорт завершён. Всего закладок: " + Object.keys(bookmarks).length);
}

/* ============================================================
   Донат (заглушка)
   ============================================================ */
function openDonate() {
    openModal("donate-modal");
}

/* ============================================================
   Модалки
   ============================================================ */
function openModal(id) {
    document.getElementById(id).classList.add("open");
}
function closeModal(id) {
    document.getElementById(id).classList.remove("open");
}

document.querySelectorAll(".modal-back").forEach(function (back) {
    back.addEventListener("click", function (e) {
        if (e.target === back) back.classList.remove("open");
    });
});

document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
        document.querySelectorAll(".modal-back.open").forEach(function (m) {
            m.classList.remove("open");
        });
    }
});

/* ============================================================
   Инициализация
   ============================================================ */
var searchTimer = null;
document.getElementById("search-input").addEventListener("input", function (e) {
    var q = e.target.value.trim().toLowerCase();
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(function () { runSearch(q); }, 120);
});

document.getElementById("filepath").addEventListener("click", copyPath);

window.addEventListener("DOMContentLoaded", function () {
    loadBookmarks();
    buildSearchIndex();
    updateBookmarkUI();
    var first = document.querySelector("li.page .page-label");
    if (first) first.click();
});
</script>

</body>
</html>
"""


# ============================================================
# Шаблон _listing.html — листинг папки с колонкой «Заголовок»,
# поиском, закреплённой шапкой и кнопкой «Открыть»
# ============================================================

LISTING_TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>__TITLE__ — список страниц</title>
<style>
  * { box-sizing: border-box; }
  html, body {
      margin: 0; padding: 0; height: 100%;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                   Roboto, "Helvetica Neue", Arial, sans-serif;
      color: #1f2328; background: #fafafa;
      -webkit-font-smoothing: antialiased;
  }
  body { display: flex; flex-direction: column; overflow: hidden; }

  header.lhead {
      flex-shrink: 0;
      padding: 16px 24px 12px;
      background: #fff;
      border-bottom: 1px solid #e6e8eb;
      z-index: 10;
  }
  .back {
      display: inline-block; margin-bottom: 10px; font-size: 13px;
      color: #0969da; text-decoration: none;
  }
  .back:hover { text-decoration: underline; }
  h1 { font-size: 18px; margin: 0 0 4px; font-weight: 600; }
  .meta { color: #57606a; font-size: 13px; margin-bottom: 10px; }
  .searchbox { position: relative; }
  .searchbox input {
      width: 100%; padding: 8px 12px 8px 34px;
      border: 1px solid #d0d7de; border-radius: 6px;
      font-size: 13px; outline: none;
      transition: border-color .15s, box-shadow .15s;
      font-family: inherit;
  }
  .searchbox input:focus {
      border-color: #0969da;
      box-shadow: 0 0 0 3px rgba(9,105,218,.15);
  }
  .searchbox::before {
      content: "🔍";
      position: absolute; left: 11px; top: 50%;
      transform: translateY(-50%);
      font-size: 13px; opacity: .55; pointer-events: none;
  }

  .tablewrap {
      flex: 1; overflow: auto; padding: 0 24px 24px;
  }
  table {
      border-collapse: separate; border-spacing: 0;
      width: 100%; background: #fff;
      border: 1px solid #d0d7de; border-radius: 8px;
      font-size: 14px;
  }
  th, td {
      text-align: left; padding: 8px 14px;
      border-bottom: 1px solid #eaecef;
      background: #fff;
      vertical-align: middle;
  }
  thead th {
      background: #f6f8fa; font-weight: 600;
      position: sticky; top: 0; z-index: 2;
      border-bottom: 1px solid #d0d7de;
  }
  tbody tr:last-child td { border-bottom: none; }
  tbody tr:hover td { background: #f0f6ff; }
  a { color: #0969da; text-decoration: none; }
  a:hover { text-decoration: underline; }
  .num { width: 60px; color: #57606a; }
  .id {
      width: 320px;
      font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo,
                   Consolas, "Liberation Mono", monospace;
      font-size: 12px; color: #57606a; word-break: break-all;
  }
  .actions {
      width: 100px; white-space: nowrap;
  }
  .actions .ibtn {
      display: inline-flex; align-items: center; justify-content: center;
      border: 1px solid #d0d7de; background: #fff;
      width: 28px; height: 26px; border-radius: 6px;
      cursor: pointer; margin-right: 4px;
      font-size: 13px; color: #57606a;
      text-decoration: none;
  }
  .actions .ibtn:hover {
      background: #eef5ff; border-color: #0969da; color: #0969da;
  }
  tr.hidden { display: none; }
  .empty {
      padding: 40px; text-align: center; color: #888; font-size: 13px;
  }
</style>
</head>
<body>
<header class="lhead">
  <a class="back" href="index.html">← назад к дереву</a>
  <h1 id="hdr">__TITLE__</h1>
  <div class="meta" id="meta"></div>
  <div class="searchbox">
    <input type="text" id="q"
           placeholder="Фильтр по заголовку или ID..."
           autocomplete="off">
  </div>
</header>

<div class="tablewrap">
  <table>
    <thead>
      <tr>
        <th class="num">#</th>
        <th>Заголовок</th>
        <th class="id">ID (имя файла)</th>
        <th class="actions">Открыть</th>
      </tr>
    </thead>
    <tbody id="rows"></tbody>
  </table>
  <div class="empty" id="empty" style="display:none;">
    Ничего не найдено.
  </div>
</div>

<script>
var PAGES = __PAGES_JSON__;
var DOC_TITLE = "__TITLE__";

var params = new URLSearchParams(location.search);
var folder = params.get("folder") || "ru_pages";
var FOLDER_LABEL = {
    "ru_pages": "перевод (RU)",
    "pages":    "оригинал (ORIG)",
    "en_pages": "English (EN)"
};
var label = FOLDER_LABEL[folder] || folder;

document.getElementById("hdr").textContent = DOC_TITLE + " — " + label;

var metaEl = document.getElementById("meta");
metaEl.textContent = "Папка: " + folder + " · страниц: " + PAGES.length;

var tb = document.getElementById("rows");

PAGES.forEach(function (p, i) {
    var tr = document.createElement("tr");
    tr.dataset.hay = (p.title + " " + p.id).toLowerCase();

    var td1 = document.createElement("td");
    td1.className = "num";
    td1.textContent = (i + 1);

    var td2 = document.createElement("td");
    var a = document.createElement("a");
    a.href = folder + "/" + p.id + ".html";
    a.target = "_blank";
    a.textContent = p.title;
    td2.appendChild(a);

    var td3 = document.createElement("td");
    td3.className = "id";
    td3.textContent = p.id;

    var td4 = document.createElement("td");
    td4.className = "actions";

    var openA = document.createElement("a");
    openA.className = "ibtn";
    openA.href = folder + "/" + p.id + ".html";
    openA.target = "_blank";
    openA.title = "Открыть в новой вкладке";
    openA.textContent = "↗";

    td4.appendChild(openA);

    tr.appendChild(td1);
    tr.appendChild(td2);
    tr.appendChild(td3);
    tr.appendChild(td4);
    tb.appendChild(tr);
});

/* ---------- filter ---------- */
var rows = Array.prototype.slice.call(tb.children);
var emptyEl = document.getElementById("empty");
var qEl = document.getElementById("q");

var timer = null;
qEl.addEventListener("input", function () {
    if (timer) clearTimeout(timer);
    timer = setTimeout(applyFilter, 100);
});

function applyFilter() {
    var q = qEl.value.trim().toLowerCase();
    var visible = 0;
    for (var i = 0; i < rows.length; i++) {
        var tr = rows[i];
        var show = !q || tr.dataset.hay.indexOf(q) !== -1;
        if (show) { tr.classList.remove("hidden"); visible++; }
        else tr.classList.add("hidden");
    }
    emptyEl.style.display = visible === 0 ? "block" : "none";
}

qEl.focus();
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
    title = capitalize_first(title)
    tree = data.get("tree", [])
    if not tree:
        raise SystemExit("❌ Пустое дерево в content.json")

    tree_html = render_tree(tree)

    # 1. Вшить стили/скрипты просмотрщика во все страницы
    inject_viewer_assets(out_root)
    print("✅ _viewer.css / _viewer.js вшиты в ru_pages/, pages/, en_pages/")

    # 2. Собрать index.html
    html = (INDEX_TEMPLATE
            .replace("__TITLE__", escape(title))
            .replace("__TREE_HTML__", tree_html)
            .replace("__DOC_ID__", escape(DOC_ID)))

    index_path = out_root / "index.html"
    index_path.write_text(html, encoding="utf-8")
    print(f"✅ {index_path}")

    # 3. Собрать _listing.html (листинг с колонкой «Заголовок»)
    pages = collect_pages(tree)
    listing_html = (LISTING_TEMPLATE
                    .replace("__TITLE__", escape(title))
                    .replace("__PAGES_JSON__",
                             json.dumps(pages, ensure_ascii=False)))
    listing_path = out_root / "_listing.html"
    listing_path.write_text(listing_html, encoding="utf-8")
    print(f"✅ {listing_path}  (страниц: {len(pages)})")

    print(f"\nОткрой:")
    print(f"   file:///{index_path.resolve().as_posix()}")


if __name__ == "__main__":
    main()