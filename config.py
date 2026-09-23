
DOC_ID       = "56746"
BASE_URL     = "https://dongcheyun.com"
OSS_URL      = "https://oss.dongcheyun.com"
DOC_URL      = f"https://dongcheyun.com/p/{DOC_ID}"
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