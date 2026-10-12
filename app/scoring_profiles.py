"""Selectable short- and medium-term technical scoring profiles."""
from __future__ import annotations

HORIZON_LABELS = {"short": "کوتاه‌مدت", "medium": "میان‌مدت"}
DEFAULT_HORIZON = "medium"

_SHORT_MA = {
    "ema5": .20, "ema10": .18, "ema20": .15, "sma5": .10,
    "sma10": .08, "bb20": .08, "sma20": .06, "ema30": .05,
    "keltner16": .04, "sma30": .03, "ema50": .02, "sma50": .01,
    "ema100": 0, "sma100": 0, "ichimoku": 0,
}
_SHORT_OSCILLATORS = {
    "rsi14": .18, "macd26": .16, "stochrsi14": .12, "so14": .10,
    "mfi14": .10, "cci14": .08, "adx14": .08, "ao534": .06,
    "aroon25": .04, "mtm6": .04, "wr14": .02, "trend": .02,
}
_SHORT_SUPPORT = {
    "camarilla": .35, "woodie": .25, "classic": .20,
    "fibonacci": .15, "demark": .05,
}
_SHORT_VOLUME = {
    "vrsi14": .25, "rv15": .22, "rv30": .18, "vmacd26": .15,
    "sm15": .10, "obv20": .10, "rv90": 0,
}

_MEDIUM_MA = {
    "ichimoku": .26, "ema100": .20, "sma100": .14, "ema50": .12,
    "sma50": .10, "bb20": .06, "ema30": .04, "sma30": .03,
    "keltner16": .02, "ema20": .01, "sma20": .01, "ema10": .005,
    "sma10": .005, "ema5": 0, "sma5": 0,
}
_MEDIUM_OSCILLATORS = {
    "macd26": .24, "mfi14": .20, "adx14": .19, "rsi14": .16,
    "trend": .05, "ao534": .06, "aroon25": .04, "cci14": .02,
    "stochrsi14": .02, "so14": .01, "wr14": .005, "mtm6": .005,
}
_MEDIUM_VOLUME = {
    "obv20": .32, "rv90": .26, "sm15": .20, "rv30": .10,
    "vmacd26": .06, "vrsi14": .04, "rv15": .02,
}
_MEDIUM_SUPPORT = {
    "fibonacci": .35, "classic": .25, "woodie": .20,
    "camarilla": .12, "demark": .08,
}

FUND_SCORING_PROFILES = {
    "short": {
        "profile": "rahavard_four_group_short_term_v1",
        "family_weights": {
            "oscillators": .40, "moving_averages": .30,
            "support_resistance": .20, "volume": .10,
        },
        "indicator_weights": {
            "oscillators": _SHORT_OSCILLATORS,
            "moving_averages": _SHORT_MA,
            "support_resistance": _SHORT_SUPPORT,
            "volume": _SHORT_VOLUME,
        },
    },
    "medium": {
        "profile": "rahavard_four_group_medium_term_v1",
        "family_weights": {
            "moving_averages": .45, "oscillators": .30,
            "volume": .15, "support_resistance": .10,
        },
        "indicator_weights": {
            "moving_averages": _MEDIUM_MA,
            "oscillators": _MEDIUM_OSCILLATORS,
            "volume": _MEDIUM_VOLUME,
            "support_resistance": _MEDIUM_SUPPORT,
        },
    },
}

DASHBOARD_SCORING_PROFILES = {
    "short": {
        "profile": "dashboard_three_group_short_term_v1",
        "family_weights": {
            "oscillators": .45, "moving_averages": .35,
            "support_resistance": .20,
        },
        "indicator_weights": {
            "oscillators": _SHORT_OSCILLATORS,
            "moving_averages": _SHORT_MA,
            "support_resistance": _SHORT_SUPPORT,
        },
    },
    "medium": {
        "profile": "dashboard_three_group_medium_term_v1",
        "family_weights": {
            "moving_averages": .45, "oscillators": .40,
            "support_resistance": .15,
        },
        "indicator_weights": {
            "moving_averages": _MEDIUM_MA,
            "oscillators": _MEDIUM_OSCILLATORS,
            "support_resistance": _MEDIUM_SUPPORT,
        },
    },
}


def normalize_horizon(value: str | None) -> str:
    """Map the public query parameter to a supported investment horizon."""
    value = str(value or "").strip().casefold()
    return value if value in HORIZON_LABELS else DEFAULT_HORIZON


def horizon_label(value: str | None) -> str:
    return HORIZON_LABELS[normalize_horizon(value)]
