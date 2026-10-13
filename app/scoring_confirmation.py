"""Independent price/volume confirmation checks for the experimental model."""
from __future__ import annotations

import math
from typing import Any

from .scoring_profiles import normalize_horizon, FUND_SCORING_PROFILES


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return min(high, max(low, value))


def _signed(value: float, scale: float) -> float:
    return _clamp(50.0 + 50.0 * math.tanh(value / scale))


def _price_series(bars: list[dict[str, Any]]) -> list[float | None]:
    return [_number(bar.get("close")) for bar in bars if isinstance(bar, dict)]


def _volume_series(bars: list[dict[str, Any]]) -> list[float | None]:
    return [_number(bar.get("volume")) for bar in bars if isinstance(bar, dict)]


def _log_return(closes: list[float | None], periods: int) -> float | None:
    if len(closes) <= periods:
        return None
    current, prior = closes[-1], closes[-periods - 1]
    if current is None or prior is None or current <= 0 or prior <= 0:
        return None
    return math.log(current / prior)


def _trend_confirmation(closes: list[float | None], periods: int) -> tuple[float | None, dict[str, Any]]:
    if len(closes) <= periods or any(value is None or value <= 0 for value in closes[-periods - 1:]):
        return None, {}
    sample = [float(value) for value in closes[-periods - 1:]]
    returns = [math.log(sample[index] / sample[index - 1]) for index in range(1, len(sample))]
    net_return = sum(returns)
    persistence = sum(value > 0 for value in returns) / len(returns) * 100.0
    score = 0.70 * _signed(net_return, 0.12 if periods <= 20 else 0.24) + 0.30 * persistence
    return score, {"net_return_pct": (math.exp(net_return) - 1.0) * 100.0,
                   "positive_sessions_pct": persistence, "lookback_sessions": periods}


def _momentum_confirmation(closes: list[float | None], horizon: str) -> tuple[float | None, dict[str, Any]]:
    fast = 5 if horizon == "short" else 20
    if len(closes) < fast * 2 + 1 or any(value is None or value <= 0 for value in closes[-fast * 2 - 1:]):
        return None, {}
    recent = math.log(float(closes[-1]) / float(closes[-fast - 1]))
    prior = math.log(float(closes[-fast - 1]) / float(closes[-fast * 2 - 1]))
    acceleration = recent - prior
    score = 0.65 * _signed(recent, 0.05 if horizon == "short" else 0.12)
    score += 0.35 * _signed(acceleration, 0.04 if horizon == "short" else 0.10)
    return score, {"recent_return_pct": (math.exp(recent) - 1.0) * 100.0,
                   "prior_return_pct": (math.exp(prior) - 1.0) * 100.0,
                   "lookback_sessions": fast}


def _volume_confirmation(closes: list[float | None], volumes: list[float | None],
                          horizon: str) -> tuple[float | None, dict[str, Any]]:
    periods = (15, 30) if horizon == "short" else (30, 90)
    rows = []
    for period in periods:
        if len(closes) <= period or len(volumes) < period * 2:
            continue
        recent_volumes = volumes[-period:]
        prior_volumes = volumes[-period * 2:-period]
        if any(value is None or value < 0 for value in recent_volumes + prior_volumes):
            continue
        recent_avg = sum(float(value) for value in recent_volumes) / period
        prior_avg = sum(float(value) for value in prior_volumes) / period
        price_return = _log_return(closes, period)
        if prior_avg <= 0 or price_return is None:
            continue
        relative_activity = min(2.0, max(0.5, recent_avg / prior_avg))
        # High activity is favorable only when price movement confirms direction.
        score = _clamp(50.0 + 40.0 * math.tanh(price_return / (0.08 if period <= 30 else 0.16))
                       * relative_activity)
        rows.append((period, score, relative_activity, (math.exp(price_return) - 1.0) * 100.0))
    if not rows:
        return None, {}
    return (sum(row[1] for row in rows) / len(rows),
            {"coverage_pct": len(rows) / len(periods) * 100.0,
             "periods": [{"lookback_sessions": period, "score": score,
                          "relative_activity": activity, "price_return_pct": return_pct}
                         for period, score, activity, return_pct in rows]})


def _entry_confirmation(price: float | None, support: float | None,
                        resistance: float | None) -> tuple[float | None, dict[str, Any]]:
    if price is None or price <= 0 or support is None or resistance is None:
        return None, {"status": "unavailable", "reason": "حمایت و مقاومت معتبر هم‌زمان در دسترس نیست."}
    downside = (price - support) / price
    upside = (resistance - price) / price
    if downside <= 0 or upside <= 0:
        return None, {"status": "unavailable", "reason": "سطوح حمایت و مقاومت برای سنجش نقطهٔ ورود معتبر نیستند."}
    reward_risk = upside / downside
    score = _clamp(50.0 + 25.0 * math.tanh(math.log(max(reward_risk, 1e-9)) * 0.8))
    resistance_distance_pct = upside * 100.0
    support_distance_pct = downside * 100.0
    suitable = score >= 60.0 and reward_risk >= 1.5 and resistance_distance_pct >= 2.0
    status = "suitable" if suitable else "unsuitable" if score < 45 or resistance_distance_pct < 1.0 else "confirmation"
    reason = ("فاصلهٔ مقاومت و نسبت سود احتمالی به ریسک مناسب است."
              if suitable else "مقاومت نزدیک یا نسبت سود احتمالی به ریسک نیازمند احتیاط است.")
    return score, {"status": status, "support": support, "resistance": resistance,
                   "support_distance_pct": support_distance_pct,
                   "resistance_distance_pct": resistance_distance_pct,
                   "reward_risk_ratio": reward_risk, "reason": reason}


def compute_confirmation(horizon: str, bars: list[dict[str, Any]], price: float | None,
                         support: float | None = None,
                         resistance: float | None = None) -> dict[str, Any]:
    """Return T/M/V/L confirmation, renormalizing only among available evidence."""
    horizon = normalize_horizon(horizon)
    profile = FUND_SCORING_PROFILES[horizon]
    configured = profile["confirmation_weights"]
    closes, volumes = _price_series(bars or []), _volume_series(bars or [])
    trend_period = 20 if horizon == "short" else 60
    trend, trend_detail = _trend_confirmation(closes, trend_period)
    momentum, momentum_detail = _momentum_confirmation(closes, horizon)
    volume, volume_detail = _volume_confirmation(closes, volumes, horizon)
    entry, entry_detail = _entry_confirmation(price, support, resistance)
    raw = {"trend": (trend, trend_detail), "momentum": (momentum, momentum_detail),
           "volume": (volume, volume_detail), "entry": (entry, entry_detail)}
    evidence_weights = {
        key: configured[key] * (_number(detail.get("coverage_pct")) or 0.0) / 100.0
        if score is not None and isinstance(detail, dict) and detail.get("coverage_pct") is not None
        else configured[key] if score is not None else 0.0
        for key, (score, detail) in raw.items()
    }
    valid_weight = sum(evidence_weights.values())
    score = (sum(float(value) * evidence_weights[key] for key, (value, _) in raw.items() if value is not None) / valid_weight
             if valid_weight >= 0.50 else None)
    components = {
        key: {"score": round(value, 1) if value is not None else None,
              "weight_pct": round(configured[key] * 100.0, 1),
              "coverage_pct": round(evidence_weights[key] / configured[key] * 100.0, 1) if configured[key] else 0.0,
              **detail}
        for key, (value, detail) in raw.items()
    }
    return {"score": round(score, 1) if score is not None else None,
            "coverage_pct": round(valid_weight * 100.0, 1),
            "weights_pct": {key: round(value * 100.0, 1) for key, value in configured.items()},
            "components": components,
            "entry_quality": {"score": round(entry, 1) if entry is not None else None, **entry_detail}}


def combine_scores(family_scores: dict[str, Any], family_weights: dict[str, float],
                   confirmation: dict[str, Any]) -> dict[str, Any]:
    """Compute main S and combined F without filling missing evidence with guesses."""
    available = [(family_scores.get(key, {}).get("score"), weight)
                 for key, weight in family_weights.items()
                 if family_scores.get(key, {}).get("score") is not None]
    available_weight = sum(weight for _, weight in available)
    main = (sum(float(score) * weight for score, weight in available) / available_weight
            if available_weight else None)
    confirmation_score = confirmation.get("score")
    combined = (0.75 * main + 0.25 * confirmation_score
                if main is not None and confirmation_score is not None else None)
    if main is None:
        band = "unavailable"
    elif main < 40:
        band = "weak"
    elif main < 55:
        band = "uncertain"
    elif main < 65:
        band = "review"
    elif main < 75:
        band = "relatively_positive"
    elif main < 85:
        band = "strong"
    else:
        band = "very_strong"
    effective = ({key: round(weight / available_weight * 100.0, 1)
                  for key, weight in family_weights.items()
                  if family_scores.get(key, {}).get("score") is not None}
                 if available_weight else {})
    return {"main_score": round(main, 1) if main is not None else None,
            "confirmation_score": confirmation_score,
            "combined_score": round(combined, 1) if combined is not None else None,
            "score_band": band,
            "available_family_weight_pct": round(available_weight * 100.0, 1),
            "effective_family_weights": effective}


def assess_purchase(main_score: float | None, confirmation_score: float | None,
                    confirmation_coverage_pct: float | None,
                    entry_quality: dict[str, Any] | None,
                    components: dict[str, Any] | None = None) -> dict[str, Any]:
    """Apply the attachment's initial S/C/L rules consistently across views."""
    coverage = _number(confirmation_coverage_pct)
    entry_quality = entry_quality if isinstance(entry_quality, dict) else {}
    components = components if isinstance(components, dict) else {}
    if main_score is None or confirmation_score is None or coverage is None or coverage < 50:
        return {"status": "unknown", "label": "دادهٔ تأیید کافی نیست",
                "reason": "برای جمع‌بندی خرید، دادهٔ اصلی و حداقل ۵۰٪ از مؤلفه‌های تأیید لازم است.", "rank": None}
    trend = components.get("trend") if isinstance(components.get("trend"), dict) else {}
    trend_score = _number(trend.get("score"))
    net_return = _number(trend.get("net_return_pct"))
    severe_downtrend = trend_score is not None and trend_score < 25 and net_return is not None and net_return < -8
    if main_score < 55 or severe_downtrend:
        reason = ("امتیاز اصلی S پایین است؛ این مدل ورود جدید را تأیید نمی‌کند."
                  if main_score < 55 else "افت و ضعف روند در دادهٔ موجود شدید است؛ ورود تازه بر اساس این مدل مناسب نیست.")
        return {"status": "unsuitable", "label": "فعلاً مناسب خرید نیست", "reason": reason, "rank": 1}
    if main_score >= 75 and confirmation_score >= 70 and entry_quality.get("status") == "suitable":
        return {"status": "suitable", "label": "قابل بررسی برای خرید",
                "reason": "امتیاز اصلی S، تأیید C و کیفیت موقعیت ورود هم‌زمان از آستانهٔ اولیه عبور کرده‌اند؛ این نتیجه تضمین معامله نیست.", "rank": 3}
    if main_score >= 65:
        if confirmation_score < 70:
            reason = "امتیاز اصلی مناسب است، اما امتیاز تأیید C به ۷۰ نرسیده؛ برای تأیید بیشتر صبر کن."
        elif entry_quality.get("status") != "suitable":
            reason = "امتیازهای S و C به‌تنهایی کافی نیستند؛ مقاومت نزدیک یا نسبت سود احتمالی به ریسک، نقطهٔ ورود را تأیید نمی‌کند."
        else:
            reason = "برای فرصت قابل بررسی، امتیاز اصلی S باید دست‌کم ۷۵ باشد."
        return {"status": "confirmation", "label": "صبر برای تأیید", "reason": reason, "rank": 2}
    return {"status": "confirmation", "label": "قابل بررسی با تأیید ناکافی",
            "reason": "امتیاز اصلی در محدودهٔ میانی است؛ پیش از ورود، روند و نقطهٔ ورود را دوباره بررسی کن.", "rank": 2}
