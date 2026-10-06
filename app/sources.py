from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any

from .config import (CODAL_API_URL, HTTP_TIMEOUT_SECONDS, NEWS_RSS_URLS,
                     MAX_STALE_HOURS, RAHAVARD_API_BASE_URL,
                     RAHAVARD_ETF_FUNDS_URL, RAHAVARD_GOLD_ASSET_ID,
                     RAHAVARD_GOLD_PAGE_URL, RAHAVARD_LIGHT_BARS_URL,
                     RAHAVARD_PUBLIC_BARS_URL, RAHAVARD_INDEX_BASE_URL,
                     RAHAVARD_TEPIX_INDEX_ID, RAHAVARD_USDT_ASSET_ID,
                     RAHAVARD_USDT_PAGE_URL)
from .db import db, utc_now

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
RAHAVARD_URL = "https://rahavard365.com"


class SourceError(RuntimeError):
    pass


def _http(url: str, *, method: str = "GET", payload: Any = None, referer: str | None = None) -> bytes:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"User-Agent": "IranMarketLens/1.0 (local market analysis; contact in README)",
               "Accept": "application/json,text/csv,application/xml,text/xml,*/*"}
    if data is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as response:
            body = response.read(20_000_000)
            if response.status < 200 or response.status >= 300:
                raise SourceError(f"HTTP {response.status}")
            return body
    except urllib.error.HTTPError as exc:
        raise SourceError(f"HTTP {exc.code} از منبع") from exc
    except urllib.error.URLError as exc:
        raise SourceError(f"اتصال به منبع برقرار نشد: {exc.reason}") from exc
    except TimeoutError as exc:
        raise SourceError("مهلت اتصال به منبع تمام شد") from exc


def _json(url: str, **kwargs) -> Any:
    try:
        return json.loads(_http(url, **kwargs).decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceError("پاسخ منبع JSON معتبر نیست") from exc


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(str(value).replace(",", "").replace("٬", "").replace("٫", ".").strip())
        return result if result == result and abs(result) != float("inf") else None
    except (TypeError, ValueError):
        return None


def yahoo_history(ticker: str, range_: str = "max", interval: str = "1d") -> tuple[list[dict[str, Any]], dict[str, Any]]:
    query = urllib.parse.urlencode({"range": range_, "interval": interval, "events": "history"})
    payload = _json(YAHOO_CHART.format(symbol=urllib.parse.quote(ticker, safe="")) + "?" + query)
    chart = payload.get("chart", {})
    if chart.get("error"):
        raise SourceError(str(chart["error"].get("description") or "Yahoo Finance API returned an error"))
    result_list = chart.get("result") or []
    if not result_list:
        raise SourceError("برای نماد درخواستی داده‌ای برنگشت")
    result = result_list[0]
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    bars = []
    fetched = utc_now()
    for idx, ts in enumerate(timestamps):
        close = (quote.get("close") or [None] * len(timestamps))[idx]
        if close is None:
            continue
        dt = datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")
        bars.append({
            "timestamp": dt, "fetched_at": fetched,
            "open": _num((quote.get("open") or [None] * len(timestamps))[idx]),
            "high": _num((quote.get("high") or [None] * len(timestamps))[idx]),
            "low": _num((quote.get("low") or [None] * len(timestamps))[idx]),
            "close": _num(close),
            "volume": _num((quote.get("volume") or [None] * len(timestamps))[idx]),
        })
    if not bars:
        raise SourceError("کندل معتبر از Yahoo Finance دریافت نشد")
    return bars, result.get("meta") or {}


def rahavard_gold_history() -> list[dict[str, Any]]:
    """Return daily XAU/USD candles from Rahavard's public chart feed."""
    now = datetime.now(timezone.utc)
    query = urllib.parse.urlencode({
        "from": "2015-01-01T00:00:00Z",
        "to": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "symbol": f"exchange.asset:{RAHAVARD_GOLD_ASSET_ID}:real_close",
        "resolution": "D",
        "countback": "5000",
    })
    payload = _json(f"{RAHAVARD_PUBLIC_BARS_URL}?{query}", referer=RAHAVARD_GOLD_PAGE_URL)
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        raise SourceError("ره‌آورد۳۶۵ برای نمودار طلای جهانی کندلی برنگرداند")

    # Rahavard sends intraday updates for the current daily candle and encodes
    # Tehran wall time as UTC. Collapse updates by chart date and correct the
    # displayed observation time; the stored day key stays stable on each refresh.
    grouped: dict[str, dict[str, Any]] = {}
    for item in sorted(rows, key=lambda row: _num(row.get("time")) or 0):
        try:
            raw_time = item.get("utc")
            if raw_time:
                candle_time = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
            elif _num(item.get("time")) is not None:
                candle_time = datetime.fromtimestamp(float(item["time"]) / 1000, timezone.utc)
            else:
                continue
            if candle_time.tzinfo is None:
                candle_time = candle_time.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError, OverflowError):
            continue
        day = candle_time.date().isoformat()
        observed_at = (candle_time - timedelta(hours=3, minutes=30)).astimezone(timezone.utc).isoformat(timespec="seconds")
        open_price, high, low, close = (_num(item.get(k)) for k in ("open", "high", "low", "close"))
        if close is None or close <= 0:
            continue
        current = grouped.get(day)
        if current is None:
            grouped[day] = {
                "timestamp": f"{day}T00:00:00+03:30",
                "observed_at": observed_at,
                "fetched_at": utc_now(),
                "open": open_price if open_price is not None else close,
                "high": high if high is not None else close,
                "low": low if low is not None else close,
                "close": close,
                "volume": _num(item.get("volume")),
            }
            continue
        current["high"] = max(current["high"], high if high is not None else close)
        current["low"] = min(current["low"], low if low is not None else close)
        current["close"] = close
        current["observed_at"] = observed_at
        volume = _num(item.get("volume"))
        if volume is not None:
            current["volume"] = volume

    bars = [grouped[day] for day in sorted(grouped)]
    if not bars:
        raise SourceError("کندل‌های دریافتی ره‌آورد۳۶۵ معتبر نیستند")
    return bars


def rahavard_usdt_history() -> list[dict[str, Any]]:
    """Return recent daily USDT/IRT candles from Rahavard's asset page feed."""
    query = urllib.parse.urlencode({"symbol": f"exchange.asset:{RAHAVARD_USDT_ASSET_ID}:real_close"})
    payload = _json(f"{RAHAVARD_LIGHT_BARS_URL}?{query}", referer=RAHAVARD_USDT_PAGE_URL)
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        raise SourceError("ره‌آورد۳۶۵ برای قیمت تتر کندلی برنگرداند")
    grouped: dict[str, dict[str, Any]] = {}
    for item in sorted(rows, key=lambda row: _num(row.get("time")) or 0):
        try:
            raw_time = item.get("utc")
            if raw_time:
                candle_time = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
            elif _num(item.get("time")) is not None:
                candle_time = datetime.fromtimestamp(float(item["time"]) / 1000, timezone.utc)
            else:
                continue
            if candle_time.tzinfo is None:
                candle_time = candle_time.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError, OverflowError):
            continue
        day = candle_time.date().isoformat()
        open_price, high, low, close = (_num(item.get(k)) for k in ("open", "high", "low", "close"))
        if close is None or close <= 0:
            continue
        current = grouped.get(day)
        if current is None:
            grouped[day] = {
                "timestamp": f"{day}T00:00:00+03:30",
                "observed_at": candle_time.astimezone(timezone.utc).isoformat(timespec="seconds"),
                "fetched_at": utc_now(), "open": open_price if open_price is not None else close,
                "high": high if high is not None else close, "low": low if low is not None else close,
                "close": close, "volume": _num(item.get("volume")),
            }
        else:
            current["high"] = max(current["high"], high if high is not None else close)
            current["low"] = min(current["low"], low if low is not None else close)
            current["close"] = close
            current["observed_at"] = candle_time.astimezone(timezone.utc).isoformat(timespec="seconds")
            volume = _num(item.get("volume"))
            if volume is not None:
                current["volume"] = volume
    bars = [grouped[day] for day in sorted(grouped)]
    if not bars:
        raise SourceError("کندل‌های قیمت تتر از ره‌آورد۳۶۵ معتبر نیستند")
    return bars


def rahavard_tepix_current() -> dict[str, Any]:
    """Return the latest TEPIX (شاخص کل بورس) observation from Rahavard365."""
    url = f"{RAHAVARD_INDEX_BASE_URL}/{RAHAVARD_TEPIX_INDEX_ID}/last-value"
    payload = _json(url, referer="https://rahavard365.com/")
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise SourceError("پاسخ شاخص کل بورس ره‌آورد۳۶۵ معتبر نیست")
    close = _num(data.get("close_value"))
    if close is None or close <= 0:
        raise SourceError("مقدار شاخص کل بورس در ره‌آورد۳۶۵ یافت نشد")
    timestamp = data.get("end_date_time") or data.get("start_date_time") or utc_now()
    return {
        "bar": {
            "timestamp": str(timestamp),
            "fetched_at": utc_now(),
            "open": _num(data.get("open_value")),
            "high": _num(data.get("high_value")),
            "low": _num(data.get("low_value")),
            "close": close,
            "volume": _num(data.get("volume")),
        },
        "raw": data,
    }


def _rahavard_asset_id(fund: dict[str, Any]) -> str:
    raw = fund.get("raw") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    asset_id = str(raw.get("rahavard_asset_id") or raw.get("asset_id") or
                   fund.get("registration_no") or "").strip()
    if not asset_id.isdigit():
        raise SourceError("شناسه صندوق در ره‌آورد۳۶۵ موجود نیست")
    return asset_id


def rahavard_etf_funds() -> list[dict[str, Any]]:
    """Map Rahavard's public ETF directory into the dashboard fund schema."""
    payload = _json(RAHAVARD_ETF_FUNDS_URL, referer=f"{RAHAVARD_URL}/fund")
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise SourceError("ساختار فهرست صندوق‌های ETF ره‌آورد۳۶۵ قابل شناسایی نیست")
    funds = []
    for row in rows:
        asset_id = str(row.get("asset_id") or "").strip()
        if not asset_id.isdigit():
            continue
        price = _num(row.get("real_close_price"))
        if price is not None and price <= 0:
            price = None
        percent = lambda key: (_num(row.get(key)) * 100
                                if _num(row.get(key)) is not None else None)
        name = str(row.get("name") or asset_id).strip()
        funds.append({
            "fund_key": f"rahavard:{asset_id}",
            "symbol": asset_id,
            "registration_no": asset_id,
            "name": name,
            "category": "قابل معامله",
            "category_id": "rahavard-etf",
            "manager": None, "custodian": None, "market_maker": None,
            "start_date": None, "aum": None, "nav": None,
            "market_price": price,
            "volume": _num(row.get("volume")),
            "value": _num(row.get("value")),
            "trades": None, "units": None, "investors": None,
            "daily_return": percent("real_close_price_change_percent"),
            "weekly_return": None,
            "monthly_return": percent("return_1m"),
            "three_month_return": percent("return_3m"),
            "six_month_return": percent("return_6m"),
            "one_year_return": percent("return_1y"),
            "volatility": None, "liquidity_score": None,
            "data_timestamp": row.get("trade_date_time"),
            "raw": {**row, "rahavard_asset_id": asset_id},
        })
    if not funds:
        raise SourceError("فهرست صندوق‌های قابل معامله از ره‌آورد۳۶۵ خالی بود")
    return funds


def rahavard_fund_profile(asset_id: str) -> dict[str, Any]:
    asset_id = str(asset_id).strip()
    if not asset_id.isdigit():
        raise SourceError("شناسه صندوق ره‌آورد معتبر نیست")
    payload = _json(f"{RAHAVARD_API_BASE_URL}/asset/{asset_id}",
                    referer=f"{RAHAVARD_URL}/asset/{asset_id}")
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or not isinstance(data.get("asset"), dict):
        raise SourceError("اطلاعات نمایه صندوق از ره‌آورد۳۶۵ قابل شناسایی نیست")
    return data


def rahavard_fund_history(asset_id: str) -> list[dict[str, Any]]:
    asset_id = str(asset_id).strip()
    if not asset_id.isdigit():
        raise SourceError("شناسه نمودار صندوق ره‌آورد معتبر نیست")
    query = urllib.parse.urlencode({"symbol": f"exchange.asset:{asset_id}:real_close"})
    payload = _json(f"{RAHAVARD_LIGHT_BARS_URL}?{query}",
                    referer=f"{RAHAVARD_URL}/asset/{asset_id}/chart")
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise SourceError("ساختار کندل‌های صندوق در ره‌آورد۳۶۵ قابل شناسایی نیست")
    fetched_at = utc_now()
    bars = []
    for row in rows:
        try:
            stamp = row.get("utc")
            if stamp:
                parsed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
                timestamp = parsed.isoformat(timespec="seconds")
            elif _num(row.get("time")) is not None:
                timestamp = datetime.fromtimestamp(float(row["time"]) / 1000,
                                                    timezone.utc).isoformat(timespec="seconds")
            else:
                continue
        except (TypeError, ValueError, OverflowError):
            continue
        close = _num(row.get("close"))
        if close is None or close <= 0:
            continue
        bars.append({
            "timestamp": timestamp, "fetched_at": fetched_at,
            "open": _num(row.get("open")), "high": _num(row.get("high")),
            "low": _num(row.get("low")), "close": close,
            "volume": _num(row.get("volume")),
        })
    bars.sort(key=lambda bar: bar["timestamp"])
    if not bars:
        raise SourceError("ره‌آورد۳۶۵ برای نمودار این صندوق کندل معتبری برنگرداند")
    return bars


def rahavard_fund_indicators(asset_id: str) -> dict[str, Any]:
    asset_id = str(asset_id).strip()
    if not asset_id.isdigit():
        raise SourceError("شناسه اندیکاتور صندوق ره‌آورد معتبر نیست")
    payload = _json(f"{RAHAVARD_API_BASE_URL}/asset/{asset_id}/indicators",
                    referer=f"{RAHAVARD_URL}/asset/{asset_id}/indicator")
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or not isinstance(data.get("gauges"), dict):
        raise SourceError("خروجی اندیکاتورهای صندوق از ره‌آورد۳۶۵ قابل شناسایی نیست")
    return data


def _save_rahavard_nav(fund_key: str, profile: dict[str, Any]) -> list[dict[str, Any]]:
    rows = profile.get("fund_values") if isinstance(profile.get("fund_values"), list) else []
    history = []
    with db.connect() as conn:
        for row in rows:
            timestamp = row.get("date")
            if not timestamp:
                continue
            record = {"timestamp": timestamp,
                      "issue_nav": _num(row.get("bid_price")),
                      "cancel_nav": _num(row.get("redemption_price")),
                      "statistical_nav": _num(row.get("statistical_price"))}
            history.append(record)
            conn.execute("""INSERT OR IGNORE INTO fund_nav(symbol,data_timestamp,issue_nav,cancel_nav,statistical_nav,source)
                VALUES(?,?,?,?,?,?)""", (fund_key, timestamp, record["issue_nav"],
                record["cancel_nav"], record["statistical_nav"], "Rahavard365"))
    return history


def codal_ping() -> int:
    url = CODAL_API_URL + "?" + urllib.parse.urlencode({"PageNumber": 1, "PageSize": 1})
    data = _json(url, referer="https://www.codal.ir/")
    return len(data.get("Letters", data.get("letters", []))) if isinstance(data, dict) else 0


def _clean_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", unescape(text or ""))).strip()


def news_from_rss(feed_url: str) -> list[dict[str, Any]]:
    root = ET.fromstring(_http(feed_url))
    items = root.findall(".//item")
    if not items:
        items = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    host = urllib.parse.urlparse(feed_url).netloc
    out = []
    for node in items[:100]:
        get = lambda name: node.findtext(name) or node.findtext("{http://www.w3.org/2005/Atom}" + name) or ""
        title = _clean_html(get("title"))
        if not title:
            continue
        url = get("link")
        if not url:
            link = node.find("{http://www.w3.org/2005/Atom}link")
            url = link.get("href") if link is not None else None
        published = get("pubDate") or get("published") or get("updated")
        try:
            dt = parsedate_to_datetime(published).astimezone(timezone.utc).isoformat(timespec="seconds")
        except (TypeError, ValueError, OverflowError):
            try:
                dt = datetime.fromisoformat(published.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat(timespec="seconds")
            except (TypeError, ValueError):
                dt = None
        summary = _clean_html(get("description") or get("summary"))[:1200]
        normalized = re.sub(r"[^\w\u0600-\u06FF]+", " ", title.casefold()).strip()
        out.append({"title": title, "url": url or None, "source": host,
                    "published_at": dt, "category": None, "importance": None,
                    "sentiment": None, "impact": None, "related_asset": None,
                    "summary": summary or None,
                    "content_hash": hashlib.sha256(normalized.encode("utf-8")).hexdigest()})
    return out


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


async def refresh_all() -> dict[str, Any]:
    """Fetch live observations; errors are persisted and never replaced with estimates."""
    import asyncio

    summary: dict[str, Any] = {"started_at": utc_now(), "sources": [], "records": 0}

    async def run_source(key: str, label: str, url: str, function, apply):
        started_at, tick = utc_now(), time.monotonic()
        try:
            result = await asyncio.to_thread(function)
            applied = apply(result)
            count, data_ts = applied[0], applied[1]
            detail = applied[2] if len(applied) > 2 else {}
            source_status = detail.get("status", "connected")
            message = detail.get("message", "داده تازه دریافت و ذخیره شد")
            db.save_source(key, label, source_status, url, data_ts, detail.get("error"), _elapsed_ms(tick))
            db.log_fetch(key, started_at, "success" if source_status == "connected" else source_status,
                         count, message, _elapsed_ms(tick))
            summary["records"] += count
            summary["sources"].append({"name": key, "status": source_status, "records": count})
        except Exception as exc:
            message = str(exc)[:400]
            # Preserve the most recent valid data; show the current source failure separately.
            db.save_source(key, label, "failed", url, None, message, _elapsed_ms(tick))
            db.log_fetch(key, started_at, "failed", 0, message, _elapsed_ms(tick))
            summary["sources"].append({"name": key, "status": "failed", "error": message})

    def apply_gold(result):
        bars = result
        db.save_bars("GOLD", "طلای جهانی (XAU/USD)", "commodity", "USD", "دلار/اونس تروا",
                     "Rahavard365", RAHAVARD_GOLD_PAGE_URL, bars)
        return len(bars), bars[-1].get("observed_at") or bars[-1]["timestamp"]

    def apply_dxy(result):
        bars, meta = result
        db.save_bars("DXY", "شاخص دلار آمریکا", "index", "USD", "شاخص",
                     "Yahoo Finance", "https://finance.yahoo.com/quote/DX-Y.NYB/", bars)
        return len(bars), bars[-1]["timestamp"]

    def apply_usd(result):
        bars = result
        db.save_bars("USD_IR_FREE", "تتر (معادل دلار آمریکا)", "currency", "IRT", "تومان",
                     "Rahavard365", RAHAVARD_USDT_PAGE_URL, bars)
        observed = bars[-1].get("observed_at") or bars[-1].get("timestamp")
        stale = bool(observed and (datetime.now(timezone.utc) - datetime.fromisoformat(str(observed).replace("Z", "+00:00"))).total_seconds() > MAX_STALE_HOURS * 3600)
        return (len(bars), observed,
                {"status": "stale", "message": "آخرین مشاهدهٔ USDT/IRT از آستانه تازگی عبور کرده است"} if stale else {})

    def apply_tepix(result):
        bar = result["bar"]
        url = f"{RAHAVARD_INDEX_BASE_URL}/{RAHAVARD_TEPIX_INDEX_ID}/last-value"
        db.save_bars("TEPIX", "شاخص کل بورس", "index", "POINT", "واحد",
                     "Rahavard365", url, [bar])
        return 1, bar["timestamp"]

    async def funds_from_rahavard():
        started_at, tick = utc_now(), time.monotonic()
        try:
            funds = await asyncio.to_thread(rahavard_etf_funds)
            db.save_funds(funds, "Rahavard365", RAHAVARD_ETF_FUNDS_URL)
            latest = max((str(x.get("data_timestamp") or "") for x in funds), default=None)
            db.save_source("rahavard_funds", "صندوق‌های قابل معامله / ره‌آورد۳۶۵", "connected",
                           RAHAVARD_ETF_FUNDS_URL, latest, None, _elapsed_ms(tick))
            db.log_fetch("rahavard_funds", started_at, "success", len(funds),
                         "فهرست و قیمت صندوق‌های ETF از ره‌آورد۳۶۵ دریافت شد", _elapsed_ms(tick))
            summary["records"] += len(funds)
            summary["sources"].append({"name": "rahavard_funds", "status": "connected", "records": len(funds)})
        except Exception as exc:
            message = str(exc)[:400]
            db.save_source("rahavard_funds", "صندوق‌های قابل معامله / ره‌آورد۳۶۵", "failed",
                           RAHAVARD_ETF_FUNDS_URL, None, message, _elapsed_ms(tick))
            db.log_fetch("rahavard_funds", started_at, "failed", 0, message, _elapsed_ms(tick))
            summary["sources"].append({"name": "rahavard_funds", "status": "failed", "error": message})

    async def codal_job():
        async def run():
            return await asyncio.to_thread(codal_ping)
        return await run()

    tasks = [
        run_source("rahavard_gold", "طلای جهانی / ره‌آورد۳۶۵", RAHAVARD_GOLD_PAGE_URL,
                   rahavard_gold_history, apply_gold),
        run_source("yahoo_dxy", "شاخص دلار آمریکا", YAHOO_CHART.format(symbol="DX-Y.NYB"),
                   lambda: yahoo_history("DX-Y.NYB"), apply_dxy),
        run_source("rahavard_usdt", "قیمت تتر / ره‌آورد۳۶۵", RAHAVARD_USDT_PAGE_URL,
                   rahavard_usdt_history, apply_usd),
        run_source("rahavard_tepix", "شاخص کل بورس / ره‌آورد۳۶۵",
                   f"{RAHAVARD_INDEX_BASE_URL}/{RAHAVARD_TEPIX_INDEX_ID}/last-value",
                   rahavard_tepix_current, apply_tepix),
        funds_from_rahavard(),
    ]
    await asyncio.gather(*tasks, return_exceptions=True)

    # Codal has a separate request because it is not mixed with market or fund observations.
    started_at, tick = utc_now(), time.monotonic()
    try:
        count = await asyncio.to_thread(codal_ping)
        db.save_source("codal", "افشاهای رسمی / کدال", "connected", CODAL_API_URL, utc_now(), None, _elapsed_ms(tick))
        db.log_fetch("codal", started_at, "success", count, "درگاه جست‌وجوی کدال پاسخ داد", _elapsed_ms(tick))
        summary["sources"].append({"name": "codal", "status": "connected", "records": count})
    except Exception as exc:
        message = str(exc)[:400]
        db.save_source("codal", "افشاهای رسمی / کدال", "failed", CODAL_API_URL, None, message, _elapsed_ms(tick))
        db.log_fetch("codal", started_at, "failed", 0, message, _elapsed_ms(tick))
        summary["sources"].append({"name": "codal", "status": "failed", "error": message})
    summary["finished_at"] = utc_now()
    return summary


async def fetch_rahavard_fund_profile(symbol: str) -> dict[str, Any]:
    import asyncio

    fund = db.get_fund(symbol)
    if not fund or fund.get("ambiguous"):
        raise SourceError("صندوق ره‌آورد در پایگاه داده پیدا نشد")
    if fund.get("source") != "Rahavard365":
        raise SourceError("این صندوق در فهرست ره‌آورد۳۶۵ نیست")
    asset_id = _rahavard_asset_id(fund)
    url = f"{RAHAVARD_API_BASE_URL}/asset/{asset_id}"
    tick = time.monotonic()
    try:
        profile = await asyncio.to_thread(rahavard_fund_profile, asset_id)
        nav_rows = _save_rahavard_nav(fund["fund_key"], profile)
        trade = profile.get("last_trade") if isinstance(profile.get("last_trade"), dict) else {}
        data_timestamp = trade.get("end_date_time") or max(
            (str(row["timestamp"]) for row in nav_rows), default=fund.get("data_timestamp"))
        db.save_source("rahavard_fund_details", "نمایه و NAV صندوق / ره‌آورد۳۶۵", "connected",
                       url, data_timestamp, None, int((time.monotonic() - tick) * 1000))
        return profile
    except Exception as exc:
        db.save_source("rahavard_fund_details", "نمایه و NAV صندوق / ره‌آورد۳۶۵", "failed",
                       url, None, str(exc)[:400], int((time.monotonic() - tick) * 1000))
        raise


async def fetch_fund_nav_history(symbol: str) -> list[dict[str, Any]]:
    fund = db.get_fund(symbol)
    if not fund or fund.get("ambiguous"):
        raise SourceError("صندوق ره‌آورد در پایگاه داده پیدا نشد")
    await fetch_rahavard_fund_profile(fund["fund_key"])
    return db.fund_nav_history(fund["fund_key"])


async def fetch_fund_price_history(symbol: str) -> list[dict[str, Any]]:
    """Fetch the public recent daily candle series from Rahavard365 on demand."""
    import asyncio

    fund = db.get_fund(symbol)
    if not fund or fund.get("ambiguous"):
        raise SourceError("صندوق ره‌آورد در پایگاه داده پیدا نشد")
    if fund.get("source") != "Rahavard365":
        raise SourceError("این صندوق در فهرست ره‌آورد۳۶۵ نیست")
    fund_key = fund["fund_key"]
    asset_id = _rahavard_asset_id(fund)
    query = urllib.parse.urlencode({"symbol": f"exchange.asset:{asset_id}:real_close"})
    url = f"{RAHAVARD_LIGHT_BARS_URL}?{query}"
    tick = time.monotonic()
    try:
        bars = await asyncio.to_thread(rahavard_fund_history, asset_id)
        db.save_bars(fund_key, fund["name"], "fund", "IRR", "ریال/واحد",
                     "Rahavard365", url, bars)
        db.save_source("rahavard_fund_charts", "نمودار صندوق / ره‌آورد۳۶۵", "connected", url,
                       bars[-1]["timestamp"], None, int((time.monotonic() - tick) * 1000))
        return bars
    except Exception as exc:
        db.save_source("rahavard_fund_charts", "نمودار صندوق / ره‌آورد۳۶۵", "failed",
                       url, None, str(exc)[:400], int((time.monotonic() - tick) * 1000))
        raise


async def fetch_fund_indicators(symbol: str) -> dict[str, Any]:
    import asyncio

    fund = db.get_fund(symbol)
    if not fund or fund.get("ambiguous"):
        raise SourceError("صندوق ره‌آورد در پایگاه داده پیدا نشد")
    if fund.get("source") != "Rahavard365":
        raise SourceError("این صندوق در فهرست ره‌آورد۳۶۵ نیست")
    asset_id = _rahavard_asset_id(fund)
    url = f"{RAHAVARD_API_BASE_URL}/asset/{asset_id}/indicators"
    tick = time.monotonic()
    try:
        data = await asyncio.to_thread(rahavard_fund_indicators, asset_id)
        db.save_fund_indicator_snapshot(fund["fund_key"], data,
                                        fund.get("data_timestamp"), "Rahavard365")
        db.save_source("rahavard_indicators", "اندیکاتورهای صندوق / ره‌آورد۳۶۵", "connected",
                       url, fund.get("data_timestamp"), None,
                       int((time.monotonic() - tick) * 1000))
        return data
    except Exception as exc:
        db.save_source("rahavard_indicators", "اندیکاتورهای صندوق / ره‌آورد۳۶۵", "failed",
                       url, None, str(exc)[:400], int((time.monotonic() - tick) * 1000))
        raise
