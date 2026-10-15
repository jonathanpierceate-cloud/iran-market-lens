"""Workbook-defined chart-based technical scoring for funds and dashboard assets."""
from __future__ import annotations

import math
from typing import Any

from .indicators import compute_indicators
from .scoring_profiles import FUND_SCORING_PROFILES, normalize_horizon

EPS = 1e-9
GROUP_WEIGHTS = FUND_SCORING_PROFILES["long"]["family_weights"]
SUBCLUSTERS: dict[str, dict[str, dict[str, Any]]] = {
    family: {"all_indicators": {"weight": 1.0, "indicators": weights}}
    for family, weights in FUND_SCORING_PROFILES["long"]["indicator_weights"].items()
}


def _num(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _clip(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(value, high))


def _at(values: Any, index: int = -1) -> float | None:
    if not isinstance(values, (list, tuple)) or not values:
        return None
    try:
        return _num(values[index])
    except IndexError:
        return None


def _sig(score: float | None) -> str:
    if score is None:
        return "Insufficient Data"
    if score > 70:
        return "Bullish"
    if score < 30:
        return "Bearish"
    return "Neutral"


def _pivot_sets(high: float, low: float, close: float, open30: float) -> dict[str, dict[str, float]]:
    span = max(0.0, high - low)

    def standard(pp: float) -> dict[str, float]:
        return {"PP": pp, "R1": 2 * pp - low, "S1": 2 * pp - high,
                "R2": pp + span, "S2": pp - span,
                "R3": high + 2 * (pp - low), "S3": low - 2 * (high - pp)}

    classic = (high + low + close) / 3.0
    fib = {"PP": classic, "R1": classic + .382 * span, "S1": classic - .382 * span,
           "R2": classic + .618 * span, "S2": classic - .618 * span,
           "R3": classic + span, "S3": classic - span}
    woodie_pp = (high + low + 2 * close) / 4.0
    x = (high + 2 * low + close if close < open30 else
         2 * high + low + close if close > open30 else high + low + 2 * close)
    demark = {"PP": x / 4.0, "R1": x / 2.0 - low, "S1": x / 2.0 - high}
    offset = 1.1 * span
    camarilla = {
        "PP": classic,
        "R1": close + offset / 12, "R2": close + offset / 6,
        "R3": close + offset / 4, "R4": close + offset / 2,
        "S1": close - offset / 12, "S2": close - offset / 6,
        "S3": close - offset / 4, "S4": close - offset / 2,
    }
    return {"Classic": standard(classic), "Fibonacci": fib,
            "Woodie": standard(woodie_pp), "DeMark": demark,
            "Camarilla": camarilla}


def _relative_change_pct(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    if abs(previous) < EPS:
        return None
    return (current - previous) / abs(previous) * 100.0


def _delta_score(current: float | None, previous: float | None) -> float | None:
    change = _relative_change_pct(current, previous)
    # The workbook's +/-5% reference points map to 70/30 respectively.
    return _clip(50.0 + 4.0 * change) if change is not None else None


def _linear_anchors(value: float, anchors: list[tuple[float, float]]) -> float:
    """Linearly interpolate score anchors, clamping outside their range."""
    if value <= anchors[0][0]:
        return anchors[0][1]
    for (left_x, left_y), (right_x, right_y) in zip(anchors, anchors[1:]):
        if value <= right_x:
            fraction = (value - left_x) / (right_x - left_x)
            return left_y + fraction * (right_y - left_y)
    return anchors[-1][1]


def _ma_score(price: float, average: float | None) -> tuple[float | None, float | None]:
    if average is None or average <= 0:
        return None, None
    distance_pct = (price / average - 1.0) * 100.0
    # The workbook fixes 70/30 at zero distance but gives no slope; map each 1%
    # of price distance to one score point, retaining those stated anchors.
    score = 70.0 + distance_pct if distance_pct >= 0 else 30.0 + distance_pct
    return _clip(score), distance_pct


def _band_score(price: float, lower: float | None,
                upper: float | None) -> tuple[float | None, float | None]:
    if lower is None or upper is None or upper <= lower:
        return None, None
    position = (price - lower) / (upper - lower)
    if position <= 0:
        score = 100.0
    elif position >= 1:
        score = _clip(10.0 - 10.0 * (position - 1.0))
    else:
        score = 60.0 - 30.0 * position
    return score, position


def _rsi_score(value: float | None) -> float | None:
    if value is None:
        return None
    if value < 30:
        return 100.0
    if value > 70:
        return 0.0
    # Workbook anchors: RSI 40 -> 60, RSI 70 -> 30; <=30 is oversold.
    return _linear_anchors(value, [(30.0, 100.0), (40.0, 60.0), (70.0, 30.0)])


def _bounded_oscillator_score(value: float | None, lower: float, upper: float,
                              anchors: list[tuple[float, float]]) -> float | None:
    if value is None:
        return None
    if value <= lower:
        return 100.0
    if value >= upper:
        return 0.0
    return _linear_anchors(value, anchors)


def _stochrsi_score(value: float | None) -> float | None:
    if value is None:
        return None
    value = _clip(value, 0.0, 1.0)
    if value <= .2:
        return 100.0
    if value >= .8:
        return 0.0
    # Inside the neutral zone: 0.2 -> 60 and 0.8 -> 30.
    return _linear_anchors(value, [(.2, 60.0), (.8, 30.0)])


def _adx_score(adx: float | None, plus_di: float | None,
               minus_di: float | None) -> float | None:
    if adx is None or plus_di is None or minus_di is None:
        return None
    if abs(plus_di - minus_di) < EPS:
        return 50.0
    uptrend = plus_di > minus_di
    if adx < 25.0:
        return 60.0 if uptrend else 30.0
    strength = _clip((adx - 25.0) / 25.0, 0.0, 1.0)
    return 70.0 + 30.0 * strength if uptrend else 30.0 - 30.0 * strength


def _aroon_score(spread: float | None) -> float | None:
    if spread is None:
        return None
    # The workbook places a weakly positive Aroon spread near 60, a weakly
    # negative spread near 30, and rewards stronger spreads toward 100/0.
    if spread <= -50.0:
        return _linear_anchors(spread, [(-100.0, 0.0), (-50.0, 30.0)])
    if spread <= 50.0:
        return _linear_anchors(spread, [(-50.0, 30.0), (50.0, 60.0)])
    # Crossing +50 is the workbook's buy threshold, so the score enters the
    # bullish band there and rises toward 100 as the spread approaches +100.
    return _linear_anchors(spread, [(50.0, 70.0), (100.0, 100.0)])


def _ao_score(value: float | None, previous: float | None,
              price: float) -> float | None:
    if value is None or previous is None or price <= 0:
        return None
    if abs(value) < EPS:
        return 50.0
    rising = value > previous
    # Normalize AO magnitude to price so this score works across price scales.
    strength = _clip(abs(value) / price * 1000.0, 0.0, 100.0) / 100.0
    if value > 0:
        return _clip(70.0 + 30.0 * strength) if rising else 60.0
    return _clip(30.0 - 30.0 * strength) if not rising else 40.0


def _indicator_scores(bars: list[dict[str, Any]], series: dict[str, Any]
                      ) -> dict[str, dict[str, dict[str, Any]]]:
    closes = [_num(item.get("close")) for item in bars]
    highs = [_num(item.get("high")) for item in bars]
    lows = [_num(item.get("low")) for item in bars]
    opens = [_num(item.get("open")) for item in bars]
    if len(closes) < 2 or any(value is None for value in closes + highs + lows + opens):
        return {}
    price = float(closes[-1])
    results: dict[str, dict[str, dict[str, Any]]] = {
        family: {} for family in FUND_SCORING_PROFILES["long"]["indicator_weights"]
    }

    def put(family: str, name: str, score: float | None,
            value: Any = None, note: str = "") -> None:
        if score is not None and not math.isfinite(score):
            score = None
        if score is not None:
            score = _clip(score)
        results[family][name] = {
            "key": name, "score": round(score, 2) if score is not None else None,
            "weight_pct": 0.0, "value": value, "note": note, "signal": _sig(score),
        }

    # Moving averages and bands.
    for kind, source in (("EMA", series.get("ema", {})), ("SMA", series.get("sma", {}))):
        for period in (5, 10, 20, 30, 50, 100):
            values = source.get(period) if isinstance(source, dict) else None
            average = _at(values)
            score, distance = _ma_score(price, average)
            put("moving_averages", f"{kind}({period})", score,
                {"price": price, "average": average, "distance_pct": distance},
                "امتیاز بر پایهٔ فاصلهٔ درصدی قیمت از میانگین متحرک محاسبه می‌شود؛ قیمت بالای میانگین صعودی و پایین آن نزولی است.")

    tenkan_values, kijun_values = series.get("tenkan"), series.get("kijun")
    tenkan, kijun = _at(tenkan_values), _at(kijun_values)
    span_a, span_b = _at(series.get("span_a_cloud")), _at(series.get("span_b_cloud"))
    cloud_position_pct = None
    if span_a is not None and span_b is not None:
        top, bottom = max(span_a, span_b), min(span_a, span_b)
        cloud_width = max(top - bottom, price * .01, EPS)
        tenkan_bullish = tenkan is not None and kijun is not None and tenkan > kijun
        tenkan_bearish = tenkan is not None and kijun is not None and tenkan < kijun
        if price > top:
            cloud_position_pct = (price / top - 1.0) * 100.0 if top > 0 else None
            distance_strength = _clip((price - top) / cloud_width, 0.0, 1.0)
            ichimoku_score = 70.0 + 30.0 * distance_strength if tenkan_bullish else 60.0
        elif price < bottom:
            cloud_position_pct = (price / bottom - 1.0) * 100.0 if bottom > 0 else None
            distance_strength = _clip((bottom - price) / cloud_width, 0.0, 1.0)
            ichimoku_score = 30.0 - 30.0 * distance_strength if tenkan_bearish else 40.0
        else:
            cloud_position_pct = (price - bottom) / (top - bottom) if top > bottom else .5
            ichimoku_score = 30.0 + 30.0 * _clip(cloud_position_pct, 0.0, 1.0)
    else:
        ichimoku_score = None
    put("moving_averages", "Ichimoku Cloud(9,26,52,26)", ichimoku_score,
        {"price": price, "span_a": span_a, "span_b": span_b,
         "tenkan": tenkan, "kijun": kijun,
         "cloud_position_pct": cloud_position_pct},
        "قیمت بیرون ابر با تأیید جهت تنکان‌سن/کیجون‌سن امتیاز خرید یا فروش می‌گیرد؛ داخل ابر بر اساس نزدیکی به سقف یا کف امتیاز می‌گیرد.")

    bb_upper, bb_lower = _at(series.get("bb_upper")), _at(series.get("bb_lower"))
    bb_score, bb_position = _band_score(price, bb_lower, bb_upper)
    put("moving_averages", "BB(20)", bb_score,
        {"lower": bb_lower, "upper": bb_upper, "position": bb_position},
        "نزدیکی کف باند امتیاز خرید را بالا می‌برد؛ داخل باند خنثی و بالای سقف باند فروش است.")

    keltner_mid, atr16 = _at(series.get("keltner_mid")), _at(series.get("atr16"))
    keltner_lower = keltner_mid - 2.0 * atr16 if keltner_mid is not None and atr16 is not None else None
    keltner_upper = keltner_mid + 2.0 * atr16 if keltner_mid is not None and atr16 is not None else None
    keltner_score, keltner_position = _band_score(price, keltner_lower, keltner_upper)
    put("moving_averages", "KELTNER(16)", keltner_score,
        {"lower": keltner_lower, "upper": keltner_upper, "position": keltner_position},
        "نزدیکی کف کانال امتیاز خرید را بالا می‌برد؛ داخل کانال خنثی و بالای سقف فروش است.")

    # Trend and momentum.
    macd, macd_previous = _at(series.get("macd_line")), _at(series.get("macd_line"), -2)
    put("trend_momentum", "MACD(26)", _delta_score(macd, macd_previous),
        {"value": macd, "previous": macd_previous,
         "change_pct": _relative_change_pct(macd, macd_previous)},
        "تغییر درصدی MACD نسبت به مقدار قبلی؛ افزایش مثبت مومنتوم صعودی و افت آن مومنتوم نزولی را نشان می‌دهد.")

    adx, plus_di, minus_di = (_at(series.get("adx14")), _at(series.get("plus_di14")),
                              _at(series.get("minus_di14")))
    put("trend_momentum", "ADX(14)", _adx_score(adx, plus_di, minus_di),
        {"adx": adx, "+DI": plus_di, "-DI": minus_di},
        "ADX زیر ۲۵ روند ضعیف است؛ بالای ۲۵ قدرت روند را تا ۵۰ می‌سنجد و جهت را از مقایسهٔ +DI و -DI می‌گیرد.")

    aroon_up, aroon_down = _at(series.get("aroon_up25")), _at(series.get("aroon_down25"))
    spread = aroon_up - aroon_down if aroon_up is not None and aroon_down is not None else None
    aroon_score = _aroon_score(spread)
    put("trend_momentum", "AROON(25)", aroon_score,
        {"up": aroon_up, "down": aroon_down, "spread": spread},
        "اختلاف Aroon Up و Down استفاده می‌شود؛ اختلاف مثبت قوی‌تر امتیاز بالاتر و اختلاف منفی قوی‌تر امتیاز پایین‌تر می‌گیرد.")

    ao, ao_previous = _at(series.get("ao534")), _at(series.get("ao534"), -2)
    put("trend_momentum", "AO(5,34)", _ao_score(ao, ao_previous, price),
        {"value": ao, "previous": ao_previous,
         "change": ao - ao_previous if ao is not None and ao_previous is not None else None,
         "normalized_strength": abs(ao) / price * 1000.0 if ao is not None and price > 0 else None},
        "AO بالای صفر و رو به رشد امتیاز خرید می‌گیرد؛ زیر صفر و رو به افت امتیاز فروش. قدرت با اندازهٔ AO نسبت به قیمت نرمال می‌شود.")

    # The pivot calculation uses the preceding 30 completed bars, without any
    # relative-volume dependency.
    pivot_sets: dict[str, dict[str, float]] = {}
    close_values = [float(value) for value in closes]
    if len(bars) >= 31:
        previous_bars = bars[-31:-1]
        pivot_sets = _pivot_sets(
            max(float(row["high"]) for row in previous_bars),
            min(float(row["low"]) for row in previous_bars),
            close_values[-2], float(previous_bars[0]["open"]),
        )
    pivot_names = {
        "Fibonacci": "PivotPoint Fibonacci(30)", "Classic": "PivotPoint Classic(30)",
        "Camarilla": "PivotPoint Camarilla(30)", "Woodie": "PivotPoint Woodie(30)",
        "DeMark": "PivotPoint DeMark(30)",
    }
    for method, name in pivot_names.items():
        levels = pivot_sets.get(method)
        pivot = _num(levels.get("PP")) if levels else None
        distance = (price / pivot - 1.0) * 100.0 if pivot is not None and pivot > 0 else None
        score = _clip(50.0 + 10.0 * distance) if distance is not None else None
        put("support_resistance", name, score,
            {"pivot": pivot, "distance_pct": distance, "levels": levels},
            "فاصلهٔ درصدی قیمت از پیوت؛ بالاتر از پیوت متمایل به خرید و پایین‌تر از آن متمایل به فروش است.")

    # Oscillators.
    rsi, rsi_previous = _at(series.get("rsi14")), _at(series.get("rsi14"), -2)
    rsi_score = _rsi_score(rsi)
    put("oscillators", "RSI(14)", rsi_score,
        {"value": rsi, "previous": rsi_previous},
        "زیر ۳۰ ناحیهٔ خرید، بالای ۷۰ ناحیهٔ فروش و بازهٔ ۳۰ تا ۷۰ خنثی با امتیاز کاهشی به سمت ۷۰ است.")

    mfi = _at(series.get("mfi14"))
    mfi_score = _bounded_oscillator_score(
        mfi, 20.0, 80.0, [(20.0, 100.0), (30.0, 60.0), (80.0, 30.0)])
    put("oscillators", "MFI(14)", mfi_score, {"value": mfi},
        "زیر ۲۰ خرید، بالای ۸۰ فروش؛ در محدودهٔ میانی با نزدیک‌شدن به ۸۰ امتیاز به ۳۰ و نزدیک‌شدن به ۳۰ امتیاز به ۶۰ می‌رسد.")

    cci = _at(series.get("cci14"))
    cci_score = _bounded_oscillator_score(
        cci, -100.0, 100.0, [(-100.0, 100.0), (-50.0, 60.0), (100.0, 30.0)])
    put("oscillators", "CCI(14)", cci_score, {"value": cci},
        "زیر ۱۰۰- خرید و بالای ۱۰۰ فروش؛ بین این دو، نزدیک ۱۰۰+ امتیاز ۳۰ و نزدیک ۵۰- امتیاز ۶۰ می‌گیرد.")

    so_k, so_d = _at(series.get("so_k")), _at(series.get("so_d"))
    so_score = _bounded_oscillator_score(
        so_k, 20.0, 80.0, [(20.0, 100.0), (30.0, 60.0), (80.0, 30.0)])
    put("oscillators", "SO(14)", so_score, {"k": so_k, "d": so_d},
        "امتیاز از خط %K محاسبه می‌شود: زیر ۲۰ خرید، بالای ۸۰ فروش و در محدودهٔ میانی نزدیک ۸۰ امتیاز ۳۰ و نزدیک ۳۰ امتیاز ۶۰.")

    stochrsi = _at(series.get("stochrsi14"))
    put("oscillators", "StochRSI(14)", _stochrsi_score(stochrsi),
        {"value": stochrsi, "scale": "0..1"},
        "مقیاس StochRSI از صفر تا یک است؛ ۰ تا ۰٫۲ خرید، ۰٫۸ تا ۱ فروش و بین آن‌ها خنثی است.")

    wr = _at(series.get("wr14"))
    wr_score = _bounded_oscillator_score(
        wr, -80.0, -20.0, [(-80.0, 100.0), (-70.0, 60.0), (-20.0, 30.0)])
    put("oscillators", "WR(14)", wr_score, {"value": wr},
        "زیر ۸۰- خرید و بالای ۲۰- فروش؛ نزدیک ۷۰- امتیاز ۶۰ و نزدیک ۲۰- امتیاز ۳۰ می‌گیرد.")

    mtm = _at(series.get("mtm6"))
    mtm_change_pct = mtm / price * 100.0 if mtm is not None and price > 0 else None
    mtm_score = _clip(50.0 + mtm / price * 1000.0) if mtm_change_pct is not None else None
    put("oscillators", "MTM(6)", mtm_score,
        {"value": mtm, "close": price, "change_pct": mtm_change_pct},
        "امتیاز MTM برابر 50 + (مومنتوم ÷ قیمت پایانی × 1000) و محدود به صفر تا ۱۰۰ است.")
    return results


def score_tse_bars(bars: list[dict[str, Any]] | None, *, horizon: str = "long",
                   trend_value: float | None = None,
                   trend_schema_type: str | None = None) -> dict[str, Any]:
    """Score the workbook-listed indicators from chart bars for one horizon."""
    horizon = normalize_horizon(horizon)
    profile = FUND_SCORING_PROFILES[horizon]
    family_weights: dict[str, float] = profile["family_weights"]  # type: ignore[assignment]
    indicator_weights: dict[str, dict[str, float]] = profile["indicator_weights"]  # type: ignore[assignment]
    normalized: list[dict[str, Any]] = []
    for row in bars or []:
        if not isinstance(row, dict):
            continue
        close = _num(row.get("close"))
        if close is None or close <= 0:
            continue
        normalized.append({
            **row,
            "close": close,
            "open": _num(row.get("open")) if _num(row.get("open")) is not None else close,
            "high": _num(row.get("high")) if _num(row.get("high")) is not None else close,
            "low": _num(row.get("low")) if _num(row.get("low")) is not None else close,
            "volume": _num(row.get("volume")),
        })
    if not normalized:
        return _empty_result(horizon)

    calculated = compute_indicators(normalized, include_series=True)
    series = calculated.get("indicator_series") or {}
    scored = _indicator_scores(normalized, series)
    family_results: dict[str, dict[str, Any]] = {}
    coverage_by_family: dict[str, float] = {}

    for family, weights in indicator_weights.items():
        rows: list[dict[str, Any]] = []
        valid: list[tuple[dict[str, Any], float]] = []
        missing: list[str] = []
        for name, weight in weights.items():
            item = scored.get(family, {}).get(name)
            if item is None:
                item = {"key": name, "score": None, "value": None,
                        "note": "دادهٔ کافی برای محاسبهٔ این اندیکاتور در دسترس نیست.",
                        "signal": "Insufficient Data"}
            else:
                item = dict(item)
            item["sub_cluster"] = family
            if item.get("score") is None:
                missing.append(name)
            else:
                valid.append((item, weight))
        coverage = sum(weight for _, weight in valid)
        # Keep only calculable indicator cards. Reallocate each missing
        # indicator's configured share proportionally across the available
        # indicators in the same family.
        if coverage > 0:
            for item, weight in valid:
                item["weight_pct"] = round(weight / coverage * 100.0, 2)
                rows.append(item)
        group_score = (sum(float(item["score"]) * weight for item, weight in valid) / coverage
                       if coverage > 0 and valid else None)
        coverage_by_family[family] = coverage
        family_results[family] = {
            "score": round(group_score, 2) if group_score is not None else None,
            "coverage_pct": round(coverage * 100.0, 1),
            "signal": _sig(group_score), "indicators": rows,
            "missing_indicators": missing,
            "sub_clusters": {"all_indicators": {
                "score": round(group_score, 2) if group_score is not None else None,
                "coverage_pct": round(coverage * 100.0, 1), "weight_pct": 100.0,
                "indicators": [item["key"] for item in rows],
            }},
        }

    valid_groups = [family for family in family_weights
                    if family_results[family]["score"] is not None]
    available_weight = sum(family_weights[family] for family in valid_groups)
    if not valid_groups or available_weight <= 0:
        raw_score = final_score = dispersion = confidence = None
        effective: dict[str, float] = {}
        final_signal = "Insufficient Data"
    else:
        # If an entire family has no valid indicators, redistribute its
        # configured share across the remaining families.
        effective = {family: family_weights[family] / available_weight
                     for family in valid_groups}
        raw_score = sum(effective[family] * float(family_results[family]["score"])
                        for family in valid_groups)
        final_score = _clip(raw_score)
        dispersion = math.sqrt(sum(effective[family] *
                                   (float(family_results[family]["score"]) - raw_score) ** 2
                                   for family in valid_groups))
        final_signal = "Bullish" if final_score > 70 else "Bearish" if final_score < 30 else "Neutral"
        weighted_coverage = sum(family_weights[family] * coverage_by_family[family]
                                for family in family_weights)
        agreement = 1.0 - _clip(dispersion / 50.0, 0.0, 1.0)
        confidence = round(100.0 * weighted_coverage * agreement, 1)

    score_weights = {family: round(weight * 100.0, 2)
                     for family, weight in family_weights.items()}
    normalized_indicator_weights = {
        family: {name: round(weight * 100.0, 2) for name, weight in weights.items()}
        for family, weights in indicator_weights.items()
    }
    return {
        "technical_score": round(final_score, 2) if final_score is not None else None,
        "raw_score": round(raw_score, 2) if raw_score is not None else None,
        "signal": final_signal,
        "score_band": {"Bullish": "bullish", "Bearish": "bearish",
                       "Neutral": "neutral", "Insufficient Data": "unavailable"}[final_signal],
        "confidence": confidence,
        "inter_group_dispersion": round(dispersion, 2) if dispersion is not None else None,
        "damping_factor": 0.0,
        "family_scores": family_results,
        "score_weights": score_weights,
        "effective_score_weights": {family: round(weight * 100.0, 2)
                                     for family, weight in effective.items()},
        "indicator_weights": normalized_indicator_weights,
        "data_coverage_pct": round(sum(family_weights[family] * coverage_by_family[family]
                                        for family in family_weights) * 100.0, 1),
        "available_family_weight_pct": round(available_weight * 100.0, 1),
        "valid_groups": valid_groups,
        "observations": len(normalized),
        "investment_horizon": horizon,
        "score_method": f"tse_excel_comprehensive_scoring_{horizon}",
    }


def _empty_result(horizon: str = "long") -> dict[str, Any]:
    profile = FUND_SCORING_PROFILES[normalize_horizon(horizon)]
    family_weights: dict[str, float] = profile["family_weights"]  # type: ignore[assignment]
    indicator_weights: dict[str, dict[str, float]] = profile["indicator_weights"]  # type: ignore[assignment]
    groups = {
        family: {"score": None, "coverage_pct": 0.0, "signal": "Insufficient Data",
                 "indicators": [], "missing_indicators": list(weights), "sub_clusters": {}}
        for family, weights in indicator_weights.items()
    }
    return {
        "technical_score": None, "raw_score": None,
        "signal": "Insufficient Data", "score_band": "unavailable",
        "confidence": None, "inter_group_dispersion": None, "damping_factor": 0.0,
        "family_scores": groups,
        "score_weights": {family: weight * 100.0 for family, weight in family_weights.items()},
        "effective_score_weights": {},
        "indicator_weights": {
            family: {name: weight * 100.0 for name, weight in weights.items()}
            for family, weights in indicator_weights.items()
        },
        "data_coverage_pct": 0.0, "available_family_weight_pct": 0.0,
        "valid_groups": [], "observations": 0,
        "investment_horizon": normalize_horizon(horizon),
        "score_method": f"tse_excel_comprehensive_scoring_{normalize_horizon(horizon)}",
    }
