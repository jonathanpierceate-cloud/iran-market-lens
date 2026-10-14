"""OHLCV-based TSE technical scoring engine defined by v1 of the TSE spec."""
from __future__ import annotations

import math
from typing import Any

from .indicators import compute_indicators

EPS = 1e-9

GROUP_WEIGHTS = {
    "support_resistance": 0.20,
    "moving_averages": 0.30,
    "volume": 0.25,
    "oscillators": 0.25,
}

# Indicator weights are proportions of their main group. Within each listed
# sub-cluster, the indicator weights sum to the sub-cluster's group weight.
SUBCLUSTERS: dict[str, dict[str, dict[str, Any]]] = {
    "support_resistance": {
        "central_pivots": {"weight": .45, "indicators": {
            "PivotPointClassic(30)": .20, "PivotPointFibonacci(30)": .15,
            "PivotPointWoodie(30)": .10}},
        "camarilla_pivot": {"weight": .35, "indicators": {"PivotPointCamarilla(30)": .35}},
        "demark_pivot": {"weight": .20, "indicators": {"PivotPointDeMark(30)": .20}},
    },
    "moving_averages": {
        "short_term_ma": {"weight": .15, "indicators": {
            "EMA(5)": .036, "SMA(5)": .024, "EMA(10)": .054, "SMA(10)": .036}},
        "medium_term_ma": {"weight": .25, "indicators": {
            "EMA(20)": .054, "SMA(20)": .036, "EMA(30)": .048,
            "SMA(30)": .032, "EMA(50)": .048, "SMA(50)": .032}},
        "long_term_ma": {"weight": .20, "indicators": {
            "EMA(100)": .060, "SMA(100)": .040,
            "EMA(200)": .060, "SMA(200)": .040}},
        "ichimoku_system": {"weight": .25, "indicators": {"Ichimoku Cloud(9,26,52,26)": .25}},
        "volatility_bands": {"weight": .15, "indicators": {"BB(20)": .09, "KELTNER(16)": .06}},
    },
    "volume": {
        "relative_volume": {"weight": .25, "indicators": {
            "RV(15)": .10, "RV(30)": .09, "RV(90)": .06}},
        "smart_money": {"weight": .25, "indicators": {"SM(15)": .25}},
        "cumulative_volume": {"weight": .20, "indicators": {"OBV(20)": .20}},
        "volume_momentum": {"weight": .30, "indicators": {"VRSI(14)": .15, "VMACD(26)": .15}},
    },
    "oscillators": {
        "rsi_family": {"weight": .18, "indicators": {"RSI(14)": .12, "StochRSI(14)": .06}},
        "money_flow": {"weight": .15, "indicators": {"MFI(14)": .15}},
        "channel_oscillators": {"weight": .22, "indicators": {
            "CCI(14)": .10, "SO(14)": .07, "WR(14)": .05}},
        "macd_momentum": {"weight": .25, "indicators": {
            "MACD(26)": .12, "AO(5,34)": .06, "MTM(6)": .07}},
        "trend_strength": {"weight": .20, "indicators": {
            "ADX(14)": .10, "AROON(25)": .06, "Trend": .04}},
    },
}

_MA_CALIBRATION = {
    5: (.60, 1, 1.8), 10: (.85, 2, 2.4), 20: (1.20, 3, 3.2),
    30: (1.46, 3, 3.8), 50: (1.89, 5, 4.8), 100: (2.67, 5, 6.5),
    200: (3.78, 10, 9.0),
}
_RV_THETA = {15: 1.4, 30: 1.5, 90: 1.7}


def _num(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _clip(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(value, high))


def _lerp(value: float, x1: float, x2: float, y1: float, y2: float) -> float:
    if abs(x2 - x1) < EPS:
        return (y1 + y2) / 2.0
    bounded = _clip(value, min(x1, x2), max(x1, x2))
    return y1 + ((bounded - x1) / (x2 - x1)) * (y2 - y1)


def _safe_atr(atr14: float | None, close: float) -> float:
    if atr14 is None or atr14 <= 0:
        return .025 * max(close, 1.0)
    return max(atr14, .005 * max(close, 1.0))


def _tanh(value: float) -> float:
    return math.tanh(value)


def _at(series: Any, index: int = -1) -> float | None:
    if not isinstance(series, (list, tuple)) or not series:
        return None
    try:
        return _num(series[index])
    except IndexError:
        return None


def _series_mean(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _sig(score: float | None) -> str:
    if score is None:
        return "Insufficient Data"
    if score >= 60:
        return "Bullish"
    if score < 30:
        return "Bearish"
    return "Neutral"


def _candle_clv(close: float, high: float, low: float, ret: float) -> float:
    if high > low:
        return ((close - low) - (high - close)) / (high - low)
    return 1.0 if ret >= 0 else -1.0


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


def _pivot_score(price: float, previous: float, open_t: float, high_t: float,
                 low_t: float, atr: float, rv15: float,
                 levels: dict[str, float]) -> float | None:
    pivot = levels.get("PP")
    if pivot is None:
        return None
    safe = max(atr, .005 * max(price, 1.0))
    base = 50.0 + 25.0 * _tanh(.5 * ((price - pivot) / safe))
    candle_range = max(high_t - low_t, .01 * price)
    reversal = _clip(((price - open_t) + (price - low_t) - (high_t - price))
                     / (2.0 * candle_range), -1.0, 1.0)
    level_values = [value for value in levels.values() if math.isfinite(value)]
    below = [value for value in level_values if value <= price]
    above = [value for value in level_values if value > price]
    low_level = max(below) if below else None
    high_level = min(above) if above else None
    modifier = 0.0
    if any(previous < level and price > level + .15 * safe for level in level_values):
        modifier = 15.0 + 15.0 * _clip((rv15 - .8) / 1.2, 0.0, 1.0)
    elif any(previous > level and price < level - .15 * safe for level in level_values):
        modifier = -20.0 - 10.0 * _clip((rv15 - .8) / 1.2, 0.0, 1.0)
    else:
        d_sup = (price - low_level) / safe if low_level is not None else math.inf
        d_res = (high_level - price) / safe if high_level is not None else math.inf
        sup_delta = (18.0 * (1.0 - d_sup / .6) * reversal
                     if d_sup <= .6 and reversal > .2 else
                     -8.0 * (1.0 - d_sup / .6) if d_sup <= .6 else 0.0)
        if d_res <= .6 and reversal < -.2:
            res_delta = -20.0 * (1.0 - d_res / .6) * abs(reversal)
        elif d_res <= .6 and reversal > .3 and rv15 > 1.3:
            res_delta = 8.0 * (1.0 - d_res / .6)
        elif d_res <= .6:
            res_delta = -10.0 * (1.0 - d_res / .6)
        else:
            res_delta = 0.0
        modifier = sup_delta + res_delta
    return _clip(base + modifier)


def _ma_score(price: float, previous: float, open_t: float, atr: float,
              ma_series: Any, period: int) -> tuple[float | None, float | None, str | None]:
    gamma, k, extended = _MA_CALIBRATION[period]
    current_ma, previous_ma, lagged_ma = _at(ma_series), _at(ma_series, -2), _at(ma_series, -(k + 1))
    if any(value is None for value in (current_ma, previous_ma, lagged_ma)):
        return None, current_ma, None
    safe = _safe_atr(atr, price)
    distance = (price - current_ma) / safe
    z_distance = distance / gamma
    z_slope = (current_ma - lagged_ma) / (k * safe)
    score = 50 + 25 * _tanh(.9 * z_distance) + 15 * _tanh(3.5 * z_slope)
    if previous < previous_ma and price > current_ma and z_slope >= 0:
        score += 10
    elif previous > previous_ma and price < current_ma and z_slope <= 0:
        score -= 10
    if distance > extended:
        score -= 18 * _tanh(.5 * (distance - extended))
    elif distance < -extended and price > open_t:
        score += 12 * _tanh(.5 * (abs(distance) - extended))
    score = _clip(score)
    signal = "Neutral" if price < current_ma and score >= 60 else _sig(score)
    return score, current_ma, signal


def _ichimoku_score(series: dict[str, Any], close: float, atr: float) -> float | None:
    tenkan, kijun = _at(series.get("tenkan")), _at(series.get("kijun"))
    span_a = _at(series.get("span_a_cloud"))
    span_b = _at(series.get("span_b_cloud"))
    span_a_future = _at(series.get("span_a_future"))
    span_b_future = _at(series.get("span_b_future"))
    close_lag26 = _at(series.get("close"), -27)
    if any(value is None for value in (tenkan, kijun, span_a, span_b,
                                       span_a_future, span_b_future, close_lag26)):
        return None
    safe = _safe_atr(atr, close)
    top, bottom = max(span_a, span_b), min(span_a, span_b)
    if close > top:
        kumo = 26 + 14 * _tanh(.6 * (close - top) / safe)
    elif close < bottom:
        kumo = 14 - 14 * _tanh(.6 * (bottom - close) / safe)
    else:
        kumo = 14 + 12 * (close - bottom) / (top - bottom + EPS)
    tk = 12.5 + 8 * _tanh(.8 * (tenkan - kijun) / safe) + 4.5 * _tanh(.5 * (close - kijun) / safe)
    chikou = 10 + 10 * _tanh(.4 * (close - close_lag26) / safe)
    future = 7.5 + 7.5 * _tanh(.6 * (span_a_future - span_b_future) / safe)
    return _clip(kumo + tk + chikou + future)


def _keltner_score(series: dict[str, Any], close: float, open_t: float,
                   atr14: float, rv15: float | None) -> float | None:
    mid_series = series.get("keltner_mid")
    mid, mid_lag3 = _at(mid_series), _at(mid_series, -4)
    atr16 = _at(series.get("atr16"))
    if any(value is None for value in (mid, mid_lag3, atr16, rv15)):
        return None
    kpos = (close - mid) / (2 * atr16 + EPS)
    slope = (mid - mid_lag3) / (3 * _safe_atr(atr14, close) + EPS)
    if kpos > 1.0 and slope > .05 and rv15 >= 1.2:
        return _clip(75 + 15 * _tanh(kpos - 1) + 10 * _tanh(3 * slope), 65, 95)
    if kpos > 1.0 and (slope <= .05 or rv15 < 1.2):
        return _clip(60 - 15 * (kpos - 1), 35, 60)
    if -1 <= kpos <= 1:
        return _clip(48 + 22 * kpos + 15 * _tanh(3 * slope), 15, 85)
    if kpos < -1 and slope < -.05:
        return _clip(20 + 15 * (kpos + 1), 0, 25)
    if kpos < -1 and slope >= -.05 and close > open_t:
        return 55.0
    return 28.0


def _bb_score(series: dict[str, Any], close: float, open_t: float,
              atr14: float, adx: float | None, bwr: float | None) -> float | None:
    mid = _at(series.get("bb_mid"))
    mid_lag3 = _at(series.get("bb_mid"), -4)
    upper, lower = _at(series.get("bb_upper")), _at(series.get("bb_lower"))
    if any(value is None for value in (mid, mid_lag3, upper, lower, adx, bwr)):
        return None
    pct_b = (close - lower) / (upper - lower + EPS)
    m_bb = (mid - mid_lag3) / (3 * _safe_atr(atr14, close) + EPS)
    breakout = (bwr > 1.15 and abs(m_bb) > .10) or adx > 25
    if breakout:
        if pct_b >= .85 and m_bb > .10:
            return _clip(70 + 20 * _tanh(2 * (pct_b - .85)) + 10 * _tanh(2 * m_bb), 65, 95)
        if pct_b <= .15 and m_bb < -.10:
            return _clip(20 - 15 * _tanh(2 * (.15 - pct_b)), 0, 25)
        return _clip(30 + 40 * pct_b + 15 * _tanh(3 * m_bb), 20, 80)
    if pct_b > .95:
        return _lerp(pct_b, .95, 1.20, 35, 20) if close < open_t else 52.0
    if pct_b < .05:
        return _lerp(pct_b, -.20, .05, 78, 65) if close > open_t else 32.0
    return _clip(30 + 40 * pct_b + 15 * _tanh(3 * m_bb), 20, 80)


def _relative_volume_score_n(ratio: float, period: int, close: float,
                             previous: float, high: float, low: float) -> float:
    ret = (close - previous) / (previous + EPS)
    clv = _candle_clv(close, high, low, ret)
    direction = .6 * _clip(ret / .035, -1, 1) + .4 * clv
    intensity = (.2 * ratio / .7 if ratio < .7 else
                 .2 + .8 * _tanh((ratio - .7) / _RV_THETA[period]))
    return _clip(46 + 54 * intensity * direction)


def _smart_money_score(closes: list[float], highs: list[float], lows: list[float],
                       volumes: list[float], volume_valid: list[bool]
                       ) -> tuple[float | None, float | None, float | None]:
    if len(closes) < 18 or not all(volume_valid[-18:]):
        return None, None, None

    def cmf15(end: int) -> float | None:
        start = end - 14
        if start < 0:
            return None
        total = sum(volumes[start:end + 1])
        if total <= EPS:
            return None
        terms = []
        for index in range(start, end + 1):
            previous = closes[index - 1] if index else closes[index]
            ret = (closes[index] - previous) / (previous + EPS)
            terms.append(_candle_clv(closes[index], highs[index], lows[index], ret) * volumes[index])
        return sum(terms) / (total + EPS)

    current, prior = cmf15(len(closes) - 1), cmf15(len(closes) - 4)
    if current is None or prior is None:
        return None, current, prior
    delta = current - prior
    if current < -.10:
        base = _lerp(current, -.60, -.10, 0, 30)
    elif current < .15:
        base = _lerp(current, -.10, .15, 30, 60)
    else:
        base = _lerp(current, .15, .65, 60, 92)
    return _clip(base + 10 * _tanh(5 * delta)), current, prior


def _vrsi_score(vrsi: float, vrsi_lag2: float) -> float:
    delta = vrsi - vrsi_lag2
    if vrsi < 42:
        base = _lerp(vrsi, 15, 42, 0, 30)
    elif vrsi < 56:
        base = _lerp(vrsi, 42, 56, 30, 60)
    else:
        base = _lerp(vrsi, 56, 85, 60, 92)
    return _clip(base + 8 * _tanh(.15 * delta))


def _obv_score(obv: float, obv_sma20: float, obv_lag20: float,
               avg_volume20: float, price: float, price_lag20: float,
               atr14: float) -> float | None:
    if avg_volume20 <= 0:
        return None
    z_pos = (obv - obv_sma20) / (5 * avg_volume20 + EPS)
    z_slope = (obv - obv_lag20) / (8 * avg_volume20 + EPS)
    t_obv = _tanh(.6 * z_pos + .4 * z_slope)
    t_price = _tanh((price - price_lag20) / (4 * _safe_atr(atr14, price)))
    divergence = 18 if t_price < -.20 and t_obv > .15 else (
        -22 if t_price > .20 and t_obv < -.15 else 0)
    return _clip(48 + 38 * t_obv + divergence)


def _rsi_score(value: float, previous: float, lag3: float,
               close: float, ema50: float, adx: float) -> float:
    delta = value - previous
    delta3 = value - lag3
    bull_regime = close > ema50 and adx >= 25
    if value < 30:
        base = 65 + 20 * (1 - value / 30) if delta > 1.5 else _lerp(value, 0, 30, 5, 25)
    elif value < 48:
        base = _lerp(value, 30, 48, 25, 45)
    elif value < 55:
        base = _lerp(value, 48, 55, 45, 60)
    elif value <= 70:
        base = _lerp(value, 55, 70, 60, 82)
    elif bull_regime and delta >= 0:
        base = _lerp(value, 70, 82, 82, 70)
    else:
        base = _lerp(value, 70, 85, 55, 22)
    return _clip(base + 6 * _tanh(delta3 / 5))


def _mfi_score(value: float, previous: float, lag5: float,
               close: float, close_lag5: float) -> float:
    delta = value - previous
    if value < 20:
        base = 72.0 if delta > 2 else _lerp(value, 0, 20, 5, 22)
    elif value < 45:
        base = _lerp(value, 20, 45, 22, 42)
    elif value < 55:
        base = _lerp(value, 45, 55, 42, 60)
    elif value <= 78:
        base = _lerp(value, 55, 78, 60, 85)
    elif delta < 0:
        base = _lerp(value, 78, 95, 55, 20)
    else:
        base = 68.0
    divergence = 12 if close < close_lag5 and value > lag5 + 5 else (
        -15 if close > close_lag5 and value < lag5 - 5 else 0)
    return _clip(base + 5 * _tanh(delta / 3) + divergence)


def _cci_score(value: float, previous: float) -> float:
    delta = value - previous
    if value < -200:
        base = 10.0
    elif value < -100:
        base = _lerp(value, -200, -100, 55, 68) if delta > 15 else _lerp(value, -200, -100, 10, 28)
    elif value < -20:
        base = _lerp(value, -100, -20, 28, 42)
    elif value < 30:
        base = _lerp(value, -20, 30, 42, 60)
    elif value < 100:
        base = _lerp(value, 30, 100, 60, 75)
    elif delta >= -10:
        base = _lerp(value, 100, 220, 75, 90)
    else:
        base = _lerp(value, 100, 250, 62, 35)
    return _clip(base + 5 * _tanh(delta / 25))


def _wr_score(value: float, previous: float) -> float:
    if value > 0:
        value = -value
    if previous > 0:
        previous = -previous
    delta = value - previous
    if -85 <= value <= -70 and previous < -80 and delta >= 8:
        base = 68.0
    elif value < -80:
        base = _lerp(value, -100, -80, 5, 25)
    elif value < -50:
        base = _lerp(value, -80, -50, 25, 48)
    elif value <= -20:
        base = _lerp(value, -50, -20, 48, 78)
    elif delta >= -3:
        base = _lerp(value, -20, 0, 78, 85)
    else:
        base = _lerp(value, -25, 0, 52, 25)
    return _clip(base + 6 * _tanh(delta / 10))


def _so_score(k: float, d: float, k_prev: float, d_prev: float) -> float:
    delta_k = k - k_prev
    diff, diff_prev = k - d, k_prev - d_prev
    if k <= 25 and delta_k > 4:
        position = _lerp(k, 0, 25, 55, 68)
    elif k < 20:
        position = _lerp(k, 0, 20, 10, 28)
    elif k < 50:
        position = _lerp(k, 20, 50, 28, 50)
    elif k <= 80:
        position = _lerp(k, 50, 80, 50, 76)
    elif delta_k >= -2:
        position = 78.0
    else:
        position = 35.0
    cross = 10 if diff_prev <= 0 and diff > 0 and k < 40 else (
        -12 if diff_prev >= 0 and diff < 0 and k > 65 else 0)
    return _clip(position + 10 * _tanh(diff / 8) + cross)


def _stochrsi_score(value: float, previous: float) -> float | None:
    current, prior = value, previous
    if current <= 1.0:
        current *= 100
    if prior <= 1.0:
        prior *= 100
    if not 0 <= current <= 100 or not 0 <= prior <= 100:
        return None
    delta = current - prior
    if 10 <= current <= 30 and prior < 20 and delta >= 8:
        base = 70.0
    elif current < 20 and delta < 8:
        base = _lerp(current, 0, 20, 12, 28)
    elif current < 50:
        base = _lerp(current, 20, 50, 28, 50)
    elif current <= 80:
        base = _lerp(current, 50, 80, 50, 72)
    elif delta >= 0:
        base = 75.0
    else:
        base = 25.0
    return _clip(base + 6 * _tanh(delta / 12))


def _adx_score(adx: float, adx_previous: float, plus_di: float | None,
               minus_di: float | None, price: float, ema20: float | None,
               atr14: float) -> float | None:
    if plus_di is not None and minus_di is not None:
        direction = _tanh(2.5 * (plus_di - minus_di) / (plus_di + minus_di + EPS))
    elif ema20 is not None:
        direction = _tanh((price - ema20) / (1.5 * _safe_atr(atr14, price)))
    else:
        return None
    if adx < 18:
        strength = .15 * adx / 18
    elif adx <= 50:
        strength = .15 + .85 * (adx - 18) / 32
    elif adx >= adx_previous:
        strength = 1.0
    else:
        strength = .70
    return _clip(46 + 52 * strength * direction)


def _ao_score(value: float, previous: float, lag2: float,
              price: float, atr14: float) -> float:
    safe = _safe_atr(atr14, price)
    a0 = value / safe
    delta1 = (value - previous) / safe
    delta2 = (previous - lag2) / safe
    base = 48 + 26 * _tanh(.8 * a0) + 16 * _tanh(2.5 * delta1)
    pattern = 12 if previous <= 0 and value > 0 else (
        8 if value > 0 and previous > 0 and delta2 < 0 and delta1 > 0 else
        -12 if previous >= 0 and value < 0 else
        -8 if value < 0 and previous < 0 and delta2 > 0 and delta1 < 0 else 0)
    return _clip(base + pattern)


def _macd_score(line: float, hist: float, hist_previous: float,
                price: float, atr14: float) -> float:
    safe = _safe_atr(atr14, price)
    m = line / safe
    h = hist / safe
    delta_h = (hist - hist_previous) / safe
    zero = 20 * _tanh(.7 * m)
    histogram = 15 * _tanh(2 * h) + 10 * _tanh(4 * delta_h)
    cross = (12 if hist_previous <= 0 < hist and line < 0 else
             10 if hist_previous <= 0 < hist and line >= 0 else
             -12 if hist_previous >= 0 and hist < 0 else 0)
    return _clip(48 + zero + histogram + cross)


def _mtm_score(value: float, previous: float, price: float, atr14: float) -> float:
    safe = _safe_atr(atr14, price)
    z = value / (2.45 * safe)
    delta_z = (value - previous) / safe
    return _clip(48 + 34 * _tanh(.9 * z) + 16 * _tanh(1.5 * delta_z))


def _trend_score(value: float | None, schema: str | None,
                 price: float, atr14: float) -> float | None:
    schema = str(schema or "UNKNOWN").upper()
    if value is None or schema == "UNKNOWN":
        return None
    if schema == "SUPERTREND":
        distance = (price - value) / _safe_atr(atr14, price)
        if price > value:
            return _clip(62 + 25 * _tanh(.5 * distance), 60, 90)
        return _clip(28 - 22 * _tanh(.5 * abs(distance)), 5, 30)
    if schema == "DISCRETE_FLAG":
        return {1.0: 75.0, 0.0: 45.0, -1.0: 15.0}.get(value)
    if schema == "NORMALIZED_SLOPE":
        return _clip(48 + 45 * _tanh(1.8 * value))
    return None


def _bb_width_ratio(series: dict[str, Any]) -> float | None:
    upper = series.get("bb_upper")
    lower = series.get("bb_lower")
    mid = series.get("bb_mid")
    if not all(isinstance(items, (list, tuple)) for items in (upper, lower, mid)):
        return None
    widths: list[float | None] = []
    for hi, lo, center in zip(upper, lower, mid):
        hi, lo, center = _num(hi), _num(lo), _num(center)
        widths.append((hi - lo) / center if hi is not None and lo is not None and center and center > 0 else None)
    if len(widths) < 21 or widths[-1] is None:
        return None
    prior = [value for value in widths[-21:-1] if value is not None]
    avg = sum(prior) / len(prior) if len(prior) == 20 else None
    return widths[-1] / avg if avg and avg > EPS else None


def _indicator_scores(bars: list[dict[str, Any]], series: dict[str, Any],
                      trend_value: float | None, trend_schema_type: str | None) -> dict[str, dict[str, dict[str, Any]]]:
    closes = [_num(item.get("close")) for item in bars]
    highs = [_num(item.get("high")) for item in bars]
    lows = [_num(item.get("low")) for item in bars]
    opens = [_num(item.get("open")) for item in bars]
    volumes = [_num(item.get("volume")) for item in bars]
    closes = [value for value in closes if value is not None]
    # Bars are normalized before this function, so the aligned OHLC arrays have equal lengths.
    if not closes or len(closes) != len(highs) or any(v is None for v in highs + lows + opens):
        return {}
    highs = [float(value) for value in highs]
    lows = [float(value) for value in lows]
    opens = [float(value) for value in opens]
    # Missing volume should only disable volume-derived indicators; it must not
    # discard valid price, trend, oscillator, or pivot calculations.
    volumes = [float(value) if value is not None else 0.0 for value in volumes]
    n = len(closes)
    price, previous, open_t, high_t, low_t = closes[-1], closes[-2] if n > 1 else None, opens[-1], highs[-1], lows[-1]
    if previous is None:
        return {}
    atr = _at(series.get("atr14"))
    safe = _safe_atr(atr, price)
    scores: dict[str, dict[str, dict[str, Any]]] = {group: {} for group in SUBCLUSTERS}

    def put(group: str, name: str, score: float | None, value: Any = None,
            note: str = "", signal: str | None = None) -> None:
        if score is not None and not math.isfinite(score):
            score = None
        if score is not None:
            score = _clip(score)
        scores[group][name] = {"key": name, "score": round(score, 2) if score is not None else None,
                               "weight_pct": 0.0, "value": value, "note": note,
                               "signal": signal or _sig(score)}

    volume_valid = [(_num(item.get("volume")) or 0.0) > 0 for item in bars]
    volume_history_complete = bool(volume_valid) and all(volume_valid)
    rv: dict[int, float | None] = {}
    for period in (15, 30, 90):
        if n > period and all(volume_valid[-(period + 1):]):
            avg = sum(volumes[-period-1:-1]) / period
            rv[period] = volumes[-1] / avg if avg > EPS else None
        else:
            rv[period] = None
    rv15 = rv[15]

    # G1: 30-trading-day pivot levels and their candle/volume reaction.
    pivot_sets: dict[str, dict[str, float]] = {}
    if n >= 31 and rv15 is not None:
        prior_bars = bars[-31:-1]
        high30 = max(float(item["high"]) for item in prior_bars)
        low30 = min(float(item["low"]) for item in prior_bars)
        close30 = closes[-2]
        open30 = float(prior_bars[0]["open"])
        pivot_sets = _pivot_sets(high30, low30, close30, open30)
    for method, name in (("Classic", "PivotPointClassic(30)"),
                         ("Fibonacci", "PivotPointFibonacci(30)"),
                         ("Woodie", "PivotPointWoodie(30)"),
                         ("Camarilla", "PivotPointCamarilla(30)"),
                         ("DeMark", "PivotPointDeMark(30)")):
        levels = pivot_sets.get(method)
        value = {"levels": levels, "RV15": rv15} if levels else None
        score = (_pivot_score(price, previous, open_t, high_t, low_t,
                              atr if atr is not None else safe, rv15, levels)
                 if levels and rv15 is not None else None)
        put("support_resistance", name, score, value,
            "پیوت ۳۰روزه با فاصله ATR، واکنش کندل و شکست/برگشت سطح.")

    # G2: period-calibrated MAs, cloud, and regime-aware bands.
    for family, source in (("EMA", series.get("ema", {})), ("SMA", series.get("sma", {}))):
        for period in (5, 10, 20, 30, 50, 100, 200):
            ma_series = source.get(period) if isinstance(source, dict) else None
            score, value, signal = _ma_score(price, previous, open_t, atr or safe, ma_series, period)
            put("moving_averages", f"{family}({period})", score, value,
                "فاصله از میانگین، شیب، تقاطع و بیش‌امتداد با مقیاس ATR.", signal)
    cloud_score = _ichimoku_score(series, price, atr or safe)
    put("moving_averages", "Ichimoku Cloud(9,26,52,26)", cloud_score,
        {"span_a": _at(series.get("span_a_cloud")), "span_b": _at(series.get("span_b_cloud")),
         "tenkan": _at(series.get("tenkan")), "kijun": _at(series.get("kijun"))},
        "ابر فعلی، تنکن/کیجون، چیکو و ابر آینده.")
    adx_now = _at(series.get("adx14"))
    bwr = _bb_width_ratio(series)
    put("moving_averages", "BB(20)", _bb_score(series, price, open_t, atr or safe, adx_now, bwr),
        {"percent_b": ((price - _at(series.get("bb_lower"))) /
                       (_at(series.get("bb_upper")) - _at(series.get("bb_lower")) + EPS))
                       if _at(series.get("bb_upper")) is not None and _at(series.get("bb_lower")) is not None else None,
         "band_width_ratio": bwr}, "BWR برابر پهنای فعلی باند تقسیم بر میانگین ۲۰ پهنای قبلی است؛ امتیاز با رژیم شکست/بازگشت و شیب باند تغییر می‌کند.")
    put("moving_averages", "KELTNER(16)",
        _keltner_score(series, price, open_t, atr or safe, rv15),
        {"mid": _at(series.get("keltner_mid")), "RV15": rv15},
        "موقعیت کانال، شیب EMA و تأیید حجم نسبی.")

    # G3: volume and money-flow. Missing/stale candle volume stays unavailable.
    for period in (15, 30, 90):
        ratio = rv[period]
        score = (_relative_volume_score_n(ratio, period, price, previous, high_t, low_t)
                 if ratio is not None else None)
        put("volume", f"RV({period})", score, {"ratio": ratio} if ratio is not None else None,
            "حجم نسبی جهت‌دار با بازده و جایگاه بسته‌شدن کندل.")
    sm_score, sm_current, sm_lag3 = _smart_money_score(closes, highs, lows, volumes, volume_valid)
    put("volume", "SM(15)", sm_score,
        {"NSM(15)": sm_current, "NSM(15)_lag3": sm_lag3},
        "جریان پول هوشمند از دادهٔ OHLCV؛ CMF(15) و تغییر سه‌روزه.")
    vrsi, vrsi_lag2 = _at(series.get("volume_rsi14")), _at(series.get("volume_rsi14"), -3)
    put("volume", "VRSI(14)", _vrsi_score(vrsi, vrsi_lag2)
        if volume_history_complete and vrsi is not None and vrsi_lag2 is not None else None,
        {"value": vrsi, "lag2": vrsi_lag2}, "مقدار و تغییر دوسه‌روزه RSI حجم.")
    vmacd, vsignal = _at(series.get("vmacd_line")), _at(series.get("vmacd_signal"))
    avg_volume26 = sum(volumes[-26:]) / 26 if n >= 26 and all(volume_valid[-26:]) else None
    ema10 = _at((series.get("ema") or {}).get(10))
    if volume_history_complete and all(value is not None for value in (vmacd, vsignal, avg_volume26, ema10, atr)):
        vm = vmacd / (avg_volume26 + EPS)
        vh = (vmacd - vsignal) / (avg_volume26 + EPS)
        avol = _tanh(1.5 * vm + 3.0 * vh)
        dtrend = _tanh((price - ema10) / safe)
        if avol > 0:
            vm_score = _clip(48 + 45 * avol * dtrend, 5, 95)
        elif dtrend > 0:
            vm_score = _clip(48 - 15 * abs(avol) * dtrend, 33, 48)
        else:
            vm_score = _clip(45 + 10 * abs(avol) * abs(dtrend), 45, 55)
    else:
        vm_score = None
    put("volume", "VMACD(26)", vm_score,
        {"line": vmacd, "signal": vsignal, "average_volume_26": avg_volume26},
        "شتاب MACD حجم در تعامل با جهت قیمت نسبت به EMA10.")
    obv, obv_ma, obv_lag20 = (_at(series.get("obv20")), _at(series.get("obv_sma20")),
                              _at(series.get("obv20"), -21))
    avg_volume20 = sum(volumes[-20:]) / 20 if n >= 20 and all(volume_valid[-20:]) else None
    price_lag20 = _at(series.get("close"), -21)
    if volume_history_complete and all(value is not None for value in (obv, obv_ma, obv_lag20, avg_volume20, price_lag20, atr)):
        obv_score = _obv_score(obv, obv_ma, obv_lag20, avg_volume20,
                               price, price_lag20, safe)
    else:
        obv_score = None
    put("volume", "OBV(20)", obv_score,
        {"obv": obv, "sma20": obv_ma, "lag20": obv_lag20},
        "جایگاه و شیب ۲۰روزه OBV همراه با واگرایی قیمت.")

    # G4: momentum oscillators, using required lags rather than raw-value proxies.
    rsi, rsi_prev, rsi_lag3 = (_at(series.get("rsi14")), _at(series.get("rsi14"), -2),
                               _at(series.get("rsi14"), -4))
    ema50 = _at((series.get("ema") or {}).get(50))
    if all(value is not None for value in (rsi, rsi_prev, rsi_lag3, ema50, adx_now)):
        rsi_score = _rsi_score(rsi, rsi_prev, rsi_lag3, price, ema50, adx_now)
    else:
        rsi_score = None
    put("oscillators", "RSI(14)", rsi_score,
        {"value": rsi, "previous": rsi_prev, "lag3": rsi_lag3},
        "محدودهٔ RSI، تغییر سه‌روزه و رژیم روند.")
    srsi, srsi_prev = _at(series.get("stochrsi14")), _at(series.get("stochrsi14"), -2)
    put("oscillators", "StochRSI(14)", _stochrsi_score(srsi, srsi_prev)
        if srsi is not None and srsi_prev is not None else None,
        {"value": srsi, "previous": srsi_prev}, "چرخش و تغییر StochRSI در مقیاس ۰ تا ۱.")
    mfi, mfi_prev, mfi_lag5 = (_at(series.get("mfi14")), _at(series.get("mfi14"), -2),
                               _at(series.get("mfi14"), -6))
    close_lag5 = _at(series.get("close"), -6)
    put("oscillators", "MFI(14)", _mfi_score(mfi, mfi_prev, mfi_lag5, price, close_lag5)
        if volume_history_complete and all(value is not None for value in (mfi, mfi_prev, mfi_lag5, close_lag5)) else None,
        {"value": mfi, "previous": mfi_prev, "lag5": mfi_lag5},
        "جریان پول، مومنتوم و واگرایی پنج‌روزه.")
    cci, cci_prev = _at(series.get("cci14")), _at(series.get("cci14"), -2)
    put("oscillators", "CCI(14)", _cci_score(cci, cci_prev)
        if cci is not None and cci_prev is not None else None,
        {"value": cci, "previous": cci_prev}, "ناحیه‌های CCI همراه با تغییر روزانه.")
    wr, wr_prev = _at(series.get("wr14")), _at(series.get("wr14"), -2)
    put("oscillators", "WR(14)", _wr_score(wr, wr_prev)
        if wr is not None and wr_prev is not None else None,
        {"value": wr, "previous": wr_prev}, "Williams %R همراه با چرخش روزانه.")
    so_k, so_d = _at(series.get("so_k")), _at(series.get("so_d"))
    so_k_prev, so_d_prev = _at(series.get("so_k"), -2), _at(series.get("so_d"), -2)
    put("oscillators", "SO(14)", _so_score(so_k, so_d, so_k_prev, so_d_prev)
        if all(value is not None for value in (so_k, so_d, so_k_prev, so_d_prev)) else None,
        {"k": so_k, "d": so_d, "k_previous": so_k_prev, "d_previous": so_d_prev},
        "جایگاه %K، تغییر آن و تقاطع خطوط %K و %D.")
    adx_prev = _at(series.get("adx14"), -2)
    plus_di, minus_di = _at(series.get("plus_di14")), _at(series.get("minus_di14"))
    ema20 = _at((series.get("ema") or {}).get(20))
    put("oscillators", "ADX(14)", _adx_score(adx_now, adx_prev, plus_di,
        minus_di, price, ema20, atr or safe)
        if adx_now is not None and adx_prev is not None else None,
        {"adx": adx_now, "previous": adx_prev, "+DI": plus_di, "-DI": minus_di},
        "قدرت روند با جهت DI و تغییر ADX.")
    aroon_up, aroon_down = _at(series.get("aroon_up25")), _at(series.get("aroon_down25"))
    if aroon_up is not None and aroon_down is not None:
        oscillator = aroon_up - aroon_down
        activity = max(aroon_up, aroon_down)
        strength = _clip((activity - 30) / 50, .2, 1.0)
        aroon_score = _clip(48 + 50 * strength * _tanh(oscillator / 55))
    else:
        aroon_score = None
    put("oscillators", "AROON(25)", aroon_score,
        {"up": aroon_up, "down": aroon_down}, "نوسان‌ساز آرون با ضریب فعالیت سقف/کف.")
    ao, ao_prev, ao_lag2 = (_at(series.get("ao534")), _at(series.get("ao534"), -2),
                            _at(series.get("ao534"), -3))
    put("oscillators", "AO(5,34)", _ao_score(ao, ao_prev, ao_lag2, price, atr or safe)
        if all(value is not None for value in (ao, ao_prev, ao_lag2)) else None,
        {"value": ao, "previous": ao_prev, "lag2": ao_lag2},
        "مقدار نرمال‌شده با ATR، شتاب و الگوی عبور از صفر.")
    macd_line, macd_hist = _at(series.get("macd_line")), _at(series.get("macd_histogram"))
    macd_hist_prev = _at(series.get("macd_histogram"), -2)
    put("oscillators", "MACD(26)", _macd_score(macd_line, macd_hist, macd_hist_prev,
        price, atr or safe)
        if all(value is not None for value in (macd_line, macd_hist, macd_hist_prev)) else None,
        {"line": macd_line, "histogram": macd_hist, "histogram_previous": macd_hist_prev},
        "خط صفر، هیستوگرام، تغییر هیستوگرام و تقاطع.")
    mtm, mtm_prev = _at(series.get("mtm6")), _at(series.get("mtm6"), -2)
    put("oscillators", "MTM(6)", _mtm_score(mtm, mtm_prev, price, atr or safe)
        if mtm is not None and mtm_prev is not None else None,
        {"value": mtm, "previous": mtm_prev}, "مومنتوم شش‌روزه نرمال‌شده با ATR و تغییر آن.")
    trend_score = _trend_score(trend_value, trend_schema_type, price, atr or safe)
    put("oscillators", "Trend", trend_score,
        {"value": trend_value, "schema": trend_schema_type or "UNKNOWN"},
        "فقط Trend دارای schema شناخته‌شده امتیاز می‌گیرد.")
    return scores


def score_tse_bars(bars: list[dict[str, Any]] | None, *,
                   trend_value: float | None = None,
                   trend_schema_type: str | None = None) -> dict[str, Any]:
    """Score all chart-derived TSE indicators with the v1 hierarchical model."""
    normalized: list[dict[str, Any]] = []
    for row in bars or []:
        if not isinstance(row, dict):
            continue
        close = _num(row.get("close"))
        if close is None or close <= 0:
            continue
        normalized.append({
            **row, "close": close,
            "open": _num(row.get("open")) if _num(row.get("open")) is not None else close,
            "high": _num(row.get("high")) if _num(row.get("high")) is not None else close,
            "low": _num(row.get("low")) if _num(row.get("low")) is not None else close,
            "volume": _num(row.get("volume")),
        })
    if not normalized:
        return _empty_result()
    calculated = compute_indicators(normalized, include_series=True)
    series = calculated.get("indicator_series") or {}
    indicators = _indicator_scores(normalized, series, _num(trend_value), trend_schema_type)
    family_results: dict[str, dict[str, Any]] = {}
    group_coverage: dict[str, float] = {}
    for group, clusters in SUBCLUSTERS.items():
        cluster_scores: list[tuple[float, float]] = []
        coverage = 0.0
        group_rows: list[dict[str, Any]] = []
        missing: list[str] = []
        cluster_results: dict[str, dict[str, Any]] = {}
        for cluster_name, config in clusters.items():
            cluster_weight = float(config["weight"])
            cluster_indicators: dict[str, float] = config["indicators"]
            available = [(name, indicators.get(group, {}).get(name), weight)
                         for name, weight in cluster_indicators.items()]
            valid = [(name, item, weight) for name, item, weight in available
                     if item is not None and item.get("score") is not None]
            valid_weight = sum(weight for _, _, weight in valid)
            cluster_coverage = valid_weight / cluster_weight if cluster_weight else 0.0
            coverage += cluster_weight * cluster_coverage
            cluster_score = (sum(float(item["score"]) * weight for _, item, weight in valid) / valid_weight
                             if cluster_coverage >= .40 and valid_weight > 0 else None)
            if cluster_score is not None:
                cluster_scores.append((cluster_score, cluster_weight))
            cluster_results[cluster_name] = {
                "score": round(cluster_score, 2) if cluster_score is not None else None,
                "coverage_pct": round(cluster_coverage * 100, 1),
                "weight_pct": round(cluster_weight * 100, 1),
                "indicators": [name for name, _, _ in available],
            }
            for name, item, weight in available:
                if item is None:
                    item = {"key": name, "score": None, "value": None,
                            "note": "دادهٔ کافی در تاریخچهٔ کندل‌ها موجود نیست.",
                            "signal": "Insufficient Data"}
                else:
                    item = dict(item)
                item["weight_pct"] = round(weight * 100, 1)
                item["sub_cluster"] = cluster_name
                group_rows.append(item)
                if item.get("score") is None:
                    missing.append(name)
        group_score = (sum(score * weight for score, weight in cluster_scores)
                       / sum(weight for _, weight in cluster_scores)
                       if coverage >= .40 and cluster_scores else None)
        group_coverage[group] = coverage
        family_results[group] = {
            "score": round(group_score, 2) if group_score is not None else None,
            "coverage_pct": round(coverage * 100, 1),
            "signal": _sig(group_score), "indicators": group_rows,
            "missing_indicators": missing, "sub_clusters": cluster_results,
        }

    valid_groups = [group for group in GROUP_WEIGHTS
                    if family_results[group]["score"] is not None]
    available_weight = sum(GROUP_WEIGHTS[group] for group in valid_groups)
    if len(valid_groups) < 3 or available_weight <= 0:
        raw_score = final_score = dispersion = None
        effective = {}
        confidence = None
        eta = 0.0
        final_signal = "Insufficient Data"
    else:
        effective = {group: GROUP_WEIGHTS[group] / available_weight for group in valid_groups}
        raw_score = sum(effective[group] * family_results[group]["score"] for group in valid_groups)
        dispersion = math.sqrt(sum(effective[group] *
                                   (family_results[group]["score"] - raw_score) ** 2
                                   for group in valid_groups))
        volume_score = family_results["volume"]["score"]
        penalty = .15 if raw_score >= 60 and volume_score is not None and volume_score < 35 else 0.0
        eta = _clip(.015 * max(0.0, dispersion - 18) + penalty, 0.0, .35)
        final_score = _clip((1 - eta) * raw_score + eta * 45.0)
        if final_score < 30:
            final_signal = "Bearish"
        elif final_score >= 60:
            min_group = min(family_results[group]["score"] for group in valid_groups)
            final_signal = ("Bullish" if min_group >= 25 and eta < .15 else "Neutral")
        else:
            final_signal = "Neutral"
        f_cov = sum(effective[group] * group_coverage[group] for group in valid_groups)
        f_agree = 1.0 - _clip(dispersion / 35.0, 0.0, 1.0)
        f_margin = .40 + .60 * _tanh(min(abs(final_score - 30), abs(final_score - 60)) / 12)
        confidence = round(100 * f_cov * (.65 * f_agree + .35 * f_margin), 1)

    return {
        "technical_score": round(final_score, 2) if final_score is not None else None,
        "raw_score": round(raw_score, 2) if raw_score is not None else None,
        "signal": final_signal,
        "score_band": {"Bullish": "bullish", "Bearish": "bearish",
                       "Neutral": "neutral", "Insufficient Data": "unavailable"}[final_signal],
        "confidence": confidence,
        "inter_group_dispersion": round(dispersion, 2) if dispersion is not None else None,
        "damping_factor": round(eta, 4),
        "family_scores": family_results,
        "score_weights": {key: round(value * 100, 1) for key, value in GROUP_WEIGHTS.items()},
        "effective_score_weights": {key: round(value * 100, 1) for key, value in effective.items()},
        "indicator_weights": {
            group: {name: round(weight * 100, 1)
                    for cluster in clusters.values()
                    for name, weight in cluster["indicators"].items()}
            for group, clusters in SUBCLUSTERS.items()
        },
        "data_coverage_pct": round(sum(GROUP_WEIGHTS[group] * group_coverage[group]
                                        for group in GROUP_WEIGHTS) * 100, 1),
        "available_family_weight_pct": round(available_weight * 100, 1),
        "valid_groups": valid_groups,
        "observations": len(normalized),
        "score_method": "tse_technical_scoring_engine_v1_hierarchical_atr",
    }


def _empty_result() -> dict[str, Any]:
    groups = {group: {"score": None, "coverage_pct": 0.0,
                      "signal": "Insufficient Data", "indicators": [],
                      "missing_indicators": [name for cluster in clusters.values()
                                              for name in cluster["indicators"]],
                      "sub_clusters": {}}
              for group, clusters in SUBCLUSTERS.items()}
    return {"technical_score": None, "raw_score": None,
            "signal": "Insufficient Data", "score_band": "unavailable",
            "confidence": None, "inter_group_dispersion": None,
            "damping_factor": 0.0, "family_scores": groups,
            "score_weights": {key: value * 100 for key, value in GROUP_WEIGHTS.items()},
            "effective_score_weights": {},
            "indicator_weights": {
                group: {name: round(weight * 100, 1)
                        for cluster in clusters.values()
                        for name, weight in cluster["indicators"].items()}
                for group, clusters in SUBCLUSTERS.items()
            },
            "data_coverage_pct": 0.0, "available_family_weight_pct": 0.0,
            "valid_groups": [], "observations": 0,
            "score_method": "tse_technical_scoring_engine_v1_hierarchical_atr"}
