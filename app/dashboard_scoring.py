from __future__ import annotations

import math
from typing import Any

from .indicators import compute_indicators


DASHBOARD_SCORE_WEIGHTS = {
    "trend_structure": 0.40,
    "momentum": 0.30,
    "support_resistance": 0.15,
    "entry_quality": 0.15,
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
    """Price-only, four-family medium-term model for the dashboard assets."""
    bars = bars or []
    # Strip volume before computing indicators so it cannot affect either the
    # score or any returned dashboard indicator.
    price_bars = [{key: item for key, item in bar.items() if key != "volume"} for bar in bars]
    tech = compute_indicators(price_bars)
    indicators = tech.get("indicators", {})
    current = _number(tech.get("latest"))

    def value(key: str, field: str = "value") -> float | None:
        item = indicators.get(key)
        return _number(item.get(field)) if isinstance(item, dict) else None

    # Trend and structure: EMA/SMA readings are paired by horizon so duplicates
    # do not get independent votes. Long horizons and broad alignment matter more.
    horizon_weights = {20: 0.10, 50: 0.20, 100: 0.30, 200: 0.40}
    ma_levels: dict[int, float] = {}
    ma_position_rows: list[tuple[float | None, float]] = []
    ma_used: list[str] = []
    for period, weight in horizon_weights.items():
        readings = [value(f"{kind}({period})") for kind in ("EMA", "SMA")]
        readings = [reading for reading in readings if reading is not None and reading > 0]
        if current is None or current <= 0 or not readings:
            continue
        level = sum(readings) / len(readings)
        ma_levels[period] = level
        ma_position_rows.append((_signed_score((current - level) / level, 0.07), weight))
        ma_used.append(f"EMA/SMA({period})" if len(readings) == 2 else
                       f"EMA({period})" if value(f"EMA({period})") is not None else f"SMA({period})")
    ma_position = _weighted(ma_position_rows)
    ma_position_coverage = sum(weight for _, weight in ma_position_rows)
    alignment_weights = {(20, 50): 0.15, (50, 100): 0.30, (100, 200): 0.55}
    alignment_rows = [
        (_signed_score((ma_levels[shorter] - ma_levels[longer]) / current, 0.04), weight)
        for (shorter, longer), weight in alignment_weights.items()
        if current is not None and current > 0 and shorter in ma_levels and longer in ma_levels
    ]
    alignment = _weighted(alignment_rows)
    alignment_coverage = sum(weight for _, weight in alignment_rows)
    ma_score = _weighted([(ma_position, 0.70), (alignment, 0.30)])
    ma_coverage = 0.70 * ma_position_coverage + 0.30 * alignment_coverage
    ma_names = ma_used + (["چیدمان میانگین‌ها"] if alignment is not None else [])

    ichi = indicators.get("Ichimoku(9,26,52,26)", {})
    cloud_a = _number(ichi.get("senkou_a_at_current")) if isinstance(ichi, dict) else None
    cloud_b = _number(ichi.get("senkou_b_at_current")) if isinstance(ichi, dict) else None
    tenkan = _number(ichi.get("tenkan")) if isinstance(ichi, dict) else None
    kijun = _number(ichi.get("kijun")) if isinstance(ichi, dict) else None
    cloud_score = None
    cloud_thickness_pct = None
    if current is not None and current > 0 and cloud_a is not None and cloud_b is not None:
        # Position within the cloud is neutral; above/below it is scored smoothly.
        cloud_low, cloud_high = min(cloud_a, cloud_b), max(cloud_a, cloud_b)
        cloud_thickness_pct = (cloud_high - cloud_low) / current * 100
        if current > cloud_high:
            cloud_score = 50 + 50 * math.tanh((current - cloud_high) / current / 0.04)
        elif current < cloud_low:
            cloud_score = 50 - 50 * math.tanh((cloud_low - current) / current / 0.04)
        else:
            cloud_position = (current - cloud_low) / (cloud_high - cloud_low) if cloud_high > cloud_low else 0.5
            cloud_score = 45 + 10 * cloud_position
    tenkan_kijun_score = (_signed_score((tenkan - kijun) / current, 0.02)
                          if current and current > 0 and tenkan is not None and kijun is not None else None)
    ichi_score = _weighted([(cloud_score, 0.70), (tenkan_kijun_score, 0.30)])
    ichi_coverage = 0.70 * (1.0 if cloud_score is not None else 0.0) + 0.30 * (1.0 if tenkan_kijun_score is not None else 0.0)
    trend_score = _weighted([(ma_score, 0.75), (ichi_score, 0.25)])
    trend_conflict = (ma_score is not None and ichi_score is not None and abs(ma_score - ichi_score) >= 30)
    if trend_score is not None and trend_conflict:
        trend_score = 50 + (trend_score - 50) * 0.80
    trend_coverage = 0.75 * ma_coverage + 0.25 * ichi_coverage
    trend_used = ma_names + (["موقعیت قیمت نسبت به ابر کومو"] if cloud_score is not None else []) + (["تنکان نسبت به کیجون"] if tenkan_kijun_score is not None else [])
    trend_expected = [f"EMA/SMA({period})" for period in horizon_weights] + [
        "چیدمان میانگین‌ها", "موقعیت قیمت نسبت به ابر کومو", "تنکان نسبت به کیجون"
    ]

    # Momentum: bounded oscillators are one cluster; MACD, directional movement,
    # Aroon, and AO/Momentum are separate groups to reduce duplicate voting.
    osc_weights = {"RSI(14)": 0.40, "CCI(14)": 0.25, "StochRSI(14)": 0.20, "WR(14)": 0.15}
    osc_scores: list[tuple[float | None, float]] = []
    momentum_used: list[str] = []
    rsi = value("RSI(14)")
    if rsi is not None:
        # Above 70 remains strong; the level alone is not treated as a reversal.
        osc_scores.append((_clamp(50 + (rsi - 50) * 0.90), osc_weights["RSI(14)"]))
        momentum_used.append("RSI(14)")
    cci = value("CCI(14)")
    if cci is not None:
        osc_scores.append((_signed_score(cci, 150), osc_weights["CCI(14)"]))
        momentum_used.append("CCI(14)")
    stoch = value("StochRSI(14)")
    if stoch is not None:
        osc_scores.append((_clamp(50 + (stoch - 50) * 0.55), osc_weights["StochRSI(14)"]))
        momentum_used.append("StochRSI(14)")
    wr = value("WR(14)")
    if wr is not None:
        osc_scores.append((_clamp(50 + ((wr + 100) - 50) * 0.55), osc_weights["WR(14)"]))
        momentum_used.append("WR(14)")
    osc_score = _weighted(osc_scores)
    osc_coverage = sum(weight for _, weight in osc_scores)

    macd_line = value("MACD(12,26,9)")
    macd_hist = value("MACD(12,26,9)", "histogram")
    macd_signal = value("MACD(12,26,9)", "signal_line")
    macd_rows: list[tuple[float | None, float]] = []
    if macd_line is not None and current is not None and current > 0:
        macd_rows.append((_signed_score(macd_line / current, 0.01), 0.50))
    macd_difference = macd_line - macd_signal if macd_line is not None and macd_signal is not None else macd_hist
    if macd_difference is not None and current is not None and current > 0:
        # Histogram and (MACD - signal) encode the same difference; count it once.
        macd_rows.append((_signed_score(macd_difference / current, 0.003), 0.50))
    macd_score = _weighted(macd_rows)
    macd_coverage = sum(weight for _, weight in macd_rows)
    if macd_rows:
        momentum_used.append("MACD(12,26,9)")

    adx_item = indicators.get("ADX(14)", {})
    adx = value("ADX(14)")
    plus_di = _number(adx_item.get("plus_di")) if isinstance(adx_item, dict) else None
    minus_di = _number(adx_item.get("minus_di")) if isinstance(adx_item, dict) else None
    dmi_score = None
    dmi_coverage = 0.0
    if plus_di is not None and minus_di is not None:
        diff = (plus_di - minus_di) / max(plus_di + minus_di, 1.0)
        dmi_score = _clamp(50 + diff * 45)
        dmi_coverage = 1.0
        momentum_used.append("جهت DI+/DI−")
    aroon_item = indicators.get("Aroon(25)", {})
    aroon_up = _number(aroon_item.get("up")) if isinstance(aroon_item, dict) else None
    aroon_down = _number(aroon_item.get("down")) if isinstance(aroon_item, dict) else None
    aroon_score = _clamp(50 + (aroon_up - aroon_down) * 0.45) if aroon_up is not None and aroon_down is not None else None
    if aroon_score is not None:
        momentum_used.append("Aroon(25)")
    directional_score = _weighted([(dmi_score, 0.65), (aroon_score, 0.35)])
    directional_coverage = 0.65 * dmi_coverage + 0.35 * (1.0 if aroon_score is not None else 0.0)

    ao = value("AO(5,34)")
    mtm = value("MTM(6)")
    impulse_rows: list[tuple[float | None, float]] = []
    if ao is not None and current is not None and current > 0:
        impulse_rows.append((_signed_score(ao / current, 0.003), 0.50))
        momentum_used.append("AO(5,34)")
    if mtm is not None and current is not None and current > 0:
        impulse_rows.append((_signed_score(mtm / current, 0.003), 0.50))
        momentum_used.append("Momentum(6)")
    impulse_score = _weighted(impulse_rows)
    impulse_coverage = sum(weight for _, weight in impulse_rows)

    momentum_groups = [(osc_score, 0.40), (macd_score, 0.25),
                       (directional_score, 0.25), (impulse_score, 0.10)]
    momentum_score = _weighted(momentum_groups)
    momentum_coverage = (0.40 * osc_coverage + 0.25 * macd_coverage
                         + 0.25 * directional_coverage + 0.10 * impulse_coverage)
    momentum_expected = list(osc_weights) + ["MACD(12,26,9)", "جهت DI+/DI−",
                                              "Aroon(25)", "AO(5,34)", "Momentum(6)"]

    levels = _support_resistance_levels(bars, tech, current)
    supports = [row for row in levels if row["kind"] == "support"]
    resistances = [row for row in levels if row["kind"] == "resistance"]
    nearest_support = max(supports, key=lambda row: row["midpoint"], default=None)
    nearest_resistance = min(resistances, key=lambda row: row["midpoint"], default=None)
    atr = value("ATR(14)")
    sr_rows: list[tuple[float | None, float]] = []
    sr_used: list[str] = []
    if nearest_support and current is not None and current > 0:
        distance = ((current - nearest_support["midpoint"]) / atr if atr and atr > 0
                    else (current - nearest_support["midpoint"]) / current / 0.03)
        sr_rows.append((_clamp(82 - max(0.0, distance) * 16, 25, 82), 0.40))
        sr_used.append("حمایت معتبر نزدیک")
    if nearest_resistance and current is not None and current > 0:
        distance = ((nearest_resistance["midpoint"] - current) / atr if atr and atr > 0
                    else (nearest_resistance["midpoint"] - current) / current / 0.03)
        sr_rows.append((_clamp(22 + max(0.0, distance) * 18, 20, 80), 0.40))
        sr_used.append("مقاومت پیش‌رو")
    classic = tech.get("pivots", {}).get("Classic", {}) if isinstance(tech.get("pivots"), dict) else {}
    pivot = _number(classic.get("pivot")) if isinstance(classic, dict) else None
    if current is not None and current > 0 and pivot is not None:
        sr_rows.append((_signed_score((current - pivot) / current, 0.025), 0.20))
        sr_used.append("پیوت مرکزی کلاسیک روز قبل")
    support_resistance_score = _weighted(sr_rows)
    support_resistance_coverage = sum(weight for _, weight in sr_rows)
    support_distance = ((current - nearest_support["midpoint"]) / current * 100
                        if nearest_support and current else None)
    resistance_distance = ((nearest_resistance["midpoint"] - current) / current * 100
                           if nearest_resistance and current else None)

    # Entry quality scores location and volatility; band width is shown as a
    # measured value but not called a squeeze without its historical baseline.
    bb = indicators.get("BB(20)", {})
    bb_pct_b = _number(bb.get("%B")) if isinstance(bb, dict) else None
    bb_width = _number(bb.get("band_width")) if isinstance(bb, dict) else None
    keltner = indicators.get("KELTNER(16)", {})
    k_mid = _number(keltner.get("middle")) if isinstance(keltner, dict) else None
    k_upper = _number(keltner.get("upper")) if isinstance(keltner, dict) else None
    k_lower = _number(keltner.get("lower")) if isinstance(keltner, dict) else None
    ema50 = value("EMA(50)")
    ema50_distance_atr = None
    entry_rows: list[tuple[float | None, float]] = []
    entry_used: list[str] = []
    if current is not None and current > 0 and ema50 is not None:
        if atr is not None and atr > 0:
            ema50_distance_atr = abs(current - ema50) / atr
            extension_score = _clamp(100 - max(0.0, ema50_distance_atr - 0.5) * 18, 10, 100)
        else:
            extension_score = _clamp(100 - abs(current - ema50) / current * 800, 20, 100)
        entry_rows.append((extension_score, 0.25))
        entry_used.append("فاصله از EMA50")
    if bb_pct_b is not None:
        entry_rows.append((_clamp(100 - abs(bb_pct_b - 0.5) * 70, 20, 100), 0.20))
        entry_used.append("موقعیت در باند بولینگر")
    if current is not None and k_mid is not None and k_upper is not None and k_lower is not None and k_upper > k_lower:
        half_width = (k_upper - k_lower) / 2
        location = (current - k_mid) / half_width if half_width else 0
        abs_location = abs(location)
        keltner_score = 80 - 15 * abs_location if abs_location <= 1 else 65 - 20 * (abs_location - 1)
        entry_rows.append((_clamp(keltner_score, 15, 80), 0.20))
        entry_used.append("موقعیت در کانال کلتنر")

    rv30 = value("RV(30)")
    atr_pct = atr / current * 100 if atr is not None and current is not None and current > 0 else None
    risk_metric = rv30 if rv30 is not None else (atr_pct * math.sqrt(252) if atr_pct is not None else None)
    risk_basis = ("نوسان تحقق‌یافتهٔ ۳۰روزهٔ سالانه‌شده" if rv30 is not None else
                  "تقریب سالانه از ATR نسبی؛ جایگزین نوسان تحقق‌یافته" if atr_pct is not None else None)
    risk_score = _clamp(risk_metric / 50 * 100) if risk_metric is not None else None
    if risk_score is not None:
        entry_rows.append((100 - risk_score, 0.25))
        entry_used.append("ATR نسبی / نوسان تحقق‌یافته")
    # No relative band-width history is available to decide whether this is a squeeze.
    entry_coverage = sum(weight for _, weight in entry_rows)
    entry_score = _weighted(entry_rows)
    entry_expected = ["فاصله از EMA50", "موقعیت در باند بولینگر", "موقعیت در کانال کلتنر",
                      "ATR نسبی / نوسان تحقق‌یافته", "پهنای باند در مقایسه با تاریخچه"]

    family_data = {
        "trend_structure": (trend_score, trend_coverage, trend_used),
        "momentum": (momentum_score, momentum_coverage, momentum_used),
        "support_resistance": (support_resistance_score, support_resistance_coverage, sr_used),
        "entry_quality": (entry_score, entry_coverage, entry_used),
    }
    family_expected = {
        "trend_structure": trend_expected,
        "momentum": momentum_expected,
        "support_resistance": ["حمایت معتبر نزدیک", "مقاومت پیش‌رو", "پیوت مرکزی کلاسیک روز قبل"],
        "entry_quality": entry_expected,
    }
    family_scores: dict[str, dict[str, Any]] = {}
    for key, (score, coverage, used) in family_data.items():
        family_scores[key] = {
            "score": round(score, 1) if score is not None else None,
            "coverage_pct": round(coverage * 100, 1),
            "indicators": used,
            "missing_indicators": [name for name in family_expected[key] if name not in used],
        }

    valid_families = [(key, score, DASHBOARD_SCORE_WEIGHTS[key])
                      for key, (score, _, _) in family_data.items() if score is not None]
    valid_weight = sum(weight for _, _, weight in valid_families)
    technical_score = (sum(score * weight for _, score, weight in valid_families) / valid_weight
                       if valid_weight else None)
    effective_weights = ({key: round(weight / valid_weight * 100, 1)
                          for key, _, weight in valid_families} if valid_weight else {})
    data_coverage = sum(DASHBOARD_SCORE_WEIGHTS[key] * family_data[key][1]
                        for key in DASHBOARD_SCORE_WEIGHTS) * 100
    direction_score = _weighted([(trend_score, 0.65), (momentum_score, 0.35)])
    if direction_score is None:
        direction = "unavailable"
    elif direction_score >= 56:
        direction = "bullish"
    elif direction_score <= 44:
        direction = "bearish"
    else:
        direction = "neutral"

    if technical_score is None:
        score_band = "unavailable"
    elif technical_score >= 80:
        score_band = "very_strong"
    elif technical_score >= 70:
        score_band = "strong"
    elif technical_score >= 60:
        score_band = "relatively_positive"
    elif technical_score >= 45:
        score_band = "neutral"
    elif technical_score >= 30:
        score_band = "weak"
    else:
        score_band = "very_weak"

    if risk_metric is None:
        risk = "unavailable"
    elif risk_metric < 15:
        risk = "low"
    elif risk_metric <= 30:
        risk = "medium"
    else:
        risk = "high"
    risk_label = {"low": "کم", "medium": "متوسط", "high": "بالا", "unavailable": "نامشخص"}[risk]
    if adx is not None:
        trend_strength = "strong" if adx >= 25 else "medium" if adx >= 20 else "weak"
    elif alignment_rows:
        aligned = [score for score, _ in alignment_rows if score is not None and
                   (score >= 60 if direction == "bullish" else score <= 40 if direction == "bearish" else False)]
        agreement = len(aligned) / len(alignment_rows)
        trend_strength = "strong" if len(alignment_rows) >= 3 and agreement >= 0.8 else "medium" if agreement >= 0.6 else "weak"
    else:
        trend_strength = "unavailable"

    entry_status = ("unavailable" if entry_score is None else "suitable" if entry_score >= 70
                    else "confirmation" if entry_score >= 45 else "unsuitable")
    entry_label = {"suitable": "مساعد", "confirmation": "نیازمند اصلاح و تثبیت",
                   "unsuitable": "نامساعد", "unavailable": "داده کافی نیست"}[entry_status]
    # Confidence describes data coverage and internal consistency, not success
    # odds. Volume absence limits breakout confirmation separately.
    confidence = data_coverage
    confidence_level = "high" if confidence >= 75 else "medium" if confidence >= 50 else "low"
    if trend_conflict:
        confidence_level = {"high": "medium", "medium": "low", "low": "low"}[confidence_level]
    confidence_label = {"high": "بالا", "medium": "متوسط", "low": "پایین"}[confidence_level]

    family_names = {"trend_structure": "روند و ساختار قیمت", "momentum": "مومنتوم و قدرت روند",
                    "support_resistance": "حمایت، مقاومت و موقعیت قیمت",
                    "entry_quality": "نوسان و کیفیت نقطه ورود"}
    score_rows = [(key, float(score)) for key, score, _ in valid_families]
    positive_evidence = [{"family": key, "name": family_names[key], "score": round(score, 1)}
                         for key, score in sorted(score_rows, key=lambda row: row[1], reverse=True) if score >= 60][:2]
    negative_evidence = [{"family": key, "name": family_names[key], "score": round(score, 1)}
                         for key, score in sorted(score_rows, key=lambda row: row[1]) if score <= 40][:2]
    factors = [{"name": key, "score": round(float(score), 1), "weight": DASHBOARD_SCORE_WEIGHTS[key],
                "evidence": ", ".join(family_data[key][2])}
               for key, score, _ in valid_families]

    daily_return_pct = None
    if current is not None and len(bars) > 1:
        previous_close = _number(bars[-2].get("close"))
        if previous_close is not None and previous_close > 0:
            daily_return_pct = (current / previous_close - 1) * 100
    levels_support = [row for row in supports if row.get("midpoint") is not None]
    levels_resistance = [row for row in resistances if row.get("midpoint") is not None]
    sma50, sma100, ema100 = value("SMA(50)"), value("SMA(100)"), value("EMA(100)")
    immediate_exit_base = sma50 or ema50 or (nearest_support["midpoint"] if nearest_support else None)
    structural_exit_base = sma100 or ema100 or (nearest_support["midpoint"] if nearest_support else None)
    medium_exit = round(immediate_exit_base * 0.995) if immediate_exit_base is not None else None
    structural_exit = round(structural_exit_base * 0.998) if structural_exit_base is not None else None
    if medium_exit is not None and structural_exit is not None and structural_exit >= medium_exit:
        structural_exit = round(medium_exit * 0.985)

    limitations = [
        "مدل عمداً حجم و جریان معاملات را وارد امتیاز نمی‌کند؛ شکست قیمت بدون تأیید حجم اطمینان کمتری دارد.",
        "از یک تصویر روزانه نمی‌توان شیب خطوط، واگرایی یا وقوع کراس تأییدشده را نتیجه گرفت.",
        "پهنای فعلی باند بولینگر موجود است، اما بدون سابقهٔ آن نمی‌توان فشردگی یا انبساط را قطعی نامید.",
    ]
    if support_resistance_score is None:
        limitations.append("سطح معتبر حمایت، مقاومت یا پیوت روز قبل در دادهٔ موجود نیست؛ این خانواده از امتیاز حذف شد.")
    if rv30 is None and atr_pct is not None:
        limitations.append("ریسک نوسان با تقریب سالانه از ATR نسبی سنجیده شد، چون نوسان تحقق‌یافتهٔ ۳۰روزه موجود نبود.")

    # Hide volume-derived fields from the dashboard analysis payload as well as
    # excluding them from all model scores.
    volume_indicator_keys = {"MFI(14)", "OBV(20)", "VMACD(12,26)", "VRSI(14)"}
    dashboard_tech = dict(tech)
    dashboard_tech["indicators"] = {key: item for key, item in indicators.items()
                                    if key not in volume_indicator_keys}
    dashboard_tech.pop("volume_analysis", None)
    return {
        "symbol": symbol,
        "data_timestamp": bars[-1].get("timestamp") if bars else None,
        "price": current,
        "daily_return_pct": daily_return_pct,
        "medium_term_exit_price": medium_exit,
        "structural_exit_price": structural_exit,
        "medium_term_exit": {
            "price": medium_exit,
            "trigger": "تثبیت قیمت زیر SMA(50) یا حمایت معتبر نزدیک",
            "action": "این سطح یک هشدار تکنیکال است؛ شکست را با دادهٔ بسته‌شدن کندل بررسی کن.",
            "structural_price": structural_exit,
            "structural_trigger": "شکست و تثبیت زیر SMA(100) یا حمایت ساختاری موجود",
        },
        "trend": direction,
        "short_term_trend": ("unavailable" if current is None or value("EMA(20)") is None else
                              "bullish" if current > value("EMA(20)") else "bearish" if current < value("EMA(20)") else "neutral"),
        "medium_term_trend": direction,
        "long_term_trend": ("unavailable" if current is None or value("EMA(200)") is None else
                             "bullish" if current > value("EMA(200)") else "bearish" if current < value("EMA(200)") else "neutral"),
        "trend_direction_score": round(direction_score, 1) if direction_score is not None else None,
        "trend_strength": trend_strength,
        "technical_score": round(technical_score, 1) if technical_score is not None else None,
        "score_method": "dashboard_four_family_midterm_no_volume_v1",
        "score_origin": "AliVest",
        "score_profile": "four_assets_midterm_price_only",
        "score_weights": {key: round(weight * 100) for key, weight in DASHBOARD_SCORE_WEIGHTS.items()},
        "effective_score_weights": effective_weights,
        "family_scores": family_scores,
        "score_band": score_band,
        "score_validation": "initial_unbacktested",
        "score_breakdown": {
            **{key: data[0] for key, data in family_data.items()},
            "family_coverage_pct": {key: round(data[1] * 100, 1) for key, data in family_data.items()},
            "available_weight": round(valid_weight * 100, 1),
            "direction_score": round(direction_score, 1) if direction_score is not None else None,
            "rsi": rsi,
            "adx": adx,
            "atr_pct": round(atr_pct, 3) if atr_pct is not None else None,
            "realized_volatility_pct": rv30,
            "ema50_distance_atr": round(ema50_distance_atr, 2) if ema50_distance_atr is not None else None,
            "bollinger_band_width": bb_width,
            "ichimoku_cloud_thickness_pct": round(cloud_thickness_pct, 3) if cloud_thickness_pct is not None else None,
            "trend_structure_conflict": trend_conflict,
            "support_distance_pct": round(support_distance, 2) if support_distance is not None else None,
            "resistance_distance_pct": round(resistance_distance, 2) if resistance_distance is not None else None,
            "front_resistance_count": len(resistances),
            "near_resistance_count": sum(1 for row in resistances if current and (row["midpoint"] - current) / current <= 0.10),
        },
        "data_coverage_pct": round(data_coverage, 1),
        "available_family_weight_pct": round(valid_weight * 100, 1),
        "confidence": round(confidence, 1),
        "confidence_score": round(confidence, 1),
        "confidence_level": confidence_level,
        "confidence_label": confidence_label,
        "confidence_basis": "اطمینان از پوشش داده و سازگاری ساختار میانگین‌ها با ایچیموکو به‌دست می‌آید و احتمال موفقیت معامله نیست. به دلیل نبود حجم، اطمینان به تأیید شکست‌های قیمتی محدود است.",
        "breakout_confidence": "limited_without_volume",
        "breakout_confidence_label": "محدود؛ حجم در مدل لحاظ نمی‌شود",
        "risk": risk,
        "risk_score": round(risk_score, 1) if risk_score is not None else None,
        "risk_label": risk_label,
        "risk_basis": risk_basis,
        "entry_quality": {"score": round(entry_score, 1) if entry_score is not None else None,
                          "status": entry_status, "label": entry_label},
        "signal": direction,
        "factors": factors,
        "positive_evidence": positive_evidence,
        "negative_evidence": negative_evidence,
        "explanation": [f"{family_names[item['name']]}: {item['evidence']}" for item in factors],
        "breakout_confirmation_note": "حجم در مدل لحاظ نمی‌شود؛ از تأیید شکست بر اساس حجم یا ورود پول ادعا نمی‌شود.",
        "data_limitations": limitations + (["ساختار میانگین‌ها و ایچیموکو هم‌جهت نیستند؛ امتیاز روند به سمت خنثی تعدیل و اطمینان کاهش داده شد."] if trend_conflict else []),
        "indicators": dashboard_tech,
        "support_resistance": levels,
        "support_levels": levels_support,
        "resistance_levels": levels_resistance,
        "nearest_support": nearest_support,
        "nearest_resistance": nearest_resistance,
        "structural_invalidation_level": nearest_support.get("midpoint") if nearest_support else None,
        "decision_support": "این امتیاز جمع‌بندی تکنیکال میان‌مدت بر پایهٔ قیمت است؛ پیش‌بینی قطعی یا توصیهٔ خرید و فروش نیست.",
    }
