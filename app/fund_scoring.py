"""Four-family technical scores for short- and medium-term Rahavard ETF data.

Weights are configurable proposals from the product specification. They have
not been optimized or backtested. Unknown vendor formulas are deliberately
left out and reported as missing instead of guessed.
"""
from __future__ import annotations

import math
import re
from typing import Any

from .scoring_profiles import normalize_horizon, horizon_label
from .scoring_rules import (adx_directional_score, band_position_score,
                            ichimoku_cloud_score, inverted_linear_score,
                            macd_histogram_score, moving_average_score,
                            percent_change_score, pivot_level_score,
                            rsi_entry_score, stoch_rsi_entry_score)
from .tse_scoring import GROUP_WEIGHTS, SUBCLUSTERS, score_tse_bars

FAMILY_WEIGHTS = GROUP_WEIGHTS

FUND_TYPE_LABELS = {
    "fixed_income": "درآمد ثابت", "mixed": "مختلط", "equity": "سهامی",
    "gold": "طلا", "venture": "جسورانه", "index": "شاخصی",
    "project": "پروژه", "land": "زمین و ساختمان", "fund_of_funds": "صندوق در صندوق",
    "private": "خصوصی", "real_estate": "املاک و مستغلات", "sector": "بخشی",
    "agriculture": "کالایی کشاورزی", "commodity_receipt": "گواهی سپرده کالایی",
    "leveraged": "اهرمی", "silver": "نقره",
}

INDICATOR_WEIGHTS = {
    family: {name: weight for cluster in clusters.values()
             for name, weight in cluster["indicators"].items()}
    for family, clusters in SUBCLUSTERS.items()
}

FUND_TYPE_BY_CATEGORY_ID = {
    "255": "fixed_income", "256": "mixed", "257": "equity", "301": "gold",
    "302": "venture", "303": "index", "542": "project", "543": "land",
    "544": "fund_of_funds", "547": "private", "560": "real_estate",
    "568": "sector", "572": "agriculture", "604": "commodity_receipt",
    "612": "leveraged", "623": "silver",
}

# Provisional comparison scales, in percentage points. Expose these as config
# before tuning; they are not statistically validated thresholds.
NAV_PREMIUM_SCALE_PCT = {
    "equity": 5.0, "index": 5.0, "mixed": 5.0, "sector": 5.0,
    "leveraged": 7.0, "gold": 4.0, "silver": 5.0,
    "agriculture": 6.0, "commodity_receipt": 6.0,
    "real_estate": 10.0, "land": 10.0, "project": 10.0,
    "venture": 8.0, "fund_of_funds": 5.0, "private": 8.0,
    "fixed_income": 1.5,
}
VOLATILITY_SCALE_PCT = {
    "equity": 45.0, "index": 40.0, "mixed": 35.0, "sector": 50.0,
    "leveraged": 80.0, "gold": 45.0, "silver": 65.0,
    "agriculture": 55.0, "commodity_receipt": 50.0,
    "real_estate": 25.0, "land": 30.0, "project": 60.0,
    "venture": 70.0, "fund_of_funds": 35.0, "private": 60.0,
    "fixed_income": 12.0,
}


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return min(high, max(low, value))


def _direction_score(ratio: float | None, scale: float) -> float | None:
    if ratio is None or not math.isfinite(ratio) or scale <= 0:
        return None
    return _clamp(50.0 + 50.0 * math.tanh(ratio / scale))


def _signal_score(item: dict[str, Any] | None) -> float | None:
    if not item:
        return None
    signal = _norm(item.get("signal"))
    return {
        "strongbuy": 90.0, "buy": 75.0, "bullish": 70.0, "support": 65.0,
        "neutral": 50.0, "hold": 50.0, "highvolume": 50.0, "lowvolume": 50.0,
        "oversold": 45.0, "overbought": 30.0,
        "resistance": 35.0, "bearish": 30.0, "sell": 25.0, "strongsell": 10.0,
    }.get(signal)


def _item_values(item: dict[str, Any] | None) -> dict[str, float]:
    if not isinstance(item, dict):
        return {}
    raw = item.get("value")
    parts = raw if isinstance(raw, list) else []
    if isinstance(raw, dict):
        parts = [{"name": key, "value": value} for key, value in raw.items()]
    result: dict[str, float] = {}
    for part in parts:
        if isinstance(part, dict):
            value = _number(part.get("value"))
            raw_name = str(part.get("name") or "").strip().casefold()
            key = _norm(raw_name)
            if raw_name in {"+di", "di+", "+d.i."}:
                key = "plusdi"
            elif raw_name in {"-di", "di-", "−di", "-d.i."}:
                key = "minusdi"
            if key and value is not None:
                result[key] = value
    for key in ("previous_value", "previousValue"):
        value = _number(item.get(key))
        if value is not None:
            result["previousvalue"] = value
            break
    return result


def _value(values: dict[str, float], *names: str) -> float | None:
    for name in names:
        key = _norm(name)
        if key in values:
            return values[key]
        for present, value in values.items():
            if present.startswith(key):
                return value
    return None


def _weighted(rows: list[tuple[str, float, float]], configured_weight: float) -> dict[str, Any]:
    valid = [(name, score, weight) for name, score, weight in rows if score is not None]
    valid_weight = sum(weight for _, _, weight in valid)
    score = sum(value * weight for _, value, weight in valid) / valid_weight if valid_weight else None
    return {
        "score": round(score, 1) if score is not None else None,
        "coverage_pct": round(valid_weight / configured_weight * 100, 1) if configured_weight else 0.0,
        "available_weight_pct": round(valid_weight / configured_weight * 100, 1) if configured_weight else 0.0,
        "indicators": [
            {"key": name, "score": round(value, 1), "weight_pct": round(weight * 100, 1)}
            for name, value, weight in valid
        ],
        "missing_indicators": [],
    }


def _group_items(groups: dict[str, list[dict[str, Any]]]) -> list[tuple[str, str, dict[str, Any]]]:
    rows = []
    for group, items in groups.items():
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("short_name_en") or item.get("name_en") or "").strip()
            if name:
                rows.append((group, _norm(name), item))
    return rows


def _find(rows: list[tuple[str, str, dict[str, Any]]], name: str,
          groups: tuple[str, ...] | None = None) -> dict[str, Any] | None:
    target = _norm(name)
    aliases = {"aroon25": "arron25"}
    candidates = tuple(candidate for candidate in (target, aliases.get(target)) if candidate)
    eligible = [(key, item) for group, key, item in rows if groups is None or group in groups]
    for key, item in eligible:
        if key in candidates:
            return item
    if target.startswith("pivotpoint") or target == "ichimokucloud":
        for key, item in eligible:
            if any(key.startswith(candidate) and key[len(candidate):].isdigit() for candidate in candidates):
                return item
    return None


def _price_distance_score(item: dict[str, Any] | None, price: float | None,
                          period: int) -> float | None:
    values = _item_values(item)
    level = _value(values, "value", "ma", "average")
    if level is not None and price is not None and level > 0:
        return moving_average_score(price, level, period)
    distance = _value(values, "distance", "distance_pct", "distancepercent")
    if distance is None:
        return None
    # Rahavard distance values are ratios; explicit percentage fields are already in points.
    distance_pct = distance if _value(values, "distance_pct", "distancepercent") is not None else distance * 100.0
    limit_pct = 3.0 if period <= 20 else 5.0 if period <= 50 else 10.0
    return _clamp(50.0 + 50.0 * distance_pct / limit_pct)


def _band_position_score(item: dict[str, Any] | None, price: float | None) -> float | None:
    if not item or price is None or price <= 0:
        return None
    values = _item_values(item)
    upper, lower = _value(values, "upper"), _value(values, "lower")
    return band_position_score(price, lower, upper)


def _trend_score(rows: list[tuple[str, str, dict[str, Any]]], price: float | None,
                 weights: dict[str, float]) -> dict[str, Any]:
    items: dict[str, dict[str, Any] | None] = {"ichimoku": _find(rows, "IchimokuCloud", ("moving_averages",))}
    for key in weights:
        if key != "ichimoku":
            groups = ("moving_averages", "bands", "volatility") if key in {"bb20", "keltner16"} else ("moving_averages",)
            items[key] = _find(rows, key, groups)
    rows_scored: list[tuple[str, float, float]] = []
    for key, weight in weights.items():
        item = items.get(key)
        score = None
        if key == "ichimoku" and item:
            values = _item_values(item)
            span_a = _value(values, "senkou_span_a_formula", "senkou_span_a", "span_a")
            span_b = _value(values, "senkou_span_b_formula", "senkou_span_b", "span_b")
            score = ichimoku_cloud_score(price, span_a, span_b)
        elif item and key in {"bb20", "keltner16"}:
            score = _band_position_score(item, price)
        elif item:
            period = int("".join(character for character in key if character.isdigit()) or 0)
            score = _price_distance_score(item, price, period)
        if score is not None:
            rows_scored.append((key, score, weight))
    result = _weighted(rows_scored, sum(weights.values()))
    result["missing_indicators"] = [key for key in weights if key not in {name for name, _, _ in rows_scored}]
    return result


def _momentum_indicator_score(key: str, item: dict[str, Any] | None,
                              price: float | None,
                              history: Any = None) -> float | None:
    if not item:
        return None
    values = _item_values(item)
    if key == "macd26":
        histogram = _value(values, "histogram", "macd_histogram", "hist")
        line = _value(values, "macd")
        signal = _value(values, "signal", "signal_line")
        if histogram is None and line is not None and signal is not None:
            histogram = line - signal
        return macd_histogram_score(histogram, price)
    elif key == "adx14":
        adx = _value(values, "adx", "value")
        plus_di, minus_di = _value(values, "plus_di", "pdi"), _value(values, "minus_di", "mdi")
        return adx_directional_score(adx, plus_di, minus_di)
    elif key in {"rsi14", "mfi14"}:
        field = "rsi" if key == "rsi14" else "mfi"
        value = _value(values, field, "value")
        if value is not None:
            return rsi_entry_score(value) if key == "rsi14" else inverted_linear_score(value, 20.0, 80.0)
    elif key == "cci14":
        value = _value(values, "cci", "value")
        if value is not None:
            return _clamp(50.0 - value / 2.0)
    elif key == "aroon25":
        up, down = _value(values, "up"), _value(values, "down")
        if up is not None and down is not None:
            return _clamp(50.0 + (up - down) / 2.0)
    elif key == "ao534":
        value = _value(values, "awesome", "ao", "value")
        if value is not None and price:
            return percent_change_score(value / price * 100.0, 25.0)
    elif key == "stochrsi14":
        value = _value(values, "stochrsi", "value")
        if value is not None:
            return stoch_rsi_entry_score(value)
    elif key == "mtm6":
        change_pct = _history_return(history, 6)
        if change_pct is None:
            value = _value(values, "mtm", "value")
            previous_price = price - value if price is not None and value is not None else None
            if previous_price is not None and previous_price > 0:
                change_pct = value / previous_price * 100.0
        if change_pct is not None:
            return percent_change_score(change_pct, 10.0)
    elif key == "so14":
        value = _value(values, "k", "value")
        if value is not None:
            return inverted_linear_score(value, 20.0, 80.0)
    elif key == "wr14":
        value = _value(values, "wr", "value")
        if value is not None:
            return inverted_linear_score(value, -80.0, -20.0)
    return None


def _momentum_score(rows: list[tuple[str, str, dict[str, Any]]], price: float | None,
                    context: dict[str, Any], weights: dict[str, float]) -> dict[str, Any]:
    rows_scored = []
    indicator_items: dict[str, dict[str, Any]] = {}
    for key, weight in weights.items():
        lookup = "aroon25" if key == "aroon25" else "wr14" if key == "wr14" else key
        item = _find(rows, lookup, ("oscillators",))
        if item:
            indicator_items[key] = item
        if key == "trend":
            score = _history_trend_score(context.get("fund_history"))
        else:
            score = _momentum_indicator_score(key, item, price,
                                              context.get("fund_history"))
        if score is not None:
            rows_scored.append((key, score, weight))
    result = _weighted(rows_scored, sum(weights.values()))
    for detail in result["indicators"]:
        item = indicator_items.get(detail["key"])
        values = _item_values(item)
        if detail["key"] == "rsi14":
            detail["value"] = _value(values, "rsi", "value")
            detail["note"] = "زیر ۳۰ ناحیه خرید، ۳۰ تا ۷۰ خنثی با امتیاز کمتر نزدیک ۷۰، و بالای ۷۰ ناحیه فروش است؛ فروش‌زدگی به‌تنهایی برگشت را تأیید نمی‌کند."
        elif detail["key"] == "adx14":
            adx = _value(values, "adx", "value")
            plus_di, minus_di = _value(values, "plus_di", "pdi"), _value(values, "minus_di", "mdi")
            detail["value"] = {"ADX": adx, "+DI": plus_di, "−DI": minus_di}
            detail["note"] = "اگر ADX حداکثر ۲۰ باشد امتیاز ۵۰ است؛ بالاتر از آن، جهت و امتیاز بر پایه اختلاف +DI و −DI محاسبه می‌شود."
    available = {name for name, _, _ in rows_scored}
    result["missing_indicators"] = [key for key in weights if key not in available]
    return result


def _cluster_levels(values: list[float], price: float | None) -> list[float]:
    valid = sorted(value for value in values if math.isfinite(value) and value > 0)
    if not valid:
        return []
    tolerance = (price or valid[-1]) * 0.0075
    clusters: list[list[float]] = []
    for value in valid:
        if clusters and value - clusters[-1][-1] <= tolerance:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    return [sum(cluster) / len(cluster) for cluster in clusters]


def _pivot_score(rows: list[tuple[str, str, dict[str, Any]]], price: float | None,
                 weights: dict[str, float]) -> dict[str, Any]:
    pivot_names = {
        "classic": "pivotpointclassic", "fibonacci": "pivotpointfibonacci",
        "camarilla": "pivotpointcamarilla", "woodie": "pivotpointwoodie",
        "demark": "pivotpointdemark",
    }
    method_rows: list[tuple[str, dict[str, Any], dict[str, float]]] = []
    raw_supports: list[float] = []
    raw_resistances: list[float] = []
    for method, prefix in pivot_names.items():
        item = _find(rows, prefix, ("pivots",))
        if not item:
            continue
        values = _item_values(item)
        method_supports: list[float] = []
        method_resistances: list[float] = []
        for key, value in values.items():
            if (key.startswith("s") or key.startswith("l")) and value > 0:
                method_supports.append(value)
            elif (key.startswith("r") or key.startswith("h")) and value > 0:
                method_resistances.append(value)
        raw_supports.extend(method_supports)
        raw_resistances.extend(method_resistances)
        if _value(values, "pivot", "p") is not None or method_supports or method_resistances:
            method_rows.append((method, item, values))
    if price is None or not method_rows:
        return _weighted([], sum(weights.values())) | {"missing_indicators": list(weights)}
    supports = _cluster_levels(raw_supports, price)
    resistances = _cluster_levels(raw_resistances, price)
    below = [level for level in supports if level < price]
    above = [level for level in resistances if level > price]
    nearest_support = max(below) if below else None
    nearest_resistance = min(above) if above else None
    rows_scored = []
    for method, item, values in method_rows:
        pivot = _value(values, "pivot", "p")
        upper_key, lower_key = ("h3", "l3") if method == "camarilla" else ("r1", "s1")
        upper, lower = _value(values, upper_key), _value(values, lower_key)
        score = pivot_level_score(price, pivot, upper, lower)
        if score is not None:
            rows_scored.append((method, score, weights[method]))
    result = _weighted(rows_scored, sum(weights.values()))
    available = {name for name, _, _ in rows_scored}
    result["missing_indicators"] = [key for key in weights if key not in available]
    result["clustered_supports"] = supports
    result["clustered_resistances"] = resistances
    result["nearest_support"] = nearest_support
    result["nearest_resistance"] = nearest_resistance
    result["support_distance_pct"] = (100 * (price - nearest_support) / price) if nearest_support else None
    result["resistance_distance_pct"] = (100 * (nearest_resistance - price) / price) if nearest_resistance else None
    return result


def _history_return(bars: Any, lookback: int) -> float | None:
    if not isinstance(bars, list) or len(bars) <= lookback:
        return None
    current = _number(bars[-1].get("close")) if isinstance(bars[-1], dict) else None
    prior = _number(bars[-lookback - 1].get("close")) if isinstance(bars[-lookback - 1], dict) else None
    if current is None or prior is None or current <= 0 or prior <= 0:
        return None
    return (current / prior - 1.0) * 100.0


def _history_trend_score(bars: Any, lookback: int = 30) -> float | None:
    change_pct = _history_return(bars, lookback)
    return percent_change_score(change_pct, 5.0) if change_pct is not None else None


def _realized_volatility_pct(bars: Any, lookback: int = 20) -> float | None:
    if not isinstance(bars, list) or len(bars) < lookback + 1:
        return None
    closes = [_number(bar.get("close")) for bar in bars[-lookback - 1:] if isinstance(bar, dict)]
    if len(closes) != lookback + 1 or any(value is None or value <= 0 for value in closes):
        return None
    returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / len(returns)
    return math.sqrt(variance * 252.0) * 100.0


def _type(context: dict[str, Any]) -> str | None:
    category_id = str(context.get("category_id") or "").strip()
    if category_id in FUND_TYPE_BY_CATEGORY_ID:
        return FUND_TYPE_BY_CATEGORY_ID[category_id]
    text = " ".join(str(context.get(key) or "") for key in ("fund_type", "category", "name", "symbol")).casefold()
    patterns = (
        (("اهرم", "leveraged"), "leveraged"), (("طلا", "gold"), "gold"),
        (("نقره", "silver"), "silver"), (("کشاورزی", "agriculture"), "agriculture"),
        (("درآمد ثابت", "fixed income"), "fixed_income"),
        (("بخشی", "sector"), "sector"), (("انرژی", "energy"), "sector"),
        (("شاخصی", "index"), "index"),
        (("مختلط", "mixed"), "mixed"), (("املاک", "real estate"), "real_estate"),
        (("صندوق در صندوق", "fund of funds"), "fund_of_funds"),
        (("خصوصی", "private"), "private"), (("زمین", "land"), "land"),
        (("جسورانه", "venture"), "venture"), (("پروژه", "project"), "project"),
        (("سهامی", "سهام", "equity"), "equity"),
        (("گواهی سپرده", "مبتنی بر کالا", "commodity"), "commodity_receipt"),
    )
    for needles, result in patterns:
        if any(needle in text for needle in needles):
            return result
    return None


def resolve_fund_type(context: dict[str, Any] | None = None) -> str | None:
    """Return a known Rahavard fund type without guessing from numeric symbols."""
    return _type(context or {})


def _entry_quality_score(rows: list[tuple[str, str, dict[str, Any]]], price: float | None,
                         context: dict[str, Any]) -> dict[str, Any]:
    kind = _type(context)
    weights = {"bb20": 0.30, "keltner16": 0.30, "atr_or_realized": 0.20,
               "ema50_distance": 0.20}
    rows_scored = []
    for key in ("bb20", "keltner16"):
        item = _find(rows, key, ("moving_averages", "bands"))
        values = _item_values(item)
        upper, lower = _value(values, "upper"), _value(values, "lower")
        if price is None or upper is None or lower is None or upper <= lower:
            continue
        score = band_position_score(price, lower, upper)
        if score is not None:
            rows_scored.append((key, score, weights[key]))
    atr_item = _find(rows, "atr14")
    atr_values = _item_values(atr_item)
    atr = _value(atr_values, "atr", "value")
    vol_pct = _number(context.get("realized_volatility_pct"))
    if vol_pct is None:
        vol_pct = _realized_volatility_pct(context.get("fund_history"))
    volatility = None
    if atr is not None and price and price > 0:
        volatility = atr / price * 100.0
    elif vol_pct is not None:
        volatility = vol_pct
    if volatility is not None and kind in VOLATILITY_SCALE_PCT:
        scale = VOLATILITY_SCALE_PCT[kind]
        score = _clamp(100.0 * math.exp(-volatility / max(scale, 1e-9)))
        rows_scored.append(("atr_or_realized", score, weights["atr_or_realized"]))
    ema50 = _find(rows, "ema50", ("moving_averages",))
    distance = _value(_item_values(ema50), "distance")
    if distance is None and ema50 and price:
        level = _value(_item_values(ema50), "value", "ma", "average")
        if level and level > 0:
            distance = price / level - 1.0
    # This is an initial, configurable distance scale pending historical tests.
    ema_distance_scale = {"leveraged": 0.10, "gold": 0.06, "silver": 0.08,
                          "real_estate": 0.08}.get(kind, 0.06)
    if distance is not None:
        score = 100.0 * math.exp(-abs(distance) / ema_distance_scale)
        rows_scored.append(("ema50_distance", _clamp(score), weights["ema50_distance"]))
    result = _weighted(rows_scored, sum(weights.values()))
    available = {name for name, _, _ in rows_scored}
    result["missing_indicators"] = [key for key in weights if key not in available]
    result["realized_volatility_pct"] = round(volatility, 2) if volatility is not None else None
    result["fund_type"] = kind
    return result


def _nav_score(price: float | None, context: dict[str, Any]) -> dict[str, Any]:
    weights = {"nav_premium": 1.0}
    kind = _type(context)
    nav = _number(context.get("nav"))
    nav_timestamp = context.get("nav_timestamp")
    premium = _number(context.get("nav_premium_pct"))
    if premium is None and price is not None and nav is not None and nav > 0:
        premium = (price / nav - 1.0) * 100.0
    price_timestamp = context.get("price_timestamp")
    nav_lag_days = _date_distance_days(nav_timestamp, price_timestamp)
    # Compare NAV freshness with the observed market price; source timestamps
    # may use either Gregorian or Jalali dates, so only their shared date fields
    # are compared here.
    if (premium is None or nav_lag_days is None or nav_lag_days > 10
            or kind not in NAV_PREMIUM_SCALE_PCT):
        return _weighted([], sum(weights.values())) | {
            "missing_indicators": ["nav_premium"],
            "premium_pct": round(premium, 3) if premium is not None else None,
            "fund_type": kind,
            "nav_age_days": nav_lag_days,
            "reason": "NAV تازه، تاریخ قیمت یا نوع صندوق برای امتیازدهی معتبر موجود نیست",
        }
    scale = NAV_PREMIUM_SCALE_PCT[kind]
    score = _direction_score(-premium / 100.0, scale / 100.0)
    result = _weighted([("nav_premium", score, weights["nav_premium"])], sum(weights.values()))
    result.update({"premium_pct": round(premium, 3), "fund_type": kind,
                   "nav_timestamp": nav_timestamp, "nav_age_days": nav_lag_days})
    return result


def _date_distance_days(left: Any, right: Any) -> int | None:
    def ordinal(value: Any) -> int | None:
        match = re.match(r"^\s*(\d{4})[-/](\d{1,2})[-/](\d{1,2})", str(value or ""))
        if not match:
            return None
        year, month, day = (int(part) for part in match.groups())
        if not 1 <= month <= 12 or not 1 <= day <= 31:
            return None
        days_before_month = (month - 1) * 31 if month <= 6 else 6 * 31 + (month - 7) * 30
        return year * 365 + days_before_month + day

    left_day, right_day = ordinal(left), ordinal(right)
    return abs(left_day - right_day) if left_day is not None and right_day is not None else None


def score_fund_model(groups: dict[str, list[dict[str, Any]]], price: float | None,
                     context: dict[str, Any] | None = None,
                     horizon: str = "long", dashboard_model: bool = False) -> dict[str, Any]:
    """Score a fund's OHLCV chart with the workbook-defined scoring model."""
    context = context or {}
    horizon = normalize_horizon(horizon)
    kind = _type(context)
    rows = _group_items(groups)
    engine = score_tse_bars(
        context.get("fund_history"),
        horizon=horizon,
        trend_value=context.get("trend_value"),
        trend_schema_type=context.get("trend_schema_type"),
        trading_status=context.get("trading_status"),
    )
    family = engine["family_scores"]
    family_weights = {key: float(value) / 100.0
                      for key, value in engine["score_weights"].items()}
    indicator_weights = engine["indicator_weights"]
    model_profile = f"{horizon}_update_4_indicators"
    entry_quality = _entry_quality_score(rows, price, context)
    nav_assessment = _nav_score(price, context)

    final_score = engine["technical_score"]
    available_family_weight = float(engine["available_family_weight_pct"]) / 100.0
    effective_family_weights = engine["effective_score_weights"]
    coverage = engine["data_coverage_pct"]
    band = engine["score_band"]

    volatility = _number(entry_quality.get("realized_volatility_pct"))
    risk_scale = VOLATILITY_SCALE_PCT.get(kind or "", 45.0)
    risk_score = min(100.0, volatility / risk_scale * 60.0) if volatility is not None else None
    if risk_score is not None and kind == "leveraged":
        risk_score = min(100.0, risk_score + 15.0)
    risk_level = None
    if risk_score is not None:
        risk_level = "high" if risk_score >= 70 else "elevated" if risk_score >= 50 else "medium" if risk_score >= 30 else "low"

    diagnostics = []
    for family_key, result in family.items():
        for indicator in result.get("missing_indicators", []):
            diagnostics.append({"family": family_key, "indicator": indicator, "status": "missing"})
        for indicator in result.get("unverified_indicators", []):
            diagnostics.append({"family": family_key, "indicator": indicator, "status": "formula_unverified"})
    scored_families = [(key, value["score"]) for key, value in family.items()
                       if value.get("score") is not None]
    top_positive = max(scored_families, key=lambda row: row[1]) if scored_families else None
    top_negative = min(scored_families, key=lambda row: row[1]) if scored_families else None
    return {
        "technical_score": round(final_score, 1) if final_score is not None else None,
        "score_method": (f"dashboard_rahavard_excel_weighted_update4_{horizon}"
                          if dashboard_model else
                          f"fund_rahavard_excel_weighted_update4_{horizon}"),
        "score_weights": {key: round(weight * 100) for key, weight in family_weights.items()},
        "indicator_weights": {
            family_key: {key: round(float(weight), 1) for key, weight in weights.items()}
            for family_key, weights in indicator_weights.items()
        },
        "effective_score_weights": effective_family_weights,
        "fund_type": kind,
        "fund_type_label": FUND_TYPE_LABELS.get(kind, "نامشخص"),
        "model_profile": model_profile,
        "investment_horizon": horizon,
        "investment_horizon_label": horizon_label(horizon),
        "family_scores": family,
        "data_coverage_pct": round(coverage, 1),
        "available_family_weight_pct": round(available_family_weight * 100, 1),
        "score_band": band,
        "decision": engine["decision"],
        "decision_label": engine["decision_label"],
        "confidence_level": engine["confidence_level"],
        "confluence_pct": engine["confluence_pct"],
        "score_validation": "update_4_indicator_model_unbacktested",
        "confidence": engine["confidence"],
        "inter_group_dispersion": engine["inter_group_dispersion"],
        "damping_factor": engine["damping_factor"],
        "raw_technical_score": engine["raw_score"],
        "signal": engine["signal"],
        "risk_rank": {"score": round(risk_score, 1) if risk_score is not None else None,
                      "level": risk_level,
                      "basis": "annualized_20d_realized_volatility_with_type_specific_scale",
                      "fund_type": kind, "type_adjusted": kind in VOLATILITY_SCALE_PCT},
        "nav_assessment": nav_assessment,
        "entry_quality": entry_quality,
        "top_factors": {
            "positive": ({"family": top_positive[0], "score": round(top_positive[1], 1)}
                          if top_positive and math.floor(top_positive[1] + 0.5) >= 70 else None),
            "negative": ({"family": top_negative[0], "score": round(top_negative[1], 1)}
                          if top_negative and math.floor(top_negative[1] + 0.5) <= 40 else None),
        },
        "missing_data": diagnostics,
        "valid_groups": engine["valid_groups"],
        "observations": engine["observations"],
        "score_change_5d": None,
        "score_change_20d": None,
    }
