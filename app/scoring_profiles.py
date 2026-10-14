"""Workbook-defined short- and medium-term technical scoring profiles."""
from __future__ import annotations

HORIZON_LABELS = {"short": "کوتاه‌مدت", "long": "میان‌مدت"}
DEFAULT_HORIZON = "long"


def _within_group(raw_weights: dict[str, float]) -> dict[str, float]:
    """Normalize the workbook's indicator weights within their named group."""
    total = sum(raw_weights.values())
    return {name: weight / total for name, weight in raw_weights.items()} if total else {}


# In the short-term Excel columns the indicator percentages add up to their
# group's weight (15%, 25%, 25%, 35%); normalize those rows within each group.
# Medium-term percentages already add up to 100% inside each group.
_SHORT_FAMILIES = {
    "moving_averages": {
        "Ichimoku Cloud(9,26,52,26)": .009, "EMA(50)": .003, "SMA(50)": .003,
        "EMA(100)": .0015, "SMA(100)": .0015, "BB(20)": .027,
        "KELTNER(16)": .012, "EMA(20)": .015, "SMA(20)": .0105,
        "EMA(30)": .0045, "SMA(30)": .0045, "EMA(10)": .0165,
        "SMA(10)": .012, "EMA(5)": .018, "SMA(5)": .012,
    },
    "trend_momentum": {
        "MACD(26)": .075, "ADX(14)": .05, "AROON(25)": .05, "AO(5,34)": .075,
    },
    "support_resistance": {
        "PivotPoint Fibonacci(30)": .0375, "PivotPoint Classic(30)": .0625,
        "PivotPoint Camarilla(30)": .075, "PivotPoint Woodie(30)": .05,
        "PivotPoint DeMark(30)": .025,
    },
    "oscillators": {
        "RSI(14)": .077, "MFI(14)": .0525, "CCI(14)": .035,
        "SO(14)": .07, "StochRSI(14)": .063, "WR(14)": .028,
        "MTM(6)": .0245,
    },
}

_MEDIUM_FAMILIES = {
    "moving_averages": {
        "Ichimoku Cloud(9,26,52,26)": .18, "EMA(50)": .10, "SMA(50)": .09,
        "EMA(100)": .10, "SMA(100)": .08, "BB(20)": .08,
        "KELTNER(16)": .07, "EMA(20)": .07, "SMA(20)": .06,
        "EMA(30)": .06, "SMA(30)": .05, "EMA(10)": .02,
        "SMA(10)": .015, "EMA(5)": .015, "SMA(5)": .01,
    },
    "trend_momentum": {
        "MACD(26)": .35, "ADX(14)": .30, "AROON(25)": .20, "AO(5,34)": .15,
    },
    "support_resistance": {
        "PivotPoint Fibonacci(30)": .30, "PivotPoint Classic(30)": .25,
        "PivotPoint Camarilla(30)": .20, "PivotPoint Woodie(30)": .15,
        "PivotPoint DeMark(30)": .10,
    },
    "oscillators": {
        "RSI(14)": .28, "MFI(14)": .22, "CCI(14)": .15,
        "SO(14)": .12, "StochRSI(14)": .10, "WR(14)": .08,
        "MTM(6)": .05,
    },
}


def _profile(family_weights: dict[str, float], raw_indicators: dict[str, dict[str, float]],
             name: str) -> dict[str, object]:
    return {
        "profile": name,
        "family_weights": family_weights,
        "indicator_weights": {
            family: _within_group(weights) for family, weights in raw_indicators.items()
        },
    }


_SHORT_PROFILE = _profile(
    {"moving_averages": .15, "trend_momentum": .25,
     "support_resistance": .25, "oscillators": .35},
    _SHORT_FAMILIES, "excel_comprehensive_short_term",
)
_MEDIUM_PROFILE = _profile(
    {"moving_averages": .35, "trend_momentum": .30,
     "support_resistance": .20, "oscillators": .15},
    _MEDIUM_FAMILIES, "excel_comprehensive_medium_term",
)

# Both screens use the same workbook-defined scoring model.
FUND_SCORING_PROFILES = {"short": _SHORT_PROFILE, "long": _MEDIUM_PROFILE}
DASHBOARD_SCORING_PROFILES = FUND_SCORING_PROFILES


def normalize_horizon(value: str | None) -> str:
    """Map the public selector value to a supported investment horizon."""
    value = str(value or "").strip().casefold()
    if value == "medium":
        return "long"
    return value if value in HORIZON_LABELS else DEFAULT_HORIZON


def horizon_label(value: str | None) -> str:
    return HORIZON_LABELS[normalize_horizon(value)]
