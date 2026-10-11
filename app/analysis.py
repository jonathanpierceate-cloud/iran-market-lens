from __future__ import annotations

from datetime import datetime, timezone
import math
import re
from typing import Any

from .indicators import compute_indicators
from .fund_scoring import score_fund_model


# Four dashboard assets use the five-family medium-term model.
DASHBOARD_SCORE_WEIGHTS = {
    "trend_structure": 0.35,
    "momentum": 0.25,
    "support_resistance": 0.15,
    "entry_quality": 0.15,
    "volume_confirmation": 0.10,
}
MEDIUM_TERM_SCORE_WEIGHTS = DASHBOARD_SCORE_WEIGHTS


def _num(item: dict[str, Any] | None) -> float | None:
    val = item.get("value") if isinstance(item, dict) else None
    try:
        out = float(val)
        return out if math.isfinite(out) else None
    except (TypeError, ValueError):
        return None


def _trend(current: float | None, average: float | None, stronger: float | None = None) -> str:
    if current is None or average is None:
        return "unavailable"
    if current > average and (stronger is None or average > stronger):
        return "bullish"
    if current < average and (stronger is None or average < stronger):
        return "bearish"
    return "neutral"


def support_resistance(bars: list[dict[str, Any]], indicators: dict[str, Any]) -> list[dict[str, Any]]:
    if not bars:
        return []
    close = float(bars[-1]["close"])
    points: list[tuple[str, float, str]] = []
    for i in range(2, len(bars) - 2):
        high = bars[i].get("high"); low = bars[i].get("low")
        if high is not None and all(high >= (bars[j].get("high") or high) for j in range(i-2, i+3) if j != i):
            if float(high) > close: points.append(("resistance", float(high), "swing high"))
        if low is not None and all(low <= (bars[j].get("low") or low) for j in range(i-2, i+3) if j != i):
            if float(low) < close: points.append(("support", float(low), "swing low"))
    periods = [20, 50, 200]
    for p in periods:
        data = [float(b["close"]) for b in bars[-p:] if b.get("close") is not None]
        if len(data) >= min(p, 20):
            value = sum(data) / len(data)
            points.append(("support" if value < close else "resistance", value, f"SMA{p}"))
    pivots = indicators.get("pivots", {}).get("Classic", {})
    for key in ["S1", "S2", "S3", "R1", "R2", "R3"]:
        value = pivots.get(key)
        if value is not None:
            points.append(("support" if key.startswith("S") else "resistance", float(value), f"Classic {key}"))
    # Cluster nearby evidence into zones, preserving the component methods for explanation.
    result = []
    for kind in ["support", "resistance"]:
        candidates = sorted([(price, method) for t, price, method in points if t == kind], key=lambda x: x[0])
        clusters: list[list[tuple[float, str]]] = []
        for candidate in candidates:
            if clusters and abs(candidate[0] - clusters[-1][-1][0]) <= max(close * 0.0075, 1e-9):
                clusters[-1].append(candidate)
            else:
                clusters.append([candidate])
        clusters.sort(key=lambda group: abs(sum(x[0] for x in group) / len(group) - close))
        for group in clusters[:3]:
            level_low = min(x[0] for x in group); level_high = max(x[0] for x in group)
            methods = sorted({x[1] for x in group})
            strength = "strong" if len(methods) >= 3 else "medium" if len(methods) == 2 else "watch"
            result.append({"kind": kind, "low": level_low, "high": level_high,
                           "midpoint": (level_low + level_high) / 2, "strength": strength,
                           "methods": methods, "method": "; ".join(methods)})
    return result


def analyze(symbol: str, bars: list[dict[str, Any]],
            weights: dict[str, float] | None = None) -> dict[str, Any]:
    score_weights = weights or DASHBOARD_SCORE_WEIGHTS
    tech = compute_indicators(bars)
    indicators = tech["indicators"]
    current = tech.get("latest")
    volume = tech.get("volume_analysis", {})

    def numeric(value: Any) -> float | None:
        try:
            result = float(value)
            return result if math.isfinite(result) else None
        except (TypeError, ValueError, OverflowError):
            return None

    def indicator_value(key: str, field: str = "value") -> float | None:
        item = indicators.get(key)
        return numeric(item.get(field)) if isinstance(item, dict) else None

    def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
        return min(high, max(low, value))

    def signed_score(value: float, scale: float) -> float:
        if scale <= 0:
            return 50.0
        return clamp(50.0 + 50.0 * math.tanh(value / scale))

    def weighted_mean(rows: list[tuple[float | None, float]]) -> float | None:
        valid = [(value, weight) for value, weight in rows
                 if value is not None and weight > 0]
        total = sum(weight for _, weight in valid)
        return sum(value * weight for value, weight in valid) / total if total else None

    # Trend: collapse EMA/SMA duplicates by horizon, then give Ichimoku a
    # separate, smaller contribution to limit overlapping evidence.
    period_weights = {20: 0.15, 50: 0.25, 100: 0.25, 200: 0.35}
    ma_levels: dict[int, float] = {}
    ma_position_scores: list[tuple[float, float]] = []
    ma_used: list[str] = []
    for period, horizon_weight in period_weights.items():
        readings = [indicator_value(f"{kind}({period})")
                    for kind in ("EMA", "SMA")]
        readings = [value for value in readings if value is not None and value > 0]
        if current is None or current <= 0 or not readings:
            continue
        level = sum(readings) / len(readings)
        ma_levels[period] = level
        ma_position_scores.append((signed_score((current - level) / level, 0.05), horizon_weight))
        ma_used.append(f"EMA/SMA({period})" if len(readings) == 2 else (f"EMA({period})" if indicator_value(f"EMA({period})") is not None else f"SMA({period})"))
    ma_position = weighted_mean(ma_position_scores)
    ma_alignment_rows = [signed_score((ma_levels[shorter] - ma_levels[longer]) / current, 0.03)
                         for shorter, longer in zip((20, 50, 100), (50, 100, 200))
                         if current and shorter in ma_levels and longer in ma_levels]
    ma_alignment = sum(ma_alignment_rows) / len(ma_alignment_rows) if ma_alignment_rows else None
    ma_score = weighted_mean([(ma_position, 0.8), (ma_alignment, 0.2)])
    ma_coverage = (0.8 * len(ma_position_scores) / len(period_weights)
                   + (0.2 if ma_alignment is not None else 0.0))

    ichi = indicators.get("Ichimoku(9,26,52,26)", {})
    cloud_low = numeric(ichi.get("senkou_a_at_current")) if isinstance(ichi, dict) else None
    cloud_high = numeric(ichi.get("senkou_b_at_current")) if isinstance(ichi, dict) else None
    tenkan = numeric(ichi.get("tenkan")) if isinstance(ichi, dict) else None
    kijun = numeric(ichi.get("kijun")) if isinstance(ichi, dict) else None
    ichimoku_parts: list[tuple[float | None, float]] = []
    if current is not None and current > 0 and cloud_low is not None and cloud_high is not None:
        low, high = min(cloud_low, cloud_high), max(cloud_low, cloud_high)
        cloud_score = 50.0 if low <= current <= high else signed_score((current - (high if current > high else low)) / current, 0.03)
        ichimoku_parts.append((cloud_score, 0.7))
    if current is not None and current > 0 and tenkan is not None and kijun is not None:
        ichimoku_parts.append((signed_score((tenkan - kijun) / current, 0.01), 0.3))
    ichimoku_score = weighted_mean(ichimoku_parts)
    ichimoku_coverage = 0.7 * (1.0 if cloud_low is not None and cloud_high is not None else 0.0) + 0.3 * (1.0 if tenkan is not None and kijun is not None else 0.0)
    trend_score = weighted_mean([(ma_score, 0.8), (ichimoku_score, 0.2)])
    trend_coverage = 0.8 * ma_coverage + 0.2 * ichimoku_coverage
    trend_used = ma_used + (["Ichimoku cloud / Tenkan / Kijun"] if ichimoku_score is not None else [])

    # Momentum indicators are grouped so several similar oscillators do not
    # outweigh independent evidence such as MACD, Aroon, or DI direction.
    momentum_groups: dict[str, list[float]] = {"directional": [], "price_momentum": [], "bounded_oscillators": []}
    momentum_used: list[str] = []
    rsi = indicator_value("RSI(14)")
    if rsi is not None:
        momentum_groups["bounded_oscillators"].append(clamp(rsi)); momentum_used.append("RSI(14)")
    cci = indicator_value("CCI(14)")
    if cci is not None:
        momentum_groups["price_momentum"].append(clamp(50.0 + clamp(cci, -200.0, 200.0) * 0.15)); momentum_used.append("CCI(14)")
    stoch_rsi = indicator_value("StochRSI(14)")
    if stoch_rsi is not None:
        momentum_groups["bounded_oscillators"].append(clamp(stoch_rsi)); momentum_used.append("StochRSI(14)")
    wr = indicator_value("WR(14)")
    if wr is not None:
        momentum_groups["bounded_oscillators"].append(clamp(wr + 100.0)); momentum_used.append("WR(14)")
    ao = indicator_value("AO(5,34)")
    mtm = indicator_value("MTM(6)")
    if ao is not None and current is not None and current > 0:
        momentum_groups["price_momentum"].append(signed_score(ao, current * 0.003)); momentum_used.append("AO(5,34)")
    if mtm is not None and current is not None and current > 0:
        momentum_groups["price_momentum"].append(signed_score(mtm, current * 0.003)); momentum_used.append("MTM(6)")
    macd_line = indicator_value("MACD(12,26,9)")
    macd_histogram = indicator_value("MACD(12,26,9)", "histogram")
    if macd_line is not None and current is not None and current > 0:
        line_score = signed_score(macd_line, current * 0.01)
        macd_score = weighted_mean([(line_score, 0.55),
                                    (signed_score(macd_histogram, current * 0.003) if macd_histogram is not None else None, 0.45)])
        momentum_groups["directional"].append(macd_score); momentum_used.append("MACD(12,26,9)")
    adx_item = indicators.get("ADX(14)", {})
    adx_value = indicator_value("ADX(14)")
    plus_di = numeric(adx_item.get("plus_di")) if isinstance(adx_item, dict) else None
    minus_di = numeric(adx_item.get("minus_di")) if isinstance(adx_item, dict) else None
    if adx_value is not None and plus_di is not None and minus_di is not None:
        di_direction = 1 if plus_di > minus_di else -1 if plus_di < minus_di else 0
        momentum_groups["directional"].append(clamp(50 + di_direction * 50 * min(1.0, adx_value / 40.0)))
        momentum_used.append("ADX(14) + DI+/DI−")
    aroon_item = indicators.get("Aroon(25)", {})
    aroon_up = numeric(aroon_item.get("up")) if isinstance(aroon_item, dict) else None
    aroon_down = numeric(aroon_item.get("down")) if isinstance(aroon_item, dict) else None
    if aroon_up is not None and aroon_down is not None:
        momentum_groups["directional"].append(clamp(50.0 + (aroon_up - aroon_down) / 2.0))
        momentum_used.append("Aroon(25)")
    if volume.get("available"):
        mfi = indicator_value("MFI(14)")
        if mfi is not None:
            momentum_groups["bounded_oscillators"].append(clamp(mfi)); momentum_used.append("MFI(14)")
    group_scores = [sum(values) / len(values) for values in momentum_groups.values() if values]
    momentum_score = sum(group_scores) / len(group_scores) if group_scores else None
    momentum_coverage = len(momentum_used) / 10.0

    levels = support_resistance(bars, tech)
    supports = [row for row in levels if row["kind"] == "support"]
    resistances = [row for row in levels if row["kind"] == "resistance"]
    nearest_support = max((row for row in supports if current is not None and row["midpoint"] < current),
                          key=lambda row: row["midpoint"], default=None)
    nearest_resistance = min((row for row in resistances if current is not None and row["midpoint"] > current),
                             key=lambda row: row["midpoint"], default=None)
    front_resistances = [row["midpoint"] for row in resistances if current is not None and row["midpoint"] > current]
    near_resistances = [value for value in front_resistances if current and (value - current) / current <= 0.10]
    atr = indicator_value("ATR(14)")
    sr_parts: list[tuple[float | None, float]] = []
    sr_used: list[str] = []
    if current is not None and current > 0 and nearest_support:
        distance = max(0.0, (current - nearest_support["midpoint"]) / (atr if atr and atr > 0 else current * 0.03))
        sr_parts.append((clamp(78.0 - distance * 13.0, 25.0, 78.0), 0.4))
        sr_used.append("حمایت نزدیک")
    if current is not None and current > 0 and nearest_resistance:
        headroom = max(0.0, (nearest_resistance["midpoint"] - current) / (atr if atr and atr > 0 else current * 0.03))
        sr_parts.append((clamp(28.0 + headroom * 14.0, 28.0, 88.0), 0.4))
        sr_used.append("مقاومت نزدیک")
    classic_pivot = numeric((tech.get("pivots", {}).get("Classic") or {}).get("pivot"))
    if current is not None and current > 0 and classic_pivot is not None:
        sr_parts.append((signed_score((current - classic_pivot) / current, 0.01), 0.2))
        sr_used.append("پیوت مرکزی")
    support_resistance_score = weighted_mean(sr_parts)
    support_resistance_coverage = len(sr_parts) / 3.0
    near_resistance_distance = ((nearest_resistance["midpoint"] - current) / current * 100
                                if nearest_resistance and current else None)
    support_distance = ((current - nearest_support["midpoint"]) / current * 100
                        if nearest_support and current else None)

    # Entry quality is kept separate from direction: extension from EMA50,
    # position within the Bollinger range, and available volatility evidence.
    quality_parts: list[float] = []
    ema50 = indicator_value("EMA(50)")
    ema50_distance_atr = None
    if current is not None and current > 0 and ema50 is not None:
        if atr is not None and atr > 0:
            ema50_distance_atr = abs(current - ema50) / atr
            quality_parts.append(clamp(100.0 - max(0.0, ema50_distance_atr - 0.5) * 18.0, 10.0, 100.0))
        else:
            quality_parts.append(clamp(100.0 - abs(current - ema50) / current * 800.0, 20.0, 100.0))
    bb_pct_b = indicator_value("BB(20)", "%B")
    if bb_pct_b is not None:
        quality_parts.append(clamp(100.0 - abs(bb_pct_b - 0.5) * 100.0, 20.0, 100.0))
    rv30 = indicator_value("RV(30)")
    atr_pct = (atr / current * 100.0) if atr is not None and current is not None and current > 0 else None
    risk_metric = rv30 if rv30 is not None else (atr_pct * math.sqrt(252.0) if atr_pct is not None else None)
    risk_basis = "RV(30) سالانه‌شده" if rv30 is not None else "برآورد نوسان سالانه از ATR(14) نسبی" if atr_pct is not None else None
    risk_score = clamp((risk_metric / 60.0) * 100.0) if risk_metric is not None else None
    if risk_score is not None:
        quality_parts.append(clamp(100.0 - risk_score * 0.8))
    entry_quality_score = sum(quality_parts) / len(quality_parts) if quality_parts else None
    entry_quality_coverage = len(quality_parts) / 3.0

    daily_return_pct = ((current / bars[-2]["close"] - 1.0) * 100.0
                        if current is not None and len(bars) > 1 and bars[-2].get("close") else None)
    daily_direction = 1 if daily_return_pct is not None and daily_return_pct > 0 else -1 if daily_return_pct is not None and daily_return_pct < 0 else 0
    volume_parts: list[float] = []
    volume_used: list[str] = []
    obv_item = indicators.get("OBV(20)", {})
    obv_value = numeric(obv_item.get("value")) if isinstance(obv_item, dict) else None
    obv_average = numeric(obv_item.get("obv_sma20")) if isinstance(obv_item, dict) else None
    if obv_value is not None and obv_average is not None:
        volume_parts.append(75.0 if obv_value > obv_average else 25.0 if obv_value < obv_average else 50.0)
        volume_used.append("OBV(20)")
    last_volume = numeric(volume.get("last_volume"))
    volume_average = numeric(volume.get("volume_sma20"))
    relative_volume = last_volume / volume_average if last_volume is not None and volume_average and volume_average > 0 else None
    if relative_volume is not None and daily_direction:
        volume_parts.append(clamp(50.0 + daily_direction * min(35.0, max(0.0, relative_volume - 1.0) * 25.0)))
        volume_used.append("حجم نسبی روزانه")
    vmacd = indicator_value("VMACD(12,26)")
    if vmacd is not None and daily_direction:
        volume_parts.append(50.0 + daily_direction * 25.0 if vmacd > 0 else 50.0)
        volume_used.append("VMACD(12,26)")
    vrsi = indicator_value("VRSI(14)")
    if vrsi is not None and daily_direction:
        volume_parts.append(clamp(50.0 + daily_direction * (vrsi - 50.0) * 0.5))
        volume_used.append("VRSI(14)")
    volume_score = sum(volume_parts) / len(volume_parts) if volume_parts else None
    volume_coverage = len(volume_parts) / 4.0

    family_data = {
        "trend_structure": (trend_score, trend_coverage, trend_used),
        "momentum": (momentum_score, momentum_coverage, momentum_used),
        "support_resistance": (support_resistance_score, support_resistance_coverage, sr_used),
        "entry_quality": (entry_quality_score, entry_quality_coverage,
                          [name for name, present in (("فاصله از EMA50", ema50 is not None),
                          ("موقعیت در باند بولینگر", bb_pct_b is not None),
                          ("معیار نوسان", risk_metric is not None)) if present]),
        "volume_confirmation": (volume_score, volume_coverage, volume_used),
    }
    momentum_expected = ["RSI(14)", "CCI(14)", "StochRSI(14)", "WR(14)", "AO(5,34)",
                         "MTM(6)", "MACD(12,26,9)", "ADX(14) + DI+/DI−", "Aroon(25)", "MFI(14)"]
    family_expected = {
        "trend_structure": ([f"EMA/SMA({period})" for period in period_weights]
                            + ["چیدمان میانگین‌ها", "ابر ایچیموکو"]),
        "momentum": momentum_expected,
        "support_resistance": ["حمایت نزدیک", "مقاومت نزدیک", "پیوت مرکزی"],
        "entry_quality": ["فاصله از EMA50", "موقعیت در باند بولینگر", "معیار نوسان"],
        "volume_confirmation": ["OBV(20)", "حجم نسبی روزانه", "VMACD(12,26)", "VRSI(14)"],
    }
    family_present = {
        "trend_structure": ([f"EMA/SMA({period})" for period in ma_levels]
                            + (["چیدمان میانگین‌ها"] if ma_alignment is not None else [])
                            + (["ابر ایچیموکو"] if ichimoku_score is not None else [])),
        "momentum": momentum_used,
        "support_resistance": sr_used,
        "entry_quality": [name for name, present in (("فاصله از EMA50", ema50 is not None),
                         ("موقعیت در باند بولینگر", bb_pct_b is not None),
                         ("معیار نوسان", risk_metric is not None)) if present],
        "volume_confirmation": volume_used,
    }
    family_scores = {
        key: {"score": round(score, 1) if score is not None else None,
              "coverage_pct": round(coverage * 100.0, 1), "indicators": used,
              "missing_indicators": [name for name in family_expected[key]
                                     if name not in family_present[key]]}
        for key, (score, coverage, used) in family_data.items()
    }
    available_families = [(key, family_data[key][0], score_weights[key])
                          for key in score_weights if family_data[key][0] is not None]
    available_weight = sum(weight for _, _, weight in available_families)
    technical_score = (sum(value * weight for _, value, weight in available_families) / available_weight
                       if available_weight else None)
    effective_weights = {key: round(weight / available_weight * 100.0, 1)
                         for key, _, weight in available_families} if available_weight else {}
    data_coverage = (sum(score_weights[key] * family_data[key][1] for key in score_weights)
                     / sum(score_weights.values()) * 100.0)
    direction_score = weighted_mean([(trend_score, 0.65), (momentum_score, 0.35)])
    if direction_score is None:
        direction = "unavailable"
    elif direction_score >= 60:
        direction = "bullish"
    elif direction_score <= 40:
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
    elif risk_metric < 30:
        risk = "medium"
    elif risk_metric < 45:
        risk = "high"
    else:
        risk = "very_high"
    risk_label = {"low": "کم", "medium": "متوسط", "high": "زیاد", "very_high": "بسیار زیاد", "unavailable": "نامشخص"}[risk]

    di_agrees = (None if direction == "unavailable" or plus_di is None or minus_di is None
                 else (plus_di > minus_di if direction == "bullish" else plus_di < minus_di if direction == "bearish" else False))
    if direction in {"neutral", "unavailable"}:
        trend_strength = "weak"
    elif adx_value is not None:
        if di_agrees is False:
            trend_strength = "weak"
        else:
            trend_strength = "strong" if adx_value >= 25 else "medium" if adx_value >= 20 else "weak"
    else:
        directional_evidence = [score for score in [*([value for value, _ in ma_position_scores]),
                              ichimoku_score, momentum_score] if score is not None]
        aligned = [value for value in directional_evidence
                   if (value >= 55 if direction == "bullish" else value <= 45)]
        agreement = len(aligned) / len(directional_evidence) if directional_evidence else 0.0
        trend_strength = "strong" if len(directional_evidence) >= 3 and agreement >= 0.8 else "medium" if agreement >= 0.6 else "weak"

    entry_label = ("unavailable" if entry_quality_score is None else "suitable" if entry_quality_score >= 65
                   else "confirmation" if entry_quality_score >= 45 else "unsuitable")
    quality_label = {"suitable": "مناسب", "confirmation": "نیازمند تأیید",
                     "unsuitable": "نامناسب", "unavailable": "داده کافی نیست"}[entry_label]
    coverage_level = "high" if data_coverage >= 75 else "medium" if data_coverage >= 50 else "low"
    confidence_level = {"high": "بالا", "medium": "متوسط", "low": "پایین"}[coverage_level]

    family_names = {"trend_structure": "روند و ساختار", "momentum": "مومنتوم",
                    "support_resistance": "حمایت و مقاومت", "entry_quality": "کیفیت ورود",
                    "volume_confirmation": "تأیید حجم"}
    valid_scores = [(key, float(value)) for key, value, _ in available_families]
    positive_evidence = [{"family": key, "name": family_names[key], "score": round(value, 1)}
                         for key, value in sorted(valid_scores, key=lambda row: row[1], reverse=True) if value >= 60][:2]
    negative_evidence = [{"family": key, "name": family_names[key], "score": round(value, 1)}
                         for key, value in sorted(valid_scores, key=lambda row: row[1]) if value <= 40][:2]
    factors = [{"name": key, "score": round(float(value), 1), "weight": score_weights[key],
                "evidence": ", ".join(family_data[key][2])}
               for key, value, _ in available_families]

    support_levels = [row for row in supports if row.get("midpoint") is not None]
    resistance_levels = [row for row in resistances if row.get("midpoint") is not None]
    exit_support = min((row["midpoint"] for row in supports if current is not None and row["midpoint"] < current), default=None)
    sma50 = indicator_value("SMA(50)")
    ema100 = indicator_value("EMA(100)")
    sma100 = indicator_value("SMA(100)")
    immediate_exit_base = sma50 or ema50 or (nearest_support["midpoint"] if nearest_support else None)
    structural_exit_base = sma100 or ema100 or exit_support
    medium_term_exit_price = round(immediate_exit_base * 0.995) if immediate_exit_base is not None else None
    structural_exit_price = round(structural_exit_base * 0.998) if structural_exit_base is not None else None
    if structural_exit_price is not None and medium_term_exit_price is not None and structural_exit_price >= medium_term_exit_price:
        structural_exit_price = round(medium_term_exit_price * 0.985)

    limitations = []
    if volume_score is None:
        limitations.append("حجم معتبر برای این دارایی در دادهٔ فعلی موجود نیست و وزن این عامل حذف شد.")
    if support_resistance_score is None:
        limitations.append("سطح معتبر حمایت، مقاومت یا پیوت در دادهٔ فعلی موجود نیست.")
    if risk_metric is None:
        limitations.append("ATR و نوسان تحقق‌یافته برای برآورد ریسک در دسترس نیست.")
    if symbol == "GOLD":
        limitations.append("حجم اونس ممکن است حجم نمایندهٔ کل بازار نباشد؛ به‌عنوان تأیید محدود خوانده شود.")
    elif symbol == "USD_IR_FREE":
        limitations.append("حجم ثبت‌شده برای دلار به تومان از منبع محدود است و نمایندهٔ کل بازار OTC نیست.")

    return {
        "symbol": symbol, "data_timestamp": bars[-1].get("timestamp") if bars else None,
        "price": current, "daily_return_pct": daily_return_pct,
        "medium_term_exit_price": medium_term_exit_price,
        "structural_exit_price": structural_exit_price,
        "medium_term_exit": {
            "price": medium_term_exit_price,
            "trigger": "تثبیت قیمت زیر SMA(50) یا حمایت میانی",
            "action": "تثبیت زیر این سطح یعنی ریسک کوتاه‌مدت بالا رفته است؛ خرید جدید را متوقف و خروج را مرحله‌ای اجرا کن.",
            "structural_price": structural_exit_price,
            "structural_trigger": "شکست و تثبیت زیر SMA(100) یا حمایت ساختاری",
        },
        "trend": direction, "short_term_trend": _trend(current, indicator_value("EMA(20)")),
        "medium_term_trend": direction, "long_term_trend": _trend(current, indicator_value("EMA(200)")),
        "trend_direction_score": round(direction_score, 1) if direction_score is not None else None,
        "trend_strength": trend_strength,
        "technical_score": round(technical_score, 1) if technical_score is not None else None,
        "score_method": "dashboard_five_family_medium_term_v1",
        "score_origin": "AliVest", "score_profile": "four_assets_medium_term_initial",
        "score_weights": {name: round(weight * 100) for name, weight in score_weights.items()},
        "effective_score_weights": effective_weights,
        "family_scores": family_scores,
        "score_band": score_band,
        "score_validation": "initial_unbacktested",
        "score_breakdown": {
            **{key: value[0] for key, value in family_data.items()},
            "family_coverage_pct": {key: round(value[1] * 100.0, 1) for key, value in family_data.items()},
            "available_weight": round(available_weight * 100.0, 1),
            "direction_score": round(direction_score, 1) if direction_score is not None else None,
            "rsi": rsi, "atr_pct": round(atr_pct, 3) if atr_pct is not None else None,
            "realized_volatility_pct": rv30, "relative_volume": round(relative_volume, 2) if relative_volume is not None else None,
            "ema50_distance_atr": round(ema50_distance_atr, 2) if ema50_distance_atr is not None else None,
            "support_distance_pct": round(support_distance, 2) if support_distance is not None else None,
            "resistance_distance_pct": round(near_resistance_distance, 2) if near_resistance_distance is not None else None,
            "front_resistance_count": len(front_resistances), "near_resistance_count": len(near_resistances),
        },
        "data_coverage_pct": round(data_coverage, 1),
        "available_family_weight_pct": round(available_weight * 100.0, 1),
        "confidence": round(data_coverage, 1), "confidence_level": coverage_level,
        "confidence_label": confidence_level,
        "confidence_basis": "میزان دسترسی و پوشش داده‌های پنج خانواده؛ این عدد احتمال موفقیت معامله نیست.",
        "risk": risk, "risk_score": round(risk_score, 1) if risk_score is not None else None,
        "risk_label": risk_label, "risk_basis": risk_basis,
        "entry_quality": {"score": round(entry_quality_score, 1) if entry_quality_score is not None else None,
                          "status": entry_label, "label": quality_label},
        "signal": direction,
        "factors": factors, "positive_evidence": positive_evidence,
        "negative_evidence": negative_evidence,
        "explanation": [f"{family_names[item['name']]}: {item['evidence']}" for item in factors],
        "volume_data_note": ("حجم خام منبع با احتیاط تفسیر شود و لزوماً کل بازار را پوشش نمی‌دهد."
                             if symbol in {"GOLD", "USD_IR_FREE"} else None),
        "data_limitations": limitations,
        "indicators": tech, "support_resistance": levels,
        "support_levels": support_levels, "resistance_levels": resistance_levels,
        "nearest_support": nearest_support, "nearest_resistance": nearest_resistance,
        "decision_support": "این خروجی جمع‌بندی تکنیکال وضعیت فعلی است، نه توصیهٔ قطعی خرید یا فروش.",
    }


def analyze_rahavard(symbol: str, payload: dict[str, Any],
                     data_timestamp: str | None = None,
                     current_price: float | None = None,
                     model_context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Describe Rahavard's published indicator readings without recalculating them."""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    groups = {key: data.get(key) if isinstance(data.get(key), list) else []
              for key in ("oscillators", "moving_averages", "pivots", "bands", "volumes")}
    fund_model = score_fund_model(groups, current_price, model_context)
    def indicator_values(items: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
        output: dict[str, dict[str, float]] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("short_name_en") or item.get("name_en") or "").strip()
            if not name:
                continue
            values: dict[str, float] = {}
            for part in item.get("value") or []:
                if not isinstance(part, dict):
                    continue
                try:
                    value = float(part.get("value"))
                    if math.isfinite(value):
                        values[str(part.get("name") or "").strip()] = value
                except (TypeError, ValueError):
                    continue
            output[name] = values
        return output
    indicator_data = indicator_values([item for items in groups.values() for item in items])
    try:
        price = float(current_price) if current_price is not None else None
        if price is not None and (not math.isfinite(price) or price <= 0):
            price = None
    except (TypeError, ValueError):
        price = None
    gauges = data.get("gauges") if isinstance(data.get("gauges"), dict) else {}
    main_gauge = gauges.get("main") if isinstance(gauges.get("main"), dict) else {}
    main_signal = main_gauge.get("signal") if isinstance(main_gauge.get("signal"), dict) else {}
    try:
        net_signal = float(main_signal.get("value"))
    except (TypeError, ValueError):
        net_signal = 0
    signal = "buy" if net_signal > 0 else "sell" if net_signal < 0 else "hold"

    meaning_by_prefix = (
        ("RSI", "شتاب قیمت را می‌سنجد؛ بالای ۷۰ معمولاً خریدزدگی و زیر ۳۰ فروش‌زدگی است."),
        ("MFI", "جریان پول را با درنظرگرفتن حجم معاملات می‌سنجد."),
        ("CCI", "فاصله قیمت از میانگین اخیر را نشان می‌دهد؛ افراط آن می‌تواند هشدار باشد."),
        ("WR", "جایگاه قیمت را در دامنه اخیر نشان می‌دهد؛ مقادیر افراطی را با روند بسنج."),
        ("SO", "شتاب کوتاه‌مدت را با خطوط K و D مقایسه می‌کند."),
        ("ARRON", "تازگی سقف و کف اخیر و استمرار روند را می‌سنجد."),
        ("ADX", "قدرت روند را می‌سنجد؛ جهت حرکت را به‌تنهایی مشخص نمی‌کند."),
        ("AO", "شتاب بازار را از اختلاف میانگین‌های کوتاه و بلند می‌سنجد."),
        ("StochRSI", "جایگاه RSI را در دامنه اخیرش می‌سنجد؛ افراط به‌تنهایی سیگنال برگشت قطعی نیست."),
        ("MACD", "خط MACD را با خط سیگنال مقایسه می‌کند تا تغییر شتاب را نشان دهد."),
        ("MTM", "تغییر مومنتوم قیمت در دوره تعیین‌شده را نشان می‌دهد."),
        ("Trend", "برچسب روند منتشرشده در ره‌آورد است."),
        ("Ichimoku", "تنکن، کیجون و ابر را برای روند و سطوح پویا کنار هم می‌گذارد."),
        ("KELTNER", "محدوده نوسان اطراف میانگین را نشان می‌دهد؛ نزدیکی به باند افراط قیمت را بررسی کن."),
        ("BB", "دامنه نوسان و جایگاه قیمت نسبت به باند بولینگر را نشان می‌دهد."),
        ("EMA", "میانگین نمایی قیمت است؛ فاصله مثبت/منفی نسبت قیمت به میانگین را نشان می‌دهد."),
        ("SMA", "میانگین ساده قیمت است؛ فاصله مثبت/منفی نسبت قیمت به میانگین را نشان می‌دهد."),
        ("RV", "حجم فعلی را با حجم مرجع مقایسه می‌کند؛ بالای ۱ یعنی بالاتر از مرجع."),
        ("SM", "شاخص حجم/جریان پول ره‌آورد است؛ جهت قیمت را به‌تنهایی تأیید نمی‌کند."),
        ("VRSI", "مومنتوم حجم را می‌سنجد؛ همراه روند قیمت خوانده شود."),
        ("VMACD", "شتاب جریان حجم را با خط سیگنال مقایسه می‌کند."),
        ("OBV", "حجم را با جهت حرکت قیمت انباشته می‌کند تا تأیید یا واگرایی حجم دیده شود."),
        ("PivotPoint", "سطوح محاسباتی حمایت و مقاومت است؛ سطح‌ها تضمین برگشت قیمت نیستند."),
    )
    signal_fa = {
        "buy": "مثبت", "sell": "منفی", "neutral": "خنثی", "hold": "خنثی",
        "overbought": "خریدزدگی · احتیاط", "oversold": "فروش‌زدگی · احتمال برگشت",
        "resistance": "مقاومت", "support": "حمایت", "highvolume": "حجم بالا · جهت‌دار نیست",
        "lowvolume": "حجم پایین · تأیید ضعیف‌تر", "strongbuy": "مثبت قوی",
        "strongsell": "منفی قوی", "bullish": "صعودی", "bearish": "نزولی",
    }
    notes = []
    available: set[str] = set()
    for group_name, items in groups.items():
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("short_name_en") or item.get("name_en") or "").strip()
            if not name:
                continue
            available.add(name.casefold())
            normalized = name.casefold()
            meaning = "شاخص تکنیکال ره‌آورد؛ سیگنال و مقدار کنار هم تفسیر شوند."
            for prefix, description in meaning_by_prefix:
                if normalized.startswith(prefix.casefold()):
                    meaning = description
                    break
            raw_signal = str(item.get("signal") or "Neutral")
            key = re.sub(r"[^a-z]", "", raw_signal.casefold())
            interpretation = signal_fa.get(key, raw_signal or "نامشخص")
            notes.append({"name": name, "group": group_name, "signal": raw_signal,
                          "signal_fa": interpretation, "meaning": meaning})

    requested = ["EMA(200)", "SMA(200)"]
    missing = [name for name in requested if name.casefold() not in available]
    for name in missing:
        notes.append({"name": name, "group": "moving_averages", "signal": None,
                      "signal_fa": "در داده ره‌آورد موجود نیست",
                      "meaning": "این مقدار در پاسخ رسمی نماد نبود؛ عدد جایگزین محاسبه نشده است.",
                      "unavailable": True})

    trend_item = next((item for item in groups["oscillators"]
                       if str(item.get("short_name_en") or "").casefold() == "trend"), {})
    trend_signal = str(trend_item.get("signal") or "Neutral").casefold()
    trend = "bullish" if trend_signal in {"buy", "bullish", "strongbuy"} else \
            "bearish" if trend_signal in {"sell", "bearish", "strongsell"} else "neutral"
    footer = main_gauge.get("footer") if isinstance(main_gauge.get("footer"), dict) else {}
    counts = {key: (footer.get(key) or {}).get("value") for key in ("Buy", "Neutral", "Sell")}
    def count_value(value: Any) -> float:
        try:
            parsed = float(value)
            return parsed if math.isfinite(parsed) and parsed >= 0 else 0.0
        except (TypeError, ValueError):
            return 0.0

    buy_count, neutral_count, sell_count = (count_value(counts.get(key)) for key in ("Buy", "Neutral", "Sell"))
    total_count = buy_count + neutral_count + sell_count
    if total_count:
        bullish_probability = round((buy_count + neutral_count * 0.5) / total_count * 100)
        bearish_probability = 100 - bullish_probability
    else:
        bullish_probability = 60 if signal == "buy" or trend == "bullish" else 40
        bearish_probability = 100 - bullish_probability

    def fmt(value: float | None) -> str:
        return "نامشخص" if value is None else f"{value:,.2f}"

    def find_values(prefix: str) -> dict[str, float]:
        for name, values in indicator_data.items():
            if name.casefold().startswith(prefix.casefold()):
                return values
        return {}

    def nearest_level(values: list[float], *, below: bool) -> float | None:
        valid = [value for value in values if price is None or (value < price if below else value > price)]
        if not valid:
            return max(values) if values else None
        return max(valid) if below else min(valid)

    supports = sorted({value for item in groups["pivots"] if isinstance(item, dict)
                       for key, value in (indicator_data.get(str(item.get("short_name_en") or item.get("name_en") or ""), {})).items()
                       if key.casefold().startswith("s")})
    resistances = sorted({value for item in groups["pivots"] if isinstance(item, dict)
                          for key, value in (indicator_data.get(str(item.get("short_name_en") or item.get("name_en") or ""), {})).items()
                          if key.casefold().startswith("r")})

    def signal_score(item: dict[str, Any]) -> float | None:
        raw = str(item.get("signal") or "").strip().casefold()
        key = re.sub(r"[^a-z]", "", raw)
        if key in {"buy", "strongbuy", "bullish", "support"}:
            return 100.0
        if key in {"sell", "strongsell", "bearish", "resistance"}:
            return 0.0
        if key == "overbought":
            return 30.0
        if key == "oversold":
            return 70.0
        if key in {"neutral", "hold", "highvolume", "lowvolume"}:
            return 50.0
        return None

    def group_score(group_name: str) -> float | None:
        values = [signal_score(item) for item in groups.get(group_name, []) if isinstance(item, dict)]
        values = [value for value in values if value is not None]
        return round(sum(values) / len(values), 1) if values else None

    rsi = find_values("RSI").get("rsi")
    moving_average_score = group_score("moving_averages")
    volume_score = group_score("volumes")
    oscillator_score = group_score("oscillators")
    # RSI over 70 caps the oscillator factor at 40; over 80 caps it at 20.
    # This prevents a neutral/bullish text label from hiding numeric overbought risk.
    if oscillator_score is not None and rsi is not None:
        if rsi >= 80:
            oscillator_score = min(oscillator_score, 20.0)
        elif rsi >= 70:
            oscillator_score = min(oscillator_score, 40.0)
    front_resistances = [value for value in resistances if price is not None and value > price]
    near_resistances = [value for value in front_resistances if (value - price) / price <= 0.10] if price else []
    nearest_front_resistance = min(front_resistances) if front_resistances else None
    nearest_resistance_distance = ((nearest_front_resistance - price) / price * 100
                                   if nearest_front_resistance is not None and price else None)
    resistance_score = None
    if price is not None:
        resistance_score = max(15.0, 100.0 - len(near_resistances) * 22.0
                               - (10.0 if nearest_resistance_distance is not None and nearest_resistance_distance <= 3 else 0.0))
        resistance_score = round(resistance_score, 1)
    resistance_pressure = min(22.0, len(near_resistances) * 7.0
                              + (8.0 if nearest_resistance_distance is not None and nearest_resistance_distance <= 3 else 0.0))
    overbought_count = sum(
        1 for item in groups["oscillators"]
        if str(item.get("signal") or "").strip().casefold().replace("_", "") == "overbought"
    )
    if rsi is not None and rsi >= 70:
        overbought_count = max(1, overbought_count)
    correction_probability = round(max(5.0, min(95.0,
        bearish_probability * 0.65
        + resistance_pressure
        + min(18.0, overbought_count * 6.0)
        + (8.0 if trend == "bearish" else 0.0))))
    correction_label = "بالا" if correction_probability >= 55 else "متوسط" if correction_probability >= 30 else "پایین"
    nearest_support = nearest_level(supports, below=True)
    nearest_resistance = nearest_level(resistances, below=False)
    exit_support = min((value for value in supports if price is not None and value < price), default=None)
    sma50 = find_values("SMA(50)").get("value")
    ema50 = find_values("EMA(50)").get("value")
    sma100 = find_values("SMA(100)").get("value")
    ema100 = find_values("EMA(100)").get("value")
    immediate_exit_base = sma50 or ema50 or (nearest_support if nearest_support is not None else None)
    structural_exit_base = sma100 or ema100 or exit_support
    immediate_exit_price = round(immediate_exit_base * 0.995) if immediate_exit_base is not None else None
    structural_exit_price = round(structural_exit_base * 0.998) if structural_exit_base is not None else None
    if structural_exit_price is not None and immediate_exit_price is not None and structural_exit_price >= immediate_exit_price:
        structural_exit_price = round(immediate_exit_price * 0.985)
    resistance_above_price = price is None or any(value > price for value in resistances)
    mfi = find_values("MFI").get("mfi")
    cci = find_values("CCI").get("cci")
    wr = find_values("WR").get("wr")
    so = find_values("SO")
    aroon = find_values("ARRON") or find_values("Aroon")
    adx = find_values("ADX").get("adx")
    ao = find_values("AO").get("awesome")
    stoch_rsi = find_values("StochRSI").get("stochrsi")
    macd_values = find_values("MACD")
    macd_line = macd_values.get("macd")
    macd_signal = macd_values.get("signal")
    ema20 = find_values("EMA(20)").get("value")
    ema50 = find_values("EMA(50)").get("value")
    bullish_reasons: list[str] = []
    bearish_reasons: list[str] = []
    if price is not None and ema20 is not None:
        bullish_reasons.append(f"قیمت {fmt(price)} بالاتر از EMA20 در {fmt(ema20)} است")
        bearish_reasons.append(f"حمایت روند کوتاه‌مدت روی EMA20 در {fmt(ema20)} قرار دارد")
    if price is not None and ema50 is not None:
        bullish_reasons.append(f"قیمت بالاتر از EMA50 در {fmt(ema50)} تثبیت شده است")
        bearish_reasons.append(f"شکست EMA50 در {fmt(ema50)} می‌تواند روند میان‌مدت را تضعیف کند")
    if macd_line is not None and macd_signal is not None:
        if macd_line >= macd_signal:
            bullish_reasons.append(f"MACD با عدد {fmt(macd_line)} بالاتر از خط سیگنال {fmt(macd_signal)} است")
            bearish_reasons.append(f"کاهش MACD از {fmt(macd_line)} به زیر خط سیگنال {fmt(macd_signal)} هشدار نزولی می‌دهد")
        else:
            bearish_reasons.append(f"MACD با عدد {fmt(macd_line)} زیر خط سیگنال {fmt(macd_signal)} است")
            bullish_reasons.append(f"عبور MACD از خط سیگنال {fmt(macd_signal)} شرط بهبود شتاب است")
    if aroon.get("up") is not None and aroon.get("down") is not None:
        bullish_reasons.append(f"Aroon صعودی {fmt(aroon['up'])} در برابر Aroon نزولی {fmt(aroon['down'])} است") if aroon["up"] > aroon["down"] else None
        bearish_reasons.append(f"Aroon نزولی {fmt(aroon['down'])} در برابر Aroon صعودی {fmt(aroon['up'])} برتری دارد") if aroon["down"] > aroon["up"] else None
    if adx is not None:
        (bullish_reasons if trend == "bullish" else bearish_reasons).append(f"ADX روی {fmt(adx)} است و قدرت روند را بالای آستانه ۲۵ نشان می‌دهد") if adx >= 25 else None
    if trend == "bullish":
        bullish_reasons.append("شاخص Trend ره‌آورد صعودی است")
    elif trend == "bearish":
        bearish_reasons.append("شاخص Trend ره‌آورد نزولی است")
    if rsi is not None:
        if rsi >= 70:
            bearish_reasons.append(f"RSI(14) روی {fmt(rsi)} است؛ بالای ۷۰ خریدزدگی و ریسک اصلاح را نشان می‌دهد")
        elif rsi <= 30:
            bullish_reasons.append(f"RSI(14) روی {fmt(rsi)} است؛ زیر ۳۰ فروش‌زدگی و امکان برگشت را نشان می‌دهد")
    if mfi is not None and mfi >= 80:
        bearish_reasons.append(f"MFI روی {fmt(mfi)} و بالای ۸۰ است؛ فشار خرید به ناحیه خریدزدگی رسیده است")
    elif mfi is not None and mfi <= 20:
        bullish_reasons.append(f"MFI روی {fmt(mfi)} و زیر ۲۰ است؛ فروش‌زدگی جریان پول دیده می‌شود")
    if cci is not None and cci >= 100:
        bearish_reasons.append(f"CCI روی {fmt(cci)} و بالای ۱۰۰ است؛ حرکت قوی اما کشیده شده است")
    elif cci is not None and cci <= -100:
        bullish_reasons.append(f"CCI روی {fmt(cci)} و زیر منفی ۱۰۰ است؛ فروش‌زدگی دیده می‌شود")
    if wr is not None and wr >= -20:
        bearish_reasons.append(f"Williams %R روی {fmt(wr)} و بالای منفی ۲۰ است؛ خریدزدگی کوتاه‌مدت وجود دارد")
    elif wr is not None and wr <= -80:
        bullish_reasons.append(f"Williams %R روی {fmt(wr)} و زیر منفی ۸۰ است؛ فروش‌زدگی کوتاه‌مدت وجود دارد")
    if so.get("k") is not None and so.get("d") is not None and so["k"] >= 80 and so["d"] >= 80:
        bearish_reasons.append(f"نوسان‌گر تصادفی K={fmt(so['k'])} و D={fmt(so['d'])} را نشان می‌دهد؛ هر دو بالای ۸۰ و در خریدزدگی‌اند")
    if ao is not None:
        (bullish_reasons if ao > 0 else bearish_reasons).append(f"AO با عدد {fmt(ao)} {'مثبت' if ao > 0 else 'منفی'} است")
    if stoch_rsi is not None and stoch_rsi <= 0.2:
        bullish_reasons.append(f"StochRSI روی {fmt(stoch_rsi)} و زیر ۰٫۲۰ است؛ فروش‌زدگی دیده می‌شود")
    elif stoch_rsi is not None and stoch_rsi >= 0.8:
        bearish_reasons.append(f"StochRSI روی {fmt(stoch_rsi)} و بالای ۰٫۸۰ است؛ خریدزدگی دیده می‌شود")
    if nearest_support is not None:
        bearish_reasons.append(f"حمایت محاسباتی نزدیک {fmt(nearest_support)} است؛ از دست‌رفتن آن سناریوی نزولی را فعال می‌کند")
    if nearest_resistance is not None:
        bullish_reasons.append(f"مقاومت محاسباتی {'نزدیک' if resistance_above_price else 'قبلی'} {fmt(nearest_resistance)} است؛ {'تثبیت بالای آن ادامه رشد را تأیید می‌کند' if resistance_above_price else 'قیمت بالای آن قرار گرفته و حفظ این سطح به نفع روند است'}")
    if not bullish_reasons:
        bullish_reasons.append("برای تأیید سناریوی صعودی، تغییر در مقادیر فعلی و عبور از مقاومت لازم است")
    if not bearish_reasons:
        bearish_reasons.append("برای تأیید سناریوی نزولی، شکست حمایت با تأیید مومنتوم لازم است")
    explanation = "؛ ".join((bullish_reasons if signal == "buy" else bearish_reasons if signal == "sell" else bullish_reasons[:2] + bearish_reasons[:2]))
    scenarios = [
        {"name": "صعودی", "direction": "bullish", "probability": bullish_probability,
         "reason": "؛ ".join(bullish_reasons),
         "condition": "تثبیت قیمت بالای مقاومت نزدیک و حفظ برتری اندیکاتورهای عددی صعودی",
         "risk": "اگر مقاومت حفظ نشود یا RSI/MFI در ناحیه افراطی بمانند، احتمال اصلاح بیشتر می‌شود."},
        {"name": "نزولی", "direction": "bearish", "probability": bearish_probability,
         "reason": "؛ ".join(bearish_reasons),
         "condition": "شکست حمایت نزدیک با تأیید MACD، مومنتوم یا حجم",
         "risk": "اگر حمایت حفظ شود و MACD بالای خط سیگنال بماند، این سناریو اعتبار کمتری دارد."},
    ]
    return {
        "source": "Rahavard365", "symbol": symbol, "data_timestamp": data_timestamp,
        "price": price, "support_levels": supports, "resistance_levels": resistances,
        "medium_term_exit_price": immediate_exit_price,
        "structural_exit_price": structural_exit_price,
        "medium_term_exit": {
            "price": immediate_exit_price,
            "trigger": "تثبیت قیمت زیر SMA(50) یا حمایت میانی ره‌آورد",
            "action": "تثبیت زیر این سطح یعنی ریسک کوتاه‌مدت بالا رفته است؛ خرید جدید را متوقف و خروج را مرحله‌ای اجرا کن.",
            "structural_price": structural_exit_price,
            "structural_trigger": "شکست و تثبیت زیر SMA(100) یا حمایت ساختاری ره‌آورد",
        },
        "technical_score": fund_model["technical_score"],
        "score_method": fund_model["score_method"],
        "score_origin": "AliVest",
        "fund_type": fund_model.get("fund_type"),
        "fund_type_label": fund_model.get("fund_type_label"),
        "model_profile": fund_model.get("model_profile"),
        "score_timestamp": data_timestamp,
        "score_weights": fund_model["score_weights"],
        "family_scores": fund_model["family_scores"],
        "data_coverage_pct": fund_model["data_coverage_pct"],
        "available_family_weight_pct": fund_model["available_family_weight_pct"],
        "score_band": fund_model["score_band"],
        "score_validation": fund_model["score_validation"],
        "risk_rank": fund_model["risk_rank"],
        "nav_assessment": fund_model["nav_assessment"],
        "top_factors": fund_model["top_factors"],
        "missing_data": fund_model["missing_data"],
        "score_change_5d": fund_model["score_change_5d"],
        "score_change_20d": fund_model["score_change_20d"],
        "score_breakdown": {
            "moving_averages": moving_average_score,
            "volume": volume_score,
            "oscillators": oscillator_score,
            "rsi": rsi,
            "resistance": resistance_score,
            "front_resistance_count": len(front_resistances),
            "near_resistance_count": len(near_resistances),
        },
        "trend_probabilities": {"bullish": bullish_probability, "bearish": bearish_probability},
        "correction_risk": {
            "probability": correction_probability,
            "label": correction_label,
            "near_resistance_count": len(near_resistances),
            "overbought_count": overbought_count,
        },
        "signal": signal, "trend": trend, "risk": "unavailable",
        "confidence": None,
        "confidence_basis": "امتیاز تکنیکال هفت‌گروهی توسط AliVest و بر پایه داده‌های ره‌آورد محاسبه می‌شود؛ امتیاز رسمی ره‌آورد یا احتمال سود نیست.",
        "decision_support": explanation,
        "explanation": explanation, "site_gauges": gauges,
        "indicators": groups, "indicator_notes": notes,
        "indicator_count": sum(len(items) for items in groups.values()),
        "missing_indicators": missing, "scenarios": scenarios,
        "scenario_note": "احتمال‌ها برآورد تحلیلی بر پایه عدد اندیکاتورها، روند و سطوح حمایت/مقاومت هستند؛ پیش‌بینی قطعی یا بک‌تست‌شده نیستند.",
    }


def stale_status(timestamp: str | None, *, max_hours: int = 36) -> bool | None:
    if not timestamp:
        return None
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() > max_hours * 3600
    except ValueError:
        return True
