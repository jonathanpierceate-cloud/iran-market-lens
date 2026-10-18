"""Shared entry-oriented scoring rules for the AliVest technical models."""
from __future__ import annotations

import math


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return min(high, max(low, value))


def inverted_linear_score(value: float, buy_at: float, sell_at: float) -> float:
    """Map a low oscillator reading to 100 and a high reading to 0, linearly."""
    if sell_at == buy_at:
        return 50.0
    return _clamp((sell_at - value) / (sell_at - buy_at) * 100.0)


def percent_change_score(change_pct: float, points_per_pct: float) -> float:
    return _clamp(50.0 + points_per_pct * change_pct)


def rsi_entry_score(value: float) -> float:
    """Spreadsheet rule: score = clamp((70 - RSI) * 2.5)."""
    return _clamp((70.0 - value) * 2.5)


def normalize_stoch_rsi(value: float | None) -> float | None:
    """Accept normalized 0–1 values and legacy 0–100 values, returning 0–1."""
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(value):
        return None
    if 1.0 < value <= 100.0:
        value /= 100.0
    if not 0.0 <= value <= 1.0:
        return None
    return value


def stoch_rsi_entry_score(value: float | None) -> float | None:
    """Spreadsheet rule: score = clamp((0.8 - StochRSI) / 0.6 * 100)."""
    value = normalize_stoch_rsi(value)
    if value is None:
        return None
    return inverted_linear_score(value, 0.2, 0.8)


def band_position_score(price: float | None, lower: float | None,
                        upper: float | None) -> float | None:
    """Update 4.2 band score: favor the lower edge and penalize the upper edge.

    Within the channel, the central area falls linearly from 70 near the lower
    edge to 40 near the upper edge. A 2%-of-price edge zone is capped at 30%
    of channel width so the buy and sell zones cannot overlap.
    """
    values = (price, lower, upper)
    if any(value is None or not math.isfinite(value) for value in values):
        return None
    if price <= 0 or upper <= lower:
        return None
    width = upper - lower
    near = min(0.02 * price, 0.30 * width)
    if near <= 0:
        return None
    if price <= lower:
        return 100.0
    lower_distance = price - lower
    if lower_distance < near:
        return 100.0 - 30.0 * lower_distance / near
    upper_distance = upper - price
    if upper_distance <= 0:
        return 0.0
    if upper_distance < near:
        return 40.0 * upper_distance / near
    middle_width = width - 2.0 * near
    if middle_width <= 0:
        return 55.0
    return 70.0 - 30.0 * (lower_distance - near) / middle_width


def moving_average_score(price: float | None, average: float | None,
                         period: int) -> float | None:
    """Linear price-vs-average score with the period bands from the workbook."""
    if (price is None or average is None or not math.isfinite(price)
            or not math.isfinite(average) or price <= 0 or average <= 0):
        return None
    limit_pct = 3.0 if period <= 20 else 5.0 if period <= 50 else 10.0
    distance_pct = (price / average - 1.0) * 100.0
    return _clamp(50.0 + 50.0 * distance_pct / limit_pct)


def ichimoku_cloud_score(price: float | None, span_a: float | None,
                         span_b: float | None) -> float | None:
    """Score position above, inside, or below the cloud using the workbook formula."""
    values = (price, span_a, span_b)
    if any(value is None or not math.isfinite(value) for value in values):
        return None
    if price <= 0 or span_a <= 0 or span_b <= 0:
        return None
    cloud_bottom, cloud_top = min(span_a, span_b), max(span_a, span_b)
    if price > cloud_top:
        distance_pct = (price / cloud_top - 1.0) * 100.0
        return _clamp(70.0 + 6.0 * distance_pct)
    if price < cloud_bottom:
        distance_pct = (cloud_bottom - price) / cloud_bottom * 100.0
        return _clamp(30.0 - 6.0 * distance_pct)
    if cloud_top == cloud_bottom:
        return 50.0
    return _clamp(30.0 + 40.0 * (price - cloud_bottom) / (cloud_top - cloud_bottom))


def macd_histogram_score(histogram: float | None, price: float | None) -> float | None:
    """Score price MACD histogram in percent of price as specified by the workbook."""
    if histogram is None or price is None or not math.isfinite(histogram) or price <= 0:
        return None
    histogram_pct = histogram / price * 100.0
    return percent_change_score(histogram_pct, 100.0)


def pivot_level_score(price: float | None, pivot: float | None,
                      resistance: float | None, support: float | None) -> float | None:
    """Linear pivot score from PP to R1/S1 (or H3/L3 for Camarilla)."""
    values = (price, pivot, resistance, support)
    if any(value is None or not math.isfinite(value) for value in values):
        return None
    if price <= 0 or pivot <= 0:
        return None
    if price >= pivot:
        if resistance <= pivot:
            return None
        return _clamp(50.0 + 50.0 * (price - pivot) / (resistance - pivot))
    if pivot <= support:
        return None
    return _clamp(50.0 - 50.0 * (pivot - price) / (pivot - support))


def obv_average_score(obv: float | None, average: float | None) -> float | None:
    if obv is None or average is None or not math.isfinite(obv) or not math.isfinite(average) or average == 0:
        return None
    deviation_pct = (obv - average) / abs(average) * 100.0
    return _clamp(50.0 + 10.0 * deviation_pct)


def relative_volume_score(ratio: float | None, price_change_pct: float | None) -> float | None:
    """Score relative volume only above its baseline, in the direction of price."""
    if (ratio is None or price_change_pct is None
            or not math.isfinite(ratio) or not math.isfinite(price_change_pct)):
        return None
    if ratio <= 1.0:
        return 50.0
    direction = 1.0 if price_change_pct > 0 else -1.0 if price_change_pct < 0 else 0.0
    return _clamp(50.0 + direction * 50.0 * (ratio - 1.0))


def volume_macd_histogram_score(histogram: float | None,
                                max_abs_histogram: float | None) -> float | None:
    if (histogram is None or max_abs_histogram is None
            or not math.isfinite(histogram) or not math.isfinite(max_abs_histogram)
            or max_abs_histogram <= 0):
        return None
    return _clamp(50.0 + 50.0 * histogram / max_abs_histogram)


def adx_directional_score(adx: float | None, plus_di: float | None,
                          minus_di: float | None) -> float | None:
    """Workbook rule: neutral at ADX <= 20; then 50 + 1.25*(+DI - -DI)."""
    if (adx is None or plus_di is None or minus_di is None
            or not all(math.isfinite(value) for value in (adx, plus_di, minus_di))):
        return None
    if adx <= 20.0:
        return 50.0
    return _clamp(50.0 + 1.25 * (plus_di - minus_di))


def entry_recommendation(rsi: float | None, moving_average_score: float | None,
                         overall_score: float | None, *,
                         above_exit_average: bool | None = None,
                         resistance_distance_pct: float | None = None) -> dict[str, str]:
    """Apply the same RSI/MA gates to immediate buys and adding to a position."""
    if rsi is None or moving_average_score is None or overall_score is None:
        return {"status": "unavailable", "label": "داده کافی نیست",
                "reason": "برای تصمیم ورود، RSI، میانگین‌های متحرک و امتیاز کل باید موجود باشند."}
    if above_exit_average is False:
        return {"status": "confirmation", "label": "صبر · زیر میانگین خروج",
                "reason": "قیمت زیر میانگین خروج افق انتخاب‌شده است؛ تا تثبیت کندل روزانه بالای آن خرید یا حجم اضافه نکن."}
    if rsi > 70:
        return {"status": "confirmation", "label": "صبر · RSI در ناحیه فروش",
                "reason": f"RSI روی {rsi:.1f} و بالای ۷۰، در ناحیه فروش است؛ برای خرید تازه یا افزایش حجم تا خنک‌شدن RSI و حفظ میانگین‌ها صبر کن."}
    if rsi < 30:
        return {"status": "confirmation", "label": "صبر · RSI در ناحیه خرید",
                "reason": f"RSI روی {rsi:.1f} و زیر ۳۰، در ناحیه خرید است؛ فروش‌زدگی به‌تنهایی برگشت را تأیید نمی‌کند، پس برای نشانه برگشت و حفظ میانگین‌ها صبر کن."}
    if rsi < 45:
        return {"status": "confirmation", "label": "صبر · مومنتوم ضعیف",
                "reason": f"RSI روی {rsi:.1f} است؛ تا برگشت مومنتوم و بهبود جایگاه قیمت نسبت به میانگین‌ها ورود را عقب بینداز."}
    if moving_average_score < 45 or overall_score < 45:
        return {"status": "unsuitable", "label": "فعلاً نامناسب",
                "reason": f"RSI متعادل است، اما امتیاز میانگین‌های متحرک {moving_average_score:.0f} و امتیاز کل {overall_score:.0f} از ۱۰۰ است؛ روند برای ورود پشتیبانی کافی نمی‌دهد."}
    if moving_average_score < 60:
        return {"status": "confirmation", "label": "صبر · روند تأیید نشده",
                "reason": f"امتیاز میانگین‌های متحرک {moving_average_score:.0f} از حداقل ۶۰ پایین‌تر است؛ تا تأیید روند صبر کن."}
    if overall_score < 70:
        return {"status": "confirmation", "label": "صبر · امتیاز زیر ۷۰",
                "reason": f"امتیاز کل {overall_score:.1f} از ۷۰ِ لازم برای وضعیت مناسب خرید پایین‌تر است؛ فعلاً حجم اضافه نکن."}
    if resistance_distance_pct is not None and resistance_distance_pct < 2.0:
        return {"status": "confirmation", "label": "صبر · مقاومت نزدیک",
                "reason": f"میانگین‌ها و RSI مناسب‌اند، اما مقاومت فقط {resistance_distance_pct:.1f}٪ بالاتر است؛ ورود را تا عبور و تثبیت یا اصلاح قیمت عقب بینداز."}
    return {"status": "suitable", "label": "مناسب · پله‌ای",
            "reason": f"RSI روی {rsi:.1f} در محدوده متعادل است، امتیاز میانگین‌های متحرک {moving_average_score:.0f} و امتیاز کل {overall_score:.0f} از ۱۰۰ است؛ اگر وارد می‌شوی پله‌ای عمل کن."}
