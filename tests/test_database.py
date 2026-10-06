import tempfile
import unittest
import hashlib
import json
from pathlib import Path

from app.db import Database


class DatabaseTests(unittest.TestCase):
    def test_funds_with_same_ticker_keep_distinct_keys(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "market.db")
            database.init()
            database.save_funds([
                {"symbol": "DUP", "name": "Fund One", "registration_no": "1001",
                 "category_id": "6", "nav": 100, "raw": {"groupId": 6, "insCode": "a"}},
                {"symbol": "DUP", "name": "Fund Two", "registration_no": "1002",
                 "category_id": "7", "nav": 200, "raw": {"groupId": 7, "insCode": "b"}},
            ], "FIPIRAN", "https://fipiran.ir/mf/list")

            items = database.funds()
            self.assertEqual(len(items), 2)
            self.assertEqual(len({item["fund_key"] for item in items}), 2)
            self.assertTrue(database.get_fund("DUP")["ambiguous"])
            for item in items:
                self.assertEqual(database.get_fund(item["fund_key"])["symbol"], "DUP")

    def test_legacy_fund_keys_migrate_and_keep_local_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "market.db")
            database.init()
            fund = {"symbol": "DUP", "name": "Fund One", "registration_no": "1001",
                    "category_id": "6", "nav": 100, "raw": {"groupId": 0, "insCode": "a"}}
            database.save_funds([fund], "FIPIRAN", "https://fipiran.ir/mf/list")
            target_key = database.funds()[0]["fund_key"]
            suffix = hashlib.sha1("DUP|Fund One".encode("utf-8")).hexdigest()[:10]
            legacy_key = f"1001:6:{suffix}"
            with database.connect() as conn:
                current = dict(conn.execute("SELECT * FROM funds WHERE fund_key=?", (target_key,)).fetchone())
                current["fund_key"] = legacy_key
                columns = list(current)
                conn.execute(f"INSERT INTO funds({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                             [current[column] for column in columns])
                conn.execute("INSERT INTO fund_portfolios(symbol,data_timestamp,asset_type,percentage,source) VALUES(?,?,?,?,?)",
                             ("DUP", "2026-10-01", "stock", 95, "FIPIRAN"))
                conn.execute("INSERT INTO assets(symbol,name,asset_type,currency,unit,source) VALUES(?,?,?,?,?,?)",
                             (legacy_key, "Fund One", "fund", "IRR", "unit", "TSETMC"))
                conn.execute("INSERT INTO prices(asset_symbol,data_timestamp,fetched_at,close,source) VALUES(?,?,?,?,?)",
                             (legacy_key, "2026-10-01", "2026-10-01", 101, "TSETMC"))
                database._canonicalize_fund_keys(conn)

            self.assertEqual(len(database.funds()), 1)
            self.assertEqual(database.history(target_key)[-1]["close"], 101)
            with database.connect() as conn:
                portfolio = conn.execute("SELECT percentage FROM fund_portfolios WHERE symbol=?", (target_key,)).fetchone()
                self.assertEqual(portfolio["percentage"], 95)
                self.assertIsNone(conn.execute("SELECT 1 FROM funds WHERE fund_key=?", (legacy_key,)).fetchone())
                conn.execute("INSERT INTO assets(symbol,name,asset_type,currency,unit,source) VALUES(?,?,?,?,?,?)",
                             (legacy_key, "Fund One", "fund", "IRR", "unit", "TSETMC"))
                conn.execute("INSERT INTO prices(asset_symbol,data_timestamp,fetched_at,close,source) VALUES(?,?,?,?,?)",
                             (legacy_key, "2026-10-02", "2026-10-02", 102, "TSETMC"))
                database._canonicalize_fund_keys(conn)
            self.assertEqual(database.history(target_key)[-1]["close"], 102)


if __name__ == "__main__":
    unittest.main()
