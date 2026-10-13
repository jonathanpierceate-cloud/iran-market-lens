"""Shared entry-oriented scoring rules for the AliVest technical models."""
from __future__ import annotations

import math


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return min(high, max(low, value))


def rsi_entry_score(value: float) -> float:
    """Score RSI for entry quality: balanced momentum is favored over extremes."""
    value = _clamp(value)
    if value <= 30:
        return 40.0 + value / 3.0
    if value <= 50:
        return 50.0 + (value - 30.0)
    if value <= 60:
        return 70.0 + (value - 50.0) * 2.0
    if value <= 70:
        return 90.0 - (value - 60.0) * 2.5
    if value <= 80:
        return 65.0 - (value - 70.0) * 3.0
    return max(15.0, 35.0 - (value - 80.0))


def adx_directional_score(adx: float | None, plus_di: float | None,
                          minus_di: float | None,
                          trend_score: float | None) -> float | None:
    """Use ADX as strength and DI/price trend as direction, never as direction alone."""
    if adx is None or not math.isfinite(adx):
        return None
    if plus_di is not None and minus_di is not None:
        direction = _clamp(2.0 * (plus_di - minus_di) / max(plus_di + minus_di, 1.0), -1.0, 1.0)
    elif trend_score is not None and math.isfinite(trend_score):
        direction = _clamp((trend_score - 50.0) / 25.0, -1.0, 1.0)
    else:
        return 50.0
    strength = _clamp((adx - 15.0) / 25.0, 0.0, 1.0)
    return _clamp(50.0 + direction * 45.0 * strength)


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
    if rsi >= 70:
        return {"status": "confirmation", "label": "صبر · RSI در خریدزدگی",
                "reason": f"RSI روی {rsi:.1f} و بالای ۷۰ است؛ با وجود روند قوی، برای خرید تازه یا افزایش حجم تا خنک‌شدن RSI و حفظ میانگین‌ها صبر کن."}
    if rsi >= 65:
        return {"status": "confirmation", "label": "صبر · RSI داغ",
                "reason": f"RSI روی {rsi:.1f} و نزدیک ناحیه خریدزدگی است؛ برای ورود بهتر تا اصلاح ملایم یا تثبیت بالای میانگین‌ها صبر کن."}
    if rsi <= 30:
        return {"status": "confirmation", "label": "صبر · فروش‌زدگی RSI",
                "reason": f"RSI روی {rsi:.1f} و زیر ۳۰ است؛ فروش‌زدگی به‌تنهایی برگشت را تأیید نمی‌کند، پس برای نشانه برگشت و حفظ میانگین‌ها صبر کن."}
    if rsi < 45:
        return {"status": "confirmation", "label": "صبر · مومنتوم ضعیف",
                "reason": f"RSI روی {rsi:.1f} است؛ تا برگشت مومنتوم و بهبود جایگاه قیمت نسبت به میانگین‌ها ورود را عقب بینداز."}
    if moving_average_score < 45 or overall_score < 45:
        return {"status": "unsuitable", "label": "فعلاً نامناسب",
                "reason": f"RSI متعادل است، اما امتیاز میانگین‌های متحرک {moving_average_score:.0f} و امتیاز کل {overall_score:.0f} از ۱۰۰ است؛ روند برای ورود پشتیبانی کافی نمی‌دهد."}
    if moving_average_score < 60 or overall_score < 60:
        return {"status": "confirmation", "label": "صبر · روند تأیید نشده",
                "reason": f"RSI روی {rsi:.1f} است، اما امتیاز میانگین‌های متحرک {moving_average_score:.0f} و امتیاز کل {overall_score:.0f} از حد ورود مدل پایین‌تر است؛ منتظر تقویت روند بمان."}
    if resistance_distance_pct is not None and resistance_distance_pct < 2.0:
        return {"status": "confirmation", "label": "صبر · مقاومت نزدیک",
                "reason": f"میانگین‌ها و RSI مناسب‌اند، اما مقاومت فقط {resistance_distance_pct:.1f}٪ بالاتر است؛ ورود را تا عبور و تثبیت یا اصلاح قیمت عقب بینداز."}
    return {"status": "suitable", "label": "مناسب · پله‌ای",
            "reason": f"RSI روی {rsi:.1f} در محدوده متعادل است، امتیاز میانگین‌های متحرک {moving_average_score:.0f} و امتیاز کل {overall_score:.0f} از ۱۰۰ است؛ اگر وارد می‌شوی پله‌ای عمل کن."}
