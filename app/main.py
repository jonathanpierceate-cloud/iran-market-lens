from __future__ import annotations

import asyncio
import csv
import io
import json
import math
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .analysis import analyze, analyze_rahavard, stale_status
from .config import (MAX_STALE_HOURS, RAHAVARD_API_BASE_URL,
                     RAHAVARD_ETF_FUNDS_URL, RAHAVARD_GOLD_PAGE_URL,
                     RAHAVARD_GOLD_18K_PAGE_URL,
                     RAHAVARD_LIGHT_BARS_URL, RAHAVARD_TEPIX_PAGE_URL,
                     RAHAVARD_USDT_PAGE_URL,
                     REFRESH_INTERVAL_SECONDS, ROOT)
from .db import db, utc_now
from .sources import (SourceError, fetch_fund_indicators, fetch_fund_nav_history,
                      fetch_fund_price_history, fetch_rahavard_fund_profile,
                      rahavard_etf_fund_asset_ids, refresh_all)

STATIC = ROOT / "app" / "static"
REFRESH_STATE: dict[str, Any] = {"running": False, "last_result": None}
REFRESH_WAKE: asyncio.Event | None = None
FUND_CATEGORY_CACHE: dict[str, tuple[float, set[str]]] = {}
FUND_CATEGORY_CACHE_TTL = 15 * 60


class WatchlistAddInput(BaseModel):
    symbol: str = Field(min_length=1, max_length=120)


class WatchlistUpdateInput(BaseModel):
    break_even_price: float | None = Field(default=None, ge=0)
    units: float | None = Field(default=None, ge=0)


class FundScoreBatchInput(BaseModel):
    fund_keys: list[str] = Field(default_factory=list, max_length=4)


def _source_map() -> dict[str, dict[str, Any]]:
    return {row["name"]: row for row in db.source_status()}


def _market_history(symbol: str, limit: int = 1000) -> list[dict[str, Any]]:
    fund = db.get_fund(symbol)
    if fund and not fund.get("ambiguous") and fund.get("source") == "Rahavard365":
        return db.history(fund["fund_key"], limit, source="Rahavard365")
    preferred = {"GOLD": "Rahavard365", "GOLD_18K": "Rahavard365", "USD_IR_FREE": "Rahavard365", "TEPIX": "Rahavard365"}.get(symbol)
    if preferred:
        bars = db.history(symbol, limit, source=preferred)
        if bars:
            if symbol == "USD_IR_FREE":
                iran_tz = timezone(timedelta(hours=3, minutes=30))
                daily: dict[str, dict[str, Any]] = {}
                for bar in bars:
                    try:
                        stamp = datetime.fromisoformat(str(bar["timestamp"]).replace("Z", "+00:00"))
                        if stamp.tzinfo is None:
                            stamp = stamp.replace(tzinfo=timezone.utc)
                        day = stamp.astimezone(iran_tz).date().isoformat()
                    except (TypeError, ValueError):
                        continue
                    price = bar.get("close")
                    if price is None:
                        continue
                    current = daily.get(day)
                    if current is None:
                        daily[day] = {**bar, "open": price, "high": price, "low": price, "volume": None}
                    else:
                        current["high"] = max(current["high"], price)
                        current["low"] = min(current["low"], price)
                        current["close"] = price
                        current["timestamp"] = bar["timestamp"]
                        current["fetched_at"] = bar.get("fetched_at")
                bars = [daily[day] for day in sorted(daily)]
                return bars[-max(1, limit):]
            return bars
    return db.history(symbol, limit)


def _refresh_interval() -> int:
    try:
        return max(60, min(86400, int(db.get_settings().get("refresh_interval_seconds", REFRESH_INTERVAL_SECONDS))))
    except (TypeError, ValueError):
        return REFRESH_INTERVAL_SECONDS


def _market_quote(symbol: str) -> dict[str, Any]:
    bars = _market_history(symbol, 10000)
    with db.connect() as conn:
        asset = conn.execute("SELECT * FROM assets WHERE symbol=?", (symbol,)).fetchone()
    if not asset:
        raise HTTPException(status_code=404, detail="دارایی پیدا نشد")
    data = dict(asset)
    if not bars:
        return {"symbol": symbol, "name": data["name"], "price": None, "history": [],
                "source": data.get("source"), "source_url": data.get("source_url"),
                "data_timestamp": None, "fetched_at": None, "stale": None,
                "status": "unavailable", "error": "هنوز مشاهده معتبری ذخیره نشده است"}
    latest = bars[-1]
    returns = {}
    for label, periods in [("daily", 1), ("weekly", 5), ("monthly", 21), ("three_month", 63), ("six_month", 126), ("one_year", 252)]:
        if len(bars) > periods and bars[-periods-1].get("close"):
            returns[label] = round((latest["close"] / bars[-periods-1]["close"] - 1) * 100, 3)
        else:
            returns[label] = None
    source_key = {"GOLD": "rahavard_gold", "GOLD_18K": "rahavard_gold_18k", "DXY": "yahoo_dxy", "USD_IR_FREE": "rahavard_usdt",
                  "TEPIX": "rahavard_tepix"}.get(symbol)
    source = _source_map().get(source_key) if source_key else None
    observed_timestamp = (source.get("last_data_timestamp") if source and symbol in {"GOLD", "GOLD_18K", "USD_IR_FREE", "TEPIX"}
                          else latest["timestamp"])
    observed_timestamp = observed_timestamp or latest["timestamp"]
    is_stale = stale_status(observed_timestamp, max_hours=MAX_STALE_HOURS)
    if source and source["status"] == "stale":
        status = "stale"
    elif source and source["status"] == "failed":
        status = "stale" if is_stale else "cached_after_source_error"
    else:
        status = "stale" if is_stale else "available"
    output = {"symbol": symbol, "name": data["name"], "price": latest["close"],
              "open": latest.get("open"), "high": latest.get("high"), "low": latest.get("low"),
              "volume": latest.get("volume"), "history": bars, "returns": returns,
              "source": latest.get("source"), "source_url": data.get("source_url"),
              "data_timestamp": observed_timestamp, "fetched_at": latest.get("fetched_at"),
              "stale": bool(is_stale), "status": status}
    iran_tz = timezone(timedelta(hours=3, minutes=30))
    try:
        observed_day = datetime.fromisoformat(str(observed_timestamp).replace("Z", "+00:00"))
        if observed_day.tzinfo is None:
            observed_day = observed_day.replace(tzinfo=iran_tz)
        output["price_is_cached"] = observed_day.astimezone(iran_tz).date() != datetime.now(iran_tz).date()
    except (TypeError, ValueError, OverflowError):
        output["price_is_cached"] = bool(is_stale)
    output["analysis"] = analyze(symbol, bars)
    output["analysis"]["price_is_cached"] = output["price_is_cached"]
    return output


def evaluate_alerts() -> list[dict[str, Any]]:
    """Evaluate active local alerts only against fresh source-backed observations."""
    triggered = []
    for alert in db.alerts():
        if not alert.get("enabled") or alert.get("triggered_at"):
            continue
        fund = db.get_fund(alert["symbol"])
        if fund and fund.get("ambiguous"):
            continue
        if fund and fund.get("source") == "Rahavard365" and alert["condition"] in {
                "rsi_overbought", "rsi_oversold", "volume_spike"}:
            snapshot = db.fund_indicator_snapshots().get(fund["fund_key"])
            if not snapshot or stale_status(snapshot.get("data_timestamp"), max_hours=MAX_STALE_HOURS):
                continue
            if alert["condition"] == "volume_spike":
                # The Rahavard endpoint does not publish a volume-spike boolean.
                continue
            result = analyze_rahavard(fund["symbol"], snapshot["data"], snapshot.get("data_timestamp"), fund.get("market_price"))
            rsi_item = next((item for item in result["indicators"].get("oscillators", [])
                             if str(item.get("short_name_en") or "").startswith("RSI(14)")), None)
            rsi_value = None
            if rsi_item:
                for part in rsi_item.get("value") or []:
                    if str(part.get("name") or "").casefold() in {"rsi", "value"}:
                        try:
                            rsi_value = float(part.get("value"))
                        except (TypeError, ValueError):
                            pass
                        break
            hit = ((alert["condition"] == "rsi_overbought" and rsi_value is not None and rsi_value >= 70)
                   or (alert["condition"] == "rsi_oversold" and rsi_value is not None and rsi_value <= 30))
            if hit:
                reason = f"RSI(14) ره‌آورد به {rsi_value:.1f} رسید"
                db.mark_alert_triggered(alert["id"], reason)
                triggered.append({"id": alert["id"], "symbol": fund["symbol"], "message": reason})
            continue
        history_symbol = fund["fund_key"] if fund else alert["symbol"]
        analysis_symbol = fund["symbol"] if fund else alert["symbol"]
        bars = _market_history(history_symbol, 5000)
        if not bars or stale_status(bars[-1].get("timestamp"), max_hours=MAX_STALE_HOURS):
            continue
        current = bars[-1].get("close")
        condition = alert["condition"]
        hit = False
        reason = ""
        if condition == "price_above" and current is not None and alert.get("threshold") is not None:
            hit = current >= alert["threshold"]; reason = f"قیمت به {current} رسید و از آستانه گذشت"
        elif condition == "price_below" and current is not None and alert.get("threshold") is not None:
            hit = current <= alert["threshold"]; reason = f"قیمت به {current} رسید و از آستانه پایین‌تر آمد"
        elif condition in {"rsi_overbought", "rsi_oversold", "volume_spike"}:
            result = analyze(analysis_symbol, bars)
            indicators = result["indicators"]["indicators"]
            rsi = indicators.get("RSI(14)", {}).get("value")
            spike = result["indicators"].get("volume_analysis", {}).get("volume_spike")
            if condition == "rsi_overbought": hit = rsi is not None and rsi >= 70; reason = f"RSI(14) به {rsi:.1f} رسید" if hit else ""
            elif condition == "rsi_oversold": hit = rsi is not None and rsi <= 30; reason = f"RSI(14) به {rsi:.1f} رسید" if hit else ""
            elif condition == "volume_spike": hit = bool(spike); reason = "جهش حجم نسبت به میانگین ۲۰ دوره ثبت شد" if hit else ""
        if hit:
            db.mark_alert_triggered(alert["id"], reason)
            triggered.append({"id": alert["id"], "symbol": analysis_symbol, "message": reason})
    return triggered


async def _periodic_refresh():
    first_run = True
    while True:
        if not first_run:
            if REFRESH_WAKE is None:
                await asyncio.sleep(_refresh_interval())
            else:
                try:
                    await asyncio.wait_for(REFRESH_WAKE.wait(), timeout=_refresh_interval())
                except asyncio.TimeoutError:
                    pass
                else:
                    REFRESH_WAKE.clear()
                    continue
        first_run = False
        try:
            if not REFRESH_STATE["running"]:
                REFRESH_STATE["running"] = True
                REFRESH_STATE["last_result"] = await refresh_all()
                evaluate_alerts()
        except Exception as exc:
            REFRESH_STATE["last_result"] = {"error": str(exc)}
        finally:
            REFRESH_STATE["running"] = False
@asynccontextmanager
async def lifespan(_: FastAPI):
    global REFRESH_WAKE
    db.init()
    REFRESH_WAKE = asyncio.Event()
    for key, label, url in [
        ("rahavard_gold", "طلای جهانی / ره‌آورد۳۶۵", RAHAVARD_GOLD_PAGE_URL),
        ("rahavard_gold_18k", "طلای ۱۸ عیار / ره‌آورد۳۶۵", RAHAVARD_GOLD_18K_PAGE_URL),
        ("rahavard_usdt", "قیمت تتر / ره‌آورد۳۶۵", RAHAVARD_USDT_PAGE_URL),
        ("rahavard_tepix", "شاخص کل بورس / ره‌آورد۳۶۵", RAHAVARD_TEPIX_PAGE_URL),
        ("yahoo_dxy", "شاخص دلار آمریکا", "https://finance.yahoo.com/quote/DX-Y.NYB/"),
        ("rahavard_funds", "صندوق‌های قابل معامله / ره‌آورد۳۶۵", RAHAVARD_ETF_FUNDS_URL),
        ("rahavard_fund_details", "نمایه و NAV صندوق / ره‌آورد۳۶۵", RAHAVARD_API_BASE_URL + "/asset/{asset_id}"),
        ("rahavard_fund_charts", "نمودار صندوق / ره‌آورد۳۶۵", RAHAVARD_LIGHT_BARS_URL + "?symbol=exchange.asset:{asset_id}:real_close"),
        ("rahavard_indicators", "اندیکاتورهای صندوق / ره‌آورد۳۶۵", RAHAVARD_API_BASE_URL + "/asset/{asset_id}/indicators"),
    ]:
        if key not in _source_map():
            db.save_source(key, label, "not_tested", url, None, "هنوز بررسی نشده است", None)
    legacy_sources = _source_map()
    for key, label in [("tsetmc", "منبع قبلی قیمت صندوق‌ها · غیرفعال"),
                       ("fipiran", "منبع قبلی مشخصات صندوق‌ها · غیرفعال"),
                       ("tabdeal_usdt", "منبع قبلی قیمت تتر · غیرفعال")]:
        previous = legacy_sources.get(key)
        if previous and previous.get("status") != "disabled":
            db.save_source(key, label, "disabled", previous.get("source_url"),
                           previous.get("last_data_timestamp"),
                           "برای داده جدید صندوق‌ها از ره‌آورد۳۶۵ استفاده می‌شود؛ تاریخچه قبلی نگهداری شده است.", None)
    for key, label in [("yahoo_gold", "Yahoo Finance · تاریخچه پیشین"),
                       ("tgju", "TGJU · تاریخچه پیشین")]:
        previous = legacy_sources.get(key)
        if previous:
            db.save_source(key, label, "not_tested", previous.get("source_url"),
                           previous.get("last_data_timestamp"),
                           "این منبع برای داده‌های جدید استفاده نمی‌شود؛ تاریخچه قبلی نگهداری شده است.", None)
    # Vercel may freeze a function immediately after a response.  A forever
    # running task is therefore not a reliable scheduler there; refreshes are
    # triggered explicitly through /api/refresh (and can be called by a cron).
    if os.getenv("VERCEL"):
        # A new Vercel instance has an empty /tmp directory.  Bootstrap it
        # once before serving the first request so a cold instance still has
        # live Rahavard365 prices, funds, and indicators instead of an empty
        # dashboard.  Warm instances can be refreshed through /api/refresh.
        if not db.funds(source="Rahavard365") or not db.history("GOLD_18K", 1, source="Rahavard365"):
            REFRESH_STATE["running"] = True
            try:
                REFRESH_STATE["last_result"] = await refresh_all()
                evaluate_alerts()
            except Exception as exc:
                REFRESH_STATE["last_result"] = {"error": str(exc)}
            finally:
                REFRESH_STATE["running"] = False
        yield
        return

    task = asyncio.create_task(_periodic_refresh())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="AliVest | تحلیل بازار سرمایه ایران", version="1.0.0", lifespan=lifespan,
              description="داشبورد محلی با ثبت منبع، زمان داده و وضعیت تازگی.")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", response_class=HTMLResponse)
def home():
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/api/health")
def health():
    try:
        with db.connect() as conn:
            conn.execute("SELECT 1")
            counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in ["prices", "funds", "alerts"]}
        counts["funds"] = len(db.funds(source="Rahavard365"))
        return {"status": "ok", "database": "connected", "counts": counts,
                "scheduler": "disabled_on_vercel" if os.getenv("VERCEL") else "running",
                "checked_at": utc_now()}
    except Exception as exc:
        return JSONResponse(status_code=503, content={"status": "error", "database": str(exc)})


def _gold18k_valuation(gold_quote: dict[str, Any], dollar_quote: dict[str, Any], rahavard_quote: dict[str, Any]) -> dict[str, Any]:
    """Estimate 18K gold per gram from XAU/USD and USDT/IRT, then compare it with Rahavard."""
    def number(value: Any) -> float | None:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) and result > 0 else None

    gold_usd_per_ounce = number(gold_quote.get("price"))
    usdt_toman = number(dollar_quote.get("price"))
    rahavard_irr_per_gram = number(rahavard_quote.get("price"))
    valuation: dict[str, Any] = {
        "theoretical_price": None,
        "rahavard_price": rahavard_irr_per_gram,
        "bubble": None,
        "bubble_percent": None,
        "gold_usd_per_ounce": gold_usd_per_ounce,
        "usdt_toman": usdt_toman,
        "purity": 0.75,
        "ounce_grams": 31.1034768,
        "method": "XAU/USD * USDT/IRT * 75% / 31.1034768",
    }
    if gold_usd_per_ounce is None or usdt_toman is None or rahavard_irr_per_gram is None:
        return valuation

    # Rahavard supplies the USDT quote in the numeric scale used by its
    # local rial-denominated gold feed; applying another factor of 10 would
    # overstate the result and create a false tenfold bubble.
    theoretical = gold_usd_per_ounce * usdt_toman * 0.75 / 31.1034768
    bubble = rahavard_irr_per_gram - theoretical
    valuation.update({
        "theoretical_price": round(theoretical),
        "bubble": round(bubble),
        "bubble_percent": round((bubble / theoretical) * 100, 2) if theoretical else None,
    })
    return valuation


@app.get("/api/market/summary")
def market_summary():
    funds = _exclude_fixed_income_funds(db.funds(sort="data_timestamp", source="Rahavard365"))
    gold_quote = _market_quote("GOLD")
    gold18k_quote = _market_quote("GOLD_18K")
    dollar_quote = _market_quote("USD_IR_FREE")
    tepix_quote = _market_quote("TEPIX")
    gold_quote.pop("history", None)
    gold18k_quote.pop("history", None)
    dollar_quote.pop("history", None)
    tepix_quote.pop("history", None)
    gold18k_quote["valuation"] = _gold18k_valuation(gold_quote, dollar_quote, gold18k_quote)
    return {"as_of": utc_now(), "gold": gold_quote, "gold18k": gold18k_quote,
            "dollar": dollar_quote,
            "tepix": tepix_quote,
            "funds_total": len(funds),
            "top_funds": sorted(funds, key=lambda f: f.get("value") or 0, reverse=True)[:5],
            "sources": db.source_status(), "refresh": REFRESH_STATE}


@app.get("/api/gold")
def gold():
    return _market_quote("GOLD")


@app.get("/api/gold-18k")
def gold_18k():
    return _market_quote("GOLD_18K")


@app.get("/api/gold/history")
def gold_history(limit: int = Query(default=1000, ge=1, le=5000)):
    bars = _market_history("GOLD", limit)
    source = _source_map().get("rahavard_gold")
    observed = (source or {}).get("last_data_timestamp") or (bars[-1]["timestamp"] if bars else None)
    return {"symbol": "GOLD", "history": bars,
            "source": bars[-1]["source"] if bars else None,
            "data_timestamp": observed,
            "stale": stale_status(observed, max_hours=MAX_STALE_HOURS) if observed else None}


@app.get("/api/dollar")
def dollar():
    return _market_quote("USD_IR_FREE")


@app.get("/api/tepix")
def tepix():
    return _market_quote("TEPIX")


@app.get("/api/dollar/history")
def dollar_history(limit: int = Query(default=1000, ge=1, le=5000)):
    bars = _market_history("USD_IR_FREE", limit)
    source = _source_map().get("rahavard_usdt")
    observed = (source or {}).get("last_data_timestamp") or (bars[-1]["timestamp"] if bars else None)
    return {"symbol": "USD_IR_FREE", "history": bars,
            "source": bars[-1]["source"] if bars else None,
            "data_timestamp": observed,
            "stale": stale_status(observed, max_hours=MAX_STALE_HOURS) if observed else None}


@app.get("/api/market/sources")
def data_sources():
    return {"sources": db.source_status(), "checked_at": utc_now()}


@app.api_route("/api/refresh", methods=["GET", "POST"])
async def manual_refresh():
    if REFRESH_STATE["running"]:
        return {"status": "already_running", "last_result": REFRESH_STATE["last_result"]}
    REFRESH_STATE["running"] = True
    try:
        result = await refresh_all()
        REFRESH_STATE["last_result"] = result
        evaluate_alerts()
        return result
    finally:
        REFRESH_STATE["running"] = False


def _fund_observation_rank(fund: dict[str, Any]) -> tuple[float, int]:
    stamp = fund.get("data_timestamp")
    try:
        observed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        timestamp = observed.timestamp()
    except (TypeError, ValueError, OverflowError):
        timestamp = float("-inf")
    return timestamp, int(fund.get("fund_key") == db.fund_key(fund))


def _fund_updated_at(fund: dict[str, Any]) -> str | None:
    raw = fund.get("raw") if isinstance(fund.get("raw"), dict) else {}
    return raw.get("trade_date_time") or raw.get("data_updated_at") or fund.get("data_timestamp")


def _fund_category_asset_ids(category_id: str) -> set[str]:
    now = time.monotonic()
    cached = FUND_CATEGORY_CACHE.get(category_id)
    if cached and now - cached[0] < FUND_CATEGORY_CACHE_TTL:
        return cached[1]
    asset_ids = rahavard_etf_fund_asset_ids(category_id)
    FUND_CATEGORY_CACHE[category_id] = (now, asset_ids)
    return asset_ids


def _exclude_fixed_income_funds(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        fixed_income_ids = _fund_category_asset_ids("255")
    except SourceError:
        fixed_income_ids = set()

    visible: list[dict[str, Any]] = []
    for item in items:
        raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
        asset_id = str(raw.get("rahavard_asset_id") or item.get("registration_no") or item.get("symbol") or "").strip()
        group_ids = (item.get("category_id"), raw.get("groupId"), raw.get("group_id"),
                     raw.get("category_id"), raw.get("categoryId"))
        labels = (item.get("category"), item.get("name"), raw.get("category"),
                  raw.get("category_name"), raw.get("groupName"), raw.get("fund_type"))
        is_fixed_income = (
            asset_id in fixed_income_ids
            or any(str(value or "").strip() == "255" for value in group_ids)
            or any("درآمد ثابت" in str(value or "").casefold()
                   or "fixed income" in str(value or "").casefold() for value in labels)
        )
        if not is_fixed_income:
            visible.append(item)
    return visible


def _dedupe_rahavard_funds(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: dict[str, tuple[int, dict[str, Any]]] = {}
    for index, item in enumerate(items):
        raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
        asset_id = str(raw.get("rahavard_asset_id") or item.get("registration_no") or item.get("symbol") or "").strip()
        identity = asset_id or str(item.get("fund_key") or index)
        current = selected.get(identity)
        if current is None or _fund_observation_rank(item) > _fund_observation_rank(current[1]):
            selected[identity] = (index, item)
    return [item for _, item in sorted(selected.values(), key=lambda entry: entry[0])]


@app.get("/api/funds")
def funds(search: str = "", category: str = "", sort: str = "data_timestamp"):
    if category == "255":
        return {"items": [], "count": 0, "source": "Rahavard365", "data_status": "available"}
    db_category = "" if category.isdigit() else category
    items = _dedupe_rahavard_funds(db.funds(search=search, category=db_category, sort=sort, source="Rahavard365"))
    if category.isdigit():
        try:
            allowed_ids = _fund_category_asset_ids(category)
            items = [item for item in items
                     if str(item.get("raw", {}).get("rahavard_asset_id") or item.get("symbol") or "") in allowed_ids]
        except SourceError:
            items = []
    items = _exclude_fixed_income_funds(items)
    snapshots = db.fund_indicator_snapshots()
    for item in items:
        raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
        current_price = _watchlist_number(item.get("market_price"))
        if current_price is None or current_price <= 0:
            current_price = _watchlist_number(raw.get("real_close_price"))
        item["rahavard_asset_id"] = str(raw.get("rahavard_asset_id") or item["symbol"])
        item["rahavard_state"] = raw.get("instrument_state")
        item["updated_at"] = _fund_updated_at(item)
        for field in ("open_price", "high_price", "low_price", "ask_price", "ask_volume",
                      "bid_price", "bid_volume", "real_close_price_change",
                      "real_close_price_change_percent", "trade_date_time"):
            item[field] = raw.get(field)
        snapshot = snapshots.get(item["fund_key"])
        result = analyze_rahavard(item["symbol"], snapshot["data"],
                                  snapshot.get("data_timestamp") or item.get("data_timestamp"),
                                  current_price) if snapshot else None
        item["analysis"] = result
        item["technical_score"] = result.get("technical_score") if result else None
        item["medium_term_exit_price"] = result.get("medium_term_exit_price") if result else None
        item["purchase_assessment"] = _fund_purchase_assessment(current_price, result)
        item["buy_suitability_rank"] = item["purchase_assessment"]["rank"]
        item["trend"] = result.get("trend") if result else "unavailable"
        item["indicator_fetched_at"] = snapshot.get("fetched_at") if snapshot else None
    sort_key = {"return": "one_year_return", "technical_score": "technical_score"}.get(sort, sort)
    if sort_key in {"one_year_return", "monthly_return", "daily_return", "technical_score"}:
        items.sort(key=lambda f: f.get(sort_key) if f.get(sort_key) is not None else float("-inf"), reverse=True)
    return {"items": items, "count": len(items), "source": "Rahavard365",
            "data_status": "available" if items else "unavailable"}


def _fund_or_error(identifier: str) -> dict[str, Any]:
    fund = db.get_fund(identifier)
    if fund and fund.get("ambiguous"):
        matches = [{"fund_key": row["fund_key"], "name": row["name"]} for row in fund["matches"]]
        raise HTTPException(status_code=409, detail={"message": "این شناسه به چند صندوق تعلق دارد؛ از fund_key استفاده کنید.", "matches": matches})
    if not fund:
        raise HTTPException(status_code=404, detail="صندوق پیدا نشد یا هنوز از منبع دریافت نشده است")
    if fund.get("source") != "Rahavard365":
        raise HTTPException(status_code=404, detail="این صندوق در فهرست ره‌آورد۳۶۵ موجود نیست")
    return fund


@app.post("/api/funds/scores/batch")
async def fund_score_batch(payload: FundScoreBatchInput):
    keys = list(dict.fromkeys(key.strip() for key in payload.fund_keys if key.strip()))
    if not keys:
        raise HTTPException(status_code=422, detail="شناسه‌ای برای محاسبه امتیاز ارسال نشده است")

    semaphore = asyncio.Semaphore(4)

    async def calculate(identifier: str) -> dict[str, Any]:
        async with semaphore:
            try:
                fund = _fund_or_error(identifier)
                indicators = await fetch_fund_indicators(fund["fund_key"])
                raw = fund.get("raw") if isinstance(fund.get("raw"), dict) else {}
                current_price = _watchlist_number(fund.get("market_price"))
                if current_price is None or current_price <= 0:
                    current_price = _watchlist_number(raw.get("real_close_price"))
                analysis_result = analyze_rahavard(
                    fund.get("symbol"), indicators, fund.get("data_timestamp"), current_price)
                purchase_assessment = _fund_purchase_assessment(current_price, analysis_result)
                return {"fund_key": fund["fund_key"], "technical_score": analysis_result.get("technical_score"),
                        "medium_term_exit_price": analysis_result.get("medium_term_exit_price"),
                        "purchase_assessment": purchase_assessment,
                        "buy_suitability_rank": purchase_assessment["rank"],
                        "error": None if analysis_result.get("technical_score") is not None else "داده کافی برای محاسبه موجود نیست"}
            except HTTPException as exc:
                return {"fund_key": identifier, "technical_score": None, "error": str(exc.detail)}
            except SourceError as exc:
                return {"fund_key": identifier, "technical_score": None, "error": str(exc)}
            except Exception as exc:
                return {"fund_key": identifier, "technical_score": None, "error": str(exc)[:180]}

    items = await asyncio.gather(*(calculate(key) for key in keys))
    return {"items": items, "processed": len(items),
            "scored": sum(item["technical_score"] is not None for item in items),
            "unavailable": sum(item["technical_score"] is None for item in items)}


def _watchlist_number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _fund_purchase_assessment(price: Any, analysis: dict[str, Any] | None) -> dict[str, Any]:
    current_price = _watchlist_number(price)
    if not isinstance(analysis, dict):
        return {"status": "unknown", "label": "داده کافی نیست", "reason": "تحلیل تکنیکال این نماد هنوز آماده نیست.", "rank": None}
    exit_price = _watchlist_number(analysis.get("medium_term_exit_price"))
    score = _watchlist_number(analysis.get("technical_score"))
    breakdown = analysis.get("score_breakdown") if isinstance(analysis.get("score_breakdown"), dict) else {}
    near_resistance_count = _watchlist_number(breakdown.get("near_resistance_count"))
    rsi = _watchlist_number(breakdown.get("rsi"))
    if current_price is None or current_price <= 0 or exit_price is None or exit_price <= 0 or score is None or near_resistance_count is None:
        return {"status": "unknown", "label": "داده کافی نیست", "reason": "برای ارزیابی قیمت فعلی، قیمت و دادهٔ کامل تکنیکال لازم است.", "rank": None}
    if current_price <= exit_price:
        return {"status": "unsuitable", "label": "نامناسب", "reason": "قیمت فعلی روی حد خروج میان‌مدت یا پایین‌تر از آن است.", "rank": 0}
    if rsi is not None and rsi >= 70:
        label = "صبر · RSI داغ" if rsi >= 80 else "صبر · RSI بالاست"
        return {"status": "wait", "label": label,
                "reason": f"RSI(14) برابر {rsi:.1f} است؛ برای خرید تازه تا کاهش خریدزدگی و تأیید دوباره صبر کن.", "rank": 2}
    if score >= 70 and near_resistance_count == 0:
        return {"status": "suitable", "label": "مناسب", "reason": "امتیاز میان‌مدت قوی است؛ قیمت بالای حد خروج و دور از مقاومت نزدیک است.", "rank": 3}
    if score >= 55:
        reason = ("امتیاز مناسب است، اما مقاومت نزدیک وجود دارد؛ برای ورود صبر کن."
                  if score >= 70 and near_resistance_count > 0
                  else "شرایط متوسط است؛ برای ورود منتظر اصلاح یا تأیید روند بمان.")
        return {"status": "wait", "label": "صبر برای تأیید", "reason": reason, "rank": 2}
    return {"status": "unsuitable", "label": "فعلاً نامناسب", "reason": "امتیاز میان‌مدت برای خرید در قیمت فعلی پایین است.", "rank": 1}


def _watchlist_match_key(value: Any) -> str:
    return str(value or "").strip().casefold().replace("ي", "ی").replace("ك", "ک")


def _watchlist_asset_id(fund: dict[str, Any]) -> str:
    raw = fund.get("raw") if isinstance(fund.get("raw"), dict) else {}
    return str(raw.get("rahavard_asset_id") or fund.get("registration_no") or fund.get("symbol") or "").strip()


def _watchlist_find_fund(identifier: str) -> dict[str, Any] | None:
    fund = db.get_fund(identifier)
    if fund and not fund.get("ambiguous") and fund.get("source") == "Rahavard365":
        return fund
    needle = _watchlist_match_key(identifier)
    matches = []
    for candidate in db.funds(source="Rahavard365"):
        raw = candidate.get("raw") if isinstance(candidate.get("raw"), dict) else {}
        exact_values = {
            candidate.get("fund_key"), candidate.get("symbol"), candidate.get("registration_no"),
            candidate.get("name"), raw.get("rahavard_asset_id"), raw.get("trade_symbol"),
        }
        if any(_watchlist_match_key(value) == needle for value in exact_values if value is not None):
            matches.append(candidate)
    unique: dict[str, dict[str, Any]] = {}
    for item in matches:
        asset_id = _watchlist_asset_id(item)
        identity = asset_id or item["fund_key"]
        previous = unique.get(identity)
        if previous is None or item["fund_key"] == f"rahavard:{asset_id}":
            unique[identity] = item
    if len(unique) > 1:
        raise HTTPException(status_code=409, detail="چند صندوق با این نام پیدا شد؛ شناسه ره‌آورد را وارد کن")
    return next(iter(unique.values()), None)


_DEFAULT_WATCHLIST_SETTING = "watchlist_default_portfolio_v2"
_DEFAULT_WATCHLIST_ITEMS = [
    ("آلتون", 6000, 73837),
    ("دارونو", 3500, 34822),
    ("سینرژی", 1000, 63651),
    ("آگاس", 100, 460104),
    ("متال", 1000, 30639),
]
_LEGACY_WATCHLIST_SYMBOLS = {"سبزآبنوس", "تکپاد"}
_WATCHLIST_DISPLAY_BY_ASSET_ID = {
    "22820": "آلتون",
    "35665": "دارونو",
    "35129": "سینرژی",
    "820": "آگاس",
    "25249": "متال",
}
_DEFAULT_WATCHLIST_ASSET_ID_BY_SYMBOL = {
    symbol: asset_id for asset_id, symbol in _WATCHLIST_DISPLAY_BY_ASSET_ID.items()
}


def _ensure_default_watchlist_fund(symbol: str) -> dict[str, Any] | None:
    """Keep known default symbols resolvable when Rahavard omits them intraday."""
    asset_id = _DEFAULT_WATCHLIST_ASSET_ID_BY_SYMBOL.get(symbol)
    if not asset_id:
        return None
    fund_key = f"rahavard:{asset_id}"
    db.save_funds([{
        "fund_key": fund_key, "symbol": asset_id, "registration_no": asset_id,
        "name": symbol, "category": "قابل معامله", "category_id": "rahavard-etf",
        "market_price": None, "raw": {"rahavard_asset_id": asset_id, "trade_symbol": symbol},
    }], "Rahavard365", f"https://rahavard365.com/asset/{asset_id}")
    return db.get_fund(fund_key)



def _seed_default_watchlist() -> None:
    settings = db.get_settings()
    if settings.get(_DEFAULT_WATCHLIST_SETTING):
        # A morning refresh can temporarily omit a fund from Rahavard's live list.
        # Repair a manual placeholder as soon as that fund appears again, while
        # preserving the user's saved units and break-even price.
        records = db.watchlist_items()
        for symbol, units, break_even_price in _DEFAULT_WATCHLIST_ITEMS:
            manual_key = f"manual:{symbol}"
            existing = next((row for row in records if row["fund_key"] == manual_key), None)
            if not existing:
                continue
            try:
                fund = _watchlist_find_fund(symbol)
            except HTTPException:
                fund = None
            if fund is None:
                fund = _ensure_default_watchlist_fund(symbol)
            if not fund:
                continue
            target_key = fund["fund_key"]
            if any(row["fund_key"] == target_key for row in records):
                db.remove_watchlist_item(manual_key)
                continue
            record = db.add_watchlist_item(target_key)
            db.update_watchlist_item(target_key, {
                "units": existing.get("units") if existing.get("units") is not None else units,
                "break_even_price": existing.get("break_even_price") if existing.get("break_even_price") is not None else break_even_price,
            })
            db.remove_watchlist_item(manual_key)
        return
    records = db.watchlist_items()
    desired_keys: set[str] = set()
    for symbol, units, break_even_price in _DEFAULT_WATCHLIST_ITEMS:
        try:
            fund = _watchlist_find_fund(symbol)
        except HTTPException:
            fund = None
        if fund is None:
            fund = _ensure_default_watchlist_fund(symbol)
        target_key = fund["fund_key"] if fund else f"manual:{symbol}"
        target_asset_id = _watchlist_asset_id(fund) if fund else None
        desired_keys.add(target_key)

        existing = None
        for record in records:
            if record["fund_key"] in {target_key, f"manual:{symbol}"}:
                existing = record
                break
            if target_asset_id:
                saved_fund = db.get_fund(record["fund_key"])
                if saved_fund and _watchlist_asset_id(saved_fund) == target_asset_id:
                    existing = record
                    break
        if existing and existing["fund_key"] != target_key:
            old_key = existing["fund_key"]
            record = db.add_watchlist_item(target_key)
            db.update_watchlist_item(target_key, {
                "units": units if existing.get("units") is None else existing.get("units"),
                "break_even_price": break_even_price if existing.get("break_even_price") is None else existing.get("break_even_price"),
            })
            db.remove_watchlist_item(old_key)
            existing = {**record, "fund_key": target_key}
            records = [row for row in records if row["fund_key"] != old_key]
            records.append(existing)
        elif existing:
            db.update_watchlist_item(existing["fund_key"], {"units": units, "break_even_price": break_even_price})
        else:
            record = db.add_watchlist_item(target_key)
            db.update_watchlist_item(target_key, {"units": units, "break_even_price": break_even_price})
            records.append({**record, "units": units, "break_even_price": break_even_price})

    # Remove the two rows that were seeded by the previous default portfolio.
    for record in list(records):
        if record["fund_key"] in desired_keys:
            continue
        saved_fund = db.get_fund(record["fund_key"])
        raw = saved_fund.get("raw") if isinstance(saved_fund, dict) else {}
        saved_symbols = {
            record["fund_key"].removeprefix("manual:"),
            saved_fund.get("symbol") if saved_fund else None,
            saved_fund.get("name") if saved_fund else None,
            raw.get("trade_symbol"),
        }
        if _LEGACY_WATCHLIST_SYMBOLS.intersection(saved_symbols):
            db.remove_watchlist_item(record["fund_key"])

    db.save_setting(_DEFAULT_WATCHLIST_SETTING, "1")


def _watchlist_levels(indicator_data: dict[str, Any] | None,
                      price: float | None) -> dict[str, list[dict[str, Any]]]:
    if not indicator_data or price is None:
        return {"supports": [], "resistances": []}
    pivots = indicator_data.get("pivots") if isinstance(indicator_data.get("pivots"), list) else []
    supports: list[dict[str, Any]] = []
    resistances: list[dict[str, Any]] = []
    for item in pivots:
        if not isinstance(item, dict):
            continue
        method = str(item.get("short_name_en") or item.get("name_en") or "Pivot")
        parts = item.get("value") if isinstance(item.get("value"), list) else []
        for part in parts:
            if not isinstance(part, dict):
                continue
            label = str(part.get("name") or "").strip().casefold()
            if label not in {"r1", "r2", "r3", "r4", "s1", "s2", "s3", "s4"}:
                continue
            level = _watchlist_number(part.get("value"))
            if level is None or level <= 0:
                continue
            entry = {"price": level, "label": f"{method} · {label.upper()}"}
            (supports if level < price else resistances).append(entry)

    def nearest(values: list[dict[str, Any]], reverse: bool) -> list[dict[str, Any]]:
        values.sort(key=lambda row: row["price"], reverse=reverse)
        distinct: list[dict[str, Any]] = []
        for row in values:
            if any(abs(row["price"] - old["price"]) / max(old["price"], 1) < 0.001 for old in distinct):
                continue
            distinct.append(row)
            if len(distinct) == 3:
                break
        return distinct

    return {"supports": nearest(supports, True), "resistances": nearest(resistances, False)}


@app.get("/api/watchlist")
async def get_watchlist():
    _seed_default_watchlist()
    records = db.watchlist_items()
    snapshots = db.fund_indicator_snapshots()
    semaphore = asyncio.Semaphore(5)

    async def load_item(record: dict[str, Any]) -> dict[str, Any]:
        fund = db.get_fund(record["fund_key"])
        if not fund or fund.get("source") != "Rahavard365":
            is_custom_symbol = str(record["fund_key"]).startswith("manual:")
            custom_symbol = str(record["fund_key"])[len("manual:"):] if is_custom_symbol else ""
            display_symbol = custom_symbol or record["fund_key"]
            return {**record, "name": display_symbol, "symbol": display_symbol,
                    "is_custom_symbol": is_custom_symbol, "price": None,
                    "supports": [], "resistances": [],
                    "midterm_outlook": "نماد سفارشی · دادهٔ قیمت موجود نیست" if is_custom_symbol else "صندوق در فهرست ره‌آورد پیدا نشد",
                    "overall_status": "داده در دسترس نیست", "technical_score": None,
                    "medium_term_exit_price": None, "distance_to_exit": None,
                    "holding_decision": {"label": "داده کافی نیست", "tone": "unknown", "reason": "قیمت و تحلیل تکنیکال این نماد در دسترس نیست."},
                    "add_position_decision": {"label": "فعلاً اضافه نکن", "tone": "neutral", "reason": "تا دریافت قیمت و تحلیل معتبر صبر کن."},
                    "explanation": "برای این نماد، نمایه و دادهٔ تحلیلی در فهرست فعلی صندوق‌های ره‌آورد موجود نیست."}
        async with semaphore:
            profile_result, indicator_result = await asyncio.gather(
                fetch_rahavard_fund_profile(record["fund_key"]),
                fetch_fund_indicators(record["fund_key"]),
                return_exceptions=True,
            )
        profile = profile_result if isinstance(profile_result, dict) else {}
        asset = profile.get("asset") if isinstance(profile.get("asset"), dict) else {}
        trade = profile.get("last_trade") if isinstance(profile.get("last_trade"), dict) else {}
        raw = fund.get("raw") if isinstance(fund.get("raw"), dict) else {}
        live_price = _watchlist_number(trade.get("real_close_price"))
        if live_price is not None and live_price <= 0:
            live_price = None
        live_timestamp = trade.get("end_date_time")
        live_price_is_today = False
        if live_price is not None and live_timestamp:
            try:
                iran_tz = timezone(timedelta(hours=3, minutes=30))
                observed = datetime.fromisoformat(str(live_timestamp).replace("Z", "+00:00"))
                if observed.tzinfo is None:
                    observed = observed.replace(tzinfo=iran_tz)
                live_price_is_today = observed.astimezone(iran_tz).date() == datetime.now(iran_tz).date()
            except (TypeError, ValueError, OverflowError):
                live_price_is_today = False
        cached_history = db.history(record["fund_key"], 1, source="Rahavard365")
        cached_price = _watchlist_number(fund.get("market_price"))
        if cached_price is None and not cached_history:
            try:
                cached_history = await fetch_fund_price_history(record["fund_key"])
            except Exception:
                cached_history = db.history(record["fund_key"], 1, source="Rahavard365")
        if cached_price is None and cached_history:
            cached_price = _watchlist_number(cached_history[-1].get("close"))
        price = live_price or cached_price
        price_is_cached = price is not None and not live_price_is_today
        price_note = ("قیمت پایانی آخرین روز معاملاتی؛ با ثبت معامله جدید به‌روز می‌شود"
                      if live_price is not None and not live_price_is_today
                      else "آخرین قیمت ذخیره‌شده قبل از شروع معاملات"
                      if live_price is None and cached_price is not None
                      else "قیمت جاری ره‌آورد۳۶۵")
        change_ratio = _watchlist_number(trade.get("real_close_price_change_percent"))
        daily_return = change_ratio * 100 if change_ratio is not None else fund.get("daily_return")
        indicator_data = indicator_result if isinstance(indicator_result, dict) else None
        cached = snapshots.get(record["fund_key"])
        if indicator_data is None and cached:
            indicator_data = cached.get("data")
        stamp = (trade.get("end_date_time") if live_price is not None else None) \
            or ((cached_history[-1].get("timestamp") if cached_history else None)) \
            or (cached or {}).get("data_timestamp") or fund.get("data_timestamp")
        analysis_result = analyze_rahavard(asset.get("trade_symbol") or fund["symbol"], indicator_data, stamp, price) if indicator_data else None
        levels = _watchlist_levels(indicator_data, price)
        signal = analysis_result.get("signal") if analysis_result else None
        trend = analysis_result.get("trend") if analysis_result else None
        medium_term_exit_price = _watchlist_number(analysis_result.get("medium_term_exit_price")) if analysis_result else None
        distance_value = price - medium_term_exit_price if price is not None and medium_term_exit_price is not None else None
        distance_pct = distance_value / price * 100 if distance_value is not None and price else None
        break_even = _watchlist_number(record.get("break_even_price"))
        units = _watchlist_number(record.get("units"))
        profit_per_unit = price - break_even if price is not None and break_even is not None else None
        profit_pct = profit_per_unit / break_even * 100 if profit_per_unit is not None and break_even else None
        profit_total = profit_per_unit * units if profit_per_unit is not None and units is not None else None
        if signal == "buy":
            outlook, tone = "تمایل مثبت · نگهداری تحت نظر", "positive"
        elif signal == "sell":
            outlook, tone = "تمایل منفی · بررسی فروش", "negative"
        elif signal == "hold":
            outlook, tone = "خنثی · نیازمند بررسی بیشتر", "neutral"
        else:
            outlook, tone = "داده تکنیکال کافی نیست", "unknown"
        signal_fa = {"buy": "مثبت", "sell": "منفی", "hold": "خنثی"}.get(signal, "نامشخص")
        technical_score = _watchlist_number(analysis_result.get("technical_score")) if analysis_result else None
        score_breakdown = analysis_result.get("score_breakdown") if analysis_result and isinstance(analysis_result.get("score_breakdown"), dict) else {}
        near_resistance_count = _watchlist_number(score_breakdown.get("near_resistance_count"))
        rsi = _watchlist_number(score_breakdown.get("rsi"))
        if price is None or medium_term_exit_price is None or technical_score is None:
            holding_decision = {"label": "داده کافی نیست", "tone": "unknown", "reason": "برای تعیین نگهداری یا خروج، قیمت و تحلیل کامل لازم است."}
            add_position_decision = {"label": "فعلاً اضافه نکن", "tone": "neutral", "reason": "تا کامل‌شدن داده‌ها برای افزایش حجم صبر کن."}
        elif (units or 0) <= 0:
            holding_decision = {"label": "موقعیتی ثبت نشده", "tone": "neutral", "reason": "برای این نماد تعداد واحدی در دیده‌بان ثبت نشده است."}
            if price <= medium_term_exit_price:
                add_position_decision = {"label": "خیر · حد خروج شکسته", "tone": "negative", "reason": "قیمت به حد خروج میان‌مدت رسیده یا پایین‌تر است."}
            elif rsi is not None and rsi >= 70:
                add_position_decision = {"label": "صبر · RSI بالاست", "tone": "neutral", "reason": f"RSI(14) برابر {rsi:.1f} است؛ برای ورود تازه تا کاهش خریدزدگی صبر کن."}
            elif technical_score >= 70 and (near_resistance_count or 0) == 0:
                add_position_decision = {"label": "بله · پله‌ای", "tone": "positive", "reason": "امتیاز میان‌مدت مناسب است و مقاومت نزدیکی ثبت نشده."}
            elif technical_score >= 55:
                add_position_decision = {"label": "صبر برای تأیید", "tone": "neutral", "reason": "برای ورود، تأیید روند یا فاصله‌گرفتن از مقاومت لازم است."}
            else:
                add_position_decision = {"label": "خیر · فعلاً", "tone": "negative", "reason": "امتیاز میان‌مدت برای افزودن موقعیت کافی نیست."}
        elif price <= medium_term_exit_price:
            holding_decision = {"label": "فروش / کاهش", "tone": "negative", "reason": "قیمت به حد خروج میان‌مدت رسیده یا پایین‌تر است؛ طبق قاعدهٔ خروج، موقعیت را کاهش بده."}
            add_position_decision = {"label": "خیر · حد خروج شکسته", "tone": "negative", "reason": "تا بازپس‌گیری و تثبیت بالای حد خروج، حجم اضافه نکن."}
        elif technical_score < 40:
            holding_decision = {"label": "کاهش ریسک", "tone": "negative", "reason": "امتیاز تکنیکال میان‌مدت ضعیف است؛ نگهداری کامل ریسک بالاتری دارد."}
            add_position_decision = {"label": "خیر · فعلاً", "tone": "negative", "reason": "امتیاز میان‌مدت ضعیف است."}
        else:
            holding_decision = {"label": "نگهداری", "tone": "positive", "reason": "قیمت بالای حد خروج میان‌مدت است؛ شکست این سطح را زیر نظر بگیر."}
            if rsi is not None and rsi >= 70:
                add_position_decision = {"label": "صبر · RSI بالاست", "tone": "neutral", "reason": f"RSI(14) برابر {rsi:.1f} است؛ با وجود حفظ موقعیت، برای افزایش حجم تا کاهش خریدزدگی صبر کن."}
            elif technical_score >= 70 and (near_resistance_count or 0) == 0:
                add_position_decision = {"label": "بله · پله‌ای", "tone": "positive", "reason": "امتیاز مناسب است و مقاومت نزدیکی ثبت نشده؛ خرید را مرحله‌ای انجام بده."}
            elif technical_score >= 55:
                add_position_decision = {"label": "صبر برای تأیید", "tone": "neutral", "reason": "برای افزایش حجم، تأیید روند یا اصلاح مناسب‌تر لازم است."}
            else:
                add_position_decision = {"label": "خیر · فعلاً", "tone": "negative", "reason": "امتیاز میان‌مدت برای افزایش حجم کافی نیست."}
        asset_id = str(raw.get("rahavard_asset_id") or fund.get("registration_no") or fund["symbol"])
        display_symbol = _WATCHLIST_DISPLAY_BY_ASSET_ID.get(asset_id) or asset.get("trade_symbol") or fund["symbol"]
        return {
            **record,
            "name": display_symbol,
            "symbol": display_symbol,
            "fund_name": asset.get("name") or fund["name"],
            "rahavard_asset_id": asset_id,
            "price": price,
            "price_is_cached": price_is_cached,
            "price_note": price_note,
            "daily_return": daily_return,
            "data_timestamp": stamp,
            "supports": levels["supports"],
            "resistances": levels["resistances"],
            "profit": {"per_unit": profit_per_unit, "pct": profit_pct, "total": profit_total},
            "signal": signal,
            "signal_fa": signal_fa,
            "trend": trend,
            "technical_score": technical_score,
            "medium_term_exit_price": medium_term_exit_price,
            "distance_to_exit": {"value": distance_value, "pct": distance_pct} if distance_value is not None else None,
            "holding_decision": holding_decision,
            "add_position_decision": add_position_decision,
            "midterm_outlook": outlook,
            "outlook_tone": tone,
            "overall_status": analysis_result.get("explanation") if analysis_result else "اندیکاتورهای ره‌آورد در دسترس نیستند.",
            "source": "Rahavard365",
        }

    items = await asyncio.gather(*(load_item(record) for record in records))
    default_order = {symbol: index for index, (symbol, _units, _price) in enumerate(_DEFAULT_WATCHLIST_ITEMS)}
    items.sort(key=lambda item: (default_order.get(item.get("symbol"), len(default_order)), str(item.get("fund_key", ""))))
    total_units = sum(_watchlist_number(item.get("units")) or 0 for item in items)
    positions = [item for item in items if (_watchlist_number(item.get("units")) or 0) > 0]
    has_cost = bool(positions) and all(_watchlist_number(item.get("break_even_price")) is not None for item in positions)
    has_market_value = bool(positions) and all(_watchlist_number(item.get("price")) is not None for item in positions)
    cost_basis = (sum(_watchlist_number(item.get("units")) * _watchlist_number(item.get("break_even_price"))
                       for item in positions) if has_cost else None)
    market_value = (sum(_watchlist_number(item.get("units")) * _watchlist_number(item.get("price"))
                        for item in positions) if has_market_value else None)
    pnl = market_value - cost_basis if has_cost and has_market_value else None
    totals = {
        "units": total_units,
        "cost_basis": cost_basis,
        "market_value": market_value,
        "pnl": pnl,
        "pnl_pct": (pnl / cost_basis * 100) if pnl is not None and cost_basis else None,
    }
    return {"items": items, "count": len(records), "source": "Rahavard365", "totals": totals}


@app.post("/api/watchlist")
def add_watchlist_item(data: WatchlistAddInput):
    fund = _watchlist_find_fund(data.symbol)
    if not fund or fund.get("source") != "Rahavard365":
        raise HTTPException(status_code=404, detail="صندوقی با این شناسه در فهرست ره‌آورد پیدا نشد")
    record = None
    for existing in db.watchlist_items():
        saved_fund = db.get_fund(existing["fund_key"])
        if saved_fund and _watchlist_asset_id(saved_fund) == _watchlist_asset_id(fund):
            record = existing
            break
    existed = record is not None
    if record is None:
        record = db.add_watchlist_item(fund["fund_key"])
    return {"item": record, "fund": {"name": fund["name"], "symbol": fund["symbol"]},
            "created": not existed}


@app.put("/api/watchlist/{fund_key}")
def update_watchlist_item(fund_key: str, data: WatchlistUpdateInput):
    if not any(row["fund_key"] == fund_key for row in db.watchlist_items()):
        raise HTTPException(status_code=404, detail="این صندوق در دیده‌بان نیست")
    fields = data.model_dump(exclude_unset=True) if hasattr(data, "model_dump") else data.dict(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=422, detail="مقداری برای ذخیره ارسال نشده است")
    if any(value is not None and not math.isfinite(value) for value in fields.values()):
        raise HTTPException(status_code=422, detail="مقدار باید یک عدد معتبر و مثبت باشد")
    updated = db.update_watchlist_item(fund_key, fields)
    if not updated:
        raise HTTPException(status_code=404, detail="این صندوق در دیده‌بان نیست")
    return {"item": updated}


@app.delete("/api/watchlist/{fund_key}")
def delete_watchlist_item(fund_key: str):
    if not db.remove_watchlist_item(fund_key):
        raise HTTPException(status_code=404, detail="این صندوق در دیده‌بان نیست")
    return {"deleted": True, "fund_key": fund_key}


@app.get("/api/funds/{symbol}")
async def fund_detail(symbol: str):
    fund = _fund_or_error(symbol)
    fund_key = fund["fund_key"]
    profile_result, bars_result, indicators_result = await asyncio.gather(
        fetch_rahavard_fund_profile(fund_key),
        fetch_fund_price_history(fund_key),
        fetch_fund_indicators(fund_key),
        return_exceptions=True,
    )
    profile = profile_result if isinstance(profile_result, dict) else None
    bars = bars_result if isinstance(bars_result, list) else db.history(fund_key, 5000, source="Rahavard365")
    if isinstance(indicators_result, dict):
        indicator_data = indicators_result
    else:
        cached = db.fund_indicator_snapshots().get(fund_key)
        indicator_data = cached.get("data") if cached else None
    nav = db.fund_nav_history(fund_key)
    fund = dict(fund)
    fund["rahavard_asset_id"] = (fund.get("raw") or {}).get("rahavard_asset_id") or fund["registration_no"]
    if profile:
        asset = profile.get("asset") or {}
        spec = profile.get("fund_specification") or {}
        category = asset.get("category") or {}
        last_trade = profile.get("last_trade") or {}
        values = profile.get("fund_values") or []
        latest_nav = next((row for row in values if row.get("date")), {})
        positive_navs = [row for row in values if (row.get("nav") or 0) > 0]
        aum_row = positive_navs[0] if positive_navs else latest_nav
        display_name = lambda value: value.get("name") if isinstance(value, dict) else value
        def number(value):
            try:
                parsed = float(value)
                return parsed if parsed == parsed and abs(parsed) != float("inf") else None
            except (TypeError, ValueError):
                return None
        fund.update({
            "name": asset.get("name") or fund["name"],
            "display_symbol": asset.get("trade_symbol") or fund["symbol"],
            "category": display_name(category) or fund.get("category"),
            "manager": display_name(spec.get("manager")),
            "custodian": display_name(spec.get("custodian")),
            "market_maker": display_name(spec.get("market_maker")),
            "start_date": spec.get("inception_date"),
            "market_price": number(last_trade.get("real_close_price")) or fund.get("market_price"),
            "volume": number(last_trade.get("volume")) or fund.get("volume"),
            "value": number(last_trade.get("value")) or fund.get("value"),
            "trades": number(last_trade.get("trade_count")),
            "daily_return": (number(last_trade.get("real_close_price_change_percent")) * 100
                             if number(last_trade.get("real_close_price_change_percent")) is not None
                             else fund.get("daily_return")),
            "data_timestamp": last_trade.get("end_date_time") or fund.get("data_timestamp"),
        })
        fund["nav"] = next((number(latest_nav.get(key)) for key in ("statistical_price", "redemption_price", "bid_price")
                            if number(latest_nav.get(key)) is not None), fund.get("nav"))
        fund["aum"] = number(aum_row.get("nav")) or fund.get("aum")
        if fund.get("market_price") and fund.get("nav"):
            fund["nav_premium_pct"] = (fund["market_price"] / fund["nav"] - 1) * 100
    fund["price_is_cached"] = False
    if fund.get("market_price") is not None and fund.get("data_timestamp"):
        try:
            iran_tz = timezone(timedelta(hours=3, minutes=30))
            observed = datetime.fromisoformat(str(fund["data_timestamp"]).replace("Z", "+00:00"))
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=iran_tz)
            fund["price_is_cached"] = observed.astimezone(iran_tz).date() != datetime.now(iran_tz).date()
        except (TypeError, ValueError, OverflowError):
            fund["price_is_cached"] = False
    if not fund.get("market_price") and bars:
        fund["market_price"] = bars[-1].get("close")
        fund["data_timestamp"] = bars[-1].get("timestamp") or fund.get("data_timestamp")
        fund["price_is_cached"] = fund["market_price"] is not None
    if fund.get("price_is_cached"):
        fund["price_note"] = "آخرین قیمت پایانی ذخیره‌شده؛ با ثبت معامله جدید به‌روز می‌شود"
    analysis_result = analyze_rahavard(fund.get("display_symbol") or fund["symbol"], indicator_data,
                                       fund.get("data_timestamp"), fund.get("market_price")) if indicator_data else None
    if analysis_result:
        analysis_result["price_is_cached"] = fund.get("price_is_cached", False)
    return {"fund": fund, "history": bars, "nav_history": nav, "portfolio": [],
            "analysis": analysis_result,
            "purchase_assessment": _fund_purchase_assessment(fund.get("market_price"), analysis_result),
            "market_data_available": bool(bars),
            "fundamentals_source": "Rahavard365", "market_price_source": "Rahavard365" if fund.get("market_price") is not None else None,
            "history_source": "Rahavard365" if bars else None}


@app.get("/api/funds/{symbol}/history")
async def fund_history(symbol: str):
    try:
        nav, price = await asyncio.gather(fetch_fund_nav_history(symbol), fetch_fund_price_history(symbol))
        return {"symbol": symbol, "nav_history": nav, "price_history": price,
                "sources": {"nav": "Rahavard365", "price": "Rahavard365"},
                "data_timestamp": {"nav": nav[-1]["timestamp"] if nav else None,
                                   "price": price[-1]["timestamp"] if price else None}}
    except SourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/funds/{symbol}/portfolio")
async def fund_portfolio(symbol: str):
    details = await fund_detail(symbol)
    return {"symbol": symbol, "portfolio": details["portfolio"], "source": "Rahavard365",
            "note": details.get("portfolio_note"),
            "data_timestamp": details["fund"].get("data_timestamp")}


@app.get("/api/funds/{symbol}/technical")
async def fund_technical(symbol: str):
    fund = _fund_or_error(symbol)
    try:
        data = await fetch_fund_indicators(fund["fund_key"])
    except SourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return analyze_rahavard(fund.get("symbol"), data, fund.get("data_timestamp"), fund.get("market_price"))


@app.get("/api/funds/{symbol}/signals")
async def fund_signals(symbol: str):
    fund = _fund_or_error(symbol)
    try:
        data = await fetch_fund_indicators(fund["fund_key"])
    except SourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    result = analyze_rahavard(fund["symbol"], data, fund.get("data_timestamp"), fund.get("market_price"))
    return {"symbol": fund["symbol"], "fund_key": fund["fund_key"], "source": "Rahavard365",
            "signal": result["signal"], "score": result["technical_score"],
            "gauges": result["site_gauges"], "indicator_notes": result["indicator_notes"],
            "explanation": result["explanation"], "scenarios": result.get("scenarios", []),
            "scenario_note": result.get("scenario_note")}


@app.get("/api/funds/{symbol}/analysis")
async def fund_analysis(symbol: str):
    fund = _fund_or_error(symbol)
    try:
        data = await fetch_fund_indicators(fund["fund_key"])
    except SourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return analyze_rahavard(fund["symbol"], data, fund.get("data_timestamp"), fund.get("market_price"))


@app.get("/api/admin")
def admin():
    health_data = health()
    return {"health": health_data, "sources": db.source_status(), "recent_logs": db.fetch_logs(),
            "scheduler": REFRESH_STATE, "database_path": str(db.path)}


class AlertInput(BaseModel):
    symbol: str = Field(min_length=1, max_length=80)
    condition: str = Field(min_length=1, max_length=80)
    threshold: float | None = None


@app.get("/api/alerts")
def alerts():
    items = db.alerts()
    for item in items:
        fund = db.get_fund(item["symbol"])
        if fund and not fund.get("ambiguous"):
            item["display_symbol"] = fund["symbol"]
            item["fund_name"] = fund["name"]
        else:
            item["display_symbol"] = item["symbol"]
    return {"items": items}


@app.post("/api/alerts")
def create_alert(data: AlertInput):
    allowed = {"price_above", "price_below", "rsi_overbought", "rsi_oversold", "volume_spike"}
    if data.condition not in allowed:
        raise HTTPException(status_code=422, detail=f"شرط مجاز: {', '.join(sorted(allowed))}")
    if data.condition in {"price_above", "price_below"} and data.threshold is None:
        raise HTTPException(status_code=422, detail="برای شرط قیمت باید آستانه وارد شود")
    fund = db.get_fund(data.symbol)
    if fund and fund.get("ambiguous"):
        matches = [{"fund_key": row["fund_key"], "name": row["name"]} for row in fund["matches"]]
        raise HTTPException(status_code=409, detail={"message": "نماد تکراری است؛ برای هشدار صندوق از fund_key استفاده کنید.", "matches": matches})
    if not fund:
        with db.connect() as conn:
            known_asset = conn.execute("SELECT 1 FROM assets WHERE symbol=?", (data.symbol,)).fetchone()
        if not known_asset:
            raise HTTPException(status_code=404, detail="نماد یا شناسه صندوق شناخته‌شده نیست")
    alert_id = db.add_alert(data.symbol, data.condition, data.threshold)
    return {"id": alert_id, "status": "created"}


@app.get("/api/settings")
def settings():
    saved = db.get_settings()
    return {"data_update_interval": _refresh_interval(),
            "max_stale_hours": MAX_STALE_HOURS,
            "theme": saved.get("theme", "dark"),
            "language": "fa-IR", "settings": saved}


class SettingInput(BaseModel):
    key: str
    value: str


@app.put("/api/settings")
def update_setting(data: SettingInput):
    allowed = {"theme", "refresh_interval_seconds"}
    if data.key not in allowed:
        raise HTTPException(status_code=422, detail="این تنظیم از رابط کاربری قابل تغییر نیست")
    if data.key == "theme" and data.value not in {"dark", "light"}:
        raise HTTPException(status_code=422, detail="مقدار تم معتبر نیست")
    if data.key == "refresh_interval_seconds":
        try:
            interval = int(data.value)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="فاصله به‌روزرسانی باید عدد باشد") from exc
        if not 60 <= interval <= 86400:
            raise HTTPException(status_code=422, detail="بازه مجاز ۶۰ تا ۸۶۴۰۰ ثانیه است")
    db.save_setting(data.key, data.value)
    if data.key == "refresh_interval_seconds" and REFRESH_WAKE is not None:
        REFRESH_WAKE.set()
    return {"saved": True, "key": data.key, "value": data.value}


@app.get("/api/export/funds.csv")
def export_funds_csv():
    items = _exclude_fixed_income_funds(db.funds(source="Rahavard365"))
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=["symbol", "name", "category", "manager", "aum", "nav", "market_price", "nav_premium_pct", "volume", "value", "data_timestamp"], extrasaction="ignore")
    writer.writeheader()
    writer.writerows(items)
    return StreamingResponse(iter(["\ufeff" + stream.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=funds.csv"})


@app.get("/api/export/funds.xlsx")
def export_funds_xlsx():
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
    except ImportError as exc:
        raise HTTPException(status_code=501, detail="برای خروجی Excel، openpyxl را نصب کنید") from exc
    items = _exclude_fixed_income_funds(db.funds(source="Rahavard365"))
    columns = [("symbol", "نماد"), ("name", "نام"), ("category", "دسته"), ("manager", "مدیر"),
               ("daily_return", "بازده روزانه"), ("weekly_return", "بازده هفتگی"),
               ("monthly_return", "بازده ماهانه"), ("three_month_return", "بازده ۳ماهه"),
               ("six_month_return", "بازده ۶ماهه"), ("one_year_return", "بازده یک‌ساله"),
               ("nav", "NAV"), ("market_price", "قیمت بازار"), ("nav_premium_pct", "فاصله NAV٪"),
               ("aum", "دارایی تحت مدیریت"), ("volume", "حجم"), ("value", "ارزش"), ("data_timestamp", "زمان داده")]
    wb = Workbook(); ws = wb.active; ws.title = "صندوق‌ها"; ws.sheet_view.rightToLeft = True
    ws.append([title for _, title in columns])
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF"); cell.fill = PatternFill("solid", fgColor="18375E")
    for item in items:
        ws.append([item.get(key) for key, _ in columns])
    for col in ws.columns:
        width = min(36, max(12, max(len(str(c.value or "")) for c in col) + 2))
        ws.column_dimensions[col[0].column_letter].width = width
    output = io.BytesIO(); wb.save(output); output.seek(0)
    return StreamingResponse(output, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": "attachment; filename=funds.xlsx"})


@app.get("/api/export/funds.json")
def export_funds_json():
    return {"exported_at": utc_now(), "source": "Rahavard365",
            "items": _exclude_fixed_income_funds(db.funds(source="Rahavard365"))}


@app.get("/api/export/analysis.json")
def export_analysis_json():
    return {symbol: analyze(symbol, _market_history(symbol)) for symbol in ["GOLD", "DXY", "USD_IR_FREE"] if _market_history(symbol, 1)}
