from __future__ import annotations

from datetime import datetime, timezone
import math
import re
from typing import Any

from .indicators import compute_indicators


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


def analyze(symbol: str, bars: list[dict[str, Any]]) -> dict[str, Any]:
    tech = compute_indicators(bars)
    indicators = tech["indicators"]
    current = tech.get("latest")
    ma = tech.get("moving_average_analysis", {})
    short = _trend(current, _num(indicators.get("EMA(20)")))
    medium = _trend(current, _num(indicators.get("EMA(50)")), _num(indicators.get("EMA(200)")))
    long = _trend(current, _num(indicators.get("EMA(200)")))

    # Factors and weights are explicit and returned for inspection. Missing inputs are excluded and weights renormalized.
    factors: list[dict[str, Any]] = []
    def add_factor(name: str, score: float | None, weight: float, evidence: str):
        if score is not None:
            factors.append({"name": name, "score": score, "weight": weight, "evidence": evidence})
    trend_score = {"bullish": 100, "neutral": 50, "bearish": 0}.get(medium)
    add_factor("trend", trend_score, 0.25, medium)
    rsi = _num(indicators.get("RSI(14)"))
    add_factor("momentum", max(0, min(100, rsi if rsi is not None else 50)), 0.18,
               f"RSI(14)={rsi:.1f}" if rsi is not None else "RSI unavailable")
    ma_score = None
    if ma.get("price_above_ema20") is not None:
        checks = [ma.get(k) for k in ["price_above_ema20", "price_above_ema50", "price_above_ema200"]]
        checks = [x for x in checks if x is not None]
        ma_score = 100 * sum(checks) / len(checks) if checks else None
    add_factor("moving_averages", ma_score, 0.22, "قیمت نسبت به EMA20/50/200")
    volume = tech.get("volume_analysis", {})
    vol_score = (65 if volume.get("volume_spike") else 55 if volume.get("volume_trend") == "up" else 45) if volume.get("available") else None
    add_factor("volume", vol_score, 0.12, "افزایش حجم" if volume.get("volume_spike") else "روند حجم روزانه")
    rv = _num(indicators.get("RV(30)"))
    risk_adj = max(0, min(100, 100 - rv * 2)) if rv is not None else None
    add_factor("volatility", risk_adj, 0.10, f"RV(30)={rv:.2f}%" if rv is not None else "RV unavailable")
    signal_score = 55
    macd = indicators.get("MACD(12,26,9)", {}).get("signal")
    if macd == "bullish": signal_score = 80
    elif macd == "bearish": signal_score = 20
    add_factor("oscillators", signal_score if rsi is not None or macd else None, 0.08, f"MACD={macd}; RSI={rsi}")
    levels = support_resistance(bars, tech)
    supports = [x for x in levels if x["kind"] == "support"]
    resistances = [x for x in levels if x["kind"] == "resistance"]
    nearest_support = max((x for x in supports if x["midpoint"] < current), key=lambda x: x["midpoint"], default=None) if current is not None else None
    nearest_resistance = min((x for x in resistances if x["midpoint"] > current), key=lambda x: x["midpoint"], default=None) if current is not None else None
    proximity = None
    if current and nearest_support:
        distance_pct = abs(current - nearest_support["midpoint"]) / current * 100
        proximity = max(0, 100 - distance_pct * 20)
    add_factor("support_resistance", proximity, 0.05,
               "نزدیکی به نزدیک‌ترین حمایت" if proximity is not None else "سطح نزدیک معتبر در دسترس نیست")
    total_weight = sum(x["weight"] for x in factors)
    score = sum(x["score"] * x["weight"] for x in factors) / total_weight if total_weight else None
    confidence = round(100 * min(1, len(bars) / 200) * (total_weight / 1.0), 0)

    explanation = []
    for factor in factors:
        if factor["name"] in ("trend", "moving_averages", "momentum", "oscillators", "volume", "support_resistance"):
            explanation.append(f"{factor['name']}: {factor['evidence']}")
    if score is None:
        signal = "unavailable"
    elif score >= 80 and confidence >= 35:
        signal = "strong_buy"
    elif score >= 62 and confidence >= 25:
        signal = "buy"
    elif score <= 25 and confidence >= 35:
        signal = "strong_sell"
    elif score <= 40 and confidence >= 25:
        signal = "sell"
    else:
        signal = "hold"

    atr = _num(indicators.get("ATR(14)"))
    scenarios = []
    if current is not None:
        for label, direction, condition, target in [
            ("صعودی", "bullish", "قیمت بالای مقاومت نزدیک تثبیت شود", current + 2 * (atr or 0)),
            ("خنثی", "neutral", "قیمت در محدوده حمایت تا مقاومت بماند", current),
            ("نزولی", "bearish", "حمایت نزدیک با تأیید حجم شکسته شود", current - 2 * (atr or 0)),
        ]:
            scenarios.append({"name": label, "condition": condition,
                              "target": target if atr is not None else None,
                              "support": nearest_support, "resistance": nearest_resistance,
                              "confidence": None, "probability": None,
                              "confidence_status": "احتمال سناریو بدون بک‌تست کالیبره نشده است",
                              "fundamental_drivers": None,
                              "risk": "هدف سناریویی بر اساس 2×ATR؛ پیش‌بینی قطعی نیست"})

    if rv is None:
        risk = "unavailable"
    elif rv >= 45:
        risk = "very_high"
    elif rv >= 30:
        risk = "high"
    elif rv >= 15:
        risk = "medium"
    else:
        risk = "low"
    return {
        "symbol": symbol, "data_timestamp": bars[-1].get("timestamp"), "price": current,
        "trend": medium, "short_term_trend": short, "medium_term_trend": medium,
        "long_term_trend": long, "technical_score": round(score, 1) if score is not None else None,
        "confidence": confidence, "confidence_basis": "پوشش عوامل قابل محاسبه و طول تاریخچه؛ احتمال موفقیت نیست",
        "risk": risk, "signal": signal,
        "factors": factors, "explanation": explanation, "indicators": tech,
        "support_resistance": levels,
        "nearest_support": nearest_support, "nearest_resistance": nearest_resistance,
        "scenarios": scenarios,
        "decision_support": "شرایط مدل برای بررسی بیشتر مناسب‌تر است" if signal in ("buy", "strong_buy") else "مدل فعلی ورود را تأیید نمی‌کند" if signal in ("sell", "strong_sell") else "برای تصمیم‌گیری داده/تأیید بیشتری لازم است",
    }


def analyze_rahavard(symbol: str, payload: dict[str, Any],
                     data_timestamp: str | None = None) -> dict[str, Any]:
    """Describe Rahavard's published indicator readings without recalculating them."""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    groups = {key: data.get(key) if isinstance(data.get(key), list) else []
              for key in ("oscillators", "moving_averages", "pivots", "bands", "volumes")}
    gauges = data.get("gauges") if isinstance(data.get("gauges"), dict) else {}
    main_gauge = gauges.get("main") if isinstance(gauges.get("main"), dict) else {}
    main_signal = main_gauge.get("signal") if isinstance(main_gauge.get("signal"), dict) else {}
    pointer = main_gauge.get("pointer")
    try:
        score = float(pointer) * 100 if pointer is not None else None
        if score is not None and not math.isfinite(score):
            score = None
    except (TypeError, ValueError):
        score = None
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
    explanation = (f"سیگنال تجمیعی ره‌آورد: {counts.get('Buy') or 0} خرید، "
                   f"{counts.get('Neutral') or 0} خنثی، {counts.get('Sell') or 0} فروش.")
    return {
        "source": "Rahavard365", "symbol": symbol, "data_timestamp": data_timestamp,
        "technical_score": round(score, 1) if score is not None else None,
        "signal": signal, "trend": trend, "risk": "unavailable",
        "confidence": None,
        "confidence_basis": "امتیاز و سیگنال از داشبورد تکنیکال خود ره‌آورد دریافت شده‌اند.",
        "decision_support": explanation,
        "explanation": explanation, "site_gauges": gauges,
        "indicators": groups, "indicator_notes": notes,
        "indicator_count": sum(len(items) for items in groups.values()),
        "missing_indicators": missing,
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
