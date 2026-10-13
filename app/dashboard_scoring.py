from __future__ import annotations

import math
from typing import Any

from .indicators import compute_indicators, pivot_points
from .scoring_profiles import DASHBOARD_SCORING_PROFILES, normalize_horizon, horizon_label
from .scoring_confirmation import assess_purchase, combine_scores, compute_confirmation


DASHBOARD_SCORE_WEIGHTS = DASHBOARD_SCORING_PROFILES["long"]["family_weights"]

DASHBOARD_INDICATOR_NAMES = {
    "moving_averages": {
        "ema5": "EMA(5)", "ema10": "EMA(10)", "ema20": "EMA(20)",
        "ema30": "EMA(30)", "ema50": "EMA(50)", "ema100": "EMA(100)",
        "sma5": "SMA(5)", "sma10": "SMA(10)", "sma20": "SMA(20)",
        "sma30": "SMA(30)", "sma50": "SMA(50)", "sma100": "SMA(100)",
        "ichimoku": "Ichimoku(9,26,52,26)", "bb20": "BB(20)",
        "keltner16": "KELTNER(16)",
    },
    "oscillators": {
        "macd26": "MACD(26)", "rsi14": "RSI(14)", "mfi14": "MFI(14)",
        "adx14": "ADX(14)", "stochrsi14": "StochRSI(14)", "trend": "Trend",
        "ao534": "AO(5,34)", "so14": "SO(14)", "aroon25": "AROON(25)",
        "cci14": "CCI(14)", "mtm6": "MTM(6)", "wr14": "WR(14)",
    },
    "support_resistance": {
        "fibonacci": "PivotPointFibonacci(30)", "classic": "PivotPointClassic(30)",
        "camarilla": "PivotPointCamarilla(30)", "woodie": "PivotPointWoodie(30)",
        "demark": "PivotPointDeMark(30)",
    },
    "volume": {
        "obv20": "OBV(20)", "sm15": "SM(15)", "rv30": "RV(30)",
        "rv90": "RV(90)", "vmacd26": "VMACD(26)",
        "vrsi14": "VRSI(14)", "rv15": "RV(15)",
    },
}


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return min(high, max(low, value))


def _signed_score(value: float, scale: float) -> float:
    return _clamp(50.0 + 50.0 * math.tanh(value / scale)) if scale > 0 else 50.0


def _weighted(rows: list[tuple[float | None, float]]) -> float | None:
    valid = [(value, weight) for value, weight in rows if value is not None and weight > 0]
    total = sum(weight for _, weight in valid)
    return sum(value * weight for value, weight in valid) / total if total else None


def _support_resistance_levels(bars: list[dict[str, Any]], tech: dict[str, Any],
                               current: float | None) -> list[dict[str, Any]]:
    """Use confirmed historical swing points and classic prior-session pivots only."""
    if current is None or current <= 0:
        return []
    points: list[tuple[float, str]] = []
    if len(bars) >= 30:
        start = max(2, len(bars) - 180)
        for index in range(start, len(bars) - 2):
            high = _number(bars[index].get("high"))
            low = _number(bars[index].get("low"))
            neighbors = bars[index - 2:index] + bars[index + 1:index + 3]
            highs = [_number(row.get("high")) for row in neighbors]
            lows = [_number(row.get("low")) for row in neighbors]
            if high is not None and all(value is not None for value in highs) and high >= max(highs):
                points.append((high, "قلهٔ تأییدشدهٔ تاریخچه"))
            if low is not None and all(value is not None for value in lows) and low <= min(lows):
                points.append((low, "کف تأییدشدهٔ تاریخچه"))

    classic = (tech.get("pivots", {}).get("Classic")
               if isinstance(tech.get("pivots"), dict) else None)
    if isinstance(classic, dict):
        for key in ("S1", "S2", "S3", "R1", "R2", "R3"):
            value = _number(classic.get(key))
            if value is not None and value > 0:
                points.append((value, f"پیوت کلاسیک {key} از روز قبل"))

    result: list[dict[str, Any]] = []
    for kind in ("support", "resistance"):
        candidates = [(price, method) for price, method in points
                      if (price <= current if kind == "support" else price > current)]
        candidates.sort(key=lambda item: item[0])
        clusters: list[list[tuple[float, str]]] = []
        for candidate in candidates:
            if clusters and abs(candidate[0] - clusters[-1][-1][0]) <= current * 0.0075:
                clusters[-1].append(candidate)
            else:
                clusters.append([candidate])
        clusters.sort(key=lambda group: abs(sum(price for price, _ in group) / len(group) - current))
        for group in clusters[:3]:
            low = min(price for price, _ in group)
            high = max(price for price, _ in group)
            methods = sorted({method for _, method in group})
            result.append({
                "kind": kind,
                "low": low,
                "high": high,
                "midpoint": (low + high) / 2,
                "strength": "strong" if len(methods) >= 3 else "medium" if len(methods) == 2 else "watch",
                "methods": methods,
                "method": "; ".join(methods),
            })
    return result


def analyze_dashboard_asset(symbol: str, bars: list[dict[str, Any]],
                            horizon: str = "long") -> dict[str, Any]:
    """AliVest score using the experimental four-family horizon model."""
    horizon = normalize_horizon(horizon)
    model = DASHBOARD_SCORING_PROFILES[horizon]
    family_weights = model["family_weights"]
    weights = {
        family: {DASHBOARD_INDICATOR_NAMES[family][key]: weight
                 for key, weight in entries.items()}
        for family, entries in model["indicator_weights"].items()
    }
    bars = bars or []
    tech = compute_indicators(bars)
    indicators = tech.get("indicators", {})
    current = _number(tech.get("latest"))
    closes = [_number(row.get("close")) for row in bars]
    closes = [value for value in closes if value is not None and value > 0]
    volume_values = [_number(row.get("volume")) for row in bars]
    volumes = [max(0.0, value or 0.0) for value in volume_values]
    names = {"moving_averages": "میانگین متحرک", "oscillators": "نوسان‌گر",
             "support_resistance": "حمایت و مقاومت", "volume": "حجم"}

    def ind(key: str) -> dict[str, Any]:
        found = indicators.get(key)
        return found if isinstance(found, dict) else {}

    def val(key: str, field: str = "value") -> float | None:
        return _number(ind(key).get(field))

    def row(family: str, key: str, score: float | None, value: Any = None, note: str = "") -> dict[str, Any]:
        return {"name": key, "score": round(score, 1) if score is not None else None,
                "weight_pct": round(weights[family][key]*100, 1), "value": value, "note": note}

    rows: dict[str, list[dict[str, Any]]] = {key: [] for key in weights}

    # Moving averages and bands
    family = "moving_averages"
    for key in weights[family]:
        score, raw, note = None, None, ""
        if key.startswith(("EMA(", "SMA(")):
            raw = val(key)
            if current and raw and current > 0:
                score = _signed_score((current-raw)/current, .025)
        elif key == "Ichimoku(9,26,52,26)":
            item = ind(key)
            ca, cb = _number(item.get("senkou_a_at_current")), _number(item.get("senkou_b_at_current"))
            tenkan, kijun = _number(item.get("tenkan")), _number(item.get("kijun"))
            cloud_score = None
            if current and ca is not None and cb is not None:
                lo, hi = min(ca, cb), max(ca, cb)
                cloud_score = (_signed_score((current-hi)/current, .04) if current > hi else
                               _signed_score((current-lo)/current, .04) if current < lo else
                               45+10*(current-lo)/max(hi-lo, current*1e-9))
            cross = _signed_score((tenkan-kijun)/current, .02) if current and tenkan is not None and kijun is not None else None
            score = _weighted([(cloud_score, .70), (cross, .30)])
            raw, note = {"cloud": item.get("price_vs_cloud"), "tenkan": tenkan, "kijun": kijun}, "موقعیت نسبت به ابر و تنکان/کیجون"
        elif key in ("BB(20)", "KELTNER(16)"):
            item = ind(key)
            middle = _number(item.get("middle", item.get("value")))
            upper, lower = _number(item.get("upper")), _number(item.get("lower"))
            if current and middle and current > 0:
                score = _signed_score((current-middle)/current, .025)
                if upper is not None and current > upper:
                    score = min(score, 65)
                elif lower is not None and current < lower:
                    score = max(score, 35)
            raw, note = {"middle": middle, "upper": upper, "lower": lower}, "جایگاه نسبت به خط میانی؛ خروج از باند به‌تنهایی سیگنال خرید نیست"
        rows[family].append(row(family, key, score, raw, note))

    # Oscillators: RSI is one bounded vote, never the sole buy criterion.
    family = "oscillators"
    rsi, mfi, stoch = val("RSI(14)"), val("MFI(14)"), val("StochRSI(14)")
    so, cci, wr = val("SO(14)"), val("CCI(14)"), val("WR(14)")
    macd, hist = val("MACD(12,26,9)"), val("MACD(12,26,9)", "histogram")
    macd_signal = val("MACD(12,26,9)", "signal_line")
    macd_diff = macd-macd_signal if macd is not None and macd_signal is not None else hist
    macd_score = None
    if current and current > 0 and macd is not None:
        pieces = [(_signed_score(macd/current, .01), .50)]
        if macd_diff is not None:
            pieces.append((_signed_score(macd_diff/current, .003), .50))
        macd_score = _weighted(pieces)
    adx, pdi, mdi = val("ADX(14)"), val("ADX(14)", "plus_di"), val("ADX(14)", "minus_di")
    adx_score = None
    if pdi is not None and mdi is not None:
        direction = (pdi-mdi)/max(pdi+mdi, 1)
        strength = _clamp(((adx or 0)-10)/25, 0, 1)
        adx_score = _clamp(50+direction*45*strength)
    elif adx is not None:
        adx_score = 50
    up, down = val("Aroon(25)", "up"), val("Aroon(25)", "down")
    aroon_score = _clamp(50+(up-down)*.45) if up is not None and down is not None else None
    sample = closes[-20:]
    trend_score = None
    if len(sample) >= 10:
        logs = [math.log(price) for price in sample]
        xm, ym = (len(logs)-1)/2, sum(logs)/len(logs)
        denom = sum((i-xm)**2 for i in range(len(logs)))
        slope = sum((i-xm)*(v-ym) for i, v in enumerate(logs))/denom
        trend_score = _signed_score(slope, .004)
    return20 = closes[-1]/closes[-21]-1 if len(closes) >= 21 else None
    def osc(value: float | None, high: float, low: float) -> float | None:
        if value is None:
            return None
        score = _clamp(50+(value-50)*.70)
        if value > high:
            score -= min(20, (value-high)*.80)
        if value < low:
            score += min(8, (low-value)*.30)
        return _clamp(score)

    osc_data = {
        "MACD(26)": (macd_score, macd, "MACD ۱۲/۲۶ و خط سیگنال"),
        "RSI(14)": (osc(rsi, 70, 30), rsi, "مومنتوم نسبی؛ اشباع به‌تنهایی سیگنال خرید نیست"),
        "MFI(14)": (osc(mfi, 80, 20), mfi, "مومنتوم قیمت و جریان حجم"),
        "ADX(14)": (adx_score, {"ADX": adx, "+DI": pdi, "-DI": mdi}, "قدرت روند همراه جهت DI"),
        "StochRSI(14)": (osc(stoch, 80, 20), stoch, "شتاب RSI؛ مقدار افراطی رأی مستقل خرید نیست"),
        "Trend": (trend_score, return20, "شیب قیمت در حدود ۲۰ کندل اخیر"),
        "AO(5,34)": (_signed_score(val("AO(5,34)")/current, .003) if val("AO(5,34)") is not None and current else None,
                     val("AO(5,34)"), "شتاب میانگین‌های ۵ و ۳۴ دوره"),
        "SO(14)": (osc(so, 80, 20), so, "موقعیت قیمت در دامنه ۱۴ دوره"),
        "AROON(25)": (aroon_score, {"up": up, "down": down}, "تازگی سقف و کف ۲۵ دوره"),
        "CCI(14)": (_signed_score(cci, 180) if cci is not None else None, cci, "فاصله از میانگین؛ اثر افراط محدود است"),
        "MTM(6)": (_signed_score(val("MTM(6)")/current, .025) if val("MTM(6)") is not None and current else None,
                   val("MTM(6)"), "تغییر قیمت در ۶ دوره"),
        "WR(14)": (osc(wr+50, 80, 20) if wr is not None else None, wr, "جایگاه بسته‌شدن در دامنه ۱۴ دوره"),
    }
    for key, (score, raw, note) in osc_data.items():
        if key not in weights[family]:
            continue
        rows[family].append(row(family, key, score, raw, note))

    # Relative volume is scored only alongside price direction, not as a
    # stand-alone bullish signal.
    relative_volumes = {}
    for period in (30, 90, 15):
        ratio = None
        recent = volume_values[-period-1:-1]
        if (len(volume_values) > period and volume_values[-1] is not None
                and volume_values[-1] > 0 and len(recent) == period
                and all(value is not None and value >= 0 for value in recent)):
            mean = sum(float(value) for value in recent) / period
            if mean > 0 and len(closes) > period:
                ratio = volume_values[-1] / mean
        relative_volumes[period] = {"ratio": ratio}

    family = "volume"
    avg_volume20 = (sum(float(value) for value in volume_values[-20:]) / 20
                    if len(volume_values) >= 20
                    and all(value is not None and value >= 0 for value in volume_values[-20:]) else None)
    price_return20 = closes[-1] / closes[-21] - 1 if len(closes) >= 21 else None
    volume_indicators = {
        "OBV(20)": (None, None, "OBV تنها وقتی با میانگین خودش مقایسه شود جهت حجم را نشان می‌دهد."),
        "SM(15)": (None, None, "تعریف محاسباتی SM در منبع مشخص نشده؛ امتیاز جایگزین ساخته نمی‌شود."),
        "RV(30)": (None, None, "حجم نسبی فقط همراه جهت تغییر قیمت تفسیر می‌شود."),
        "RV(90)": (None, None, "حجم نسبی فقط همراه جهت تغییر قیمت تفسیر می‌شود."),
        "VMACD(26)": (None, None, "شتاب حجم با جهت حرکت قیمت سنجیده می‌شود."),
        "VRSI(14)": (None, None, "RSI حجم با جهت حرکت قیمت سنجیده می‌شود."),
        "RV(15)": (None, None, "حجم نسبی فقط همراه جهت تغییر قیمت تفسیر می‌شود."),
    }
    obv_item = ind("OBV(20)")
    obv_value = _number(obv_item.get("value"))
    obv_average = _number(obv_item.get("obv_sma20"))
    if obv_value is not None and obv_average is not None and avg_volume20 and avg_volume20 > 0:
        volume_indicators["OBV(20)"] = (_signed_score((obv_value-obv_average)/avg_volume20, 1.5),
                                         {"obv": obv_value, "obv_sma20": obv_average},
                                         "مقایسه OBV با میانگین ۲۰ دوره؛ جهت قیمت در ساخت آن لحاظ می‌شود.")
    elif obv_item.get("signal") in {"bullish", "bearish"}:
        volume_indicators["OBV(20)"] = (75.0 if obv_item.get("signal") == "bullish" else 25.0,
                                         obv_value, "مقایسهٔ جهت‌دار OBV با میانگین ۲۰ دوره.")
    for period in (15, 30, 90):
        ratio = relative_volumes[period]["ratio"]
        period_return = closes[-1]/closes[-period-1]-1 if len(closes) > period else None
        if ratio is not None and period_return is not None:
            activity = min(2.0, max(.5, ratio))
            volume_indicators[f"RV({period})"] = (
                _clamp(50 + 40*math.tanh(period_return/.05)*activity),
                {"relative_volume": ratio, "price_return_pct": period_return*100},
                "حجم بالاتر فقط وقتی امتیاز می‌گیرد که با جهت قیمت همراه باشد.")
    price_direction = 1 if price_return20 is not None and price_return20 > 0 else -1 if price_return20 is not None and price_return20 < 0 else None
    vrsi = val("VRSI(14)")
    if vrsi is not None and price_direction is not None:
        volume_indicators["VRSI(14)"] = (_clamp(50+(vrsi-50)*.45*price_direction), vrsi,
                                          "فشار نسبی حجم در جهت حرکت حدود ۲۰ کندل اخیر.")
    vmacd = _number(ind("VMACD(12,26)").get("value"))
    if vmacd is not None and avg_volume20 and avg_volume20 > 0 and price_direction is not None:
        volume_indicators["VMACD(26)"] = (_signed_score(vmacd/avg_volume20*price_direction, .20), vmacd,
                                           "شتاب حجم با جهت قیمت تأیید می‌شود.")
    for key in weights[family]:
        score, raw, note = volume_indicators.get(key, (None, None, "دادهٔ معتبر موجود نیست."))
        rows[family].append(row(family, key, score, raw, note))

    # Support/resistance: pivot calculations use the previous 30 completed bars.
    family = "support_resistance"
    schemes = {
        "PivotPointFibonacci(30)": "Fibonacci", "PivotPointClassic(30)": "Classic",
        "PivotPointCamarilla(30)": "Camarilla", "PivotPointWoodie(30)": "Woodie",
        "PivotPointDeMark(30)": "DeMark",
    }
    pivot_sets = {}
    if current is not None and len(bars) >= 31:
        window = bars[-31:-1]
        highs = [_number(item.get("high", item.get("close"))) for item in window]
        lows = [_number(item.get("low", item.get("close"))) for item in window]
        prior_close = _number(window[-1].get("close"))
        prior_open = _number(window[-1].get("open", prior_close))
        if all(value is not None for value in highs+lows) and prior_close is not None and prior_open is not None:
            pivot_sets = pivot_points(max(highs), min(lows), prior_close, prior_open)
    atr = val("ATR(14)")
    scale = atr if atr is not None and atr > 0 else (current*.03 if current else 1)
    for key, scheme in schemes.items():
        levels = pivot_sets.get(scheme, {})
        pivot = _number(levels.get("pivot")) if levels else None
        score, raw = None, None
        if current is not None and pivot is not None and pivot > 0:
            position = _signed_score((current-pivot)/max(scale, current*.01), 1)
            r1, s1 = _number(levels.get("R1")), _number(levels.get("S1"))
            headroom = (65+20*math.tanh((current-r1)/scale) if current >= r1 else
                        50+25*math.tanh((r1-current)/(2*scale))) if r1 is not None else 50
            support = _clamp(78-max(0, (current-s1)/scale-.5)*10, 38, 78) if s1 is not None and current >= s1 else 50
            score = _clamp(.55*position+.25*headroom+.20*support)
            raw = {"pivot": pivot, "S1": s1, "R1": r1}
        rows[family].append(row(family, key, score, raw, "پیوت ۳۰ کندل کامل‌شده؛ موقعیت قیمت نسبت به سطوح"))

    family_scores = {}
    for family, indicator_family_weights in weights.items():
        valid = [item for item in rows[family] if item["score"] is not None]
        weight_sum = sum(indicator_family_weights[item["name"]] for item in valid)
        score = sum(item["score"]*indicator_family_weights[item["name"]] for item in valid)/weight_sum if weight_sum else None
        family_scores[family] = {
            "score": round(score, 1) if score is not None else None,
            "coverage_pct": round(weight_sum*100, 1), "indicators": rows[family],
            "missing_indicators": [key for key in indicator_family_weights if key not in {item["name"] for item in valid}],
        }
    levels = _support_resistance_levels(bars, tech, current)
    supports = [item for item in levels if item["kind"] == "support"]
    resistances = [item for item in levels if item["kind"] == "resistance"]
    near_support = max(supports, key=lambda item: item["midpoint"], default=None)
    near_resistance = min(resistances, key=lambda item: item["midpoint"], default=None)
    support_distance = (current-near_support["midpoint"])/current*100 if current and near_support else None
    resistance_distance = (near_resistance["midpoint"]-current)/current*100 if current and near_resistance else None
    family_scores["support_resistance"].update({
        "nearest_support": near_support["midpoint"] if near_support else None,
        "nearest_resistance": near_resistance["midpoint"] if near_resistance else None,
        "support_distance_pct": support_distance,
        "resistance_distance_pct": resistance_distance,
    })
    confirmation = compute_confirmation(
        horizon, bars, current,
        near_support["midpoint"] if near_support else None,
        near_resistance["midpoint"] if near_resistance else None)
    combined = combine_scores(family_scores, family_weights, confirmation)
    main_score = combined["main_score"]
    total = combined["combined_score"]
    available_weight = combined["available_family_weight_pct"] / 100.0
    effective = combined["effective_family_weights"]
    coverage = sum(family_weights[key]*family_scores[key]["coverage_pct"]/100
                   for key in family_weights)*100
    direction = "unavailable" if main_score is None else "bullish" if main_score >= 56 else "bearish" if main_score <= 44 else "neutral"
    band = combined["score_band"]
    entry_quality = confirmation["entry_quality"]
    purchase_assessment = assess_purchase(
        main_score, confirmation["score"], confirmation["coverage_pct"],
        entry_quality, confirmation["components"])
    entry = entry_quality.get("status", "unavailable")

    # Keep historical realized volatility for risk only (the app's legacy RV(30)).
    realized_volatility = val("RV(30)")
    risk_value = realized_volatility if realized_volatility is not None else (
        atr/current*100*math.sqrt(252) if atr and current else None)
    risk = "unavailable" if risk_value is None else "low" if risk_value < 15 else "medium" if risk_value <= 30 else "high"
    if purchase_assessment.get("status") == "suitable":
        if coverage < 30 or available_weight * 100 < 50:
            purchase_assessment = {
                "status": "confirmation", "label": "صبر · پوشش داده کم",
                "reason": "پوشش داده یا خانواده‌های قابل‌محاسبه برای تأیید فرصت خرید کافی نیست.", "rank": 2,
            }
        elif risk == "high":
            purchase_assessment = {
                "status": "confirmation", "label": "صبر · ریسک بالا",
                "reason": "نوسان تاریخی بالاست؛ امتیاز تکنیکال به‌تنهایی برای ورود کافی نیست.", "rank": 2,
            }
    adx_value = val("ADX(14)")
    strength = "unavailable" if adx_value is None else "strong" if adx_value >= 25 else "medium" if adx_value >= 20 else "weak"
    daily = closes[-1]/closes[-2]-1 if len(closes) > 1 else None
    ema20, ema100 = val("EMA(20)"), val("EMA(100)")
    sma10 = val("SMA(10)")
    sma50 = val("SMA(50)")
    short_exit = round(sma10) if sma10 is not None else None
    medium_exit = round(sma50) if sma50 is not None else None

    positive = [{"family": key, "name": names[key], "score": family_scores[key]["score"]}
                for key in sorted(family_scores, key=lambda k: family_scores[k]["score"] or -1, reverse=True)
                if family_scores[key]["score"] is not None and family_scores[key]["score"] >= 60][:2]
    negative = [{"family": key, "name": names[key], "score": family_scores[key]["score"]}
                for key in sorted(family_scores, key=lambda k: family_scores[k]["score"] or 101)
                if family_scores[key]["score"] is not None and family_scores[key]["score"] <= 40][:2]
    factors = [{"name": key, "score": family_scores[key]["score"], "weight": family_weights[key],
                "evidence": ", ".join(item["name"] for item in rows[key] if item["score"] is not None)}
               for key in family_weights if family_scores[key]["score"] is not None]
    missing = [f"{names[family]}: {key}" for family in weights for key in family_scores[family]["missing_indicators"]]
    limitations = [
        "این امتیاز محاسبهٔ اختصاصی AliVest است، نه امتیاز رسمی ره‌آورد یا احتمال آماری موفقیت.",
        "وزن شاخص‌های بدون داده در همان گروه متناسب می‌شود؛ در نبود کامل یک گروه، وزن گروه‌های دیگر متناسب می‌شود و پوشش نمایش داده می‌شود.",
        f"امتیاز اصلی S از چهار گروه ساخته می‌شود؛ RSI تنها {family_weights['oscillators'] * weights['oscillators']['RSI(14)'] * 100:.1f}٪ از وزن پایهٔ کل را دارد.",
        "امتیاز ترکیبی F برابر ۷۵٪ امتیاز اصلی S و ۲۵٪ امتیاز تأیید C است؛ داده‌های مفقود امتیاز جایگزین نمی‌گیرند.",
        "حجم تنها وقتی امتیاز می‌گیرد که با جهت حرکت قیمت همراه باشد؛ تعریف نامشخص SM(15) محاسبه نشده است.",
    ]
    if missing:
        limitations.append("شاخص‌های فاقد داده یا فرمول قابل اتکا حذف شدند: "+"، ".join(missing))
    coverage_by_family = {key: family_scores[key]["coverage_pct"] for key in family_scores}
    breakdown = {key: family_scores[key]["score"] for key in family_scores}
    breakdown.update({
        "family_coverage_pct": coverage_by_family, "available_weight": round(available_weight*100, 1),
        "direction_score": main_score,
        "main_score": main_score,
        "confirmation_score": confirmation["score"],
        "combined_score": total,
        "rsi": rsi, "adx": adx_value, "realized_volatility_pct": realized_volatility,
        "support_distance_pct": round(support_distance, 2) if support_distance is not None else None,
        "resistance_distance_pct": round(resistance_distance, 2) if resistance_distance is not None else None,
        "front_resistance_count": len(resistances),
        "near_resistance_count": sum(1 for item in resistances if current and (item["midpoint"]-current)/current <= .10),
    })
    dashboard_indicators = dict(indicators)
    for period, data in relative_volumes.items():
        historical = dashboard_indicators.pop(f"RV({period})", None)
        if historical is not None:
            dashboard_indicators[f"HV({period})"] = historical
        ratio = data["ratio"]
        dashboard_indicators[f"RV({period})"] = {
            "value": ratio, "previous_value": None,
            "signal": "HighVolume" if ratio is not None and ratio >= 1 else "LowVolume" if ratio is not None else "unavailable",
            "interpretation": "Relative volume versus preceding lookback average",
            "formula": "current volume / average volume over preceding period",
            "parameters": {"period": period},
        }
    dashboard_tech = dict(tech)
    dashboard_tech["indicators"] = dashboard_indicators
    return {
        "symbol": symbol, "data_timestamp": bars[-1].get("timestamp") if bars else None,
        "price": current, "daily_return_pct": daily*100 if daily is not None else None,
        "short_term_exit_price": short_exit, "medium_term_exit_price": medium_exit,
        "short_term_exit": {"price": short_exit, "trigger": "بسته‌شدن کندل روزانه زیر SMA(10)",
                            "action": "اگر کندل روزانه زیر SMA(10) بسته شد، حد ضرر کوتاه‌مدت فعال است."},
        "medium_term_exit": {"price": medium_exit, "trigger": "بسته‌شدن کندل روزانه زیر SMA(50)",
                             "action": "اگر کندل روزانه زیر SMA(50) بسته شد، حد ضرر میان‌مدت فعال است."},
        "trend": direction, "medium_term_trend": direction,
        "short_term_trend": "unavailable" if current is None or ema20 is None else "bullish" if current > ema20 else "bearish" if current < ema20 else "neutral",
        "long_term_trend": "unavailable" if current is None or ema100 is None else "bullish" if current > ema100 else "bearish" if current < ema100 else "neutral",
        "trend_direction_score": main_score,
        "trend_strength": strength, "technical_score": round(total, 1) if total is not None else None,
        "main_score": main_score, "confirmation_score": confirmation["score"],
        "confirmation_coverage_pct": confirmation["coverage_pct"],
        "confirmation_components": confirmation["components"],
        "combined_score": total,
        "score_method": f"dashboard_rahavard_four_group_weighted_{horizon}_trial_v1",
        "score_origin": "AliVest", "score_profile": model["profile"],
        "investment_horizon": horizon, "investment_horizon_label": horizon_label(horizon),
        "score_weights": {key: round(value*100) for key, value in family_weights.items()},
        "indicator_weights": {family: {key: round(value*100, 1) for key, value in values.items()}
                              for family, values in weights.items()},
        "effective_score_weights": effective, "family_scores": family_scores, "score_band": band,
        "score_validation": "initial_unbacktested", "score_breakdown": breakdown,
        "data_coverage_pct": round(coverage, 1), "available_family_weight_pct": round(available_weight*100, 1),
        "confidence": round(coverage, 1), "confidence_score": round(coverage, 1),
        "confidence_level": "high" if coverage >= 75 else "medium" if coverage >= 50 else "low",
        "confidence_label": "بالا" if coverage >= 75 else "متوسط" if coverage >= 50 else "پایین",
        "confidence_basis": "پوشش دادهٔ قابل محاسبه؛ این عدد احتمال موفقیت معامله نیست.",
        "breakout_confidence": "volume_scored_with_price_direction",
        "breakout_confidence_label": "حجم فقط همراه جهت قیمت امتیاز می‌گیرد",
        "risk": risk, "risk_score": round(risk_value, 1) if risk_value is not None else None,
        "risk_label": {"low":"کم","medium":"متوسط","high":"بالا","unavailable":"نامشخص"}[risk],
        "risk_basis": "نوسان تاریخی RV(30)، و در نبود آن تخمین از ATR(14).",
        "entry_quality": {**entry_quality,
                           "label": {"suitable":"مناسب","confirmation":"نیازمند تأیید",
                                     "unsuitable":"نامناسب","unavailable":"داده کافی نیست"}.get(entry, "داده کافی نیست")},
        "purchase_assessment": purchase_assessment,
        "signal": direction, "factors": factors, "positive_evidence": positive, "negative_evidence": negative,
        "explanation": [f"{names[item['name']]}: {item['evidence']}" for item in factors],
        "breakout_confirmation_note": "شاخص‌های فاقد داده امتیاز جایگزین نمی‌گیرند.",
        "data_limitations": limitations, "indicators": dashboard_tech,
        "support_resistance": levels, "support_levels": supports, "resistance_levels": resistances,
        "nearest_support": near_support, "nearest_resistance": near_resistance,
        "structural_invalidation_level": near_support.get("midpoint") if near_support else None,
        "decision_support": "امتیاز ترکیبی F از امتیاز اصلی چهارگروهی S و امتیاز تأیید C ساخته می‌شود؛ توصیه قطعی خرید یا فروش نیست.",
    }
