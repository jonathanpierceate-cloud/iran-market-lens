from __future__ import annotations

import math
import statistics
from typing import Any


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _ema(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    alpha = 2 / (period + 1)
    current = seed
    for i in range(period, len(values)):
        current = alpha * values[i] + (1 - alpha) * current
        out[i] = current
    return out


def _sma(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for i in range(period - 1, len(values)):
        out[i] = sum(values[i - period + 1:i + 1]) / period
    return out


def _rolling_std(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1:i + 1]
        out[i] = statistics.pstdev(window)
    return out


def _rsi(values: list[float], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return out
    deltas = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    out[period] = 100.0 if avg_loss == 0 and avg_gain > 0 else (50.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss))
    for i in range(period + 1, len(values)):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        out[i] = 100.0 if avg_loss == 0 and avg_gain > 0 else (50.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss))
    return out


def _atr(high: list[float], low: list[float], close: list[float], period: int) -> list[float | None]:
    tr: list[float] = []
    for i in range(len(close)):
        tr.append(max(high[i] - low[i], abs(high[i] - close[i - 1]) if i else 0,
                      abs(low[i] - close[i - 1]) if i else 0))
    out: list[float | None] = [None] * len(close)
    if len(tr) < period:
        return out
    current = sum(tr[:period]) / period
    out[period - 1] = current
    for i in range(period, len(tr)):
        current = (current * (period - 1) + tr[i]) / period
        out[i] = current
    return out


def _value(series: list[float | None], index: int = -1) -> float | None:
    if not series:
        return None
    try:
        value = series[index]
    except IndexError:
        return None
    return float(value) if value is not None and math.isfinite(value) else None


def _band_scenario(price: float, upper: float | None,
                   lower: float | None) -> tuple[str, str]:
    if upper is None or lower is None or upper <= lower:
        return "unavailable", "داده کافی برای تعیین جایگاه قیمت نسبت به باند نیست"
    if price > upper:
        return "sell", "قیمت بالاتر از سقف باند است؛ ناحیه فروش"
    if price < lower:
        return "buy", "قیمت پایین‌تر از کف باند است؛ ناحیه خرید"
    return "neutral", "قیمت داخل محدوده باند است؛ وضعیت خنثی و با نزدیک‌شدن به سقف، امتیاز کمتر می‌شود"


def _indicator(value: float | None, previous: float | None, *, signal="neutral", interpretation="داده کافی نیست",
               formula="", parameters: dict[str, Any] | None = None, extras: dict[str, Any] | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {"value": value, "previous_value": previous, "signal": signal,
                              "interpretation": interpretation, "formula": formula,
                              "parameters": parameters or {}}
    if extras:
        record.update(extras)
    return record


def pivot_points(high: float, low: float, close: float, open_: float) -> dict[str, dict[str, float | None]]:
    span = high - low
    classic = (high + low + close) / 3
    def standard(pp):
        return {"pivot": pp, "R1": 2 * pp - low, "R2": pp + span,
                "R3": high + 2 * (pp - low), "S1": 2 * pp - high,
                "S2": pp - span, "S3": low - 2 * (high - pp)}
    woodie = (high + low + 2 * close) / 4
    fib = {"pivot": classic, "R1": classic + 0.382 * span, "R2": classic + 0.618 * span,
           "R3": classic + span, "S1": classic - 0.382 * span, "S2": classic - 0.618 * span,
           "S3": classic - span}
    x = (high + 2 * low + close) if close < open_ else ((2 * high + low + close) if close > open_ else (high + low + 2 * close))
    demark = {"pivot": x / 4, "R1": x / 2 - low, "R2": None, "R3": None,
              "S1": x / 2 - high, "S2": None, "S3": None}
    camarilla = {"pivot": close, "H3": close + span * 1.1 / 4,
                 "L3": close - span * 1.1 / 4, "R1": close + span * 1.1 / 12,
                 "R2": close + span * 1.1 / 6, "R3": close + span * 1.1 / 4,
                 "S1": close - span * 1.1 / 12, "S2": close - span * 1.1 / 6,
                 "S3": close - span * 1.1 / 4}
    return {"Classic": standard(classic), "Woodie": standard(woodie),
            "Fibonacci": fib, "DeMark": demark, "Camarilla": camarilla}


def compute_indicators(bars: list[dict[str, Any]], *, include_series: bool = False) -> dict[str, Any]:
    bars = [b for b in bars if b.get("close") is not None]
    close = [float(b["close"]) for b in bars]
    high = [float(b.get("high") if b.get("high") is not None else b["close"]) for b in bars]
    low = [float(b.get("low") if b.get("low") is not None else b["close"]) for b in bars]
    open_ = [float(b.get("open") if b.get("open") is not None else b["close"]) for b in bars]
    volume = [float(b.get("volume") or 0) for b in bars]
    # A missing current volume (often encoded by chart vendors as zero) makes
    # current volume indicators stale/unavailable even if older bars had volume.
    has_volume = bool(volume) and volume[-1] > 0 and any(v > 0 for v in volume)
    n = len(close)
    current = close[-1] if n else None
    previous_close = close[-2] if n > 1 else None
    output: dict[str, Any] = {"latest": current, "previous_close": previous_close,
                              "observations": n, "indicators": {}, "pivots": {},
                              "data_status": "available" if n else "unavailable"}
    if n == 0:
        return output
    ind = output["indicators"]

    rsi = _rsi(close, 14)
    rsi_now, rsi_prev = _value(rsi), _value(rsi, -2)
    ind["RSI(14)"] = _indicator(rsi_now, rsi_prev,
        signal="buy" if rsi_now is not None and rsi_now < 30 else ("sell" if rsi_now is not None and rsi_now > 70 else "neutral"),
        interpretation=("ناحیه خرید؛ RSI زیر ۳۰" if rsi_now is not None and rsi_now < 30 else "ناحیه فروش؛ RSI بالای ۷۰" if rsi_now is not None and rsi_now > 70 else "محدوده خنثی ۳۰ تا ۷۰" if rsi_now is not None else "داده کافی نیست"),
        formula="100 - 100 / (1 + میانگین هموارشده رشد / میانگین هموارشده افت)", parameters={"period": 14, "smoothing": "Wilder"})

    typical = [(high[i] + low[i] + close[i]) / 3 for i in range(n)]
    money = [typical[i] * volume[i] for i in range(n)]
    mfi: list[float | None] = [None] * n
    for i in (range(14, n) if has_volume else []):
        pos = sum(money[j] for j in range(i - 13, i + 1) if typical[j] > typical[j - 1])
        neg = sum(money[j] for j in range(i - 13, i + 1) if typical[j] < typical[j - 1])
        mfi[i] = 100.0 if neg == 0 and pos > 0 else (50.0 if neg == 0 and pos == 0 else 100 - 100 / (1 + pos / neg))
    mfi_now = _value(mfi)
    ind["MFI(14)"] = _indicator(mfi_now, _value(mfi, -2),
        signal="oversold" if mfi_now is not None and mfi_now < 20 else "overbought" if mfi_now is not None and mfi_now > 80 else "neutral",
        interpretation="اشباع فروش" if mfi_now is not None and mfi_now < 20 else "اشباع خرید" if mfi_now is not None and mfi_now > 80 else "محدوده میانی" if mfi_now is not None else "داده کافی نیست",
        formula="100 - 100 / (1 + جریان پول مثبت ۱۴دوره / جریان پول منفی ۱۴دوره)", parameters={"period": 14, "source": "typical price × volume"})

    cci: list[float | None] = [None] * n
    for i in range(13, n):
        w = typical[i - 13:i + 1]; mean = sum(w) / 14
        dev = sum(abs(x - mean) for x in w) / 14
        cci[i] = (typical[i] - mean) / (0.015 * dev) if dev else 0.0
    cci_now = _value(cci)
    ind["CCI(14)"] = _indicator(cci_now, _value(cci, -2),
        signal="oversold" if cci_now is not None and cci_now < -100 else "overbought" if cci_now is not None and cci_now > 100 else "neutral",
        interpretation="ضعف/اشباع فروش" if cci_now is not None and cci_now < -100 else "قدرت/اشباع خرید" if cci_now is not None and cci_now > 100 else "محدوده میانی" if cci_now is not None else "داده کافی نیست",
        formula="(Typical Price - SMA14) / (0.015 × میانگین انحراف مطلق)", parameters={"period": 14, "constant": 0.015})

    wr: list[float | None] = [None] * n
    stoch: list[float | None] = [None] * n
    for i in range(13, n):
        hh, ll = max(high[i - 13:i + 1]), min(low[i - 13:i + 1])
        wr[i] = -100 * (hh - close[i]) / (hh - ll) if hh != ll else -50.0
        stoch[i] = 100 * (close[i] - ll) / (hh - ll) if hh != ll else 50.0
    wr_now = _value(wr)
    ind["WR(14)"] = _indicator(wr_now, _value(wr, -2),
        signal="oversold" if wr_now is not None and wr_now < -80 else "overbought" if wr_now is not None and wr_now > -20 else "neutral",
        interpretation="اشباع فروش" if wr_now is not None and wr_now < -80 else "اشباع خرید" if wr_now is not None and wr_now > -20 else "محدوده میانی" if wr_now is not None else "داده کافی نیست",
        formula="-100 × (Highest High14 - Close) / (Highest High14 - Lowest Low14)", parameters={"period": 14})
    stoch_d = _sma([x if x is not None else 50 for x in stoch], 3)
    stoch_now, stoch_d_now = _value(stoch), _value(stoch_d)
    ind["SO(14)"] = _indicator(stoch_now, _value(stoch, -2),
        signal="oversold" if stoch_now is not None and stoch_now < 20 else "overbought" if stoch_now is not None and stoch_now > 80 else "neutral",
        interpretation="%K و %D از محدوده ۱۴ دوره؛ %D میانگین ۳ دوره‌ای %K است",
        formula="%K=100×(Close-Lowest Low14)/(Highest High14-Lowest Low14); %D=SMA3(%K)", parameters={"period": 14, "signal_period": 3},
        extras={"%K": stoch_now, "%D": stoch_d_now})

    aroon_up: list[float | None] = [None] * n; aroon_down: list[float | None] = [None] * n
    for i in range(24, n):
        w_hi, w_lo = high[i - 24:i + 1], low[i - 24:i + 1]
        since_hi = 24 - max(j for j, v in enumerate(w_hi) if v == max(w_hi))
        since_lo = 24 - max(j for j, v in enumerate(w_lo) if v == min(w_lo))
        aroon_up[i], aroon_down[i] = (25 - since_hi) / 25 * 100, (25 - since_lo) / 25 * 100
    au, ad = _value(aroon_up), _value(aroon_down)
    ind["Aroon(25)"] = _indicator(au, _value(aroon_up, -2),
        signal="bullish" if au is not None and ad is not None and au > ad else "bearish" if au is not None and ad is not None else "neutral",
        interpretation=f"Aroon Up {au:.1f} / Down {ad:.1f}" if au is not None and ad is not None else "داده کافی نیست",
        formula="100 × (period - periods since extreme) / period", parameters={"period": 25}, extras={"up": au, "down": ad})

    plus_dm = [0.0] * n; minus_dm = [0.0] * n; tr = [0.0] * n
    for i in range(1, n):
        up = high[i] - high[i - 1]; down = low[i - 1] - low[i]
        plus_dm[i] = up if up > down and up > 0 else 0
        minus_dm[i] = down if down > up and down > 0 else 0
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
    adx: list[float | None] = [None] * n; dx: list[float | None] = [None] * n
    plus_di: list[float | None] = [None] * n; minus_di: list[float | None] = [None] * n
    if n > 27:
        smooth_tr = sum(tr[1:15]); smooth_plus = sum(plus_dm[1:15]); smooth_minus = sum(minus_dm[1:15])
        dx_values = []
        for i in range(14, n):
            if i > 14:
                smooth_tr = smooth_tr - smooth_tr / 14 + tr[i]
                smooth_plus = smooth_plus - smooth_plus / 14 + plus_dm[i]
                smooth_minus = smooth_minus - smooth_minus / 14 + minus_dm[i]
            pdi = 100 * smooth_plus / smooth_tr if smooth_tr else 0
            mdi = 100 * smooth_minus / smooth_tr if smooth_tr else 0
            plus_di[i], minus_di[i] = pdi, mdi
            dx[i] = 100 * abs(pdi - mdi) / (pdi + mdi) if pdi + mdi else 0
            dx_values.append((i, dx[i]))
        if len(dx_values) >= 14:
            seed_idx = dx_values[13][0]
            current_adx = sum(x[1] for x in dx_values[:14]) / 14
            adx[seed_idx] = current_adx
            for i in range(seed_idx + 1, n):
                current_adx = (current_adx * 13 + float(dx[i] or 0)) / 14
                adx[i] = current_adx
    adx_now = _value(adx)
    ind["ADX(14)"] = _indicator(adx_now, _value(adx, -2),
        signal="strong" if adx_now is not None and adx_now >= 25 else "weak" if adx_now is not None else "neutral",
        interpretation="روند قوی" if adx_now is not None and adx_now >= 25 else "روند ضعیف" if adx_now is not None else "داده کافی نیست",
        formula="Wilder smoothing of True Range, +DM/-DM, then DX", parameters={"period": 14},
        extras={"plus_di": _value(plus_di), "minus_di": _value(minus_di)})

    ema_by_period = {p: _ema(close, p) for p in [5, 10, 12, 16, 20, 26, 30, 50, 100, 200]}
    sma_by_period = {p: _sma(close, p) for p in [5, 10, 20, 30, 50, 100, 200]}
    for p in [5, 10, 20, 30, 50, 100, 200]:
        ev = _value(ema_by_period[p]); sv = _value(sma_by_period[p])
        ind[f"EMA({p})"] = _indicator(ev, _value(ema_by_period[p], -2), signal="bullish" if ev is not None and current > ev else "bearish" if ev is not None else "neutral",
            interpretation="قیمت بالای میانگین" if ev is not None and current > ev else "قیمت پایین میانگین" if ev is not None else "داده کافی نیست",
            formula="EMA_t = α×Price_t + (1-α)×EMA_(t-1)", parameters={"period": p, "alpha": 2 / (p + 1), "seed": "SMA"})
        ind[f"SMA({p})"] = _indicator(sv, _value(sma_by_period[p], -2), signal="bullish" if sv is not None and current > sv else "bearish" if sv is not None else "neutral",
            interpretation="قیمت بالای میانگین" if sv is not None and current > sv else "قیمت پایین میانگین" if sv is not None else "داده کافی نیست",
            formula="arithmetic mean of closing prices", parameters={"period": p})

    ema12, ema26 = ema_by_period[12], ema_by_period[26]
    macd_line: list[float | None] = [((ema12[i] - ema26[i]) if ema12[i] is not None and ema26[i] is not None else None) for i in range(n)]
    valid_macd = [x for x in macd_line if x is not None]
    macd_signal_valid = _ema([float(x) for x in valid_macd], 9)
    macd_signal: list[float | None] = [None] * n
    start_idx = n - len(macd_signal_valid)
    macd_signal[start_idx:] = macd_signal_valid
    macd_now, macd_sig = _value(macd_line), _value(macd_signal)
    hist = (macd_now - macd_sig) if macd_now is not None and macd_sig is not None else None
    ind["MACD(12,26,9)"] = _indicator(macd_now, _value(macd_line, -2),
        signal="bullish" if hist is not None and hist > 0 else "bearish" if hist is not None and hist < 0 else "neutral",
        interpretation="خط MACD بالای سیگنال" if hist is not None and hist > 0 else "خط MACD پایین سیگنال" if hist is not None else "داده کافی نیست",
        formula="EMA12 - EMA26; Signal = EMA9(MACD); Histogram = MACD - Signal",
        parameters={"fast": 12, "slow": 26, "signal": 9}, extras={"signal_line": macd_sig, "histogram": hist})

    ao: list[float | None] = [None] * n
    midpoint = [(high[i] + low[i]) / 2 for i in range(n)]
    sma5, sma34 = _sma(midpoint, 5), _sma(midpoint, 34)
    for i in range(n):
        if sma5[i] is not None and sma34[i] is not None:
            ao[i] = sma5[i] - sma34[i]
    ao_now = _value(ao)
    ind["AO(5,34)"] = _indicator(ao_now, _value(ao, -2), signal="bullish" if ao_now is not None and ao_now > 0 else "bearish" if ao_now is not None else "neutral",
        interpretation="شتاب مثبت" if ao_now is not None and ao_now > 0 else "شتاب منفی" if ao_now is not None else "داده کافی نیست",
        formula="SMA5(median price) - SMA34(median price)", parameters={"fast": 5, "slow": 34})

    stoch_rsi: list[float | None] = [None] * n
    for i in range(13, n):
        w = [v for v in rsi[i - 13:i + 1] if v is not None]
        if len(w) == 14:
            lo, hi = min(w), max(w)
            stoch_rsi[i] = (float(rsi[i]) - lo) / (hi - lo) if hi != lo else 0.5
    srsi_now = _value(stoch_rsi)
    ind["StochRSI(14)"] = _indicator(srsi_now, _value(stoch_rsi, -2),
        signal="buy" if srsi_now is not None and srsi_now <= 0.2 else "sell" if srsi_now is not None and srsi_now >= 0.8 else "neutral",
        interpretation="ناحیه خرید؛ StochRSI بین ۰ و ۰٫۲۰" if srsi_now is not None and srsi_now <= 0.2 else "ناحیه فروش؛ StochRSI بین ۰٫۸۰ و ۱" if srsi_now is not None and srsi_now >= 0.8 else "محدوده خنثی ۰٫۲۰ تا ۰٫۸۰" if srsi_now is not None else "داده کافی نیست",
        formula="(RSI14 - min(RSI14,14)) / (max(RSI14,14) - min(RSI14,14)); range 0–1", parameters={"rsi_period": 14, "stochastic_period": 14})

    momentum: list[float | None] = [None] * n
    for i in range(6, n): momentum[i] = close[i] - close[i - 6]
    momentum_now = _value(momentum)
    ind["MTM(6)"] = _indicator(momentum_now, _value(momentum, -2), signal="bullish" if momentum_now is not None and momentum_now > 0 else "bearish" if momentum_now is not None else "neutral",
        interpretation="شتاب مثبت" if momentum_now is not None and momentum_now > 0 else "شتاب منفی" if momentum_now is not None else "داده کافی نیست",
        formula="Close_t - Close_(t-6)", parameters={"period": 6})

    def midline(series_h, series_l, period):
        vals = [None] * n
        for k in range(period - 1, n): vals[k] = (max(series_h[k-period+1:k+1]) + min(series_l[k-period+1:k+1])) / 2
        return vals
    tenkan = midline(high, low, 9); kijun = midline(high, low, 26); span_b = midline(high, low, 52)
    span_a = [( (tenkan[i] + kijun[i]) / 2 if tenkan[i] is not None and kijun[i] is not None else None) for i in range(n)]
    ten, kij = _value(tenkan), _value(kijun)
    sa, sb = _value(span_a), _value(span_b)
    # The visible cloud at the latest candle consists of Senkou values calculated 26 periods earlier.
    sa_current = _value(span_a, -27) if n >= 27 else None
    sb_current = _value(span_b, -27) if n >= 27 else None
    cloud_low = min(sa_current, sb_current) if sa_current is not None and sb_current is not None else None
    cloud_high = max(sa_current, sb_current) if sa_current is not None and sb_current is not None else None
    cloud_state = ("above" if current > cloud_high else "below" if current < cloud_low else "inside") if cloud_high is not None and cloud_low is not None else None
    ichi_signal = "bullish" if cloud_state == "above" and ten is not None and kij is not None and ten > kij else "bearish" if cloud_state == "below" and ten is not None and kij is not None and ten < kij else "neutral"
    ind["Ichimoku(9,26,52,26)"] = _indicator(ten, _value(tenkan, -2), signal=ichi_signal,
        interpretation={"above": "قیمت بالای ابر", "inside": "قیمت داخل ابر", "below": "قیمت پایین ابر"}.get(cloud_state, "داده کافی نیست"),
        formula="Tenkan=(HH9+LL9)/2; Kijun=(HH26+LL26)/2; SpanA=(Tenkan+Kijun)/2; SpanB=(HH52+LL52)/2; Cloud offset 26",
        parameters={"tenkan": 9, "kijun": 26, "senkou_b": 52, "displacement": 26},
        extras={"tenkan": ten, "kijun": kij, "senkou_a_projected": sa, "senkou_b_projected": sb,
                "senkou_a_at_current": sa_current, "senkou_b_at_current": sb_current,
                "chikou": close[-1], "chikou_reference_close": close[-27] if n >= 27 else None,
                "price_vs_cloud": cloud_state})

    atr14 = _atr(high, low, close, 14); atr_now = _value(atr14)
    ind["ATR(14)"] = _indicator(atr_now, _value(atr14, -2), signal="neutral",
        interpretation="میانگین دامنه واقعی؛ معیار نوسان، نه جهت",
        formula="Wilder average of max(H-L, |H-prevC|, |L-prevC|)", parameters={"period": 14})
    adx16_atr = _atr(high, low, close, 16); ema16 = ema_by_period[16]
    k_mid, k_atr = _value(ema16), _value(adx16_atr)
    k_upper = k_mid + 2 * k_atr if k_mid is not None and k_atr is not None else None
    k_lower = k_mid - 2 * k_atr if k_mid is not None and k_atr is not None else None
    k_signal, k_interpretation = _band_scenario(current, k_upper, k_lower)
    ind["KELTNER(16)"] = _indicator(k_mid, _value(ema16, -2), signal=k_signal,
        interpretation=k_interpretation,
        formula="Middle=EMA16; Upper/Lower=Middle ± 2×ATR16", parameters={"period": 16, "atr_period": 16, "multiplier": 2},
        extras={"middle": k_mid, "upper": k_upper, "lower": k_lower,
                "distance": (k_upper - current) / current if k_upper is not None and current else None,
                "dl": (current - k_lower) / current if k_lower is not None and current else None,
                "width": k_upper - k_lower if k_upper is not None and k_lower is not None else None})

    bbmid = _sma(close, 20); bbstd = _rolling_std(close, 20)
    bmid, bstd = _value(bbmid), _value(bbstd)
    bup, blow = (bmid + 2*bstd, bmid - 2*bstd) if bmid is not None and bstd is not None else (None, None)
    pctb = (current - blow) / (bup - blow) if bup is not None and blow is not None and bup != blow else None
    bbwidth = ((bup - blow) / bmid) if bup is not None and blow is not None and bmid else None
    bb_signal, bb_interpretation = _band_scenario(current, bup, blow)
    ind["BB(20)"] = _indicator(bmid, _value(bbmid, -2), signal=bb_signal,
        interpretation=bb_interpretation,
        formula="Middle=SMA20; Upper/Lower=Middle ± 2×population SD20", parameters={"period": 20, "deviations": 2},
        extras={"upper": bup, "middle": bmid, "lower": blow,
                "distance": (bup - current) / current if bup is not None and current else None,
                "dl": (current - blow) / current if blow is not None and current else None,
                "band_width": bbwidth, "%B": pctb})

    volume_rsi = _rsi(volume, 14) if has_volume else [None] * n; vr_now = _value(volume_rsi)
    ind["VRSI(14)"] = _indicator(vr_now, _value(volume_rsi, -2), signal="neutral",
        interpretation="RSI روی حجم معاملات" if vr_now is not None else "داده کافی نیست",
        formula="RSI14(volume)", parameters={"period": 14})
    vfast, vslow = _ema(volume, 12), _ema(volume, 26)
    vmacd = [(vfast[i] - vslow[i] if vfast[i] is not None and vslow[i] is not None else None) for i in range(n)]
    if not has_volume: vmacd = [None] * n
    vm_now = _value(vmacd)
    valid_vmacd = [value for value in vmacd if value is not None]
    valid_vmacd_signal = _ema([float(value) for value in valid_vmacd], 9)
    vmacd_signal = [None] * (n - len(valid_vmacd_signal)) + valid_vmacd_signal
    vmacd_histogram = [line - signal if line is not None and signal is not None else None
                       for line, signal in zip(vmacd, vmacd_signal)]
    vmacd_histogram_now = _value(vmacd_histogram)
    recent_vmacd_histograms = [abs(value) for value in vmacd_histogram[-26:] if value is not None]
    vmacd_histogram_max = max(recent_vmacd_histograms) if recent_vmacd_histograms else None
    ind["VMACD(12,26)"] = _indicator(vm_now, _value(vmacd, -2), signal="bullish" if vm_now is not None and vm_now > 0 else "bearish" if vm_now is not None else "neutral",
        interpretation="شتاب حجم مثبت" if vm_now is not None and vm_now > 0 else "شتاب حجم منفی" if vm_now is not None else "داده کافی نیست",
        formula="EMA12(volume) - EMA26(volume); histogram = line - EMA9(line)",
        parameters={"fast": 12, "slow": 26, "signal": 9},
        extras={"signal_line": _value(vmacd_signal), "histogram": vmacd_histogram_now,
                "max_abs_histogram_26": vmacd_histogram_max})

    obv = [0.0] * n
    for i in range(1, n): obv[i] = obv[i-1] + (volume[i] if close[i] > close[i-1] else -volume[i] if close[i] < close[i-1] else 0)
    if not has_volume: obv = [None] * n
    obv_numeric = [float(x or 0) for x in obv]
    obv_ma = _sma(obv_numeric, 20); obv_now = _value(obv); obv_signal = _value(obv_ma) if has_volume else None
    ind["OBV(20)"] = _indicator(obv_now, _value(obv, -2), signal="bullish" if obv_now is not None and obv_signal is not None and obv_now > obv_signal else "bearish" if obv_now is not None and obv_signal is not None else "neutral",
        interpretation="OBV بالای میانگین ۲۰ دوره" if obv_now is not None and obv_signal is not None and obv_now > obv_signal else "OBV پایین میانگین ۲۰ دوره" if obv_now is not None and obv_signal is not None else "داده کافی نیست",
        formula="Cumulative volume signed by closing-price direction; compare with SMA20(OBV)", parameters={"average_period": 20}, extras={"obv_sma20": obv_signal})

    returns = [0.0] + [math.log(close[i] / close[i-1]) if close[i] > 0 and close[i-1] > 0 else 0 for i in range(1, n)]
    for p in [15, 30, 90]:
        rolling = _rolling_std(returns, p)
        rv = _value(rolling)
        if rv is not None: rv *= math.sqrt(252) * 100
        rv_previous = _value(rolling, -2)
        if rv_previous is not None: rv_previous *= math.sqrt(252) * 100
        ind[f"RV({p})"] = _indicator(rv, rv_previous, signal="neutral",
            interpretation="نوسان تاریخی سالانه‌شده بازده لگاریتمی (%)" if rv is not None else "داده کافی نیست",
            formula="population SD of log returns over window × √252 × 100", parameters={"period": p, "annualization": 252})
    # The requested ARRON spelling is preserved in its label; the standard indicator is Aroon.
    ind["ARRON(25)"] = ind["Aroon(25)"]
    if n >= 2:
        # Add explicit cross and volume summary flags to make explanations inspectable.
        e20, e50, e200 = (_value(ema_by_period[p]) for p in [20, 50, 200])
        volume_avg = _value(_sma(volume, 20))
        output["moving_average_analysis"] = {
            "price_above_ema20": current > e20 if e20 is not None else None,
            "price_above_ema50": current > e50 if e50 is not None else None,
            "price_above_ema200": current > e200 if e200 is not None else None,
            "ema20_50_cross": "golden_cross" if e20 is not None and e50 is not None and _value(ema_by_period[20], -2) is not None and _value(ema_by_period[50], -2) is not None and _value(ema_by_period[20], -2) <= _value(ema_by_period[50], -2) and e20 > e50 else "death_cross" if e20 is not None and e50 is not None and _value(ema_by_period[20], -2) is not None and _value(ema_by_period[50], -2) is not None and _value(ema_by_period[20], -2) >= _value(ema_by_period[50], -2) and e20 < e50 else "none",
            "ema50_200_cross": "golden_cross" if e50 is not None and e200 is not None and _value(ema_by_period[50], -2) is not None and _value(ema_by_period[200], -2) is not None and _value(ema_by_period[50], -2) <= _value(ema_by_period[200], -2) and e50 > e200 else "death_cross" if e50 is not None and e200 is not None and _value(ema_by_period[50], -2) is not None and _value(ema_by_period[200], -2) is not None and _value(ema_by_period[50], -2) >= _value(ema_by_period[200], -2) and e50 < e200 else "none",
        }
        output["volume_analysis"] = {
            "available": has_volume,
            "last_volume": volume[-1], "volume_sma20": volume_avg,
            "volume_spike": bool(has_volume and volume_avg and volume[-1] > 1.5 * volume_avg),
            "volume_trend": "up" if has_volume and volume[-1] > volume[-2] else "down" if has_volume and volume[-1] < volume[-2] else "flat" if has_volume else None,
        }
    output["pivots"] = pivot_points(high[-2], low[-2], close[-2], open_[-2]) if n >= 2 else {}
    # Keep a compact, aligned sample for the on-page price/indicator chart.
    chart_start = max(0, n - 90)
    def chart_values(series):
        return [float(value) if value is not None and math.isfinite(float(value)) else None
                for value in series[chart_start:]]
    chart_timestamps = []
    for bar in bars[chart_start:]:
        timestamp = bar.get("timestamp")
        chart_timestamps.append(timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp or ""))
    bb_upper = [mid + 2 * std if mid is not None and std is not None else None for mid, std in zip(bbmid, bbstd)]
    bb_lower = [mid - 2 * std if mid is not None and std is not None else None for mid, std in zip(bbmid, bbstd)]
    macd_histogram = [line - signal if line is not None and signal is not None else None
                      for line, signal in zip(macd_line, macd_signal)]
    if include_series:
        span_a_cloud = ([None] * 26 + span_a[:-26]) if n > 26 else [None] * n
        output["indicator_series"] = {
            "open": open_, "high": high, "low": low, "close": close, "volume": volume,
            "atr14": atr14, "atr16": adx16_atr,
            "rsi14": rsi, "mfi14": mfi, "cci14": cci, "wr14": wr,
            "so_k": stoch, "so_d": stoch_d,
            "aroon_up25": aroon_up, "aroon_down25": aroon_down,
            "adx14": adx, "plus_di14": plus_di, "minus_di14": minus_di,
            "ema": {period: values for period, values in ema_by_period.items()},
            "sma": {period: values for period, values in sma_by_period.items()},
            "macd_line": macd_line, "macd_signal": macd_signal,
            "macd_histogram": macd_histogram, "ao534": ao,
            "stochrsi14": stoch_rsi, "mtm6": momentum,
            "tenkan": tenkan, "kijun": kijun,
            "span_a_cloud": span_a_cloud, "span_b_cloud": ([None] * 26 + span_b[:-26]) if n > 26 else [None] * n,
            "span_a_future": span_a, "span_b_future": span_b,
            "keltner_mid": ema16, "bb_mid": bbmid,
            "bb_upper": bb_upper, "bb_lower": bb_lower,
            "volume_rsi14": volume_rsi, "vmacd_line": vmacd,
            "vmacd_signal": vmacd_signal, "obv20": obv, "obv_sma20": obv_ma,
        }
    output["chart_series"] = {
        "timestamps": chart_timestamps,
        "close": chart_values(close),
        "ema20": chart_values(ema_by_period[20]),
        "ema50": chart_values(ema_by_period[50]),
        "ema200": chart_values(ema_by_period[200]),
        "sma200": chart_values(sma_by_period[200]),
        "bb_upper": chart_values(bb_upper),
        "bb_lower": chart_values(bb_lower),
        "rsi": chart_values(rsi),
        "macd": chart_values(macd_line),
        "macd_signal": chart_values(macd_signal),
        "macd_histogram": chart_values(macd_histogram),
        "adx": chart_values(adx),
    }
    return output


def fund_chart_indicator_groups(bars: list[dict[str, Any]], *, source: str = "Rahavard365Chart") -> dict[str, Any]:
    """Calculate fund-scoring indicators from daily OHLCV chart candles."""
    computed = compute_indicators(bars)
    raw = computed.get("indicators") or {}

    def item(name: str, values: dict[str, Any], signal: str | None) -> dict[str, Any]:
        parts = []
        for key, value in values.items():
            try:
                number = float(value)
                if math.isfinite(number):
                    parts.append({"name": key, "value": number})
            except (TypeError, ValueError, OverflowError):
                continue
        return {"short_name_en": name, "name_en": name,
                "signal": signal if parts else "unavailable", "value": parts}

    def measured(name: str, display_name: str, extra: dict[str, str] | None = None) -> dict[str, Any]:
        record = raw.get(name) or {}
        values = {"value": record.get("value"), "previous_value": record.get("previous_value")}
        for source_name, output_name in (extra or {}).items():
            values[output_name] = record.get(source_name)
        return item(display_name, values, record.get("signal"))

    oscillators = [
        measured("RSI(14)", "RSI(14)", {"value": "rsi"}),
        measured("MACD(12,26,9)", "MACD(26)", {"value": "macd", "signal_line": "signal", "histogram": "histogram"}),
        measured("MFI(14)", "MFI(14)", {"value": "mfi"}),
        measured("ADX(14)", "ADX(14)", {"value": "adx", "plus_di": "plus_di", "minus_di": "minus_di"}),
        measured("StochRSI(14)", "StochRSI(14)", {"value": "stochrsi"}),
        measured("AO(5,34)", "AO(5,34)", {"value": "awesome"}),
        measured("ARRON(25)", "AROON(25)", {"value": "value", "up": "up", "down": "down"}),
        measured("CCI(14)", "CCI(14)", {"value": "cci"}),
        measured("SO(14)", "SO(14)", {"value": "value", "%K": "k", "%D": "d"}),
        measured("MTM(6)", "MTM(6)", {"value": "mtm"}),
        measured("WR(14)", "WR(14)", {"value": "wr"}),
    ]

    closes = [float(bar["close"]) for bar in bars if bar.get("close") is not None]
    trend_signal = "unavailable"
    trend_value = None
    if len(closes) > 30 and all(value > 0 for value in closes[-31:]):
        trend_value = (closes[-1] / closes[-31] - 1.0) * 100.0
        trend_score = min(100.0, max(0.0, 50.0 + 5.0 * trend_value))
        shown_trend_score = math.floor(trend_score + 0.5)
        trend_signal = "bullish" if shown_trend_score >= 70 else "bearish" if shown_trend_score <= 40 else "neutral"
    oscillators.insert(5, item("Trend", {"value": trend_value}, trend_signal))

    moving_averages = []
    for period in (5, 10, 20, 30, 50, 100, 200):
        moving_averages.append(measured(f"EMA({period})", f"EMA({period})"))
        moving_averages.append(measured(f"SMA({period})", f"SMA({period})"))
    cloud = raw.get("Ichimoku(9,26,52,26)") or {}
    moving_averages.append(item("Ichimoku Cloud", {
        "tenkan_sen_formula": cloud.get("tenkan"),
        "kijun_sen_formula": cloud.get("kijun"),
        "senkou_span_a_formula": cloud.get("senkou_a_at_current"),
        "senkou_span_b_formula": cloud.get("senkou_b_at_current"),
    }, cloud.get("signal")))

    def band(name: str) -> dict[str, Any]:
        record = raw.get(name) or {}
        values = {key: record.get(key) for key in ("upper", "middle", "lower", "distance", "dl")}
        return item(name, values, record.get("signal"))

    bands = [band("BB(20)"), band("KELTNER(16)")]

    pivot_bars = [bar for bar in bars if bar.get("close") is not None]
    pivot_window = pivot_bars[-31:-1]
    pivot_levels = {}
    if len(pivot_window) >= 30:
        pivot_high = max(float(bar.get("high") or bar["close"]) for bar in pivot_window)
        pivot_low = min(float(bar.get("low") or bar["close"]) for bar in pivot_window)
        pivot_close = float(pivot_window[-1]["close"])
        pivot_open = float(pivot_window[-1].get("open") or pivot_window[-1]["close"])
        pivot_levels = pivot_points(pivot_high, pivot_low, pivot_close, pivot_open)
    pivots = []
    for method in ("Fibonacci", "Classic", "Camarilla", "Woodie", "DeMark"):
        levels = pivot_levels.get(method) or {}
        pivots.append(item(f"PivotPoint{method}(30)", levels,
                           "neutral" if levels else "unavailable"))

    volumes = []
    obv = raw.get("OBV(20)") or {}
    volumes.append(item("OBV(20)", {
        "obv": obv.get("value"), "obv_sma20": obv.get("obv_sma20"),
        "previous_value": obv.get("previous_value"),
    }, obv.get("signal")))

    usable_bars = [bar for bar in bars if bar.get("close") is not None]
    volume_values = [float(bar.get("volume") or 0) for bar in usable_bars]
    volume_available = bool(computed.get("volume_analysis", {}).get("available"))
    for period in (15, 30, 90):
        if not volume_available or len(volume_values) <= period:
            volumes.append(item(f"RV({period})", {}, "unavailable"))
            continue
        current_volume = volume_values[-1] if volume_values else 0
        baseline = volume_values[-period-1:-1]
        average = sum(baseline) / len(baseline) if baseline else 0
        ratio = current_volume / average if average > 0 else None
        signal = "highvolume" if ratio is not None and ratio >= 1.2 else \
                 "lowvolume" if ratio is not None and ratio <= 0.8 else "neutral"
        volumes.append(item(f"RV({period})", {"relative_volume": ratio, "ratio": ratio,
                                               "value": ratio}, signal))

    volumes.append(measured("VRSI(14)", "VRSI(14)", {"value": "vrsi", "rsi": "rsi"}))
    volume_macd = raw.get("VMACD(12,26)") or {}
    volumes.append(item("VMACD(26)", {"vmacd": volume_macd.get("value"),
                                        "macd": volume_macd.get("value"),
                                        "value": volume_macd.get("value"),
                                        "histogram": volume_macd.get("histogram"),
                                        "max_abs_histogram_26": volume_macd.get("max_abs_histogram_26")},
                       volume_macd.get("signal")))
    return {"data": {"oscillators": oscillators,
                     "moving_averages": moving_averages,
                     "pivots": pivots, "bands": bands, "volumes": volumes},
            "source": source, "observations": computed.get("observations"),
            "data_status": computed.get("data_status"),
            "volume_data_available": bool(computed.get("volume_analysis", {}).get("available"))}
