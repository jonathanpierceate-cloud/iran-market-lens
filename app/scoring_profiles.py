"""Workbook scoring profiles for funds (4.3.1) and dashboard assets (4.2)."""
from __future__ import annotations

HORIZON_LABELS = {"short": "\u06a9\u0648\u062a\u0627\u0647\u200c\u0645\u062f\u062a", "long": "\u0645\u06cc\u0627\u0646\u200c\u0645\u062f\u062a"}
DEFAULT_HORIZON = "long"


def _normalize(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values())
    return {key: value / total for key, value in weights.items()} if total else {}


# Workbook 4.3.1. EMA/SMA pairs are each one combined indicator.
_FUND_FAMILIES = {
    "moving_averages": {
        "medium": {"Ichimoku Cloud(9,26,52,26)": .24, "EMA/SMA(50)": .17, "EMA/SMA(100)": .17, "BB(20)": .10, "KELTNER(16)": .08, "EMA/SMA(20)": .12, "EMA/SMA(30)": .06, "EMA/SMA(10)": .04, "EMA/SMA(5)": .02},
        "short": {"Ichimoku Cloud(9,26,52,26)": .12, "EMA/SMA(50)": .08, "EMA/SMA(100)": .04, "BB(20)": .18, "KELTNER(16)": .10, "EMA/SMA(20)": .14, "EMA/SMA(30)": .06, "EMA/SMA(10)": .14, "EMA/SMA(5)": .14},
    },
    "trend_momentum": {
        "medium": {"MACD(12,26,9)": .30, "ADX(14)": .30, "AROON(25)": .25, "AO(5,34)": .15},
        "short": {"MACD(12,26,9)": .30, "ADX(14)": .25, "AROON(25)": .25, "AO(5,34)": .20},
    },
    "support_resistance": {
        "medium": {"PivotPoint Fibonacci(30)": .20, "PivotPoint Classic(30)": .20, "PivotPoint Camarilla(30)": .20, "PivotPoint Woodie(30)": .20, "PivotPoint DeMark(30)": .20},
        "short": {"PivotPoint Fibonacci(30)": .20, "PivotPoint Classic(30)": .20, "PivotPoint Camarilla(30)": .20, "PivotPoint Woodie(30)": .20, "PivotPoint DeMark(30)": .20},
    },
    "oscillators": {
        "medium": {"RSI(14)": .26, "MFI(14)": .22, "CCI(14)": .16, "SO(14) %K": .20, "StochRSI(14) %K": .08, "MTM(6)": .08},
        "short": {"RSI(14)": .22, "MFI(14)": .16, "CCI(14)": .12, "SO(14) %K": .28, "StochRSI(14) %K": .12, "MTM(6)": .10},
    },
    "volume_flow": {
        "medium": {"RV(90)": .17, "RV(30)": .13, "RV(15)": .09, "VRSI(14)": .17, "VMACD(26)": .21, "OBV(20)": .23},
        "short": {"RV(90)": .095, "RV(30)": .145, "RV(15)": .19, "VRSI(14)": .20, "VMACD(26)": .18, "OBV(20)": .19},
    },
}

# Workbook 4.2 dashboard model has four scoring groups and no volume group.
_DASHBOARD_FAMILIES = {key: _FUND_FAMILIES[key] for key in ("moving_averages", "trend_momentum", "support_resistance", "oscillators")}
_FUND_MEDIUM_WEIGHTS = {"moving_averages": .35, "trend_momentum": .30, "support_resistance": .08, "oscillators": .12, "volume_flow": .15}
_FUND_SHORT_WEIGHTS = {"moving_averages": .18, "trend_momentum": .25, "support_resistance": .12, "oscillators": .25, "volume_flow": .20}
_DASHBOARD_MEDIUM_WEIGHTS = {"moving_averages": .40, "trend_momentum": .35, "support_resistance": .10, "oscillators": .15}
_DASHBOARD_SHORT_WEIGHTS = {"moving_averages": .20, "trend_momentum": .30, "support_resistance": .15, "oscillators": .35}


def _profile(horizon: str, family_weights: dict[str, float], families: dict[str, dict[str, dict[str, float]]], version: str) -> dict[str, object]:
    indicator_horizon = "short" if horizon == "short" else "medium"
    return {"profile": f"{version}_{indicator_horizon}_term", "family_weights": family_weights,
            "indicator_weights": {family: _normalize(weights[indicator_horizon]) for family, weights in families.items()}}


def _profiles(version: str, families: dict[str, dict[str, dict[str, float]]], short_weights: dict[str, float], medium_weights: dict[str, float]) -> dict[str, dict[str, object]]:
    return {"short": _profile("short", short_weights, families, version),
            "long": _profile("medium", medium_weights, families, version)}


FUND_SCORING_PROFILES = _profiles("update_4_3_1", _FUND_FAMILIES, _FUND_SHORT_WEIGHTS, _FUND_MEDIUM_WEIGHTS)
DASHBOARD_SCORING_PROFILES = _profiles("update_4_2", _DASHBOARD_FAMILIES, _DASHBOARD_SHORT_WEIGHTS, _DASHBOARD_MEDIUM_WEIGHTS)


def normalize_horizon(value: str | None) -> str:
    """Map public selector values to the supported short/medium horizons."""
    value = str(value or "").strip().casefold()
    if value == "medium":
        return "long"
    return value if value in HORIZON_LABELS else DEFAULT_HORIZON


def horizon_label(value: str | None) -> str:
    return HORIZON_LABELS[normalize_horizon(value)]