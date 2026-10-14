import unittest
import tempfile
from datetime import date, timedelta
from pathlib import Path

from app.db import Database
from app.fund_scoring import FAMILY_WEIGHTS, FAMILY_WEIGHTS_BY_TYPE, score_fund_model
from app.analysis import DASHBOARD_SCORE_WEIGHTS, analyze_rahavard


def indicator(name, values, signal=None):
    row = {"short_name_en": name,
           "value": [{"name": key, "value": value} for key, value in values.items()]}
    if signal:
        row["signal"] = signal
    return row


class FundScoringTests(unittest.TestCase):
    def test_uses_the_seven_configured_family_weights(self):
        self.assertEqual(sum(FAMILY_WEIGHTS.values()), 1.0)
        result = score_fund_model(
            {"moving_averages": [indicator("EMA50", {"Distance": 0.03})]}, 103)
        self.assertEqual(result["score_weights"], {
            "trend_structure": 30, "momentum": 20, "volume_confirmation": 15,
            "support_resistance": 10, "relative_strength": 10,
            "entry_quality": 10, "nav_pricing": 5,
        })
        trend = result["family_scores"]["trend_structure"]["score"]
        entry = result["family_scores"]["entry_quality"]["score"]
        self.assertAlmostEqual(result["technical_score"], (trend * 30 + entry * 10) / 40, places=1)
        self.assertEqual(result["available_family_weight_pct"], 40)

    def test_rahavard_analysis_uses_model_and_dashboard_weights_stay_separate(self):
        result = analyze_rahavard("TEST", {
            "moving_averages": [indicator("EMA50", {"Distance": 0.02})],
        }, current_price=102, model_context={"category_id": "257"})
        self.assertEqual(result["score_method"], "fund_seven_family_initial_v1")
        self.assertEqual(result["score_origin"], "AliVest")
        self.assertEqual(result["score_weights"]["trend_structure"], 30)
        self.assertEqual(DASHBOARD_SCORE_WEIGHTS["moving_averages"], 0.40)

    def test_missing_families_are_reweighted_and_reported(self):
        result = score_fund_model(
            {"moving_averages": [indicator("EMA50", {"Distance": 0.03})]}, 103)
        self.assertIsNotNone(result["technical_score"])
        self.assertEqual(result["family_scores"]["momentum"]["score"], None)
        self.assertEqual(result["family_scores"]["trend_structure"]["coverage_pct"], 15)
        self.assertEqual(result["family_scores"]["entry_quality"]["coverage_pct"], 20)
        self.assertEqual(result["available_family_weight_pct"], 40)
        self.assertEqual(result["data_coverage_pct"], 6.5)

    def test_unverified_vendor_formulas_are_not_counted(self):
        result = score_fund_model({
            "oscillators": [indicator("Trend", {}, "Bullish"), indicator("RSI(14)", {"RSI": 61})],
            "volumes": [indicator("SM(15)", {}, "HighVolume"), indicator("RV(30)", {"RV": 1.2})],
        }, 100)
        momentum = result["family_scores"]["momentum"]
        volume = result["family_scores"]["volume_confirmation"]
        self.assertNotIn("trend", [item["key"] for item in momentum["indicators"]])
        self.assertIn("trend", momentum["missing_indicators"])
        self.assertEqual(volume["unverified_indicators"], ["vmacd26", "vrsi14"])
        self.assertFalse({"sm15", "vmacd26", "vrsi14"} & {item["key"] for item in volume["indicators"]})
        self.assertTrue(any(row["status"] == "formula_unverified" for row in result["missing_data"]))

    def test_high_relative_volume_needs_a_price_direction_to_score(self):
        groups = {"volumes": [
            indicator("RV(30)", {"RV": 1.4}, "HighVolume"),
            indicator("VRSI(14)", {"VRSI": 65}),
            indicator("VMACD(12,26)", {"VMACD": 0.4, "Signal": 0.2}),
        ]}
        without_return = score_fund_model(groups, 100)
        with_return = score_fund_model(groups, 100, {"daily_return_pct": 1.0})
        self.assertNotIn("rv30", [item["key"] for item in without_return["family_scores"]["volume_confirmation"]["indicators"]])
        self.assertIn("rv30", [item["key"] for item in with_return["family_scores"]["volume_confirmation"]["indicators"]])

    def test_nav_score_requires_a_fresh_observation(self):
        groups = {"moving_averages": [indicator("EMA50", {"Distance": 0})]}
        fresh = score_fund_model(groups, 102, {
            "category_id": "301", "nav": 100, "nav_timestamp": "1405-07-18T12:00:00",
            "price_timestamp": "1405-07-18T13:00:00",
        })
        stale = score_fund_model(groups, 102, {
            "category_id": "301", "nav": 100, "nav_timestamp": "1405-06-01T12:00:00",
            "price_timestamp": "1405-07-18T13:00:00",
        })
        self.assertIsNotNone(fresh["family_scores"]["nav_pricing"]["score"])
        self.assertIsNone(stale["family_scores"]["nav_pricing"]["score"])
        self.assertEqual(stale["family_scores"]["nav_pricing"]["coverage_pct"], 0)

    def test_relative_strength_and_risk_use_supplied_history(self):
        fund_history = [{"close": 100 + index} for index in range(121)]
        benchmark_history = [{"close": 100 + index * 0.5} for index in range(121)]
        result = score_fund_model({}, 220, {
            "category_id": "257", "fund_history": fund_history,
            "benchmark_history": benchmark_history,
            "benchmark_symbol": "TEPIX", "peer_percentile": 75,
        })
        relative = result["family_scores"]["relative_strength"]
        self.assertIsNotNone(relative["score"])
        self.assertIsNotNone(relative["excess_60d_pct"])
        self.assertIsNotNone(relative["excess_120d_pct"])
        self.assertIsNotNone(result["risk_rank"]["score"])
        self.assertTrue(result["risk_rank"]["type_adjusted"] is True)

    def test_fixed_income_uses_a_liquidity_and_nav_focused_profile(self):
        result = score_fund_model({
            "volumes": [indicator("RV(30)", {"RV": 1.3}, "HighVolume")],
        }, 100, {"category_id": "255", "daily_return_pct": 0.4,
                "liquidity_percentile": 80})
        self.assertEqual(sum(FAMILY_WEIGHTS_BY_TYPE["fixed_income"].values()), 1.0)
        self.assertEqual(result["fund_type"], "fixed_income")
        self.assertEqual(result["model_profile"], "fixed_income_specialized_v1")
        self.assertEqual(result["score_weights"]["nav_pricing"], 20)
        volume_keys = {item["key"] for item in result["family_scores"]["volume_confirmation"]["indicators"]}
        self.assertIn("liquidity_peer", volume_keys)

    def test_score_history_reports_only_when_full_lookback_exists(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Database(Path(folder) / "scores.sqlite")
            database.init()
            first = date(2026, 1, 1)
            for index in range(21):
                observed = (first + timedelta(days=index)).isoformat()
                database.save_fund_score_snapshot("fund-1", observed, float(index), 75, "model-v1")
            current_date = (first + timedelta(days=20)).isoformat()
            sessions = [(first + timedelta(days=index)).isoformat() for index in range(21)]
            self.assertEqual(database.fund_score_changes("fund-1", current_date, "model-v1", sessions),
                             {"score_change_5d": 5.0, "score_change_20d": 20.0})
            self.assertEqual(database.fund_score_changes("fund-2", current_date, "model-v1", sessions),
                             {"score_change_5d": None, "score_change_20d": None})


if __name__ == "__main__":
    unittest.main()
