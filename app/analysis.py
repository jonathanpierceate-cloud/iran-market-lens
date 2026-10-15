from __future__ import annotations

from datetime import datetime, timezone
import math
import re
from typing import Any

from .fund_scoring import score_fund_model
from .dashboard_scoring import DASHBOARD_SCORE_WEIGHTS, analyze_dashboard_asset
from .scoring_profiles import normalize_horizon
from .scoring_rules import entry_recommendation, normalize_stoch_rsi


LONG_TERM_SCORE_WEIGHTS = DASHBOARD_SCORE_WEIGHTS
MEDIUM_TERM_SCORE_WEIGHTS = LONG_TERM_SCORE_WEIGHTS


def analyze(symbol: str, bars: list[dict[str, Any]],
            weights: dict[str, float] | None = None,
            horizon: str = "long") -> dict[str, Any]:
    # `weights` remains in the signature for callers on older app versions.
    return analyze_dashboard_asset(symbol, bars, normalize_horizon(horizon))


def analyze_rahavard(symbol: str, payload: dict[str, Any],
                     data_timestamp: str | None = None,
                     current_price: float | None = None,
                     model_context: dict[str, Any] | None = None,
                     horizon: str = "long",
                     indicator_source: str = "Rahavard365",
                     dashboard_model: bool = False) -> dict[str, Any]:
    """Analyze an indicator payload with the shared fund scoring and presentation model."""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    source_name = str(indicator_source or payload.get("source") or "Rahavard365")
    is_tsetmc = source_name.casefold() == "tsetmc"
    groups = {key: data.get(key) if isinstance(data.get(key), list) else []
              for key in ("oscillators", "moving_averages", "pivots", "bands")}
    for item in groups["oscillators"]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("short_name_en") or item.get("name_en") or "").casefold()
        if not (name.startswith("stochrsi") or name == "rsi(14)"):
            continue
        scalar = None
        for part in item.get("value") or []:
            if not isinstance(part, dict):
                continue
            field = str(part.get("name") or "").casefold()
            if name.startswith("stochrsi") and field in {"value", "stochrsi"}:
                normalized = normalize_stoch_rsi(part.get("value"))
                if normalized is not None:
                    part["value"] = normalized
                    scalar = normalized
            elif name == "rsi(14)" and field in {"value", "rsi"}:
                try:
                    scalar = float(part.get("value"))
                except (TypeError, ValueError):
                    continue
        if scalar is not None:
            if name.startswith("stochrsi"):
                item["signal"] = "buy" if scalar <= 0.2 else "sell" if scalar >= 0.8 else "neutral"
            else:
                item["signal"] = "buy" if scalar < 30 else "sell" if scalar > 70 else "neutral"
    fund_model = score_fund_model(groups, current_price, model_context, horizon=horizon,
                                  dashboard_model=dashboard_model)
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
    model_signal = fund_model.get("signal")
    signal = {"Bullish": "buy", "Bearish": "sell", "Neutral": "hold"}.get(
        model_signal, "hold")
    net_signal = 1 if signal == "buy" else -1 if signal == "sell" else 0

    meaning_by_prefix = (
        ("RSI", "زیر ۳۰ ناحیه خرید، ۳۰ تا ۷۰ خنثی و بالای ۷۰ ناحیه فروش است؛ در بازه خنثی امتیاز نزدیک ۷۰ کمتر می‌شود."),
        ("MFI", "جریان پول را با درنظرگرفتن حجم معاملات می‌سنجد."),
        ("CCI", "فاصله قیمت از میانگین اخیر را نشان می‌دهد؛ افراط آن می‌تواند هشدار باشد."),
        ("WR", "جایگاه قیمت را در دامنه اخیر نشان می‌دهد؛ مقادیر افراطی را با روند بسنج."),
        ("SO", "شتاب کوتاه‌مدت را با خطوط K و D مقایسه می‌کند."),
        ("ARRON", "تازگی سقف و کف اخیر و استمرار روند را می‌سنجد."),
        ("ADX", "قدرت روند را می‌سنجد؛ جهت حرکت را به‌تنهایی مشخص نمی‌کند."),
        ("AO", "شتاب بازار را از اختلاف میانگین‌های کوتاه و بلند می‌سنجد."),
        ("StochRSI", "مقیاس ۰ تا ۱؛ ۰ تا ۰٫۲۰ ناحیه خرید، ۰٫۲۰ تا ۰٫۸۰ خنثی و ۰٫۸۰ تا ۱ ناحیه فروش است."),
        ("MACD", "خط MACD را با خط سیگنال مقایسه می‌کند تا تغییر شتاب را نشان دهد."),
        ("MTM", "تغییر مومنتوم قیمت در دوره تعیین‌شده را نشان می‌دهد."),
        ("Trend", "برچسب روند منتشرشده در ره‌آورد است."),
        ("Ichimoku", "تنکن، کیجون و ابر را برای روند و سطوح پویا کنار هم می‌گذارد."),
        ("KELTNER", "محدوده نوسان اطراف میانگین را نشان می‌دهد؛ نزدیکی به باند افراط قیمت را بررسی کن."),
        ("BB", "دامنه نوسان و جایگاه قیمت نسبت به باند بولینگر را نشان می‌دهد."),
        ("EMA", "میانگین نمایی قیمت است؛ فاصله مثبت/منفی نسبت قیمت به میانگین را نشان می‌دهد."),
        ("SMA", "میانگین ساده قیمت است؛ فاصله مثبت/منفی نسبت قیمت به میانگین را نشان می‌دهد."),
        ("RV", "حجم فعلی را با حجم مرجع مقایسه می‌کند؛ بالای ۱ یعنی بالاتر از مرجع."),
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
            if is_tsetmc and normalized.startswith("trend"):
                meaning = "تغییر درصدی قیمت در ۳۰ دورهٔ اخیر؛ هر ۱٪ تغییر ۵ امتیاز جابه‌جا می‌کند."
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

    # Summary cards and detailed analysis share the selected model's verdict.
    # An individual Trend indicator (or its absence) must not override it.
    trend = fund_model.get("score_band") or "unavailable"
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
    if is_tsetmc and fund_model.get("technical_score") is not None:
        bullish_probability = round(max(5.0, min(95.0,
            50.0 + (float(fund_model["technical_score"]) - 50.0) * 0.5)))
        bearish_probability = 100 - bullish_probability
    elif total_count:
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
                normalized = {str(key).strip().casefold(): value for key, value in values.items()}
                return normalized
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

    rsi_values = find_values("RSI")
    rsi = rsi_values.get("rsi", rsi_values.get("value"))
    family_scores = fund_model.get("family_scores") if isinstance(fund_model.get("family_scores"), dict) else {}
    moving_average_score = (family_scores.get("moving_averages") or {}).get("score")
    oscillator_score = (family_scores.get("oscillators") or {}).get("score")
    trend_momentum_score = (family_scores.get("trend_momentum") or {}).get("score")
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
    ema10 = find_values("EMA(10)").get("value")
    sma30 = find_values("SMA(30)").get("value")
    short_term_exit_price = round(ema10) if ema10 is not None else None
    medium_term_exit_price = round(sma30) if sma30 is not None else None
    resistance_above_price = price is None or any(value > price for value in resistances)
    mfi_values = find_values("MFI")
    mfi = mfi_values.get("mfi", mfi_values.get("value"))
    cci_values = find_values("CCI")
    cci = cci_values.get("cci", cci_values.get("value"))
    wr_values = find_values("WR")
    wr = wr_values.get("wr", wr_values.get("value"))
    so = find_values("SO")
    aroon = find_values("ARRON") or find_values("Aroon")
    adx_values = find_values("ADX")
    adx = adx_values.get("adx", adx_values.get("value"))
    trend_strength = ("unavailable" if adx is None else "strong" if adx >= 25
                      else "medium" if adx >= 20 else "weak")
    oscillator_indicators = (family_scores.get("oscillators") or {}).get("indicators", [])
    rsi_score = next((item.get("score") for item in oscillator_indicators
                      if isinstance(item, dict) and item.get("key") == "RSI(14)"), None)
    entry_score = (round(float(moving_average_score) * 0.60 + float(rsi_score) * 0.40, 1)
                   if moving_average_score is not None and rsi_score is not None else None)
    active_exit_price = (short_term_exit_price
                         if fund_model.get("investment_horizon") == "short"
                         else medium_term_exit_price)
    entry_assessment = entry_recommendation(
        rsi, moving_average_score, fund_model.get("technical_score"),
        above_exit_average=(price > active_exit_price)
        if price is not None and active_exit_price is not None else None,
        resistance_distance_pct=nearest_resistance_distance)
    entry_quality = {
        **entry_assessment,
        "score": entry_score,
        "score_method": "۶۰٪ میانگین‌های متحرک + ۴۰٪ امتیاز RSI",
        "rsi": rsi,
        "rsi_score": rsi_score,
        "moving_average_score": moving_average_score,
    }
    risk_rank = fund_model.get("risk_rank") or {}
    ao = find_values("AO").get("awesome")
    stoch_values = find_values("StochRSI")
    stoch_rsi = normalize_stoch_rsi(stoch_values.get("stochrsi", stoch_values.get("value")))
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
    if adx is not None and trend in {"bullish", "bearish"}:
        (bullish_reasons if trend == "bullish" else bearish_reasons).append(f"ADX روی {fmt(adx)} است و قدرت روند را بالای آستانه ۲۵ نشان می‌دهد") if adx >= 25 else None
    if trend == "bullish":
        bullish_reasons.append(f"برآیند مدل {fund_model['investment_horizon_label']} صعودی است")
    elif trend == "bearish":
        bearish_reasons.append(f"برآیند مدل {fund_model['investment_horizon_label']} نزولی است")
    if rsi is not None:
        if rsi > 70:
            bearish_reasons.append(f"RSI(14) روی {fmt(rsi)} است؛ بالای ۷۰ در ناحیه فروش و در معرض اصلاح قرار دارد")
        elif rsi < 30:
            bullish_reasons.append(f"RSI(14) روی {fmt(rsi)} است؛ زیر ۳۰ در ناحیه خرید و فروش‌زده است")
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
        threshold = "۰٫۲۰"
        bullish_reasons.append(f"StochRSI روی {fmt(stoch_rsi)} و برابر یا کمتر از {threshold} است؛ ناحیه خرید دیده می‌شود")
    elif stoch_rsi is not None and stoch_rsi >= 0.8:
        threshold = "۰٫۸۰"
        bearish_reasons.append(f"StochRSI روی {fmt(stoch_rsi)} و برابر یا بیشتر از {threshold} است؛ ناحیه فروش دیده می‌شود")
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
         "condition": "شکست حمایت نزدیک با تأیید MACD یا مومنتوم",
         "risk": "اگر حمایت حفظ شود و MACD بالای خط سیگنال بماند، این سناریو اعتبار کمتری دارد."},
    ]
    score_method = fund_model["score_method"]
    if is_tsetmc:
        score_method = score_method.replace("fund_rahavard_", "fund_tsetmc_", 1)
    return {
        "source": source_name, "indicator_source": source_name,
        "volume_data_available": payload.get("volume_data_available"),
        "dashboard_asset": dashboard_model,
        "symbol": symbol, "data_timestamp": data_timestamp,
        "price": price, "support_levels": supports, "resistance_levels": resistances,
        "short_term_exit_price": short_term_exit_price,
        "medium_term_exit_price": medium_term_exit_price,
        "short_term_exit": {
            "price": short_term_exit_price,
            "trigger": "بسته‌شدن کندل روزانه زیر EMA(10)",
            "action": "حد خروج کوتاه‌مدت فقط پس از بسته‌شدن کندل روزانه زیر EMA(10) تأیید می‌شود.",
        },
        "medium_term_exit": {
            "price": medium_term_exit_price,
            "trigger": "بسته‌شدن کندل روزانه زیر SMA(30)",
            "action": "حد خروج میان‌مدت فقط پس از بسته‌شدن کندل روزانه زیر SMA(30) تأیید می‌شود.",
        },
        "technical_score": fund_model["technical_score"],
        "score_method": score_method,
        "score_origin": "AliVest",
        "investment_horizon": fund_model["investment_horizon"],
        "investment_horizon_label": fund_model["investment_horizon_label"],
        "fund_type": fund_model.get("fund_type"),
        "fund_type_label": fund_model.get("fund_type_label"),
        "model_profile": fund_model.get("model_profile"),
        "score_timestamp": data_timestamp,
        "score_weights": fund_model["score_weights"],
        "indicator_weights": fund_model["indicator_weights"],
        "effective_score_weights": fund_model["effective_score_weights"],
        "family_scores": fund_model["family_scores"],
        "decision": fund_model.get("decision"),
        "decision_label": fund_model.get("decision_label"),
        "confidence_level": fund_model.get("confidence_level"),
        "confluence_pct": fund_model.get("confluence_pct"),
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
            "trend_momentum": trend_momentum_score,
            "oscillators": oscillator_score,
            "rsi": rsi,
            "resistance": resistance_score,
            "front_resistance_count": len(front_resistances),
            "near_resistance_count": len(near_resistances),
            "nearest_resistance_distance_pct": round(nearest_resistance_distance, 2)
            if nearest_resistance_distance is not None else None,
        },
        "trend_probabilities": {"bullish": bullish_probability, "bearish": bearish_probability},
        "correction_risk": {
            "probability": correction_probability,
            "label": correction_label,
            "near_resistance_count": len(near_resistances),
            "overbought_count": overbought_count,
        },
        "signal": signal, "trend": trend, "trend_strength": trend_strength,
        "risk": risk_rank.get("level") or "unavailable",
        "risk_score": risk_rank.get("score"),
        "entry_quality": entry_quality,
        "confidence": fund_model.get("confidence"),
        "inter_group_dispersion": fund_model.get("inter_group_dispersion"),
        "damping_factor": fund_model.get("damping_factor"),
        "raw_technical_score": fund_model.get("raw_technical_score"),
        "confidence_basis": "اعتماد بر پایهٔ پوشش داده، توافق گروه‌ها و فاصلهٔ امتیاز از آستانه‌ها محاسبه می‌شود؛ احتمال سود نیست.",
        "decision_support": explanation,
        "explanation": explanation, "site_gauges": gauges,
        "indicators": groups, "indicator_notes": notes,
        "indicator_count": sum(len(items) for items in groups.values()),
        "missing_indicators": missing, "scenarios": scenarios,
        "scenario_note": ("درصد سناریو برآورد داخلی AliVest از امتیاز اندیکاتورهای محاسبه‌شده روی کندل‌های TSETMC است و احتمال آماریِ بک‌تست‌شده نیست."
                          if is_tsetmc else
                          "درصد سناریو از شمارش سیگنال‌های Buy/Neutral/Sell در شاخص کلی ره‌آورد برآورد شده و احتمال آماریِ بک‌تست‌شده نیست."),
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
