
DOC_ID       = "56749"
BASE_DOMEN   = "dongcheyun.com"
BASE_URL     = f"https://{BASE_DOMEN}"
OSS_URL      = f"https://oss.{BASE_DOMEN}"
DOC_URL      = f"https://{BASE_DOMEN}/p/{DOC_ID}"
SYSTEM_TYPE  = "webpage"
OUTPUT_DIR   = "output"
COOKIES_FILE = "cookies.json"

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/120.0.0.0 Safari/537.36")

# Тайминги (сек)
DELAY_BETWEEN_PAGES = (1.5, 3.0)   # пауза между страницами
DELAY_TRANSLATE     = 0.4          # пауза после перевода
TRANSLATE_TIMEOUT   = 30           # сколько ждать готовности переводчика