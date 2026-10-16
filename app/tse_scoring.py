"""Update 4.2 chart-based technical scoring for funds and dashboard assets."""
from __future__ import annotations

import math
from typing import Any

from .indicators import compute_indicators
from .scoring_profiles import FUND_SCORING_PROFILES, normalize_horizon
from .scoring_rules import band_position_score

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


def _clip(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(value, high))


def _at(values: Any, index: int = -1) -> float | None:
    if not isinstance(values, (list, tuple)) or not values:
        return None
    try:
        return _num(values[index])
    except IndexError:
        return None


def _score(z: float | None) -> float | None:
    return max(0.0, min(100.0, 50.0 + 50.0 * z)) if z is not None else None


def _signal(score: float | None) -> str:
    if score is None:
        return "Insufficient Data"
    shown_score = math.floor(score + 0.5)
    if shown_score >= 70:
        return "Buy"
    if shown_score > 40:
        return "Neutral"
    return "Sell"


def _linear(value: float | None, anchors: list[tuple[float, float]]) -> float | None:
    if value is None:
        return None
    if value <= anchors[0][0]:
        return anchors[0][1]
    for (left_x, left_y), (right_x, right_y) in zip(anchors, anchors[1:]):
        if value <= right_x:
            fraction = (value - left_x) / (right_x - left_x)
            return left_y + fraction * (right_y - left_y)
    return anchors[-1][1]


def _pivot_sets(high: float, low: float, close: float, previous_open: float
                ) -> dict[str, dict[str, float]]:
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
    x = (high + 2 * low + close if close < previous_open else
         2 * high + low + close if close > previous_open else high + low + 2 * close)
    demark = {"PP": x / 4.0, "R1": x / 2.0 - low, "S1": x / 2.0 - high}
    offset = 1.1 * span
    camarilla = {
        "PP": close,
        "R1": close + offset / 12, "R2": close + offset / 6,
        "R3": close + offset / 4, "R4": close + offset / 2,
        "S1": close - offset / 12, "S2": close - offset / 6,
        "S3": close - offset / 4, "S4": close - offset / 2,
    }
    return {"Classic": standard(classic), "Fibonacci": fib,
            "Woodie": standard(woodie_pp), "DeMark": demark,
            "Camarilla": camarilla}


def _indicator_scores(bars: list[dict[str, Any]], series: dict[str, Any]
                      ) -> dict[str, dict[str, dict[str, Any]]]:
    """Calculate Update 4.2 indicator scores as z values, then map to 0–100."""
    results: dict[str, dict[str, dict[str, Any]]] = {
        family: {} for family in FUND_SCORING_PROFILES["long"]["indicator_weights"]
    }
    if not bars:
        return results
    price = _num(bars[-1].get("close"))
    if price is None or price <= 0:
        return results

    atr = _at(series.get("atr14"))
    adx = _at(series.get("adx14"))
    plus_di = _at(series.get("plus_di14"))
    minus_di = _at(series.get("minus_di14"))
    trend_direction = 0
    if plus_di is not None and minus_di is not None:
        trend_direction = 1 if plus_di > minus_di else -1 if minus_di > plus_di else 0
    strong_trend = adx is not None and adx >= 25.0

    def put(family: str, key: str, z: float | None, value: Any = None,
            note: str = "", *, counter_trend: bool = False) -> None:
        if z is not None and not math.isfinite(z):
            z = None
        raw_z = z
        damped = bool(counter_trend and strong_trend and trend_direction and z is not None
                      and z * trend_direction < 0)
        if damped and z is not None:
            z *= .5
        raw_score = _score(raw_z) if raw_z is not None else None
        score = _score(z) if z is not None else None
        results[family][key] = {
            "key": key,
            "score": score,
            "weight_pct": 0.0,
            "value": value,
            "note": note,
            "signal": _signal(score),
            "regime_adjusted": damped,
            "raw_score": raw_score,
        }

    # Moving averages: combine each same-period EMA/SMA pair into one vote.
    averages = [
        ("EMA/SMA(100)", 100), ("EMA/SMA(50)", 50), ("EMA/SMA(30)", 30),
        ("EMA/SMA(20)", 20), ("EMA/SMA(10)", 10), ("EMA/SMA(5)", 5),
    ]
    for key, period in averages:
        ema = _at((series.get("ema") or {}).get(period))
        sma = _at((series.get("sma") or {}).get(period))
        z = None
        if atr is not None and atr > 0 and ema is not None and sma is not None:
            z = (_clip((price - ema) / (2.0 * atr))
                 + _clip((price - sma) / (2.0 * atr))) / 2.0
        put("moving_averages", key, z, {"EMA": ema, "SMA": sma, "ATR": atr},
            "\u0645\u06cc\u0627\u0646\u06af\u06cc\u0646 \u0627\u0645\u062a\u06cc\u0627\u0632 EMA \u0648 SMA \u0628\u0631 \u0627\u0633\u0627\u0633 \u0641\u0627\u0635\u0644\u0647\u200c\u06cc \u0642\u06cc\u0645\u062a \u0628\u0631\u062d\u0633\u0628 ATR.")

    span_a = _at(series.get("span_a_cloud"))
    span_b = _at(series.get("span_b_cloud"))
    tenkan, kijun = _at(series.get("tenkan")), _at(series.get("kijun"))
    ichi_z = None
    if (atr is not None and atr > 0 and span_a is not None and span_b is not None
            and tenkan is not None and kijun is not None):
        top, bottom = max(span_a, span_b), min(span_a, span_b)
        edge_strength = .4
        if price > top:
            cloud_z = edge_strength + (1.0 - edge_strength) * min(1.0, (price - top) / (2.0 * atr))
        elif price < bottom:
            cloud_z = -(edge_strength + (1.0 - edge_strength) * min(1.0, (bottom - price) / (2.0 * atr)))
        elif top > bottom:
            cloud_z = ((price - bottom) / (top - bottom) - .5) * 2.0 * edge_strength
        else:
            cloud_z = 0.0
        tk_z = _clip((tenkan - kijun) / atr)
        ichi_z = .7 * cloud_z + .3 * tk_z
    put("moving_averages", "Ichimoku Cloud(9,26,52,26)", ichi_z,
        {"price": price, "span_a": span_a, "span_b": span_b,
         "tenkan": tenkan, "kijun": kijun, "ATR": atr},
        "\u06f7\u06f0\u066a \u062c\u0627\u06cc\u06af\u0627\u0647 \u0642\u06cc\u0645\u062a \u0646\u0633\u0628\u062a \u0628\u0647 \u0627\u0628\u0631 \u0648 \u06f3\u06f0\u066a \u0627\u062e\u062a\u0644\u0627\u0641 \u062a\u0646\u06a9\u0627\u0646\u200c\u0633\u0646 \u0648 \u06a9\u06cc\u062c\u0648\u0646\u200c\u0633\u0646\u060c \u0646\u0631\u0645\u0627\u0644\u200c\u0634\u062f\u0647 \u0628\u0627 ATR.")

    bb_upper, bb_lower = _at(series.get("bb_upper")), _at(series.get("bb_lower"))
    bb_score = band_position_score(price, bb_lower, bb_upper)
    bb_z = (bb_score - 50.0) / 50.0 if bb_score is not None else None
    put("moving_averages", "BB(20)", bb_z,
        {"lower": bb_lower, "upper": bb_upper, "price": price},
        "\u0645\u0648\u0642\u0639\u06cc\u062a \u0646\u0633\u0628\u06cc \u062f\u0631 \u0628\u0627\u0646\u062f\u061b \u06a9\u0641 \u0628\u0627\u0646\u062f \u0627\u0645\u062a\u06cc\u0627\u0632 \u0628\u0627\u0644\u0627\u060c \u0633\u0642\u0641 \u0628\u0627\u0646\u062f \u0627\u0645\u062a\u06cc\u0627\u0632 \u067e\u0627\u06cc\u06cc\u0646\u061b \u062f\u0631 \u0631\u0648\u0646\u062f \u0642\u0648\u06cc \u0633\u06cc\u06af\u0646\u0627\u0644 \u062e\u0644\u0627\u0641 \u0631\u0648\u0646\u062f \u0646\u0635\u0641 \u0645\u06cc\u200c\u0634\u0648\u062f.",
        counter_trend=True)

    keltner_mid, atr16 = _at(series.get("keltner_mid")), _at(series.get("atr16"))
    keltner_lower = keltner_mid - 2.0 * atr16 if keltner_mid is not None and atr16 is not None else None
    keltner_upper = keltner_mid + 2.0 * atr16 if keltner_mid is not None and atr16 is not None else None
    keltner_score = band_position_score(price, keltner_lower, keltner_upper)
    keltner_z = (keltner_score - 50.0) / 50.0 if keltner_score is not None else None
    put("moving_averages", "KELTNER(16)", keltner_z,
        {"lower": keltner_lower, "upper": keltner_upper, "price": price},
        "\u0645\u0648\u0642\u0639\u06cc\u062a \u0646\u0633\u0628\u06cc \u062f\u0631 \u06a9\u0627\u0646\u0627\u0644\u061b \u0633\u06cc\u06af\u0646\u0627\u0644 \u062e\u0644\u0627\u0641 \u0631\u0648\u0646\u062f \u0642\u0648\u06cc \u0646\u0635\u0641 \u0645\u06cc\u200c\u0634\u0648\u062f.",
        counter_trend=True)

    # Trend and momentum indicators.
    macd = _at(series.get("macd_line"))
    macd_signal = _at(series.get("macd_signal"))
    macd_z = None
    if atr is not None and atr > 0 and macd is not None and macd_signal is not None:
        macd_z = .5 * _clip(macd / atr) + .5 * _clip((macd - macd_signal) / (.3 * atr))
    put("trend_momentum", "MACD(12,26,9)", macd_z,
        {"MACD": macd, "signal": macd_signal,
         "histogram": macd - macd_signal if macd is not None and macd_signal is not None else None,
         "ATR": atr},
        "\u06f5\u06f0\u066a \u062e\u0637 MACD \u0646\u0633\u0628\u062a \u0628\u0647 \u0635\u0641\u0631 + \u06f5\u06f0\u066a \u0647\u06cc\u0633\u062a\u0648\u06af\u0631\u0627\u0645\u061b \u0647\u0631\u062f\u0648 \u0628\u0627 ATR \u0646\u0631\u0645\u0627\u0644 \u0634\u062f\u0647\u200c\u0627\u0646\u062f.")

    adx_z = None
    if adx is not None and plus_di is not None and minus_di is not None:
        total_di = plus_di + minus_di
        direction = 2.0 * (plus_di - minus_di) / total_di if total_di else 0.0
        strength = max(0.0, min(1.0, (adx - 10.0) / 30.0))
        adx_z = _clip(direction) * strength
    put("trend_momentum", "ADX(14)", adx_z,
        {"ADX": adx, "+DI": plus_di, "-DI": minus_di},
        "\u062c\u0647\u062a \u0627\u0632 \u0645\u0642\u0627\u06cc\u0633\u0647\u200c\u06cc DI\u0647\u0627 \u0648 \u0642\u062f\u0631\u062a \u0627\u0632 \u0645\u0642\u062f\u0627\u0631 ADX \u062d\u0633\u0627\u0628 \u0645\u06cc\u200c\u0634\u0648\u062f.")

    aroon_up, aroon_down = _at(series.get("aroon_up25")), _at(series.get("aroon_down25"))
    aroon_z = _clip((aroon_up - aroon_down) / 100.0) \
        if aroon_up is not None and aroon_down is not None else None
    put("trend_momentum", "AROON(25)", aroon_z,
        {"up": aroon_up, "down": aroon_down,
         "spread": aroon_up - aroon_down if aroon_up is not None and aroon_down is not None else None},
        "\u0627\u062e\u062a\u0644\u0627\u0641 Aroon Up \u0648 Down \u0628\u0631 100 \u0646\u0631\u0645\u0627\u0644 \u0634\u062f\u0647 \u0627\u0633\u062a.")

    ao, ao_previous = _at(series.get("ao534")), _at(series.get("ao534"), -2)
    ao_z = None
    if atr is not None and atr > 0 and ao is not None and ao_previous is not None:
        ao_z = .7 * _clip(ao / (1.5 * atr)) + .3 * _clip((ao - ao_previous) / (.3 * atr))
    put("trend_momentum", "AO(5,34)", ao_z,
        {"AO": ao, "previous": ao_previous, "ATR": atr},
        "\u06f7\u06f0\u066a \u0633\u0637\u062d AO \u0648 \u06f3\u06f0\u066a \u062a\u063a\u06cc\u06cc\u0631\u0634 \u0646\u0633\u0628\u062a \u0628\u0647 \u06a9\u0646\u062f\u0644 \u0642\u0628\u0644\u060c \u0646\u0631\u0645\u0627\u0644\u200c\u0634\u062f\u0647 \u0628\u0627 ATR.")

    # Pivot scores are normalized to the current pivot's S1/R1 range.
    pivot_sets: dict[str, dict[str, float]] = {}
    if len(bars) >= 31:
        previous = bars[-31:-1]
        highs = [_num(row.get("high")) or _num(row.get("close")) for row in previous]
        lows = [_num(row.get("low")) or _num(row.get("close")) for row in previous]
        closes = [_num(row.get("close")) for row in previous]
        previous_open = _num(previous[-1].get("open")) or closes[-1]
        if (all(value is not None for value in highs + lows + closes)
                and previous_open is not None and closes[-1] is not None):
            pivot_sets = _pivot_sets(max(highs), min(lows), closes[-1], previous_open)
    pivot_names = {
        "Fibonacci": "PivotPoint Fibonacci(30)",
        "Classic": "PivotPoint Classic(30)",
        "Camarilla": "PivotPoint Camarilla(30)",
        "Woodie": "PivotPoint Woodie(30)",
        "DeMark": "PivotPoint DeMark(30)",
    }
    for method, key in pivot_names.items():
        levels = pivot_sets.get(method)
        pivot = ((_num(levels.get("S1")) + _num(levels.get("R1"))) / 2.0
                 if scheme == "Camarilla" and levels
                 and _num(levels.get("S1")) is not None and _num(levels.get("R1")) is not None
                 else _num(levels.get("PP")) if levels else None)
        support = _num(levels.get("S1")) if levels else None
        resistance = _num(levels.get("R1")) if levels else None
        z = None
        if pivot is not None and support is not None and resistance is not None:
            if price >= pivot and resistance > pivot:
                z = _clip((price - pivot) / (resistance - pivot))
            elif price < pivot and pivot > support:
                z = _clip((price - pivot) / (pivot - support))
        put("support_resistance", key, z,
            {"pivot": pivot, "S1": support, "R1": resistance},
            "\u0641\u0627\u0635\u0644\u0647\u200c\u06cc \u0642\u06cc\u0645\u062a \u0627\u0632 Pivot \u0628\u0631 \u0627\u0633\u0627\u0633 \u0641\u0627\u0635\u0644\u0647\u200c\u06cc \u0648\u0627\u0642\u0639\u06cc \u062a\u0627 S1 \u06cc\u0627 R1 \u0646\u0631\u0645\u0627\u0644 \u0634\u062f\u0647.")

    # Oscillator values follow the Update 4 piecewise-linear breakpoints.
    oscillator_z_points = [
        (30, [(30, 1), (35, .4), (40, .2), (50, 0), (60, -.2), (65, -.4), (70, -1)]),
        (20, [(20, 1), (30, .4), (40, .2), (50, 0), (60, -.2), (70, -.4), (80, -1)]),
        (-100, [(-100, 1), (-70, .4), (-35, .2), (0, 0), (35, -.2), (70, -.4), (100, -1)]),
    ]
    rsi = _at(series.get("rsi14"))
    put("oscillators", "RSI(14)", _linear(rsi, oscillator_z_points[0][1]),
        {"value": rsi},
        "\u0627\u0645\u062a\u06cc\u0627\u0632 RSI \u0628\u0647\u200c\u0635\u0648\u0631\u062a \u067e\u06cc\u0648\u0633\u062a\u0647 \u0627\u0632 \u0645\u0631\u0632\u0647\u0627\u06cc \u0641\u0627\u06cc\u0644 Update 4 \u062f\u0631\u0648\u0646\u200c\u06cc\u0627\u0628\u06cc \u0645\u06cc\u200c\u0634\u0648\u062f.",
        counter_trend=True)

    mfi = _at(series.get("mfi14"))
    put("oscillators", "MFI(14)", _linear(mfi, oscillator_z_points[1][1]),
        {"value": mfi},
        "\u0628\u0631\u0627\u0633\u0627\u0633 \u0646\u0642\u0627\u0637 \u0634\u06a9\u0633\u062a \u0627\u06a9\u0633\u0644\u061b \u0648\u0631\u0648\u062f \u062d\u062c\u0645 \u0645\u0639\u0627\u0645\u0644\u0647 \u0628\u0631\u0627\u06cc \u0645\u062d\u0627\u0633\u0628\u0647 \u0644\u0627\u0632\u0645 \u0627\u0633\u062a.",
        counter_trend=True)

    cci = _at(series.get("cci14"))
    put("oscillators", "CCI(14)", _linear(cci, oscillator_z_points[2][1]),
        {"value": cci},
        "\u0628\u0631\u0627\u0633\u0627\u0633 \u0646\u0642\u0627\u0637 \u0634\u06a9\u0633\u062a CCI \u062f\u0631 \u0641\u0627\u06cc\u0644 Update 4.",
        counter_trend=True)

    so_k = _at(series.get("so_k"))
    put("oscillators", "SO(14) %K", _linear(so_k, oscillator_z_points[1][1]),
        {"value": so_k},
        "\u0627\u0645\u062a\u06cc\u0627\u0632 \u0627\u0632 %K \u0627\u0633\u062a\u0648\u06a9\u0627\u0633\u062a\u06cc\u06a9 \u062d\u0633\u0627\u0628 \u0645\u06cc\u200c\u0634\u0648\u062f\u061b WR \u0647\u0645\u200c\u0627\u0631\u0632 \u0627\u0633\u062a \u0648 \u062c\u062f\u0627\u06af\u0627\u0646\u0647 \u0634\u0645\u0627\u0631\u0634 \u0646\u0645\u06cc\u200c\u0634\u0648\u062f.",
        counter_trend=True)

    stochrsi = _at(series.get("stochrsi14"))
    stochrsi_100 = stochrsi * 100.0 if stochrsi is not None else None
    put("oscillators", "StochRSI(14) %K",
        _linear(stochrsi_100, oscillator_z_points[1][1]),
        {"value": stochrsi},
        "\u0627\u0645\u062a\u06cc\u0627\u0632 \u0628\u0627 \u0646\u0642\u0627\u0637 \u0634\u06a9\u0633\u062a \u06f0\u002e\u06f2 \u062a\u0627 \u06f0\u002e\u06f8 \u062f\u0631 \u0645\u0642\u06cc\u0627\u0633 \u06f0 \u062a\u0627 \u06f1 \u0645\u062d\u0627\u0633\u0628\u0647 \u0645\u06cc\u200c\u0634\u0648\u062f.",
        counter_trend=True)

    closes = [_num(row.get("close")) for row in bars]
    mtm = closes[-1] - closes[-7] if len(closes) >= 7 and closes[-1] is not None and closes[-7] is not None else None
    mtm_z = (_clip(mtm / (1.5 * atr * math.sqrt(6.0)))
             if mtm is not None and atr is not None and atr > 0 else None)
    put("oscillators", "MTM(6)", mtm_z,
        {"change": mtm, "ATR": atr, "period": 6},
        "\u062a\u063a\u06cc\u06cc\u0631 \u0642\u06cc\u0645\u062a \u0637\u06cc \u06f6 \u06a9\u0646\u062f\u0644 \u0628\u0631 ATR \u00d7 \u221a6 \u0646\u0631\u0645\u0627\u0644 \u0634\u062f\u0647.")

    return results


def score_tse_bars(bars: list[dict[str, Any]] | None, *, horizon: str = "long",
                   trend_value: float | None = None,
                   trend_schema_type: str | None = None,
                   trading_status: str | None = None) -> dict[str, Any]:
    """Score available indicators and redistribute missing weights in-group."""
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
    raw_family_scores: dict[str, float] = {}
    coverage_by_family: dict[str, float] = {}
    valid_indicators: list[tuple[str, float, float]] = []
    effective_indicator_weights: dict[str, dict[str, float]] = {}

    for family, weights in indicator_weights.items():
        available: list[tuple[dict[str, Any], float]] = []
        missing: list[str] = []
        for name, weight in weights.items():
            item = scored.get(family, {}).get(name)
            if item is None or item.get("score") is None:
                missing.append(name)
                continue
            available.append((dict(item), weight))

        coverage = sum(weight for _, weight in available)
        rows: list[dict[str, Any]] = []
        effective_indicator_weights[family] = {}
        if coverage > 0:
            for item, weight in available:
                item["sub_cluster"] = family
                item["weight_pct"] = round(weight / coverage * 100.0, 2)
                rows.append(item)
                effective_indicator_weights[family][item["key"]] = round(weight / coverage * 100.0, 2)
                valid_indicators.append((family, weight, float(item["score"])))
        group_score = (sum(float(item["score"]) * weight for item, weight in available) / coverage
                       if coverage > 0 else None)
        coverage_by_family[family] = coverage
        if group_score is not None:
            raw_family_scores[family] = group_score
        for item in rows:
            item["score"] = round(float(item["score"]), 2)
        family_results[family] = {
            "score": round(group_score, 2) if group_score is not None else None,
            "coverage_pct": round(coverage * 100.0, 1),
            "signal": _signal(group_score),
            "indicators": rows,
            "missing_indicators": missing,
            "sub_clusters": {"all_indicators": {
                "score": round(group_score, 2) if group_score is not None else None,
                "coverage_pct": round(coverage * 100.0, 1),
                "weight_pct": 100.0,
                "indicators": [item["key"] for item in rows],
            }},
        }

    valid_groups = [family for family in family_weights
                    if family_results[family]["score"] is not None]
    available_family_weight = sum(family_weights[family] for family in valid_groups)
    if not valid_groups or available_family_weight <= 0:
        raw_score = final_score = dispersion = None
        effective: dict[str, float] = {}
        coverage = agreement = 0.0
        final_signal = "Insufficient Data"
    else:
        effective = {family: family_weights[family] / available_family_weight
                     for family in valid_groups}
        raw_score = sum(effective[family] * raw_family_scores[family]
                        for family in valid_groups)
        final_score = max(0.0, min(100.0, raw_score))
        dispersion = math.sqrt(sum(effective[family] *
                                   (raw_family_scores[family] - raw_score) ** 2
                                   for family in valid_groups))
        final_signal = {"Buy": "Bullish", "Sell": "Bearish",
                        "Neutral": "Neutral"}[_signal(final_score)]
        coverage = sum(family_weights[family] * coverage_by_family[family]
                       for family in family_weights)
        directional = [(family_weights[family] * weight, value)
                       for family, weight, value in valid_indicators
                       if abs(value - 50.0) >= 5.0]
        directional_weight = sum(weight for weight, _ in directional)
        result_up = final_score > 50.0
        aligned_weight = sum(weight for weight, value in directional
                             if (value > 50.0) == result_up)
        agreement = aligned_weight / directional_weight if directional_weight else 0.0

    if final_score is None or coverage < .70:
        confidence_level = "insufficient"
        decision = "Insufficient Data"
    elif agreement >= .75:
        confidence_level = "high"
        decision = ("Buy Confirmed" if final_signal == "Bullish" else "Sell Confirmed"
                    if final_signal == "Bearish" else "Neutral")
    elif agreement >= .60:
        confidence_level = "medium"
        decision = ("Buy Confirmed" if final_signal == "Bullish" else "Sell Confirmed"
                    if final_signal == "Bearish" else "Neutral")
    else:
        confidence_level = "low"
        decision = ("Buy, Low Confidence" if final_signal == "Bullish" else
                    "Sell, Low Confidence" if final_signal == "Bearish" else "Neutral")

    score_weights = {family: round(weight * 100.0, 2)
                     for family, weight in family_weights.items()}
    normalized_indicator_weights = {
        family: {name: round(weight * 100.0, 2) for name, weight in weights.items()}
        for family, weights in indicator_weights.items()
    }
    decision_labels = {
        "Buy Confirmed": "\u062e\u0631\u06cc\u062f \u062a\u0623\u06cc\u06cc\u062f\u0634\u062f\u0647",
        "Buy, Low Confidence": "\u062e\u0631\u06cc\u062f \u0628\u0627 \u0627\u0637\u0645\u06cc\u0646\u0627\u0646 \u067e\u0627\u06cc\u06cc\u0646",
        "Buy Lean": "\u062a\u0645\u0627\u06cc\u0644 \u0628\u0647 \u062e\u0631\u06cc\u062f",
        "Neutral": "\u062e\u0646\u062b\u06cc",
        "Sell Lean": "\u062a\u0645\u0627\u06cc\u0644 \u0628\u0647 \u0641\u0631\u0648\u0634",
        "Sell Confirmed": "\u0641\u0631\u0648\u0634 \u062a\u0623\u06cc\u06cc\u062f\u0634\u062f\u0647",
        "Sell, Low Confidence": "\u0641\u0631\u0648\u0634 \u0628\u0627 \u0627\u0637\u0645\u06cc\u0646\u0627\u0646 \u067e\u0627\u06cc\u06cc\u0646",
        "Insufficient Data": "\u062f\u0627\u062f\u0647 \u0646\u0627\u06a9\u0627\u0641\u06cc",
    }
    # Apply the workbook's status filter only when a source supplies a status.
    status = str(trading_status or "").strip()
    if status and status.casefold() not in {"normal", "active", "trading", "open", "عادی", "مجاز"}:
        decision = "Invalid Market Status"
        decision_labels[decision] = f"نامعتبر ({status})"
    return {
        "technical_score": round(final_score, 2) if final_score is not None else None,
        "raw_score": round(raw_score, 2) if raw_score is not None else None,
        "signal": final_signal,
        "decision": decision,
        "decision_label": decision_labels[decision],
        "score_band": {"Bullish": "bullish", "Bearish": "bearish",
                       "Neutral": "neutral", "Insufficient Data": "unavailable"}[final_signal],
        "confidence": round(100.0 * coverage * agreement, 1),
        "confidence_level": confidence_level,
        "confluence_pct": round(agreement * 100.0, 1),
        "inter_group_dispersion": round(dispersion, 2) if dispersion is not None else None,
        "damping_factor": 0.5,
        "family_scores": family_results,
        "score_weights": score_weights,
        "effective_score_weights": {family: round(weight * 100.0, 2)
                                     for family, weight in effective.items()},
        "indicator_weights": normalized_indicator_weights,
        "effective_indicator_weights": effective_indicator_weights,
        "data_coverage_pct": round(coverage * 100.0, 1),
        "available_family_weight_pct": round(available_family_weight * 100.0, 1),
        "valid_groups": valid_groups,
        "observations": len(normalized),
        "investment_horizon": horizon,
        "score_method": f"tse_update4_scoring_{horizon}",
    }


def _empty_result(horizon: str = "long") -> dict[str, Any]:
    horizon = normalize_horizon(horizon)
    profile = FUND_SCORING_PROFILES[horizon]
    family_weights: dict[str, float] = profile["family_weights"]  # type: ignore[assignment]
    indicator_weights: dict[str, dict[str, float]] = profile["indicator_weights"]  # type: ignore[assignment]
    groups = {
        family: {"score": None, "coverage_pct": 0.0, "signal": "Insufficient Data",
                 "indicators": [], "missing_indicators": list(weights), "sub_clusters": {}}
        for family, weights in indicator_weights.items()
    }
    return {
        "technical_score": None, "raw_score": None,
        "signal": "Insufficient Data", "decision": "Insufficient Data",
        "decision_label": "\u062f\u0627\u062f\u0647 \u0646\u0627\u06a9\u0627\u0641\u06cc",
        "score_band": "unavailable", "confidence": 0.0,
        "confidence_level": "insufficient", "confluence_pct": 0.0,
        "inter_group_dispersion": None, "damping_factor": 0.5,
        "family_scores": groups,
        "score_weights": {family: weight * 100.0 for family, weight in family_weights.items()},
        "effective_score_weights": {},
        "indicator_weights": {
            family: {name: weight * 100.0 for name, weight in weights.items()}
            for family, weights in indicator_weights.items()
        },
        "effective_indicator_weights": {family: {} for family in indicator_weights},
        "data_coverage_pct": 0.0, "available_family_weight_pct": 0.0,
        "valid_groups": [], "observations": 0,
        "investment_horizon": horizon,
        "score_method": f"tse_update4_scoring_{horizon}",
    }
