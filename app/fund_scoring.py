"""Initial six-family, medium-term technical score for Rahavard ETF data.

Weights are configurable proposals from the product specification. They have
not been optimized or backtested. Unknown vendor formulas are deliberately
left out and reported as missing instead of guessed.
"""
from __future__ import annotations

import math
import re
from typing import Any


FAMILY_WEIGHTS = {
    "trend_structure": 0.40,
    "momentum": 0.20,
    "volume_confirmation": 0.15,
    "support_resistance": 0.10,
    "entry_quality": 0.10,
    "nav_pricing": 0.05,
}

# Fixed-income ETFs have different return and risk drivers. Keep the same
# six explainable families, but reduce stock-oscillator influence and give
# liquidity, realized volatility, and fresh NAV more weight. These rounded
# weights proportionally redistribute the removed relative-strength weight.
FAMILY_WEIGHTS_BY_TYPE = {
    "fixed_income": {
        "trend_structure": 0.24, "momentum": 0.06, "volume_confirmation": 0.23,
        "support_resistance": 0.06, "entry_quality": 0.17, "nav_pricing": 0.24,
    },
}

FIXED_INCOME_VOLUME_WEIGHTS = {
    "obv20": 0.20, "rv90": 0.20, "rv30": 0.15, "rv15": 0.10,
    "liquidity_peer": 0.35,
}

FUND_TYPE_LABELS = {
    "fixed_income": "درآمد ثابت", "mixed": "مختلط", "equity": "سهامی",
    "gold": "طلا", "venture": "جسورانه", "index": "شاخصی",
    "project": "پروژه", "land": "زمین و ساختمان", "fund_of_funds": "صندوق در صندوق",
    "private": "خصوصی", "real_estate": "املاک و مستغلات", "sector": "بخشی",
    "agriculture": "کالایی کشاورزی", "commodity_receipt": "گواهی سپرده کالایی",
    "leveraged": "اهرمی", "silver": "نقره",
}

INDICATOR_WEIGHTS = {
    "trend_structure": {
        "ichimoku": 0.25, "ema20": 0.15, "ema50": 0.15, "ema100": 0.12,
        "ema30": 0.08, "sma50": 0.07, "sma100": 0.05, "sma30": 0.04,
        "sma20": 0.03, "ema10": 0.02, "ema5": 0.01, "sma10": 0.01,
        "sma5": 0.02,
    },
    "momentum": {
        "macd26": 0.15, "adx14": 0.15, "rsi14": 0.12, "mfi14": 0.10,
        "cci14": 0.08, "aroon25": 0.08, "ao534": 0.07, "stochrsi14": 0.06,
        "mtm6": 0.05, "so14": 0.05, "trend": 0.05, "wr14": 0.04,
    },
    "volume_confirmation": {
        "obv20": 0.25, "vmacd26": 0.20, "vrsi14": 0.15, "rv90": 0.15,
        "rv30": 0.10, "rv15": 0.08, "sm15": 0.07,
    },
    "support_resistance": {
        "classic": 0.25, "fibonacci": 0.25, "camarilla": 0.20,
        "woodie": 0.15, "demark": 0.15,
    },
    "entry_quality": {"bb20": 0.30, "keltner16": 0.30, "atr_or_realized": 0.20, "ema50_distance": 0.20},
    "nav_pricing": {"nav_premium": 1.0},
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
        "oversold": 40.0, "overbought": 60.0,
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
            key = _norm(part.get("name"))
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
                          scale: float = 0.05) -> float | None:
    values = _item_values(item)
    distance = _value(values, "distance", "distance_pct", "distancepercent")
    if distance is not None:
        # Rahavard publishes MA distance as a signed price-relative ratio.
        return _direction_score(distance, scale)
    level = _value(values, "value", "ma", "average")
    if level is not None and price is not None and level > 0:
        return _direction_score(price / level - 1.0, scale)
    return _signal_score(item)


def _trend_score(rows: list[tuple[str, str, dict[str, Any]]], price: float | None) -> dict[str, Any]:
    weights = INDICATOR_WEIGHTS["trend_structure"]
    items: dict[str, dict[str, Any] | None] = {"ichimoku": _find(rows, "IchimokuCloud", ("moving_averages",))}
    for key in weights:
        if key != "ichimoku":
            items[key] = _find(rows, key, ("moving_averages",))
    rows_scored: list[tuple[str, float, float]] = []
    for key, weight in weights.items():
        item = items.get(key)
        score = None
        if key == "ichimoku" and item:
            values = _item_values(item)
            tenkan = _value(values, "tenkan_sen_formula", "tenken_sen_formula", "tenkan")
            kijun = _value(values, "kijun_sen_formula", "kijun")
            span_a = _value(values, "senkou_span_a_formula", "senkou_span_a", "span_a")
            span_b = _value(values, "senkou_span_b_formula", "senkou_span_b", "span_b")
            parts = []
            if price is not None and span_a is not None and span_b is not None:
                cloud_top = max(span_a, span_b)
                cloud_bottom = min(span_a, span_b)
                cloud = (100.0 if price > cloud_top else 0.0 if price < cloud_bottom else 50.0)
                if price > cloud_top:
                    cloud = 50.0 + 50.0 * min(1.0, (price / cloud_top - 1.0) / 0.05)
                elif price < cloud_bottom:
                    cloud = 50.0 - 50.0 * min(1.0, (cloud_bottom / price - 1.0) / 0.05)
                parts.append((cloud, 0.50))
            if tenkan is not None and kijun is not None and kijun > 0:
                parts.append((_direction_score(tenkan / kijun - 1.0, 0.03), 0.25))
            if span_a is not None and span_b is not None and span_b > 0:
                parts.append((_direction_score(span_a / span_b - 1.0, 0.03), 0.25))
            valid_parts = [(value, part_weight) for value, part_weight in parts if value is not None]
            if valid_parts:
                score = sum(value * part_weight for value, part_weight in valid_parts) / sum(w for _, w in valid_parts)
            else:
                score = _signal_score(item)
        elif item:
            score = _price_distance_score(item, price)
        if score is not None:
            rows_scored.append((key, score, weight))
    result = _weighted(rows_scored, sum(weights.values()))
    result["missing_indicators"] = [key for key in weights if key not in {name for name, _, _ in rows_scored}]
    return result


def _momentum_indicator_score(key: str, item: dict[str, Any] | None,
                              price: float | None, trend_score: float | None) -> float | None:
    if not item:
        return None
    values = _item_values(item)
    signal_fallback = _signal_score(item)
    if key == "macd26":
        line, signal = _value(values, "macd"), _value(values, "signal")
        if line is not None and signal is not None and price:
            cross = _direction_score((line - signal) / price, 0.01)
            zero = _direction_score(line / price, 0.02)
            return 0.65 * cross + 0.35 * zero
    elif key == "adx14":
        adx = _value(values, "adx", "value")
        if adx is not None and trend_score is not None:
            strength = min(1.0, max(0.0, adx / 30.0))
            return 50.0 + (trend_score - 50.0) * strength
        return None
    elif key in {"rsi14", "mfi14"}:
        field = "rsi" if key == "rsi14" else "mfi"
        value = _value(values, field, "value")
        if value is not None:
            return _regime_oscillator_score(value, trend_score)
    elif key == "cci14":
        value = _value(values, "cci", "value")
        if value is not None:
            return _direction_score(value / 100.0, 1.0)
    elif key == "aroon25":
        up, down = _value(values, "up"), _value(values, "down")
        if up is not None and down is not None:
            return _clamp(50.0 + (up - down) * 0.5)
    elif key == "ao534":
        value = _value(values, "awesome", "ao", "value")
        if value is not None and price:
            return _direction_score(value / price, 0.02)
    elif key == "stochrsi14":
        value = _value(values, "stochrsi", "value")
        if value is not None:
            if 0.0 <= value <= 1.0:
                value *= 100.0
            return _regime_oscillator_score(value, trend_score)
    elif key == "mtm6":
        value = _value(values, "mtm", "value")
        if value is not None and price:
            return _direction_score(value / price, 0.02)
    elif key == "so14":
        k, d = _value(values, "k"), _value(values, "d")
        if k is not None and d is not None:
            value = (k + d) / 2.0
            level_score = _regime_oscillator_score(value, trend_score)
            cross_score = _direction_score((k - d) / 100.0, 0.25)
            return 0.65 * level_score + 0.35 * cross_score
    elif key == "wr14":
        value = _value(values, "wr", "value")
        if value is not None:
            normalized = value + 100.0 if -100.0 <= value <= 0.0 else value
            return _regime_oscillator_score(normalized, trend_score)
    return signal_fallback


def _regime_oscillator_score(value: float, trend_score: float | None) -> float:
    """Convert bounded oscillators to a trend-aware, non-probability score."""
    value = _clamp(value)
    regime = _clamp(((trend_score if trend_score is not None else 50.0) - 50.0) / 50.0, -1.0, 1.0)
    centered = (value - 50.0) / 50.0
    score = 50.0 + 25.0 * centered + 15.0 * centered * regime
    # A very high reading is less constructive when the medium-term trend is
    # weak. In a strong uptrend the same level is treated more leniently.
    overbought_zone = 75.0 + 10.0 * max(0.0, regime)
    score -= max(0.0, value - overbought_zone) * 1.2
    return _clamp(score)


def _momentum_score(rows: list[tuple[str, str, dict[str, Any]]], price: float | None,
                    trend_score: float | None) -> dict[str, Any]:
    weights = INDICATOR_WEIGHTS["momentum"]
    rows_scored = []
    for key, weight in weights.items():
        # Rahavard's Trend formula is not defined in the supplied data. It is
        # excluded instead of counting an unknown/possibly duplicate signal.
        if key == "trend":
            continue
        lookup = "aroon25" if key == "aroon25" else "wr14" if key == "wr14" else key
        item = _find(rows, lookup, ("oscillators",))
        score = _momentum_indicator_score(key, item, price, trend_score)
        if score is not None:
            rows_scored.append((key, score, weight))
    result = _weighted(rows_scored, sum(weights.values()))
    available = {name for name, _, _ in rows_scored}
    result["missing_indicators"] = [key for key in weights if key not in available]
    return result


def _volume_score(rows: list[tuple[str, str, dict[str, Any]]], price: float | None,
                  context: dict[str, Any], kind: str | None) -> dict[str, Any]:
    weights = (FIXED_INCOME_VOLUME_WEIGHTS if kind == "fixed_income"
               else INDICATOR_WEIGHTS["volume_confirmation"])
    rows_scored = []
    unverified = {"vmacd26", "vrsi14", "sm15"}
    daily_return_pct = _number(context.get("daily_return_pct"))
    liquidity_peer = _number(context.get("liquidity_percentile"))
    if daily_return_pct is None:
        daily_return_ratio = _history_return(context.get("fund_history"), 1)
        daily_return_pct = daily_return_ratio * 100.0 if daily_return_ratio is not None else None
    for key, weight in weights.items():
        if key == "liquidity_peer":
            if liquidity_peer is not None and 0 <= liquidity_peer <= 100:
                rows_scored.append((key, liquidity_peer, weight))
            continue
        if key in unverified:
            continue
        lookup = {"obv20": "obv20", "vmacd26": "vmacd26", "vrsi14": "vrsi14",
                  "rv90": "rv90", "rv30": "rv30", "rv15": "rv15"}[key]
        item = _find(rows, lookup, ("volumes",))
        if not item:
            continue
        values = _item_values(item)
        score = None
        if key == "obv20":
            obv = _value(values, "obv")
            average = _value(values, "obv_sma20", "sma20", "average")
            previous = _value(values, "previous_value", "previous")
            if obv is not None and average is not None:
                score = 75.0 if obv > average else 25.0 if obv < average else 50.0
            elif obv is not None and previous is not None:
                score = 75.0 if obv > previous else 25.0 if obv < previous else 50.0
            else:
                # An absolute cumulative OBV value does not encode direction.
                item_signal = _norm(item.get("signal"))
                score = _signal_score(item) if item_signal not in {"highvolume", "lowvolume"} else None
        elif key.startswith("rv"):
            item_signal = _norm(item.get("signal"))
            if item_signal == "lowvolume":
                score = 50.0
            elif item_signal == "highvolume" and daily_return_pct is not None:
                direction = math.tanh(daily_return_pct / 1.5)
                score = _clamp(50.0 + 30.0 * direction)
        if score is None:
            item_signal = _norm(item.get("signal"))
            if item_signal not in {"highvolume", "lowvolume"}:
                score = _signal_score(item)
        if score is not None:
            rows_scored.append((key, score, weight))
    result = _weighted(rows_scored, sum(weights.values()))
    available = {name for name, _, _ in rows_scored}
    result["missing_indicators"] = [key for key in weights if key not in available]
    result["unverified_indicators"] = sorted(unverified)
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


def _pivot_score(rows: list[tuple[str, str, dict[str, Any]]], price: float | None) -> dict[str, Any]:
    weights = INDICATOR_WEIGHTS["support_resistance"]
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
            if key.startswith("s") and value > 0:
                method_supports.append(value)
            elif key.startswith("r") and value > 0:
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
        method_supports = [value for key, value in values.items()
                           if key.startswith("s") and value > 0 and value < price]
        method_resistances = [value for key, value in values.items()
                              if key.startswith("r") and value > price]
        parts: list[tuple[float, float]] = []
        if pivot is not None and pivot > 0:
            parts.append((_direction_score(price / pivot - 1.0, 0.05), 0.60))
        if method_supports:
            local_support = max(method_supports)
            support_quality = 100.0 * math.exp(-((price - local_support) / price) / 0.10)
            parts.append((support_quality, 0.20 if pivot is not None else 0.50))
        if method_resistances:
            local_resistance = min(method_resistances)
            headroom = _clamp((local_resistance - price) / price / 0.10 * 100.0)
            parts.append((headroom, 0.20 if pivot is not None else 0.50))
        valid_parts = [(score, weight) for score, weight in parts if score is not None]
        if not valid_parts:
            continue
        score = sum(value * weight for value, weight in valid_parts) / sum(weight for _, weight in valid_parts)
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
    weights = ({"bb20": 0.10, "keltner16": 0.10, "atr_or_realized": 0.65,
                "ema50_distance": 0.15} if kind == "fixed_income"
               else INDICATOR_WEIGHTS["entry_quality"])
    rows_scored = []
    for key in ("bb20", "keltner16"):
        item = _find(rows, key, ("moving_averages", "bands"))
        values = _item_values(item)
        upper, lower = _value(values, "upper"), _value(values, "lower")
        if price is None or upper is None or lower is None or upper <= lower:
            continue
        position = (price - lower) / (upper - lower)
        signal = _norm(item.get("signal")) if item else ""
        if position < 0:
            score = 20.0
        elif position > 1:
            score = 60.0 if signal in {"buy", "bullish", "breakoutup"} else 35.0
        else:
            score = _clamp(100.0 - 60.0 * abs(position - 0.5))
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
    weights = INDICATOR_WEIGHTS["nav_pricing"]
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
                     context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Score an ETF using only valid, supplied indicators and metadata."""
    context = context or {}
    kind = _type(context)
    rows = _group_items(groups)
    family = {
        "trend_structure": _trend_score(rows, price),
    }
    family["momentum"] = _momentum_score(rows, price, family["trend_structure"].get("score"))
    family["volume_confirmation"] = _volume_score(rows, price, context, kind)
    family["support_resistance"] = _pivot_score(rows, price)
    family["entry_quality"] = _entry_quality_score(rows, price, context)
    family["nav_pricing"] = _nav_score(price, context)

    family_weights = FAMILY_WEIGHTS_BY_TYPE.get(kind, FAMILY_WEIGHTS)
    valid_families = [(key, value["score"], family_weights[key])
                      for key, value in family.items() if value.get("score") is not None]
    available_family_weight = sum(weight for _, _, weight in valid_families)
    final_score = (sum(score * weight for _, score, weight in valid_families) / available_family_weight
                   if available_family_weight else None)
    coverage = sum(family_weights[key] * float(value.get("coverage_pct") or 0.0) / 100.0
                   for key, value in family.items()) * 100.0
    if final_score is None:
        band = "unavailable"
    elif final_score >= 80:
        band = "very_strong"
    elif final_score >= 70:
        band = "strong"
    elif final_score >= 60:
        band = "relatively_positive"
    elif final_score >= 45:
        band = "neutral"
    elif final_score >= 30:
        band = "weak"
    else:
        band = "very_weak"

    volatility = _number(family["entry_quality"].get("realized_volatility_pct"))
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
        "score_method": "fund_six_family_no_relative_initial_v1",
        "score_weights": {key: round(weight * 100) for key, weight in family_weights.items()},
        "fund_type": kind,
        "fund_type_label": FUND_TYPE_LABELS.get(kind, "نامشخص"),
        "model_profile": "fixed_income_six_family_v1" if kind == "fixed_income" else "medium_term_six_family_v1",
        "family_scores": family,
        "data_coverage_pct": round(coverage, 1),
        "available_family_weight_pct": round(available_family_weight * 100, 1),
        "score_band": band,
        "score_validation": "initial_unbacktested",
        "risk_rank": {"score": round(risk_score, 1) if risk_score is not None else None,
                      "level": risk_level,
                      "basis": "annualized_20d_realized_volatility_with_type_specific_scale",
                      "fund_type": kind, "type_adjusted": kind in VOLATILITY_SCALE_PCT},
        "nav_assessment": family["nav_pricing"],
        "top_factors": {
            "positive": ({"family": top_positive[0], "score": round(top_positive[1], 1)}
                          if top_positive and top_positive[1] >= 50 else None),
            "negative": ({"family": top_negative[0], "score": round(top_negative[1], 1)}
                          if top_negative and top_negative[1] < 50 else None),
        },
        "missing_data": diagnostics,
        "score_change_5d": None,
        "score_change_20d": None,
    }
