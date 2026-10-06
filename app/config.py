from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read_env_file() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_read_env_file()

# Vercel functions run with a read-only project directory.  Keep the same
# SQLite-backed code, but place the temporary per-instance database in /tmp
# when the app is running as a Vercel Function.  Persistent deployments keep
# using the normal data/ directory (or an explicitly configured DATA_DIR).
_default_data_dir = "/tmp/iran-market-lens-data" if os.getenv("VERCEL") else str(ROOT / "data")
DATA_DIR = Path(os.getenv("DATA_DIR", _default_data_dir)).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(DATA_DIR / "market.db"))).resolve()
REFRESH_INTERVAL_SECONDS = max(60, int(os.getenv("DATA_UPDATE_INTERVAL", "900")))
_default_http_timeout = "8" if os.getenv("VERCEL") else "15"
HTTP_TIMEOUT_SECONDS = max(3, int(os.getenv("HTTP_TIMEOUT_SECONDS", _default_http_timeout)))
MAX_STALE_HOURS = max(1, int(os.getenv("MAX_STALE_HOURS", "36")))
DEFAULT_NEWS_RSS_URLS = [
    "https://www.tasnimnews.ir/fa/rss/feeds/84/0/0/0",  # بازار سهام
    "https://www.tasnimnews.ir/fa/rss/feeds/79/0/0/0",  # طلا و ارز
]
_news_rss_setting = os.getenv("NEWS_RSS_URLS", "").strip()
NEWS_RSS_URLS = (
    [item.strip() for item in _news_rss_setting.split(",") if item.strip()]
    if _news_rss_setting
    else DEFAULT_NEWS_RSS_URLS
)
RAHAVARD_API_BASE_URL = os.getenv("RAHAVARD_API_BASE_URL", "https://rahavard365.com/api/v2").rstrip("/")
RAHAVARD_PUBLIC_BARS_URL = os.getenv(
    "RAHAVARD_PUBLIC_BARS_URL", f"{RAHAVARD_API_BASE_URL}/chart/public-bars"
)
RAHAVARD_ETF_FUNDS_URL = os.getenv(
    "RAHAVARD_ETF_FUNDS_URL", f"{RAHAVARD_API_BASE_URL}/market-data/etf-funds"
)
RAHAVARD_LIGHT_BARS_URL = os.getenv(
    "RAHAVARD_LIGHT_BARS_URL", f"{RAHAVARD_API_BASE_URL}/chart/light-bars"
)
TABDEAL_TRADES_URL = os.getenv(
    "TABDEAL_TRADES_URL", "https://api1.tabdeal.org/r/api/v1/trades"
)
CODAL_API_URL = os.getenv("CODAL_API_URL", "https://search.codal.ir/api/search/v2/q")
