from __future__ import annotations

import json
import hashlib
import math
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from .config import DATABASE_PATH


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path=DATABASE_PATH):
        self.path = str(path)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS assets (
          id INTEGER PRIMARY KEY, symbol TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
          asset_type TEXT NOT NULL, currency TEXT, unit TEXT, source TEXT,
          source_url TEXT, updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS prices (
          id INTEGER PRIMARY KEY, asset_symbol TEXT NOT NULL, data_timestamp TEXT NOT NULL,
          fetched_at TEXT NOT NULL, open REAL, high REAL, low REAL, close REAL NOT NULL,
          volume REAL, source TEXT NOT NULL, source_url TEXT,
          UNIQUE(asset_symbol, data_timestamp, source),
          FOREIGN KEY(asset_symbol) REFERENCES assets(symbol) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS ix_prices_asset_time ON prices(asset_symbol, data_timestamp);
        CREATE TABLE IF NOT EXISTS historical_prices (
          id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, data_timestamp TEXT NOT NULL,
          open REAL, high REAL, low REAL, close REAL, volume REAL, source TEXT NOT NULL,
          UNIQUE(symbol, data_timestamp, source)
        );
        CREATE TABLE IF NOT EXISTS funds (
          fund_key TEXT PRIMARY KEY, symbol TEXT NOT NULL, registration_no TEXT, name TEXT NOT NULL,
          category TEXT, category_id TEXT, manager TEXT, custodian TEXT,
          market_maker TEXT, start_date TEXT, aum REAL, nav REAL, market_price REAL,
          volume REAL, value REAL, trades INTEGER, units REAL, investors INTEGER,
          daily_return REAL, weekly_return REAL, monthly_return REAL, three_month_return REAL,
          six_month_return REAL, one_year_return REAL, volatility REAL, liquidity_score REAL,
          source TEXT NOT NULL, source_url TEXT, data_timestamp TEXT, raw_json TEXT
        );
        CREATE TABLE IF NOT EXISTS fund_nav (
          id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, data_timestamp TEXT NOT NULL,
          issue_nav REAL, cancel_nav REAL, statistical_nav REAL, source TEXT NOT NULL,
          UNIQUE(symbol, data_timestamp, source)
        );
        CREATE TABLE IF NOT EXISTS fund_indicator_snapshots (
          fund_key TEXT PRIMARY KEY, data_timestamp TEXT, fetched_at TEXT NOT NULL,
          source TEXT NOT NULL, payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS fund_portfolios (
          id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, data_timestamp TEXT NOT NULL,
          asset_type TEXT, percentage REAL, source TEXT NOT NULL,
          UNIQUE(symbol, data_timestamp, asset_type, source)
        );
        CREATE TABLE IF NOT EXISTS fund_holdings (
          id INTEGER PRIMARY KEY, fund_symbol TEXT NOT NULL, holding_symbol TEXT,
          holding_name TEXT NOT NULL, weight REAL, value REAL, data_timestamp TEXT,
          source TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS fund_managers (
          id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, registration_no TEXT,
          source TEXT, raw_json TEXT
        );
        CREATE TABLE IF NOT EXISTS technical_indicators (
          id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, data_timestamp TEXT NOT NULL,
          indicator TEXT NOT NULL, value REAL, previous_value REAL, signal TEXT,
          interpretation TEXT, parameters TEXT, source TEXT,
          UNIQUE(symbol, data_timestamp, indicator)
        );
        CREATE TABLE IF NOT EXISTS technical_signals (
          id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, data_timestamp TEXT NOT NULL,
          signal TEXT NOT NULL, score REAL, explanation_json TEXT, source TEXT
        );
        CREATE TABLE IF NOT EXISTS support_resistance (
          id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, data_timestamp TEXT NOT NULL,
          kind TEXT NOT NULL, low REAL, high REAL, strength TEXT, method TEXT
        );
        CREATE TABLE IF NOT EXISTS pivot_points (
          id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, data_timestamp TEXT NOT NULL,
          method TEXT NOT NULL, levels_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS news (
          id INTEGER PRIMARY KEY, title TEXT NOT NULL, url TEXT UNIQUE, source TEXT,
          published_at TEXT, category TEXT, importance TEXT, sentiment TEXT,
          impact TEXT, related_asset TEXT, summary TEXT, content_hash TEXT UNIQUE
        );
        CREATE TABLE IF NOT EXISTS news_events (
          id INTEGER PRIMARY KEY, event_key TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
          category TEXT, importance TEXT, sentiment TEXT, impact TEXT,
          related_asset TEXT, published_at TEXT
        );
        CREATE TABLE IF NOT EXISTS news_sources (
          id INTEGER PRIMARY KEY, event_id INTEGER, news_id INTEGER, source_name TEXT,
          url TEXT, published_at TEXT, UNIQUE(event_id,url)
        );
        CREATE TABLE IF NOT EXISTS market_data (
          id INTEGER PRIMARY KEY, key TEXT NOT NULL, value_json TEXT NOT NULL,
          source TEXT, data_timestamp TEXT, fetched_at TEXT
        );
        CREATE TABLE IF NOT EXISTS alerts (
          id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, condition TEXT NOT NULL,
          threshold REAL, enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
          triggered_at TEXT, message TEXT
        );
        CREATE TABLE IF NOT EXISTS watchlist_items (
          fund_key TEXT PRIMARY KEY, break_even_price REAL, units REAL,
          added_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS data_sources (
          name TEXT PRIMARY KEY, label TEXT NOT NULL, status TEXT NOT NULL,
          source_url TEXT, last_sync TEXT, last_data_timestamp TEXT,
          error TEXT, latency_ms INTEGER
        );
        CREATE TABLE IF NOT EXISTS data_fetch_logs (
          id INTEGER PRIMARY KEY, source TEXT NOT NULL, started_at TEXT NOT NULL,
          finished_at TEXT, status TEXT NOT NULL, records INTEGER DEFAULT 0,
          message TEXT, latency_ms INTEGER
        );
        CREATE TABLE IF NOT EXISTS analysis_results (
          id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, data_timestamp TEXT NOT NULL,
          trend TEXT, short_trend TEXT, medium_trend TEXT, long_trend TEXT,
          score REAL, risk TEXT, signal TEXT, explanation_json TEXT, raw_json TEXT
        );
        CREATE TABLE IF NOT EXISTS settings (
          key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY, name TEXT, created_at TEXT NOT NULL
        );
        """
        with self.connect() as conn:
            conn.executescript(schema)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(funds)").fetchall()}
            if "fund_key" not in columns:
                old_rows = [dict(row) for row in conn.execute("SELECT * FROM funds").fetchall()]
                conn.execute("ALTER TABLE funds RENAME TO funds_legacy")
                conn.execute("""CREATE TABLE funds (
                  fund_key TEXT PRIMARY KEY, symbol TEXT NOT NULL, registration_no TEXT, name TEXT NOT NULL,
                  category TEXT, category_id TEXT, manager TEXT, custodian TEXT, market_maker TEXT, start_date TEXT,
                  aum REAL, nav REAL, market_price REAL, volume REAL, value REAL, trades INTEGER, units REAL, investors INTEGER,
                  daily_return REAL, weekly_return REAL, monthly_return REAL, three_month_return REAL,
                  six_month_return REAL, one_year_return REAL, volatility REAL, liquidity_score REAL,
                  source TEXT NOT NULL, source_url TEXT, data_timestamp TEXT, raw_json TEXT
                )""")
                columns_to_copy = ["fund_key", "symbol", "registration_no", "name", "category", "category_id", "manager", "custodian",
                    "market_maker", "start_date", "aum", "nav", "market_price", "volume", "value", "trades", "units", "investors",
                    "daily_return", "weekly_return", "monthly_return", "three_month_return", "six_month_return", "one_year_return",
                    "volatility", "liquidity_score", "source", "source_url", "data_timestamp", "raw_json"]
                insert_sql = f"INSERT OR IGNORE INTO funds({','.join(columns_to_copy)}) VALUES({','.join('?' for _ in columns_to_copy)})"
                for row in old_rows:
                    row["fund_key"] = self.fund_key(row)
                    conn.execute(insert_sql, [row.get(column) for column in columns_to_copy])
                conn.execute("CREATE INDEX IF NOT EXISTS ix_funds_symbol ON funds(symbol)")
            conn.execute("CREATE INDEX IF NOT EXISTS ix_funds_symbol ON funds(symbol)")
            self._canonicalize_fund_keys(conn)
            conn.execute("UPDATE funds SET market_price=NULL,volume=NULL,value=NULL,trades=NULL WHERE market_price<=0")
            conn.execute("""UPDATE funds SET market_price=(SELECT close FROM prices WHERE asset_symbol=funds.fund_key AND close>0
                ORDER BY data_timestamp DESC LIMIT 1),
                volume=COALESCE(volume,(SELECT volume FROM prices WHERE asset_symbol=funds.fund_key AND close>0
                ORDER BY data_timestamp DESC LIMIT 1))
                WHERE market_price IS NULL AND EXISTS(SELECT 1 FROM prices WHERE asset_symbol=funds.fund_key AND close>0)""")
            for row in [
                ("GOLD", "طلای جهانی (قرارداد آتی COMEX)", "commodity", "USD", "دلار/اونس تروا", "Yahoo Finance", "https://finance.yahoo.com/quote/GC=F/"),
                ("DXY", "شاخص دلار آمریکا", "index", "USD", "شاخص", "Yahoo Finance", "https://finance.yahoo.com/quote/DX-Y.NYB/"),
                ("USD_IR_FREE", "دلار بازار آزاد ایران", "currency", "IRR", "تومان", "TGJU", "https://www.tgju.org/profile/price_dollar_rl"),
            ]:
                conn.execute(
                    "INSERT OR IGNORE INTO assets(symbol,name,asset_type,currency,unit,source,source_url) VALUES(?,?,?,?,?,?,?)",
                    row,
                )

    @staticmethod
    def _move_watchlist_fund_key(conn: sqlite3.Connection, old_key: str, new_key: str) -> None:
        source = conn.execute("SELECT * FROM watchlist_items WHERE fund_key=?", (old_key,)).fetchone()
        if source is None or old_key == new_key:
            return
        target = conn.execute("SELECT * FROM watchlist_items WHERE fund_key=?", (new_key,)).fetchone()
        if target is None:
            conn.execute("UPDATE watchlist_items SET fund_key=? WHERE fund_key=?", (new_key, old_key))
            return
        conn.execute("""UPDATE watchlist_items SET
            break_even_price=COALESCE(break_even_price,?), units=COALESCE(units,?),
            added_at=MIN(added_at,?), updated_at=MAX(updated_at,?) WHERE fund_key=?""",
            (source["break_even_price"], source["units"], source["added_at"], source["updated_at"], new_key))
        conn.execute("DELETE FROM watchlist_items WHERE fund_key=?", (old_key,))

    def _canonicalize_fund_keys(self, conn: sqlite3.Connection) -> None:
        """Re-key migrated fund rows from their preserved FIPIRAN identity fields."""
        rows = [dict(row) for row in conn.execute("SELECT * FROM funds ORDER BY data_timestamp DESC").fetchall()]
        for row in rows:
            old_key = row["fund_key"]
            canonical_key = self.fund_key(row)
            if old_key == canonical_key:
                continue
            target = conn.execute("SELECT fund_key FROM funds WHERE fund_key=?", (canonical_key,)).fetchone()
            if target:
                preserve = ["registration_no", "category", "category_id", "manager", "custodian", "market_maker",
                    "start_date", "aum", "nav", "market_price", "volume", "value", "trades", "units", "investors",
                    "daily_return", "weekly_return", "monthly_return", "three_month_return", "six_month_return",
                    "one_year_return", "volatility", "liquidity_score"]
                assignments = ",".join(f"{column}=COALESCE({column},?)" for column in preserve)
                conn.execute(f"UPDATE funds SET {assignments} WHERE fund_key=?",
                             [row.get(column) for column in preserve] + [canonical_key])
            else:
                conn.execute("UPDATE funds SET fund_key=? WHERE fund_key=?", (canonical_key, old_key))

            # Older releases keyed these histories by ticker. Since the legacy funds
            # table enforced one row per ticker, its preserved identity resolves them.
            for table, columns in [
                ("fund_nav", ["data_timestamp", "issue_nav", "cancel_nav", "statistical_nav", "source"]),
                ("fund_portfolios", ["data_timestamp", "asset_type", "percentage", "source"]),
            ]:
                for source_key in {old_key, row["symbol"]}:
                    if source_key == canonical_key:
                        continue
                    cols = ",".join(["symbol", *columns])
                    selected = ",".join(["?", *columns])
                    conn.execute(f"INSERT OR IGNORE INTO {table}({cols}) SELECT {selected} FROM {table} WHERE symbol=?",
                                 [canonical_key, source_key])
                    conn.execute(f"DELETE FROM {table} WHERE symbol=?", (source_key,))
            for source_key in {old_key, row["symbol"]}:
                if source_key == canonical_key or source_key in {"GOLD", "DXY", "USD_IR_FREE"}:
                    continue
                self._move_fund_asset_history(conn, source_key, canonical_key, row["name"])
            conn.execute("UPDATE fund_holdings SET fund_symbol=? WHERE fund_symbol IN (?,?)",
                         (canonical_key, old_key, row["symbol"]))
            self._move_watchlist_fund_key(conn, old_key, canonical_key)
            conn.execute("DELETE FROM funds WHERE fund_key=?", (old_key,))

        # Earlier migration runs may already have changed the fund row while leaving
        # an asset/history key with its former category segment. Match the stable
        # registration number and symbol/name hash to repair those orphaned keys.
        known_keys = {row["fund_key"] for row in conn.execute("SELECT fund_key FROM funds")}
        for asset in conn.execute("SELECT symbol,name FROM assets WHERE instr(symbol, ':')>0").fetchall():
            source_key = asset["symbol"]
            if source_key in known_keys:
                continue
            parts = source_key.split(":", 2)
            if len(parts) != 3:
                continue
            registration_no, _, suffix = parts
            candidates = [row for row in conn.execute("SELECT fund_key,name FROM funds WHERE registration_no=?", (registration_no,))
                          if row["fund_key"].endswith(f":{suffix}")]
            if len(candidates) == 1:
                self._move_fund_asset_history(conn, source_key, candidates[0]["fund_key"], candidates[0]["name"])

    @staticmethod
    def _move_fund_asset_history(conn: sqlite3.Connection, source_key: str, target_key: str, name: str) -> None:
        asset = conn.execute("SELECT * FROM assets WHERE symbol=?", (source_key,)).fetchone()
        if not asset:
            return
        conn.execute("INSERT OR IGNORE INTO assets(symbol,name,asset_type,currency,unit,source,source_url,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                     (target_key, name, "fund", asset["currency"], asset["unit"],
                      asset["source"], asset["source_url"], asset["updated_at"]))
        conn.execute("""INSERT OR IGNORE INTO prices(asset_symbol,data_timestamp,fetched_at,open,high,low,close,volume,source,source_url)
            SELECT ?,data_timestamp,fetched_at,open,high,low,close,volume,source,source_url FROM prices WHERE asset_symbol=?""",
                     (target_key, source_key))
        conn.execute("""INSERT OR IGNORE INTO historical_prices(symbol,data_timestamp,open,high,low,close,volume,source)
            SELECT ?,data_timestamp,open,high,low,close,volume,source FROM historical_prices WHERE symbol=?""",
                     (target_key, source_key))
        conn.execute("DELETE FROM prices WHERE asset_symbol=?", (source_key,))
        conn.execute("DELETE FROM historical_prices WHERE symbol=?", (source_key,))
        conn.execute("DELETE FROM assets WHERE symbol=?", (source_key,))

    @staticmethod
    def fund_key(fund: dict[str, Any]) -> str:
        raw = fund.get("raw") or fund.get("raw_json") or {}
        if isinstance(raw, str):
            try: raw = json.loads(raw)
            except json.JSONDecodeError: raw = {}
        symbol = str(fund.get("symbol") or "").strip()
        name = str(fund.get("name") or symbol).strip()
        reg_no = str(fund.get("registration_no") or raw.get("regNo") or "unknown")
        group_id = str(raw.get("groupId", fund.get("category_id") or "0"))
        suffix = hashlib.sha1(f"{symbol}|{name}".encode("utf-8")).hexdigest()[:10]
        return f"{reg_no}:{group_id}:{suffix}"

    def save_source(self, name: str, label: str, status: str, url: str | None = None,
                    last_data_timestamp: str | None = None, error: str | None = None,
                    latency_ms: int | None = None) -> None:
        with self.connect() as conn:
            conn.execute("""INSERT INTO data_sources(name,label,status,source_url,last_sync,last_data_timestamp,error,latency_ms)
                VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET label=excluded.label,status=excluded.status,
                source_url=excluded.source_url,last_sync=excluded.last_sync,last_data_timestamp=excluded.last_data_timestamp,
                error=excluded.error,latency_ms=excluded.latency_ms""",
                (name, label, status, url, utc_now(), last_data_timestamp, error, latency_ms))

    def log_fetch(self, source: str, started_at: str, status: str, records: int = 0,
                  message: str | None = None, latency_ms: int | None = None) -> None:
        with self.connect() as conn:
            conn.execute("INSERT INTO data_fetch_logs(source,started_at,finished_at,status,records,message,latency_ms) VALUES(?,?,?,?,?,?,?)",
                         (source, started_at, utc_now(), status, records, message, latency_ms))

    def save_bars(self, symbol: str, name: str, asset_type: str, currency: str, unit: str,
                  source: str, source_url: str, bars: list[dict[str, Any]]) -> None:
        if not bars:
            raise ValueError("منبع هیچ کندل معتبری برنگرداند")
        with self.connect() as conn:
            conn.execute("INSERT OR IGNORE INTO assets(symbol,name,asset_type,currency,unit,source,source_url) VALUES(?,?,?,?,?,?,?)",
                         (symbol, name, asset_type, currency, unit, source, source_url))
            conn.execute("UPDATE assets SET name=?,currency=?,unit=?,source=?,source_url=?,updated_at=? WHERE symbol=?",
                         (name, currency, unit, source, source_url, utc_now(), symbol))
            for bar in bars:
                ts = str(bar["timestamp"])
                values = (symbol, ts, bar.get("fetched_at") or utc_now(), bar.get("open"), bar.get("high"),
                          bar.get("low"), bar.get("close"), bar.get("volume"), source, source_url)
                conn.execute("""INSERT INTO prices(asset_symbol,data_timestamp,fetched_at,open,high,low,close,volume,source,source_url)
                    VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(asset_symbol,data_timestamp,source) DO UPDATE SET
                    fetched_at=excluded.fetched_at,open=excluded.open,high=excluded.high,low=excluded.low,
                    close=excluded.close,volume=excluded.volume,source_url=excluded.source_url""", values)
                conn.execute("INSERT OR IGNORE INTO historical_prices(symbol,data_timestamp,open,high,low,close,volume,source) VALUES(?,?,?,?,?,?,?,?)",
                             (symbol, ts, bar.get("open"), bar.get("high"), bar.get("low"), bar.get("close"), bar.get("volume"), source))

    def history(self, symbol: str, limit: int = 1000, source: str | None = None) -> list[dict[str, Any]]:
        where = "asset_symbol=?"
        params: list[Any] = [symbol]
        if source is not None:
            where += " AND source=?"
            params.append(source)
        params.append(max(1, min(limit, 10000)))
        with self.connect() as conn:
            rows = conn.execute(f"SELECT data_timestamp AS timestamp,open,high,low,close,volume,source,fetched_at FROM prices WHERE {where} ORDER BY data_timestamp DESC LIMIT ?",
                                params).fetchall()
        return [dict(row) for row in reversed(rows)]

    def save_funds(self, funds: list[dict[str, Any]], source: str, source_url: str) -> None:
        with self.connect() as conn:
            for fund in funds:
                symbol = str(fund.get("symbol") or fund.get("registration_no") or "").strip()
                if not symbol:
                    continue
                fund["symbol"] = symbol
                fund_key = fund.get("fund_key") or self.fund_key(fund)
                fund["fund_key"] = fund_key
                conn.execute("""INSERT INTO funds(fund_key,symbol,registration_no,name,category,category_id,manager,custodian,
                  market_maker,start_date,aum,nav,market_price,volume,value,trades,units,investors,source,source_url,
                  daily_return,weekly_return,monthly_return,three_month_return,six_month_return,one_year_return,volatility,liquidity_score,
                  data_timestamp,raw_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(fund_key) DO UPDATE SET symbol=excluded.symbol,registration_no=excluded.registration_no,name=excluded.name,
                  category=excluded.category,category_id=excluded.category_id,manager=excluded.manager,custodian=excluded.custodian,
                  market_maker=excluded.market_maker,start_date=excluded.start_date,aum=excluded.aum,nav=excluded.nav,
                  market_price=COALESCE(excluded.market_price,funds.market_price),volume=COALESCE(excluded.volume,funds.volume),
                  value=COALESCE(excluded.value,funds.value),trades=COALESCE(excluded.trades,funds.trades),units=excluded.units,
                  investors=excluded.investors,daily_return=excluded.daily_return,weekly_return=excluded.weekly_return,
                  monthly_return=excluded.monthly_return,three_month_return=excluded.three_month_return,
                  six_month_return=excluded.six_month_return,one_year_return=excluded.one_year_return,
                  volatility=excluded.volatility,liquidity_score=excluded.liquidity_score,source=excluded.source,source_url=excluded.source_url,
                  data_timestamp=excluded.data_timestamp,raw_json=excluded.raw_json""",
                    (fund_key, symbol, fund.get("registration_no"), fund.get("name") or symbol,
                     fund.get("category"), fund.get("category_id"), fund.get("manager"), fund.get("custodian"),
                     fund.get("market_maker"), fund.get("start_date"), fund.get("aum"), fund.get("nav"),
                     fund.get("market_price"), fund.get("volume"), fund.get("value"), fund.get("trades"),
                     fund.get("units"), fund.get("investors"), source, source_url,
                     fund.get("daily_return"), fund.get("weekly_return"), fund.get("monthly_return"),
                     fund.get("three_month_return"), fund.get("six_month_return"), fund.get("one_year_return"),
                     fund.get("volatility"), fund.get("liquidity_score"), fund.get("data_timestamp"),
                     json.dumps(fund.get("raw") or {}, ensure_ascii=False, default=str)))
                for nav in fund.get("nav_history", []):
                    if not nav.get("timestamp"):
                        continue
                    conn.execute("""INSERT OR IGNORE INTO fund_nav(symbol,data_timestamp,issue_nav,cancel_nav,statistical_nav,source)
                                  VALUES(?,?,?,?,?,?)""", (fund_key, nav.get("timestamp"), nav.get("issue_nav"),
                                  nav.get("cancel_nav"), nav.get("statistical_nav"), source))
                for item in fund.get("portfolio_history", []):
                    if not item.get("timestamp") or not item.get("asset_type"):
                        continue
                    conn.execute("""INSERT OR IGNORE INTO fund_portfolios(symbol,data_timestamp,asset_type,percentage,source)
                                  VALUES(?,?,?,?,?)""", (fund_key, item.get("timestamp"), item.get("asset_type"), item.get("percentage"), source))

    def funds(self, search: str = "", category: str = "", sort: str = "score",
              source: str | None = None) -> list[dict[str, Any]]:
        allowed = {"aum", "nav", "market_price", "volume", "value", "data_timestamp", "symbol", "name",
                   "daily_return", "weekly_return", "monthly_return", "three_month_return",
                   "six_month_return", "one_year_return", "volatility", "liquidity_score"}
        order = sort if sort in allowed else "data_timestamp"
        where, params = [], []
        if source:
            where.append("source=?"); params.append(source)
        if search:
            where.append("(symbol LIKE ? OR name LIKE ? OR fund_key LIKE ?)"); params.extend([f"%{search}%"] * 3)
        if category:
            where.append("category LIKE ?"); params.append(f"%{category}%")
        clause = " WHERE " + " AND ".join(where) if where else ""
        with self.connect() as conn:
            rows = conn.execute(f"SELECT * FROM funds{clause} ORDER BY {order} DESC LIMIT 2000", params).fetchall()
            out = []
            for row in rows:
                item = dict(row)
                if item.get("raw_json"):
                    try: item["raw"] = json.loads(item["raw_json"])
                    except json.JSONDecodeError: item["raw"] = {}
                item["nav_premium_pct"] = ((item["market_price"] / item["nav"] - 1) * 100) if item.get("market_price") and item.get("nav") else None
                out.append(item)
            return out

    def save_fund_indicator_snapshot(self, fund_key: str, payload: dict[str, Any],
                                     data_timestamp: str | None, source: str = "Rahavard365") -> None:
        with self.connect() as conn:
            conn.execute("""INSERT INTO fund_indicator_snapshots(fund_key,data_timestamp,fetched_at,source,payload_json)
                VALUES(?,?,?,?,?) ON CONFLICT(fund_key) DO UPDATE SET data_timestamp=excluded.data_timestamp,
                fetched_at=excluded.fetched_at,source=excluded.source,payload_json=excluded.payload_json""",
                (fund_key, data_timestamp, utc_now(), source,
                 json.dumps(payload, ensure_ascii=False, default=str)))

    def fund_indicator_snapshots(self, source: str = "Rahavard365") -> dict[str, dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT fund_key,data_timestamp,fetched_at,payload_json FROM fund_indicator_snapshots WHERE source=?",
                                (source,)).fetchall()
        result = {}
        for row in rows:
            try:
                payload = json.loads(row["payload_json"] or "{}")
            except json.JSONDecodeError:
                payload = {}
            result[row["fund_key"]] = {"data_timestamp": row["data_timestamp"],
                                       "fetched_at": row["fetched_at"], "data": payload}
        return result

    def fund_nav_history(self, symbol: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT data_timestamp AS timestamp,issue_nav,cancel_nav,statistical_nav,source FROM fund_nav WHERE symbol=? ORDER BY data_timestamp", (symbol,)).fetchall()
        return [dict(row) for row in rows]

    def get_fund(self, identifier: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM funds WHERE fund_key=?", (identifier,)).fetchone()
            if row is None:
                candidates = conn.execute("SELECT * FROM funds WHERE symbol=? ORDER BY data_timestamp DESC", (identifier,)).fetchall()
                if len(candidates) > 1:
                    return {"ambiguous": True, "matches": [dict(candidate) for candidate in candidates]}
                row = candidates[0] if candidates else None
        if row is None:
            return None
        item = dict(row)
        try: item["raw"] = json.loads(item.get("raw_json") or "{}")
        except json.JSONDecodeError: item["raw"] = {}
        item["nav_premium_pct"] = ((item["market_price"] / item["nav"] - 1) * 100) if item.get("market_price") and item.get("nav") else None
        return item

    def watchlist_items(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM watchlist_items ORDER BY added_at, fund_key").fetchall()
        return [dict(row) for row in rows]

    def add_watchlist_item(self, fund_key: str) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as conn:
            conn.execute("INSERT OR IGNORE INTO watchlist_items(fund_key,added_at,updated_at) VALUES(?,?,?)",
                         (fund_key, now, now))
            row = conn.execute("SELECT * FROM watchlist_items WHERE fund_key=?", (fund_key,)).fetchone()
        return dict(row)

    def update_watchlist_item(self, fund_key: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {"break_even_price", "units"}
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return None
        assignments = ",".join(f"{key}=?" for key in updates)
        values = list(updates.values()) + [utc_now(), fund_key]
        with self.connect() as conn:
            cursor = conn.execute(f"UPDATE watchlist_items SET {assignments},updated_at=? WHERE fund_key=?", values)
            if not cursor.rowcount:
                return None
            row = conn.execute("SELECT * FROM watchlist_items WHERE fund_key=?", (fund_key,)).fetchone()
        return dict(row)

    def remove_watchlist_item(self, fund_key: str) -> bool:
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM watchlist_items WHERE fund_key=?", (fund_key,))
        return bool(cursor.rowcount)

    def source_status(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM data_sources ORDER BY name").fetchall()]

    def fetch_logs(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM data_fetch_logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]

    def save_setting(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute("INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
                         (key, value, utc_now()))

    def get_settings(self) -> dict[str, str]:
        with self.connect() as conn:
            return {row["key"]: row["value"] for row in conn.execute("SELECT key,value FROM settings")}

    def insert_news(self, items: list[dict[str, Any]]) -> int:
        count = 0
        with self.connect() as conn:
            for item in items:
                cur = conn.execute("INSERT OR IGNORE INTO news(title,url,source,published_at,category,importance,sentiment,impact,related_asset,summary,content_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (item.get("title"), item.get("url"), item.get("source"), item.get("published_at"), item.get("category"),
                     item.get("importance"), item.get("sentiment"), item.get("impact"), item.get("related_asset"), item.get("summary"), item.get("content_hash")))
                news_row = None
                if item.get("content_hash"):
                    news_row = conn.execute("SELECT id FROM news WHERE content_hash=?", (item["content_hash"],)).fetchone()
                if news_row is None and item.get("url"):
                    news_row = conn.execute("SELECT id FROM news WHERE url=?", (item["url"],)).fetchone()
                if news_row:
                    title = item.get("title") or "بدون عنوان"
                    key = item.get("content_hash") or str(news_row["id"])
                    conn.execute("INSERT OR IGNORE INTO news_events(event_key,title,category,importance,sentiment,impact,related_asset,published_at) VALUES(?,?,?,?,?,?,?,?)",
                                 (key, title, item.get("category"), item.get("importance"), item.get("sentiment"), item.get("impact"), item.get("related_asset"), item.get("published_at")))
                    event = conn.execute("SELECT id FROM news_events WHERE event_key=?", (key,)).fetchone()
                    conn.execute("INSERT OR IGNORE INTO news_sources(event_id,news_id,source_name,url,published_at) VALUES(?,?,?,?,?)",
                                 (event["id"], news_row["id"], item.get("source"), item.get("url"), item.get("published_at")))
                count += max(cur.rowcount, 0)
        return count

    def news(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM news ORDER BY COALESCE(published_at,'') DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def add_alert(self, symbol: str, condition: str, threshold: float | None) -> int:
        with self.connect() as conn:
            cur = conn.execute("INSERT INTO alerts(symbol,condition,threshold,created_at,message) VALUES(?,?,?,?,?)",
                               (symbol, condition, threshold, utc_now(), "فعال"))
            return cur.lastrowid

    def alerts(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM alerts ORDER BY id DESC").fetchall()]

    def mark_alert_triggered(self, alert_id: int, message: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE alerts SET triggered_at=?,message=? WHERE id=? AND triggered_at IS NULL",
                         (utc_now(), message, alert_id))


db = Database()
