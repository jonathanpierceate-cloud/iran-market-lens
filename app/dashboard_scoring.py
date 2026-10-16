from __future__ import annotations

import math
from typing import Any

from .indicators import compute_indicators, pivot_points
from .scoring_profiles import DASHBOARD_SCORING_PROFILES, normalize_horizon, horizon_label
from .scoring_rules import (adx_directional_score, band_position_score,
                            ichimoku_cloud_score, inverted_linear_score,
                            macd_histogram_score, moving_average_score,
                            entry_recommendation, percent_change_score,
                            pivot_level_score, rsi_entry_score,
                            stoch_rsi_entry_score)
from .tse_scoring import GROUP_WEIGHTS, score_tse_bars


DASHBOARD_SCORE_WEIGHTS = GROUP_WEIGHTS


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return min(high, max(low, value))


def _weighted(rows: list[tuple[float | None, float]]) -> float | None:
    valid = [(value, weight) for value, weight in rows if value is not None and weight > 0]
    total = sum(weight for _, weight in valid)
    return sum(value * weight for value, weight in valid) / total if total else None


def _support_resistance_levels(bars: list[dict[str, Any]], tech: dict[str, Any],
                               current: float | None) -> list[dict[str, Any]]:
    """Use confirmed historical swing points and classic prior-session pivots only."""
    if current is None or current <= 0:
        return []
    points: list[tuple[float, str]] = []
    if len(bars) >= 30:
        start = max(2, len(bars) - 180)
        for index in range(start, len(bars) - 2):
            high = _number(bars[index].get("high"))
            low = _number(bars[index].get("low"))
            neighbors = bars[index - 2:index] + bars[index + 1:index + 3]
            highs = [_number(row.get("high")) for row in neighbors]
            lows = [_number(row.get("low")) for row in neighbors]
            if high is not None and all(value is not None for value in highs) and high >= max(highs):
                points.append((high, "قلهٔ تأییدشدهٔ تاریخچه"))
            if low is not None and all(value is not None for value in lows) and low <= min(lows):
                points.append((low, "کف تأییدشدهٔ تاریخچه"))

    classic = (tech.get("pivots", {}).get("Classic")
               if isinstance(tech.get("pivots"), dict) else None)
    if isinstance(classic, dict):
        for key in ("S1", "S2", "S3", "R1", "R2", "R3"):
            value = _number(classic.get(key))
            if value is not None and value > 0:
                points.append((value, f"پیوت کلاسیک {key} از روز قبل"))

    result: list[dict[str, Any]] = []
    for kind in ("support", "resistance"):
        candidates = [(price, method) for price, method in points
                      if (price <= current if kind == "support" else price > current)]
        candidates.sort(key=lambda item: item[0])
        clusters: list[list[tuple[float, str]]] = []
        for candidate in candidates:
            if clusters and abs(candidate[0] - clusters[-1][-1][0]) <= current * 0.0075:
                clusters[-1].append(candidate)
            else:
                clusters.append([candidate])
        clusters.sort(key=lambda group: abs(sum(price for price, _ in group) / len(group) - current))
        for group in clusters[:3]:
            low = min(price for price, _ in group)
            high = max(price for price, _ in group)
            methods = sorted({method for _, method in group})
            result.append({
                "kind": kind,
                "low": low,
                "high": high,
                "midpoint": (low + high) / 2,
                "strength": "strong" if len(methods) >= 3 else "medium" if len(methods) == 2 else "watch",
                "methods": methods,
                "method": "; ".join(methods),
            })
    return result


def analyze_dashboard_asset(symbol: str, bars: list[dict[str, Any]],
                            horizon: str = "long") -> dict[str, Any]:
    """AliVest score using the chart-derived four-family TSE v1 engine."""
    horizon = normalize_horizon(horizon)
    model = DASHBOARD_SCORING_PROFILES[horizon]
    family_weights = model["family_weights"]
    weights = {family: dict(entries) for family, entries in model["indicator_weights"].items()}
    # These keys are needed only by the legacy readout below; engine results replace it.
    weights.setdefault("oscillators", {}).update({
        "MACD(26)": 0.0, "ADX(14)": 0.0, "AROON(25)": 0.0,
        "AO(5,34)": 0.0, "Trend": 0.0, "SO(14)": 0.0,
        "StochRSI(14)": 0.0, "WR(14)": 0.0,
    })
    weights.setdefault("support_resistance", {}).update({
        "PivotPointFibonacci(30)": 0.0, "PivotPointClassic(30)": 0.0,
        "PivotPointCamarilla(30)": 0.0, "PivotPointWoodie(30)": 0.0,
        "PivotPointDeMark(30)": 0.0,
    })
    bars = bars or []
    tech = compute_indicators(bars)
    engine = score_tse_bars(bars, horizon=horizon)
    indicators = tech.get("indicators", {})
    current = _number(tech.get("latest"))
    closes = [_number(row.get("close")) for row in bars]
    closes = [value for value in closes if value is not None and value > 0]
    names = {"moving_averages": "\u0645\u06cc\u0627\u0646\u06af\u06cc\u0646\u200c\u0647\u0627\u06cc \u0645\u062a\u062d\u0631\u06a9", "trend_momentum": "\u0631\u0648\u0646\u062f \u0648 \u0634\u062a\u0627\u0628",
             "oscillators": "\u0627\u0633\u06cc\u0644\u0627\u062a\u0648\u0631\u0647\u0627", "support_resistance": "\u062d\u0645\u0627\u06cc\u062a \u0648 \u0645\u0642\u0627\u0648\u0645\u062a"}


    def ind(key: str) -> dict[str, Any]:
        found = indicators.get(key)
        return found if isinstance(found, dict) else {}

    def val(key: str, field: str = "value") -> float | None:
        return _number(ind(key).get(field))

    def row(family: str, key: str, score: float | None, value: Any = None, note: str = "") -> dict[str, Any]:
        return {"name": key, "score": round(score, 1) if score is not None else None,
                "weight_pct": round(weights[family][key]*100, 1), "value": value, "note": note}

    rows: dict[str, list[dict[str, Any]]] = {key: [] for key in weights}

    # Moving averages and bands
    family = "moving_averages"
    for key in weights[family]:
        score, raw, note = None, None, ""
        if key.startswith(("EMA(", "SMA(")):
            raw = val(key)
            period = int(key.split("(", 1)[1].split(")", 1)[0])
            score = moving_average_score(current, raw, period)
        elif key == "Ichimoku(9,26,52,26)":
            item = ind(key)
            ca, cb = _number(item.get("senkou_a_at_current")), _number(item.get("senkou_b_at_current"))
            score = ichimoku_cloud_score(current, ca, cb)
            raw, note = {"span_a": ca, "span_b": cb}, "امتیاز با فاصله از ابر یا جایگاه داخل ابر محاسبه می‌شود."
        elif key in ("BB(20)", "KELTNER(16)"):
            item = ind(key)
            middle = _number(item.get("middle", item.get("value")))
            upper, lower = _number(item.get("upper")), _number(item.get("lower"))
            scenario = str(item.get("signal") or "").lower()
            score = band_position_score(current, lower, upper)
            raw, note = {"middle": middle, "upper": upper, "lower": lower, "scenario": scenario}, "داخل باند خنثی است و نزدیک‌شدن به سقف امتیاز را کاهش می‌دهد؛ زیر کف ناحیه خرید و بالای سقف ناحیه فروش است."
        rows[family].append(row(family, key, score, raw, note))

    # Oscillators: RSI is one bounded vote, never the sole buy criterion.
    family = "oscillators"
    rsi, mfi, stoch = val("RSI(14)"), val("MFI(14)"), val("StochRSI(14)")
    so, cci, wr = val("SO(14)", "k"), val("CCI(14)"), val("WR(14)")
    if so is None:
        so = val("SO(14)")
    macd, hist = val("MACD(12,26,9)"), val("MACD(12,26,9)", "histogram")
    macd_signal = val("MACD(12,26,9)", "signal_line")
    if hist is None and macd is not None and macd_signal is not None:
        hist = macd - macd_signal
    macd_score = macd_histogram_score(hist, current)
    adx, pdi, mdi = val("ADX(14)"), val("ADX(14)", "plus_di"), val("ADX(14)", "minus_di")
    adx_score = adx_directional_score(adx, pdi, mdi)
    up, down = val("Aroon(25)", "up"), val("Aroon(25)", "down")
    aroon_score = _clamp(50+(up-down)/2) if up is not None and down is not None else None
    return30_pct = (closes[-1]/closes[-31]-1)*100 if len(closes) >= 31 else None
    trend_score = percent_change_score(return30_pct, 5.0) if return30_pct is not None else None
    return6_pct = (closes[-1]/closes[-7]-1)*100 if len(closes) >= 7 else None

    rsi_score = rsi_entry_score(rsi) if rsi is not None else None

    osc_data = {
        "MACD(26)": (macd_score, hist, "هیستوگرام MACD به درصد قیمت تبدیل و خطی به امتیاز نگاشت می‌شود."),
        "RSI(14)": (rsi_score, rsi, "زیر ۳۰ ناحیه خرید، ۳۰ تا ۷۰ خنثی با امتیاز کمتر نزدیک ۷۰، و بالای ۷۰ ناحیه فروش است"),
        "MFI(14)": (inverted_linear_score(mfi, 20, 80) if mfi is not None else None, mfi, "امتیاز خطی از ۱۰۰ در ۲۰ تا صفر در ۸۰."),
        "ADX(14)": (adx_score, {"ADX": adx, "+DI": pdi, "-DI": mdi}, "اگر ADX حداکثر ۲۰ باشد امتیاز ۵۰ است؛ بالاتر از آن، جهت و امتیاز بر پایه اختلاف +DI و −DI محاسبه می‌شود."),
        "StochRSI(14)": (stoch_rsi_entry_score(stoch), stoch, "مقیاس ۰ تا ۱؛ ۰ تا ۰٫۲۰ ناحیه خرید، ۰٫۲۰ تا ۰٫۸۰ خنثی، و ۰٫۸۰ تا ۱ ناحیه فروش"),
        "Trend": (trend_score, return30_pct, "تغییر قیمت طی ۳۰ دوره؛ هر ۱٪ تغییر ۵ امتیاز جابه‌جا می‌کند."),
        "AO(5,34)": (percent_change_score(val("AO(5,34)")/current*100, 25.0) if val("AO(5,34)") is not None and current else None,
                     val("AO(5,34)"), "شتاب میانگین‌های ۵ و ۳۴ دوره"),
        "SO(14)": (inverted_linear_score(so, 20, 80) if so is not None else None, so, "امتیاز بر پایهٔ خط %K: ۲۰ برابر ۱۰۰ و ۸۰ برابر صفر."),
        "AROON(25)": (aroon_score, {"up": up, "down": down}, "تازگی سقف و کف ۲۵ دوره"),
        "CCI(14)": (_clamp(50-cci/2) if cci is not None else None, cci, "امتیاز خطی از فرمول ۵۰ منهای نصف CCI."),
        "MTM(6)": (percent_change_score(return6_pct, 10.0) if return6_pct is not None else None,
                   return6_pct, "درصد تغییر قیمت طی ۶ دوره؛ هر ۱٪ تغییر ۱۰ امتیاز جابه‌جا می‌کند."),
        "WR(14)": (inverted_linear_score(wr, -80, -20) if wr is not None else None, wr, "امتیاز خطی از ۱۰۰ در منفی ۸۰ تا صفر در منفی ۲۰."),
    }
    for key, (score, raw, note) in osc_data.items():
        rows[family].append(row(family, key, score, raw, note))

    # Support/resistance: pivot calculations use the previous 30 completed bars.
    family = "support_resistance"
    schemes = {
        "PivotPointFibonacci(30)": "Fibonacci", "PivotPointClassic(30)": "Classic",
        "PivotPointCamarilla(30)": "Camarilla", "PivotPointWoodie(30)": "Woodie",
        "PivotPointDeMark(30)": "DeMark",
    }
    pivot_sets = {}
    if current is not None and len(bars) >= 31:
        window = bars[-31:-1]
        highs = [_number(item.get("high", item.get("close"))) for item in window]
        lows = [_number(item.get("low", item.get("close"))) for item in window]
        prior_close = _number(window[-1].get("close"))
        prior_open = _number(window[-1].get("open", prior_close))
        if all(value is not None for value in highs+lows) and prior_close is not None and prior_open is not None:
            pivot_sets = pivot_points(max(highs), min(lows), prior_close, prior_open)
    for key, scheme in schemes.items():
        levels = pivot_sets.get(scheme, {})
        pivot = _number(levels.get("pivot")) if levels else None
        score, raw = None, None
        if current is not None and pivot is not None and pivot > 0:
            upper_name, lower_name = ("H3", "L3") if scheme == "Camarilla" else ("R1", "S1")
            upper, lower = _number(levels.get(upper_name)), _number(levels.get(lower_name))
            score = pivot_level_score(current, pivot, upper, lower)
            raw = {"pivot": pivot, upper_name: upper, lower_name: lower}
        rows[family].append(row(family, key, score, raw, "فرمول خطی پیوت؛ برای کاماریلا از H3 و L3 استفاده می‌شود."))

    family_scores = engine["family_scores"]
    rsi_score = next((item.get("score") for item in family_scores.get("oscillators", {}).get("indicators", [])
                      if item.get("key") == "RSI(14)"), None)
    family_weights = {key: float(value) / 100.0
                      for key, value in engine["score_weights"].items()}
    weights = {family: {key: float(value) / 100.0 for key, value in entries.items()}
               for family, entries in engine["indicator_weights"].items()}
    rows = {family: result["indicators"] for family, result in family_scores.items()}
    total = engine["technical_score"]
    available_weight = float(engine["available_family_weight_pct"]) / 100.0
    effective = engine["effective_score_weights"]
    coverage = engine["data_coverage_pct"]
    direction = {"Bullish": "bullish", "Bearish": "bearish", "Neutral": "neutral"}.get(
        engine["signal"], "unavailable")
    band = engine["score_band"]

    levels = _support_resistance_levels(bars, tech, current)
    supports = [item for item in levels if item["kind"] == "support"]
    resistances = [item for item in levels if item["kind"] == "resistance"]
    near_support = max(supports, key=lambda item: item["midpoint"], default=None)
    near_resistance = min(resistances, key=lambda item: item["midpoint"], default=None)
    support_distance = (current-near_support["midpoint"])/current*100 if current and near_support else None
    resistance_distance = (near_resistance["midpoint"]-current)/current*100 if current and near_resistance else None
    # Keep historical realized volatility for risk only (the app's legacy RV(30)).
    realized_volatility = val("RV(30)")
    risk_value = realized_volatility if realized_volatility is not None else (
        atr/current*100*math.sqrt(252) if atr and current else None)
    risk = "unavailable" if risk_value is None else "low" if risk_value < 15 else "medium" if risk_value <= 30 else "high"
    adx_value = val("ADX(14)")
    strength = "unavailable" if adx_value is None else "strong" if adx_value >= 25 else "medium" if adx_value >= 20 else "weak"
    daily = closes[-1]/closes[-2]-1 if len(closes) > 1 else None
    ema20, ema100 = val("EMA(20)"), val("EMA(100)")
    ema10 = val("EMA(10)")
    sma30 = val("SMA(30)")
    short_exit = round(ema10) if ema10 is not None else None
    medium_exit = round(sma30) if sma30 is not None else None
    active_exit_price = short_exit if horizon == "short" else medium_exit
    entry_assessment = entry_recommendation(
        rsi, family_scores.get("moving_averages", {}).get("score"), total,
        above_exit_average=(current > active_exit_price)
        if current is not None and active_exit_price is not None else None,
        resistance_distance_pct=resistance_distance)
    entry_score = (_weighted([
        (family_scores.get("moving_averages", {}).get("score"), .60),
        (rsi_score, .40),
    ]) if family_scores.get("moving_averages", {}).get("score") is not None and rsi_score is not None
                   else None)

    positive = [{"family": key, "name": names[key], "score": family_scores[key]["score"]}
                for key in sorted(family_scores, key=lambda k: family_scores[k]["score"] or -1, reverse=True)
                if family_scores[key]["score"] is not None and math.floor(family_scores[key]["score"] + 0.5) >= 70][:2]
    negative = [{"family": key, "name": names[key], "score": family_scores[key]["score"]}
                for key in sorted(family_scores, key=lambda k: family_scores[k]["score"] or 101)
                if family_scores[key]["score"] is not None and math.floor(family_scores[key]["score"] + 0.5) <= 40][:2]
    factors = [{"name": key, "score": family_scores[key]["score"],
                "weight": float(effective.get(key, 0.0)) / 100.0,
                "evidence": ", ".join((item.get("name") or item.get("key") or "")
                                       for item in rows[key] if item["score"] is not None)}
               for key in family_weights if family_scores[key]["score"] is not None]
    missing = [f"{names[family]}: {key}" for family in weights for key in family_scores[family]["missing_indicators"]]
    limitations = [
        "این امتیاز محاسبهٔ اختصاصی AliVest است، نه امتیاز رسمی ره‌آورد یا احتمال آماری موفقیت.",
        "وزن اندیکاتورهای بدون داده در همان گروه متناسب می‌شود؛ اگر یک گروه کامل داده نداشته باشد، وزن آن بین گروه‌های قابل محاسبه تقسیم می‌شود.",
        f"RSI یکی از شاخص‌های نوسان‌گر و {family_weights['oscillators'] * weights['oscillators']['RSI(14)'] * 100:.1f}٪ از وزن پایهٔ کل است؛ خرید بر پایهٔ برآیند چهار گروه ارزیابی می‌شود.",
        "\u0627\u0646\u062f\u06cc\u06a9\u0627\u062a\u0648\u0631\u0647\u0627\u06cc \u0645\u0633\u062a\u0642\u0644 \u062d\u062c\u0645 \u0627\u0632 \u0627\u0645\u062a\u06cc\u0627\u0632\u062f\u0647\u06cc \u062d\u0630\u0641 \u0634\u062f\u0647\u200c\u0627\u0646\u062f\u061b MFI \u0637\u0628\u0642 \u0641\u0627\u06cc\u0644 \u0627\u06a9\u0633\u0644 \u062f\u0631 \u06af\u0631\u0648\u0647 \u0627\u0633\u06cc\u0644\u0627\u062a\u0648\u0631\u0647\u0627 \u0628\u0627\u0642\u06cc \u0645\u0627\u0646\u062f\u0647 \u0627\u0633\u062a.",
    ]
    if missing:
        limitations.append("شاخص‌های فاقد داده یا فرمول قابل اتکا حذف شدند: "+"، ".join(missing))
    coverage_by_family = {key: family_scores[key]["coverage_pct"] for key in family_scores}
    breakdown = {key: family_scores[key]["score"] for key in family_scores}
    breakdown.update({
        "family_coverage_pct": coverage_by_family, "available_weight": round(available_weight*100, 1),
        "direction_score": round(total, 1) if total is not None else None,
        "rsi": rsi, "adx": adx_value, "realized_volatility_pct": realized_volatility,
        "support_distance_pct": round(support_distance, 2) if support_distance is not None else None,
        "resistance_distance_pct": round(resistance_distance, 2) if resistance_distance is not None else None,
        "front_resistance_count": len(resistances),
        "near_resistance_count": sum(1 for item in resistances if current and (item["midpoint"]-current)/current <= .10),
    })
    dashboard_indicators = dict(indicators)
    for key in ("OBV(20)", "VRSI(14)", "VMACD(12,26)"):
        dashboard_indicators.pop(key, None)
    for period in (15, 30, 90):
        historical = dashboard_indicators.pop(f"RV({period})", None)
        if historical is not None:
            dashboard_indicators[f"HV({period})"] = historical
    dashboard_tech = dict(tech)
    dashboard_tech["indicators"] = dashboard_indicators
    return {
        "symbol": symbol, "data_timestamp": bars[-1].get("timestamp") if bars else None,
        "price": current, "daily_return_pct": daily*100 if daily is not None else None,
        "short_term_exit_price": short_exit, "medium_term_exit_price": medium_exit,
        "short_term_exit": {"price": short_exit, "trigger": "بسته‌شدن کندل روزانه زیر EMA(10)",
                            "action": "حد خروج کوتاه‌مدت فقط پس از بسته‌شدن کندل روزانه زیر EMA(10) تأیید می‌شود."},
        "medium_term_exit": {"price": medium_exit, "trigger": "بسته‌شدن کندل روزانه زیر SMA(30)",
                             "action": "حد خروج میان‌مدت فقط پس از بسته‌شدن کندل روزانه زیر SMA(30) تأیید می‌شود."},
        "trend": direction, "medium_term_trend": direction,
        "short_term_trend": "unavailable" if current is None or ema20 is None else "bullish" if current > ema20 else "bearish" if current < ema20 else "neutral",
        "long_term_trend": "unavailable" if current is None or ema100 is None else "bullish" if current > ema100 else "bearish" if current < ema100 else "neutral",
        "trend_direction_score": round(total, 1) if total is not None else None,
        "trend_strength": strength, "technical_score": round(total, 1) if total is not None else None,
        "score_method": f"dashboard_rahavard_excel_weighted_update4_{horizon}",
        "score_origin": "AliVest", "score_profile": f"{horizon}_update_4_indicators",
        "investment_horizon": horizon, "investment_horizon_label": horizon_label(horizon),
        "score_weights": {key: round(value*100) for key, value in family_weights.items()},
        "indicator_weights": engine["indicator_weights"],
        "effective_score_weights": effective, "family_scores": family_scores, "score_band": band,
        "score_validation": "update_4_indicator_model_unbacktested", "score_breakdown": breakdown,
        "data_coverage_pct": round(coverage, 1), "available_family_weight_pct": round(available_weight*100, 1),
        "confidence": engine["confidence"], "confidence_score": engine["confidence"],
        "inter_group_dispersion": engine["inter_group_dispersion"],
        "damping_factor": engine["damping_factor"], "raw_technical_score": engine["raw_score"],
        "decision": engine["decision"], "decision_label": engine["decision_label"],
        "confidence_level": engine["confidence_level"],
        "confluence_pct": engine["confluence_pct"],
        "confidence_label": {"high": "بالا", "medium": "متوسط", "low": "پایین",
                             "insufficient": "داده ناکافی"}[engine["confidence_level"]],
        "confidence_basis": "بر پایهٔ پوشش داده و هم‌جهتی اندیکاتورها؛ احتمال موفقیت معامله نیست.",
        "breakout_confidence": "independent_volume_indicators_removed",
        "breakout_confidence_label": "\u0627\u0646\u062f\u06cc\u06a9\u0627\u062a\u0648\u0631\u0647\u0627\u06cc \u062d\u062c\u0645 \u0627\u0632 \u0627\u0645\u062a\u06cc\u0627\u0632\u062f\u0647\u06cc \u062d\u0630\u0641 \u0634\u062f\u0647\u200c\u0627\u0646\u062f",
        "risk": risk, "risk_score": round(risk_value, 1) if risk_value is not None else None,
        "risk_label": {"low":"کم","medium":"متوسط","high":"بالا","unavailable":"نامشخص"}[risk],
        "risk_basis": "نوسان تاریخی RV(30)، و در نبود آن تخمین از ATR(14).",
        "entry_quality": {"score": round(entry_score, 1) if entry_score is not None else None,
                          "status": entry_assessment["status"], "label": entry_assessment["label"],
                          "reason": entry_assessment["reason"],
                          "score_method": "۶۰٪ میانگین‌های متحرک + ۴۰٪ امتیاز RSI",
                          "rsi": rsi,
                          "rsi_score": round(rsi_score, 1) if rsi_score is not None else None,
                          "moving_average_score": family_scores.get("moving_averages", {}).get("score")},
        "signal": direction, "factors": factors, "positive_evidence": positive, "negative_evidence": negative,
        "explanation": [f"{names[item['name']]}: {item['evidence']}" for item in factors],
        "breakout_confirmation_note": "شاخص‌های فاقد داده امتیاز جایگزین نمی‌گیرند.",
        "data_limitations": limitations, "indicators": dashboard_tech,
        "support_resistance": levels, "support_levels": supports, "resistance_levels": resistances,
        "nearest_support": near_support, "nearest_resistance": near_resistance,
        "structural_invalidation_level": near_support.get("midpoint") if near_support else None,
        "decision_support": "\u0627\u0645\u062a\u06cc\u0627\u0632 \u0628\u0631\u0622\u06cc\u0646\u062f \u0686\u0647\u0627\u0631 \u06af\u0631\u0648\u0647 \u0645\u06cc\u0627\u0646\u06af\u06cc\u0646\u200c\u0647\u0627\u06cc \u0645\u062a\u062d\u0631\u06a9\u060c \u0631\u0648\u0646\u062f \u0648 \u0634\u062a\u0627\u0628\u060c \u062d\u0645\u0627\u06cc\u062a \u0648 \u0645\u0642\u0627\u0648\u0645\u062a \u0648 \u0627\u0633\u06cc\u0644\u0627\u062a\u0648\u0631\u0647\u0627 \u0627\u0633\u062a.",
    }
