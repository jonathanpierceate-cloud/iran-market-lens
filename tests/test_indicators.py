import json
import unittest
from datetime import datetime, timedelta, timezone

from app.analysis import analyze
from app.indicators import compute_indicators, pivot_points


def rising_bars(count=240):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(count):
        close = 100 + i * 0.65 + (i % 7) * 0.14
        rows.append({"timestamp": (start + timedelta(days=i)).isoformat(),
                     "open": close - 0.4, "high": close + 1.2,
                     "low": close - 1.1, "close": close,
                     "volume": 1000 + (i % 11) * 90})
    return rows


class IndicatorTests(unittest.TestCase):
    def test_classic_and_fibonacci_pivots(self):
        result = pivot_points(110, 90, 100, 95)
        self.assertEqual(result["Classic"]["pivot"], 100)
        self.assertEqual(result["Classic"]["R1"], 110)
        self.assertEqual(result["Classic"]["S1"], 90)
        self.assertAlmostEqual(result["Fibonacci"]["R1"], 107.64)
        self.assertIsNone(result["DeMark"]["R2"])

    def test_requested_periods_and_explanations_are_present(self):
        result = compute_indicators(rising_bars())
        indicators = result["indicators"]
        for name in ["RSI(14)", "MFI(14)", "CCI(14)", "WR(14)", "SO(14)",
                     "ARRON(25)", "ADX(14)", "AO(5,34)", "StochRSI(14)",
                     "MACD(12,26,9)", "MTM(6)", "Ichimoku(9,26,52,26)",
                     "KELTNER(16)", "BB(20)", "EMA(200)", "SMA(200)",
                     "RV(90)", "RV(30)", "RV(15)", "VRSI(14)",
                     "VMACD(12,26)", "OBV(20)", "SM(15)"]:
            self.assertIn(name, indicators)
            self.assertIn("formula", indicators[name])
            self.assertIn("parameters", indicators[name])
        self.assertEqual(indicators["SM(15)"]["value"], None)
        self.assertEqual(indicators["CCI(14)"]["parameters"]["period"], 14)
        self.assertIsNotNone(indicators["RSI(14)"]["value"])
        self.assertIsNotNone(indicators["EMA(200)"]["value"])

    def test_missing_volume_stays_unavailable(self):
        bars = rising_bars(40)
        for bar in bars:
            bar["volume"] = None
        result = compute_indicators(bars)
        self.assertIsNone(result["indicators"]["MFI(14)"]["value"])
        self.assertIsNone(result["indicators"]["VRSI(14)"]["value"])
        self.assertIsNone(result["indicators"]["VMACD(12,26)"]["value"])
        self.assertFalse(result["volume_analysis"]["available"])

    def test_analysis_is_explainable_and_json_safe(self):
        result = analyze("TEST", rising_bars())
        self.assertGreaterEqual(result["technical_score"], 0)
        self.assertLessEqual(result["technical_score"], 100)
        self.assertTrue(result["factors"])
        self.assertTrue(result["explanation"])
        self.assertIn("احتمال موفقیت نیست", result["confidence_basis"])
        json.dumps(result, allow_nan=False)

    def test_empty_series_has_no_score_inputs(self):
        result = compute_indicators([])
        self.assertIsNone(result["latest"])
        self.assertEqual(result["data_status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
