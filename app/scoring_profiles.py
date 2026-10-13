"""Experimental four-family Rahavard scoring weights (user supplied)."""
from __future__ import annotations

HORIZON_LABELS = {"short": "کوتاه‌مدت", "long": "میان‌مدت"}
DEFAULT_HORIZON = "long"

_SHORT_OSCILLATORS = {
    "rsi14": .14, "mfi14": .10, "cci14": .08, "wr14": .07,
    "so14": .08, "aroon25": .10, "adx14": .12, "ao534": .08,
    "stochrsi14": .07, "macd26": .10, "mtm6": .06,
}
_SHORT_MA = {
    "ichimoku": .18, "keltner16": .06, "bb20": .06,
    "ema5": .04, "ema10": .06, "ema20": .08, "ema30": .07,
    "ema50": .08, "ema100": .05, "sma5": .03, "sma10": .04,
    "sma20": .06, "sma30": .05, "sma50": .07, "sma100": .07,
}
_SHORT_VOLUME = {
    "rv90": .10, "rv30": .15, "rv15": .20, "sm15": .10,
    "vrsi14": .15, "vmacd26": .15, "obv20": .15,
}
_SHORT_SUPPORT = {"woodie": .20, "fibonacci": .20, "demark": .20,
                  "classic": .20, "camarilla": .20}

_MEDIUM_OSCILLATORS = {
    "rsi14": .15, "mfi14": .10, "cci14": .07, "wr14": .05,
    "so14": .06, "aroon25": .12, "adx14": .14, "ao534": .08,
    "stochrsi14": .05, "macd26": .13, "mtm6": .05,
}
_MEDIUM_MA = {
    "ichimoku": .20, "keltner16": .05, "bb20": .05,
    "ema5": .02, "ema10": .03, "ema20": .05, "ema30": .06,
    "ema50": .10, "ema100": .10, "sma5": .02, "sma10": .03,
    "sma20": .05, "sma30": .06, "sma50": .09, "sma100": .09,
}
_MEDIUM_VOLUME = {
    "rv90": .20, "rv30": .20, "rv15": .10, "sm15": .10,
    "vrsi14": .15, "vmacd26": .10, "obv20": .15,
}
_MEDIUM_SUPPORT = {"fibonacci": .20, "demark": .20, "classic": .20,
                   "camarilla": .20, "woodie": .20}

_TRIAL_PROFILES = {
    "short": {
        "profile": "rahavard_user_model_short_trial_v1",
        "family_weights": {
            "oscillators": .30, "moving_averages": .35,
            "volume": .20, "support_resistance": .15,
        },
        "indicator_weights": {
            "oscillators": _SHORT_OSCILLATORS,
            "moving_averages": _SHORT_MA,
            "volume": _SHORT_VOLUME,
            "support_resistance": _SHORT_SUPPORT,
        },
        "confirmation_weights": {"trend": .30, "momentum": .25, "volume": .20, "entry": .25},
    },
    "long": {
        "profile": "rahavard_user_model_medium_trial_v1",
        "family_weights": {
            "oscillators": .25, "moving_averages": .40,
            "volume": .20, "support_resistance": .15,
        },
        "indicator_weights": {
            "oscillators": _MEDIUM_OSCILLATORS,
            "moving_averages": _MEDIUM_MA,
            "volume": _MEDIUM_VOLUME,
            "support_resistance": _MEDIUM_SUPPORT,
        },
        "confirmation_weights": {"trend": .40, "momentum": .20, "volume": .20, "entry": .20},
    },
}

# Both products consume the same user-provided model so their displayed score,
# buy assessment, and watchlist sort order have the same basis.
FUND_SCORING_PROFILES = _TRIAL_PROFILES
DASHBOARD_SCORING_PROFILES = _TRIAL_PROFILES


def normalize_horizon(value: str | None) -> str:
    """Map public horizon parameters while keeping the existing `long` API key."""
    value = str(value or "").strip().casefold()
    if value == "medium":
        return "long"
    return value if value in HORIZON_LABELS else DEFAULT_HORIZON


def horizon_label(value: str | None) -> str:
    return HORIZON_LABELS[normalize_horizon(value)]
