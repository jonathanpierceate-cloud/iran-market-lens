from __future__ import annotations

from datetime import datetime, timezone
import math
import re
from typing import Any

from .fund_scoring import score_fund_model
from .dashboard_scoring import DASHBOARD_SCORE_WEIGHTS, analyze_dashboard_asset


MEDIUM_TERM_SCORE_WEIGHTS = DASHBOARD_SCORE_WEIGHTS


def analyze(symbol: str, bars: list[dict[str, Any]],
            weights: dict[str, float] | None = None) -> dict[str, Any]:
    # The dashboard assets use the dedicated three-group medium-term model.
    # `weights` remains in the signature for callers on older app versions;
    # the canonical model weights are intentionally fixed in dashboard_scoring.
    return analyze_dashboard_asset(symbol, bars)


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

    rsi = find_values("RSI").get("rsi")
    family_scores = fund_model.get("family_scores") if isinstance(fund_model.get("family_scores"), dict) else {}
    moving_average_score = (family_scores.get("moving_averages") or {}).get("score")
    oscillator_score = (family_scores.get("oscillators") or {}).get("score")
    volume_score = (family_scores.get("volume") or {}).get("score")
    resistance_score = (family_scores.get("support_resistance") or {}).get("score")
    front_resistances = [value for value in resistances if price is not None and value > price]
    near_resistances = [value for value in front_resistances if (value - price) / price <= 0.10] if price else []
    nearest_front_resistance = min(front_resistances) if front_resistances else None
    nearest_resistance_distance = ((nearest_front_resistance - price) / price * 100
                                   if nearest_front_resistance is not None and price else None)
    resistance_pressure = min(22.0, len(near_resistances) * 7.0
                              + (8.0 if nearest_resistance_distance is not None and nearest_resistance_distance <= 3 else 0.0))
    overbought_count = sum(
        1 for item in groups["oscillators"]
        if str(item.get("signal") or "").strip().casefold().replace("_", "") == "overbought"
    )
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
        "effective_score_weights": fund_model["effective_score_weights"],
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
        "confidence_basis": "امتیاز تکنیکال چهارگروهی توسط AliVest و بر پایه داده‌های ره‌آورد محاسبه می‌شود؛ امتیاز رسمی ره‌آورد یا احتمال سود نیست.",
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
