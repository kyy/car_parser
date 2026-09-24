# launcher.py
"""
pywebview-лаунчер для руководства.

Поднимает локальный HTTP-сервер над папкой OUTPUT_DIR/DOC_ID
и открывает index.html в нативном окне.

Особенности:
  - работает offline (без интернета);
  - внешние ссылки (http/https, mailto, tel, tg) уходят в системный браузер;
  - внутренние ссылки остаются внутри окна;
  - F5 — перезагрузка, F12 — DevTools (если включены);
  - закладки хранятся в файле рядом с пользовательскими данными;
  - можно открыть руководство во внешнем системном браузере (кнопка
    «🌐 В браузере» в шапке index.html).
"""
from __future__ import annotations

# ---- Фикс кодировки консоли на Windows (cp1251 -> utf-8) ----
import sys
import io

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
        except Exception:
            pass
# -----------------------------------------------------------

import json
import os
import socket
import threading
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import webview  # pywebview

from config import OUTPUT_DIR, DOC_ID


# ============================================================
# Настройки
# ============================================================



WINDOW_WIDTH = 1400
WINDOW_HEIGHT = 900
WINDOW_MIN = (900, 600)

ENABLE_DEVTOOLS = False
ENABLE_CONTEXT_MENU = False


# ============================================================
# Утилиты
# ============================================================

def find_free_port(preferred: int = 0) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", preferred))
        return s.getsockname()[1]


def resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def app_data_dir(doc_id: str) -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))

    d = base / "Guide" / doc_id
    d.mkdir(parents=True, exist_ok=True)
    return d


# ============================================================
# HTTP-сервер
# ============================================================

class QuietHandler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".js":    "application/javascript",
        ".mjs":   "application/javascript",
        ".css":   "text/css",
        ".json":  "application/json",
        ".svg":   "image/svg+xml",
        ".woff":  "font/woff",
        ".woff2": "font/woff2",
        ".html":  "text/html",
    }

    def log_message(self, fmt, *args):
        pass


def start_server(root: Path, port: int) -> ThreadingHTTPServer:
    handler = partial(QuietHandler, directory=str(root))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd


# ============================================================
# Мост JS <-> Python
# ============================================================

class Api:
    def __init__(self, doc_id: str, base_url: str = ""):
        self.doc_id = doc_id
        self.base_url = base_url
        self.data_dir = app_data_dir(doc_id)
        self.bm_file = self.data_dir / "bookmarks.json"

    # ---------- внешние ссылки ----------

    def open_external(self, url: str) -> None:
        if not isinstance(url, str):
            return
        if url.startswith(("http://", "https://", "mailto:", "tel:", "tg://")):
            webbrowser.open(url)

    # ---------- адрес сервера ----------

    def get_server_url(self) -> str:
        return self.base_url or ""

    def open_in_browser(self) -> bool:
        url = self.get_server_url()
        if not url:
            return False
        try:
            webbrowser.open(url)
            return True
        except Exception:
            return False

    # ---------- закладки ----------

    def load_bookmarks(self) -> str:
        try:
            if self.bm_file.is_file():
                return self.bm_file.read_text(encoding="utf-8")
        except Exception:
            pass
        return "{}"

    def save_bookmarks(self, data: str) -> bool:
        try:
            parsed = json.loads(data)
            if not isinstance(parsed, dict):
                return False
            tmp = self.bm_file.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(parsed, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(self.bm_file)
            return True
        except Exception:
            return False

    def bookmarks_path(self) -> str:
        return str(self.bm_file)

    def reveal_bookmarks(self) -> None:
        try:
            if sys.platform == "win32":
                os.startfile(str(self.data_dir))  # noqa: S606
            elif sys.platform == "darwin":
                os.system(f'open "{self.data_dir}"')
            else:
                os.system(f'xdg-open "{self.data_dir}"')
        except Exception:
            pass

    def log(self, msg: str) -> None:
        try:
            print(f"[js] {msg}", file=sys.stderr)
        except Exception:
            pass


# ============================================================
# Главный сценарий
# ============================================================

def main() -> int:
    local_root = resource_root() / "site"
    cfg_root = Path(OUTPUT_DIR) / DOC_ID



    if (local_root / "index.html").is_file():
        site_root = local_root
    elif (cfg_root / "index.html").is_file():
        site_root = cfg_root
    else:
        site_root = resource_root()
        if not (site_root / "index.html").is_file():
            print(
                "Не найден index.html.\n"
                f"   Проверьте: {local_root}\n"
                f"   или:      {cfg_root}",
                file=sys.stderr,
            )
            return 2
    content_path = site_root / "content.ru.json"

    with content_path.open(encoding="utf-8") as f:
        doc_title = json.load(f)
    WINDOW_TITLE = doc_title.get("doc_title")

    print(f"Контент: {site_root}")
    print(f"Данные:  {app_data_dir(DOC_ID)}")

    port = find_free_port(0)
    httpd = start_server(site_root, port)
    base_url = f"http://127.0.0.1:{port}/index.html"
    print(f"Сервер: http://127.0.0.1:{port}/")

    api = Api(DOC_ID, base_url=base_url)

    window = webview.create_window(
        title=WINDOW_TITLE,
        url=base_url,
        js_api=api,
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        min_size=WINDOW_MIN,
        resizable=True,
        confirm_close=False,
        text_select=True,
    )

    def _on_loaded():
        window.evaluate_js(r"""
        (function () {
            if (window.__ext_hook_installed) return;
            window.__ext_hook_installed = true;

            function isExternal(href) {
                try {
                    var u = new URL(href, location.href);
                    if (u.origin === location.origin) return false;
                    return /^https?:|^mailto:|^tel:|^tg:/.test(u.protocol);
                } catch (e) { return false; }
            }

            document.addEventListener("click", function (e) {
                var a = e.target.closest && e.target.closest("a[href]");
                if (!a) return;
                var href = a.getAttribute("href") || "";
                if (href.startsWith("javascript:")) return;
                if (isExternal(a.href)) {
                    e.preventDefault();
                    if (window.pywebview && window.pywebview.api) {
                        window.pywebview.api.open_external(a.href);
                    }
                }
            }, true);

            document.addEventListener("keydown", function (e) {
                if (e.key === "F5") { e.preventDefault(); location.reload(); }
            });
        })();
        """)

    window.events.loaded += _on_loaded

    webview.start(debug=ENABLE_DEVTOOLS)

    try:
        httpd.shutdown()
        httpd.server_close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())