from __future__ import annotations

import math
from typing import Any

from .indicators import compute_indicators, pivot_points


DASHBOARD_SCORE_WEIGHTS = {
    "moving_averages": 0.45,
    "oscillators": 0.40,
    "support_resistance": 0.15,
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


def analyze_dashboard_asset(symbol: str, bars: list[dict[str, Any]]) -> dict[str, Any]:
    """AliVest medium-term score using the three requested indicator families."""
    bars = bars or []
    tech = compute_indicators(bars)
    indicators = tech.get("indicators", {})
    current = _number(tech.get("latest"))
    closes = [_number(row.get("close")) for row in bars]
    closes = [value for value in closes if value is not None and value > 0]
    volumes = [max(0.0, _number(row.get("volume")) or 0.0) for row in bars]
    weights = {
        "moving_averages": {
            "EMA(50)": .16, "EMA(20)": .14, "Ichimoku(9,26,52,26)": .14,
            "EMA(100)": .12, "BB(20)": .10, "SMA(50)": .08, "SMA(20)": .06,
            "EMA(10)": .06, "SMA(100)": .04, "KELTNER(16)": .04, "EMA(30)": .02,
            "SMA(10)": .02, "SMA(30)": .01, "EMA(5)": .005, "SMA(5)": .005,
        },
        "oscillators": {
            "MACD(26)": .22, "RSI(14)": .20, "MFI(14)": .16, "ADX(14)": .12,
            "StochRSI(14)": .08, "Trend": .06, "AO(5,34)": .05, "SO(14)": .04,
            "AROON(25)": .03, "CCI(14)": .02, "MTM(6)": .01, "WR(14)": .01,
        },
        "support_resistance": {
            "PivotPointFibonacci(30)": .32, "PivotPointClassic(30)": .26,
            "PivotPointCamarilla(30)": .20, "PivotPointWoodie(30)": .14,
            "PivotPointDeMark(30)": .08,
        },
    }
    names = {"moving_averages": "میانگین متحرک", "oscillators": "نوسان‌گر",
             "support_resistance": "حمایت و مقاومت"}

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
        rows[family].append(row(family, key, score, raw, note))

    # Relative volume remains available as a raw indicator, but is not one of
    # the three weighted scoring families.
    relative_volumes = {}
    for period in (30, 90, 15):
        ratio = None
        if len(volumes) > period and volumes[-1] > 0:
            mean = sum(volumes[-period-1:-1])/period
            if mean > 0 and len(closes) > period:
                ratio = volumes[-1]/mean
        relative_volumes[period] = {"ratio": ratio}

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
    for family, family_weights in weights.items():
        valid = [item for item in rows[family] if item["score"] is not None]
        weight_sum = sum(family_weights[item["name"]] for item in valid)
        score = sum(item["score"]*family_weights[item["name"]] for item in valid)/weight_sum if weight_sum else None
        family_scores[family] = {
            "score": round(score, 1) if score is not None else None,
            "coverage_pct": round(weight_sum*100, 1), "indicators": rows[family],
            "missing_indicators": [key for key in family_weights if key not in {item["name"] for item in valid}],
        }
    valid_groups = [(family_scores[key]["score"], DASHBOARD_SCORE_WEIGHTS[key])
                    for key in DASHBOARD_SCORE_WEIGHTS if family_scores[key]["score"] is not None]
    available_weight = sum(weight for _, weight in valid_groups)
    total = sum(score*weight for score, weight in valid_groups)/available_weight if available_weight else None
    effective = {key: round(DASHBOARD_SCORE_WEIGHTS[key]/available_weight*100, 1)
                 for key in DASHBOARD_SCORE_WEIGHTS if family_scores[key]["score"] is not None} if available_weight else {}
    coverage = sum(DASHBOARD_SCORE_WEIGHTS[key]*family_scores[key]["coverage_pct"]/100
                   for key in DASHBOARD_SCORE_WEIGHTS)*100
    direction = "unavailable" if total is None else "bullish" if total >= 56 else "bearish" if total <= 44 else "neutral"
    band = ("unavailable" if total is None else "very_strong" if total >= 80 else "strong" if total >= 70
            else "relatively_positive" if total >= 60 else "neutral" if total >= 45 else "weak" if total >= 30 else "very_weak")

    levels = _support_resistance_levels(bars, tech, current)
    supports = [item for item in levels if item["kind"] == "support"]
    resistances = [item for item in levels if item["kind"] == "resistance"]
    near_support = max(supports, key=lambda item: item["midpoint"], default=None)
    near_resistance = min(resistances, key=lambda item: item["midpoint"], default=None)
    support_distance = (current-near_support["midpoint"])/current*100 if current and near_support else None
    resistance_distance = (near_resistance["midpoint"]-current)/current*100 if current and near_resistance else None
    entry = ("unavailable" if total is None else "suitable" if total >= 65 and
             (resistance_distance is None or resistance_distance >= 2) else
             "confirmation" if total >= 48 else "unsuitable")

    # Keep historical realized volatility for risk only (the app's legacy RV(30)).
    realized_volatility = val("RV(30)")
    risk_value = realized_volatility if realized_volatility is not None else (
        atr/current*100*math.sqrt(252) if atr and current else None)
    risk = "unavailable" if risk_value is None else "low" if risk_value < 15 else "medium" if risk_value <= 30 else "high"
    adx_value = val("ADX(14)")
    strength = "unavailable" if adx_value is None else "strong" if adx_value >= 25 else "medium" if adx_value >= 20 else "weak"
    daily = closes[-1]/closes[-2]-1 if len(closes) > 1 else None
    ema20, ema50, ema100 = val("EMA(20)"), val("EMA(50)"), val("EMA(100)")
    sma50, sma100 = val("SMA(50)"), val("SMA(100)")
    immediate = sma50 or ema50 or (near_support["midpoint"] if near_support else None)
    structural = sma100 or ema100 or (near_support["midpoint"] if near_support else None)
    medium_exit = round(immediate*.995) if immediate else None
    structural_exit = round(structural*.998) if structural else None
    if medium_exit and structural_exit and structural_exit >= medium_exit:
        structural_exit = round(medium_exit*.985)

    positive = [{"family": key, "name": names[key], "score": family_scores[key]["score"]}
                for key in sorted(family_scores, key=lambda k: family_scores[k]["score"] or -1, reverse=True)
                if family_scores[key]["score"] is not None and family_scores[key]["score"] >= 60][:2]
    negative = [{"family": key, "name": names[key], "score": family_scores[key]["score"]}
                for key in sorted(family_scores, key=lambda k: family_scores[k]["score"] or 101)
                if family_scores[key]["score"] is not None and family_scores[key]["score"] <= 40][:2]
    factors = [{"name": key, "score": family_scores[key]["score"], "weight": DASHBOARD_SCORE_WEIGHTS[key],
                "evidence": ", ".join(item["name"] for item in rows[key] if item["score"] is not None)}
               for key in DASHBOARD_SCORE_WEIGHTS if family_scores[key]["score"] is not None]
    missing = [f"{names[family]}: {key}" for family in weights for key in family_scores[family]["missing_indicators"]]
    limitations = [
        "این امتیاز محاسبهٔ اختصاصی AliVest است، نه امتیاز رسمی ره‌آورد یا احتمال آماری موفقیت.",
        "وزن شاخص‌های بدون داده در همان گروه متناسب می‌شود؛ در نبود کامل یک گروه، وزن گروه‌های دیگر متناسب می‌شود و پوشش نمایش داده می‌شود.",
        "RSI یکی از ۱۲ شاخص نوسان‌گر و ۸٪ از وزن پایهٔ کل است؛ خرید بر پایه برآیند هر سه گروه ارزیابی می‌شود.",
        "حجم نسبی فقط به‌عنوان دادهٔ زمینه‌ای نمایش داده می‌شود و در امتیاز کل وزن ندارد؛ ریسک با نوسان تاریخی و ATR سنجیده می‌شود.",
    ]
    if missing:
        limitations.append("شاخص‌های فاقد داده یا فرمول قابل اتکا حذف شدند: "+"، ".join(missing))
    coverage_by_family = {key: family_scores[key]["coverage_pct"] for key in family_scores}
    breakdown = {key: family_scores[key]["score"] for key in family_scores}
    breakdown.update({
        "family_coverage_pct": coverage_by_family, "available_weight": round(available_weight*100, 1),
        "direction_score": round(total, 1) if total is not None else None,
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
        "medium_term_exit_price": medium_exit, "structural_exit_price": structural_exit,
        "medium_term_exit": {"price": medium_exit, "trigger": "تثبیت زیر SMA(50) یا حمایت نزدیک",
                             "action": "سطح هشدار تکنیکال است؛ شکست را با بسته‌شدن کندل بررسی کن.",
                             "structural_price": structural_exit, "structural_trigger": "شکست و تثبیت زیر SMA(100) یا حمایت ساختاری"},
        "trend": direction, "medium_term_trend": direction,
        "short_term_trend": "unavailable" if current is None or ema20 is None else "bullish" if current > ema20 else "bearish" if current < ema20 else "neutral",
        "long_term_trend": "unavailable" if current is None or ema100 is None else "bullish" if current > ema100 else "bearish" if current < ema100 else "neutral",
        "trend_direction_score": round(total, 1) if total is not None else None,
        "trend_strength": strength, "technical_score": round(total, 1) if total is not None else None,
        "score_method": "dashboard_rahavard_three_group_weighted_v1",
        "score_origin": "AliVest", "score_profile": "three_group_midterm_custom",
        "score_weights": {key: round(value*100) for key, value in DASHBOARD_SCORE_WEIGHTS.items()},
        "indicator_weights": {family: {key: round(value*100, 1) for key, value in values.items()}
                              for family, values in weights.items()},
        "effective_score_weights": effective, "family_scores": family_scores, "score_band": band,
        "score_validation": "initial_unbacktested", "score_breakdown": breakdown,
        "data_coverage_pct": round(coverage, 1), "available_family_weight_pct": round(available_weight*100, 1),
        "confidence": round(coverage, 1), "confidence_score": round(coverage, 1),
        "confidence_level": "high" if coverage >= 75 else "medium" if coverage >= 50 else "low",
        "confidence_label": "بالا" if coverage >= 75 else "متوسط" if coverage >= 50 else "پایین",
        "confidence_basis": "پوشش دادهٔ قابل محاسبه؛ این عدد احتمال موفقیت معامله نیست.",
        "breakout_confidence": "volume_not_in_model",
        "breakout_confidence_label": "حجم جزو این مدل امتیازدهی نیست",
        "risk": risk, "risk_score": round(risk_value, 1) if risk_value is not None else None,
        "risk_label": {"low":"کم","medium":"متوسط","high":"بالا","unavailable":"نامشخص"}[risk],
        "risk_basis": "نوسان تاریخی RV(30)، و در نبود آن تخمین از ATR(14).",
        "entry_quality": {"score": round(total, 1) if total is not None else None, "status": entry,
                          "label": {"suitable":"مناسب","confirmation":"نیازمند تأیید",
                                    "unsuitable":"نامناسب","unavailable":"داده کافی نیست"}[entry]},
        "signal": direction, "factors": factors, "positive_evidence": positive, "negative_evidence": negative,
        "explanation": [f"{names[item['name']]}: {item['evidence']}" for item in factors],
        "breakout_confirmation_note": "شاخص‌های فاقد داده امتیاز جایگزین نمی‌گیرند.",
        "data_limitations": limitations, "indicators": dashboard_tech,
        "support_resistance": levels, "support_levels": supports, "resistance_levels": resistances,
        "nearest_support": near_support, "nearest_resistance": near_resistance,
        "structural_invalidation_level": near_support.get("midpoint") if near_support else None,
        "decision_support": "امتیاز برآیند وزنی میانگین متحرک، نوسان‌گر و حمایت/مقاومت است؛ توصیه قطعی خرید یا فروش نیست.",
    }
