# build_index.py
"""
Генерирует index.html для просмотра переведённого руководства.
Слева — дерево, справа — iframe с контентом.
Кнопка переключает RU / ORIG.
Контент вписан в окно; большие картинки грузятся лениво.
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
                f'<span class="label page-label" onclick="openPage(\'{pid}\')">'
                f'{escape(name)}</span>'
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
# Шаблон
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
                   Roboto, Arial, sans-serif;
      font-size: 14px; color: #222; background: #fafafa;
  }

  #layout { display: flex; height: 100vh; overflow: hidden; }

  /* ---------- Sidebar ---------- */
  #sidebar {
      width: 360px;
      min-width: 240px;
      max-width: 60vw;
      background: #fff;
      border-right: 1px solid #e0e0e0;
      display: flex;
      flex-direction: column;
      resize: horizontal;
      overflow: hidden;
      flex-shrink: 0;
  }

  #sidebar-header {
      padding: 12px 16px;
      border-bottom: 1px solid #e8e8e8;
      background: #f5f5f5;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
  }

  #doc-title {
      font-weight: 600;
      font-size: 14px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      flex: 1;
  }

  #lang-toggle {
      border: 1px solid #ccc;
      background: #fff;
      padding: 4px 10px;
      border-radius: 4px;
      cursor: pointer;
      font-size: 12px;
      font-weight: 600;
      transition: all 0.15s;
      white-space: nowrap;
  }
  #lang-toggle:hover { background: #f0f0f0; }
  #lang-toggle.ru { background: #d4edda; border-color: #28a745; color: #155724; }
  #lang-toggle.orig { background: #fff3cd; border-color: #ffc107; color: #856404; }

  #search {
      padding: 8px 12px;
      border-bottom: 1px solid #eee;
  }
  #search input {
      width: 100%;
      padding: 6px 10px;
      border: 1px solid #ccc;
      border-radius: 4px;
      font-size: 13px;
      outline: none;
  }
  #search input:focus { border-color: #007bff; }

  #tree-container {
      flex: 1;
      overflow-y: auto;
      padding: 8px 0 24px 0;
  }

  /* ---------- Tree ---------- */
  ul.tree { list-style: none; margin: 0; padding: 0; }
  ul.tree ul.tree { padding-left: 16px; }
  li { margin: 0; }

  .label {
      display: block;
      padding: 4px 12px;
      cursor: pointer;
      border-radius: 3px;
      user-select: none;
      font-size: 13px;
      line-height: 1.4;
      white-space: normal;
      word-wrap: break-word;
  }
  .label:hover { background: #eef5ff; }

  .folder-label { font-weight: 600; color: #333; }
  .folder-label .arrow {
      display: inline-block;
      width: 14px;
      transition: transform 0.15s;
      color: #888;
      font-size: 11px;
  }
  li.folder.open > .folder-label .arrow { transform: rotate(90deg); }
  li.folder > ul.tree { display: none; }
  li.folder.open > ul.tree { display: block; }

  .page-label { color: #007bff; padding-left: 26px; }
  .page-label.active { background: #007bff; color: #fff; }

  li.hidden { display: none; }

  /* ---------- Main ---------- */
  #main {
      flex: 1;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      background: #fff;
      min-width: 0;
  }

  #topbar {
      padding: 8px 16px;
      background: #fff;
      border-bottom: 1px solid #e8e8e8;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      font-size: 13px;
      min-height: 40px;
      flex-shrink: 0;
  }

  #current-title {
      font-weight: 600;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      flex: 1;
      color: #333;
  }

  #open-external {
      color: #007bff;
      text-decoration: none;
      font-size: 12px;
      padding: 4px 8px;
      border-radius: 4px;
      white-space: nowrap;
  }
  #open-external:hover { background: #eef5ff; }

  #content-frame {
      flex: 1;
      width: 100%;
      border: none;
      background: #fff;
      display: block;
  }

  #welcome {
      padding: 60px 40px;
      text-align: center;
      color: #888;
      flex: 1;
      overflow: auto;
  }
  #welcome h1 { font-weight: 400; color: #333; }

  @media (max-width: 700px) {
      #sidebar { width: 100%; position: absolute; z-index: 10; height: 100%; }
      #sidebar.hidden-mobile { display: none; }
  }
</style>
</head>
<body>

<div id="layout">

  <aside id="sidebar">
    <div id="sidebar-header">
      <div id="doc-title" title="__TITLE__">__TITLE__</div>
      <button id="lang-toggle" class="ru"
              onclick="toggleLang()"
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
      <div id="current-title">—</div>
      <a id="open-external" href="#" target="_blank" style="display:none;">
        открыть в новой вкладке ↗
      </a>
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
    const li = el.parentElement;
    li.classList.toggle("open");
}

function openPage(id) {
    currentPageId = id;

    document.querySelectorAll(".page-label.active")
        .forEach(e => e.classList.remove("active"));
    const active = document.querySelector(`.page[data-id="${id}"] .page-label`);
    if (active) {
        active.classList.add("active");
        let p = active.closest("li.folder");
        while (p) {
            p.classList.add("open");
            p = p.parentElement.closest("li.folder");
        }
        active.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }

    const name = active ? active.textContent.trim() : id;
    document.getElementById("current-title").textContent = name;

    loadPage();
}

function loadPage() {
    if (!currentPageId) return;

    const folder = currentLang === "ru" ? "ru_pages" : "pages";
    const src = `${folder}/${currentPageId}.html`;

    const frame = document.getElementById("content-frame");
    frame.src = src;

    document.getElementById("welcome").style.display = "none";
    frame.style.display = "block";

    const ext = document.getElementById("open-external");
    ext.href = src;
    ext.style.display = "inline-block";
}

// ---------- Язык ----------
function toggleLang() {
    currentLang = currentLang === "ru" ? "orig" : "ru";
    const btn = document.getElementById("lang-toggle");
    btn.textContent = currentLang === "ru" ? "RU" : "ORIG";
    btn.className = currentLang === "ru" ? "ru" : "orig";

    if (currentPageId) loadPage();
}

// ---------- Поиск ----------
document.getElementById("search-input").addEventListener("input", function (e) {
    const q = e.target.value.trim().toLowerCase();

    document.querySelectorAll("li").forEach(li => li.classList.remove("hidden"));
    if (!q) return;

    document.querySelectorAll("li.page").forEach(li => {
        const name = li.textContent.toLowerCase();
        if (!name.includes(q)) li.classList.add("hidden");
    });

    let changed = true;
    while (changed) {
        changed = false;
        document.querySelectorAll("li.folder").forEach(f => {
            const vp = f.querySelectorAll("li.page:not(.hidden)");
            const vf = Array.from(f.querySelectorAll("li.folder"))
                .filter(sub => !sub.classList.contains("hidden"));
            if (vp.length === 0 && vf.length === 0) {
                f.classList.add("hidden");
                changed = true;
            }
        });
    }

    document.querySelectorAll("li.folder").forEach(f => {
        if (f.querySelector("li.page:not(.hidden)")) f.classList.add("open");
    });
});

// ============================================================
// Инжект в iframe: стили + lazy-loading + зум
// ============================================================

const IFRAME_CSS = `
  html, body {
      margin: 0 !important;
      padding: 0 !important;
      max-width: none !important;
      width: 100% !important;
      overflow-x: hidden !important;
  }
  body {
      padding: 16px 24px 32px 24px !important;
      font-size: 14px;
      line-height: 1.5;
      background: #fff;
      color: #222;
  }

  img, svg, video {
      display: block;
      width: 100% !important;
      max-width: 100% !important;
      height: auto !important;
      margin: 12px 0;
      cursor: zoom-in;
      opacity: 0;
      transition: opacity 0.2s ease-in;
  }
  img.loaded, svg.loaded, video.loaded { opacity: 1; }

  img[data-small="1"] {
      width: auto !important;
      max-width: min(100%, 300px) !important;
      display: inline-block;
      vertical-align: middle;
  }

  table { max-width: 100%; overflow-x: auto; display: block; }
  pre, code { overflow-x: auto; max-width: 100%; }

  #__lightbox {
      position: fixed; inset: 0; background: rgba(0,0,0,0.92);
      display: none; align-items: center; justify-content: center;
      z-index: 999999; cursor: zoom-out;
  }
  #__lightbox img {
      width: auto !important;
      max-width: 96vw !important;
      max-height: 96vh !important;
      box-shadow: 0 0 40px rgba(0,0,0,0.6);
      background: #fff;
      opacity: 1 !important;
      cursor: zoom-out;
      transition: none;
  }
  #__lightbox.open { display: flex; }

  img.__loading {
      background: #f0f0f0 url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='40' height='40' viewBox='0 0 40 40'><circle cx='20' cy='20' r='14' fill='none' stroke='%23ccc' stroke-width='3' stroke-dasharray='60 20'><animateTransform attributeName='transform' type='rotate' from='0 20 20' to='360 20 20' dur='1s' repeatCount='indefinite'/></circle></svg>") center center no-repeat;
      min-height: 80px;
  }

  .goog-te-banner-frame, #goog-gt-tt, .goog-tooltip,
  .goog-te-balloon-frame, #google_translate_element { display: none !important; }
  body { top: 0 !important; }
`;

function hookIframe(frame) {
    let doc;
    try {
        doc = frame.contentDocument;
        if (!doc) return;
    } catch (e) {
        console.warn("iframe hook: нет доступа к contentDocument", e);
        return;
    }

    if (!doc.getElementById("__zoom_css")) {
        const style = doc.createElement("style");
        style.id = "__zoom_css";
        style.textContent = IFRAME_CSS;
        (doc.head || doc.documentElement).appendChild(style);
    }

    if (!doc.getElementById("__lightbox")) {
        const lb = doc.createElement("div");
        lb.id = "__lightbox";
        lb.innerHTML = '<img id="__lightbox_img" alt="">';
        lb.addEventListener("click", () => lb.classList.remove("open"));
        (doc.body || doc.documentElement).appendChild(lb);

        doc.addEventListener("click", (e) => {
            const t = e.target;
            if (t.tagName !== "IMG" || t.id === "__lightbox_img") return;
            const orig = t.dataset.orig || t.src;
            const img = doc.getElementById("__lightbox_img");
            img.src = orig;
            doc.getElementById("__lightbox").classList.add("open");
        });

        doc.addEventListener("keydown", (e) => {
            if (e.key === "Escape") {
                doc.getElementById("__lightbox").classList.remove("open");
            }
        });
    }

    const imgs = doc.querySelectorAll("img");
    imgs.forEach(img => {
        if (!img.hasAttribute("loading")) img.setAttribute("loading", "lazy");
        img.setAttribute("decoding", "async");

        const preview = img.getAttribute("src") || "";
        const orig = img.getAttribute("data-orig") || "";

        const w = parseInt(img.getAttribute("width") || "0", 10);
        const h = parseInt(img.getAttribute("height") || "0", 10);
        if ((w > 0 && w < 200) || (h > 0 && h < 100)) {
            img.dataset.small = "1";
        }

        img.removeAttribute("width");
        img.removeAttribute("height");

        if (preview && !preview.startsWith("data:")) {
            img.dataset.realSrc = preview;
            img.removeAttribute("src");
            img.classList.add("__loading");
        } else {
            img.classList.add("loaded");
        }

        img.addEventListener("load", () => {
            img.classList.remove("__loading");
            img.classList.add("loaded");
        });
        img.addEventListener("error", () => {
            img.classList.remove("__loading");
            img.classList.add("loaded");
        });
    });

    if (imgs.length && "IntersectionObserver" in doc.defaultView) {
        const io = new doc.defaultView.IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (!entry.isIntersecting) return;
                const img = entry.target;
                if (img.dataset.realSrc) {
                    img.src = img.dataset.realSrc;
                    delete img.dataset.realSrc;
                }
                io.unobserve(img);
            });
        }, { rootMargin: "600px 0px", threshold: 0.01 });
        imgs.forEach(img => io.observe(img));
    } else {
        imgs.forEach(img => {
            if (img.dataset.realSrc) {
                img.src = img.dataset.realSrc;
                delete img.dataset.realSrc;
            }
        });
    }

    doc.documentElement.scrollTop = 0;
    doc.body.scrollTop = 0;
}

// ---------- Слушаем загрузку iframe ----------
const contentFrame = document.getElementById("content-frame");
contentFrame.addEventListener("load", () => hookIframe(contentFrame));

// ---------- Автооткрытие первой страницы ----------
window.addEventListener("DOMContentLoaded", () => {
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

    # ВАЖНО: replace, не format — CSS с {} ломает format
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