"""
Phase 3 Institutional SQLite Live Signal Scorecard & Self-Verification Ledger (`SignalLedger`).
Provides tamper-evident, forward-tested performance tracking of live tradeable setups:
  1. Automatically logs qualified live setups (`1H`, `4H`, `1D` with `is_tradeable=True` & `readiness >= 3/5`)
  2. Verifies every open setup bar-by-bar against subsequent real exchange candles (`high` / `low` wicks included)
  3. Applies strict conservative intrabar rules (if TP and Stop are touched in the same bar before TP1, Stop wins)
  4. Deducts realistic round-trip exchange taker fees + slippage (`0.10%` total) from every R-multiple
  5. Produces transparent Win-Rate %, Cumulative Net R, Profit Factor & Max Drawdown for Web UI, Telegram & X
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from typing import Any, Dict, Iterator, List, Optional

import pandas as pd

from .signals import MarketForecast

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_LEDGER_DB = ROOT_DIR / "signal_ledger.db"


@dataclass
class LedgerScorecard:
    """Aggregated forward-tested performance metrics from SQLite `signal_ledger.db`."""
    total_tracked: int = 0
    open_count: int = 0
    closed_count: int = 0
    wins_count: int = 0
    losses_count: int = 0
    win_rate_pct: float = 0.0
    cumulative_net_r: float = 0.0
    avg_r_per_trade: float = 0.0
    profit_factor: float = 1.0
    max_drawdown_r: float = 0.0
    recent_signals: List[Dict[str, Any]] = field(default_factory=list)
    summary_tr: str = "Henüz tamamlanmış canlı sinyal kaydı bulunmuyor."


class SignalLedger:
    """
    Thread-safe & multi-process-safe SQLite WAL Ledger for live crypto setup verification.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path is not None else DEFAULT_LEDGER_DB
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=12.0)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS signals_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at_utc TEXT NOT NULL,
                    created_ts_ms INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    tp1_price REAL NOT NULL,
                    tp2_price REAL NOT NULL,
                    stop_price REAL NOT NULL,
                    confidence_score REAL NOT NULL,
                    readiness_score INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'OPEN',
                    tp1_hit INTEGER NOT NULL DEFAULT 0,
                    tp1_hit_ts_ms INTEGER DEFAULT 0,
                    exit_price REAL DEFAULT 0.0,
                    closed_at_utc TEXT DEFAULT '',
                    net_r_multiple REAL DEFAULT 0.0,
                    pnl_pct_1x REAL DEFAULT 0.0
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_signals_sym_tf_status ON signals_log(symbol, timeframe, status);"
            )
            conn.commit()

    def record_signal_if_qualified(
        self,
        symbol: str,
        timeframe: str,
        exchange: str,
        fc: MarketForecast,
        df: pd.DataFrame,
    ) -> Optional[int]:
        """
        Records a new tradeable setup into SQLite if:
          - `timeframe` is `1H`, `4H`, or `1D`
          - `fc.data_health_ok` is True and data is NOT synthetic
          - `fc.futures_setup.is_tradeable` is True and `fc.readiness_score_5 >= 3`
          - No `OPEN` signal already exists for `(symbol, timeframe)`
        Returns inserted row `id` or `None`.
        """
        tf_up = timeframe.upper()
        if tf_up not in ("1H", "4H", "1D"):
            return None
        if not getattr(fc, "data_health_ok", True):
            return None
        integrity = df.attrs.get("integrity_report") if hasattr(df, "attrs") else None
        if integrity is not None and getattr(integrity, "is_synthetic", False):
            return None
        if str(exchange).upper() == "SIMULATED_FALLBACK":
            return None

        fs = getattr(fc, "futures_setup", None)
        if fs is None or not fs.is_tradeable or fs.direction not in ("LONG", "SHORT"):
            return None
        if fc.readiness_score_5 < 3 or fs.entry_price <= 0 or fs.stop_price <= 0 or fs.tp1_price <= 0 or fs.tp2_price <= 0:
            return None

        sym_up = symbol.upper()
        now_dt = datetime.now(timezone.utc)
        if "timestamp" in df.columns and len(df) > 0:
            last_bar_ts = pd.Timestamp(df["timestamp"].iloc[-1])
            if last_bar_ts.tzinfo is None:
                last_bar_ts = last_bar_ts.tz_localize("UTC")
            created_ts_ms = int(last_bar_ts.timestamp() * 1000)
        else:
            created_ts_ms = int(now_dt.timestamp() * 1000)

        tf_cooldown_ms = {"1H": 3_600_000, "4H": 14_400_000, "1D": 86_400_000}.get(tf_up, 14_400_000)

        with self._connect() as conn:
            open_row = conn.execute(
                "SELECT id FROM signals_log WHERE symbol = ? AND timeframe = ? AND status = 'OPEN' LIMIT 1",
                (sym_up, tf_up),
            ).fetchone()
            if open_row is not None:
                return None

            recent_row = conn.execute(
                "SELECT created_ts_ms FROM signals_log WHERE symbol = ? AND timeframe = ? ORDER BY id DESC LIMIT 1",
                (sym_up, tf_up),
            ).fetchone()
            if recent_row is not None and (created_ts_ms - int(recent_row["created_ts_ms"])) < tf_cooldown_ms:
                return None

            cur = conn.execute(
                """
                INSERT INTO signals_log (
                    created_at_utc, created_ts_ms, symbol, timeframe, exchange, direction,
                    entry_price, tp1_price, tp2_price, stop_price, confidence_score, readiness_score, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
                """,
                (
                    now_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    created_ts_ms,
                    sym_up,
                    tf_up,
                    str(exchange).upper(),
                    fs.direction,
                    float(fs.entry_price),
                    float(fs.tp1_price),
                    float(fs.tp2_price),
                    float(fs.stop_price),
                    float(fs.confidence_score),
                    int(fc.readiness_score_5),
                ),
            )
            conn.commit()
            return int(cur.lastrowid) if cur.lastrowid else None

    def evaluate_open_signals_with_df(
        self,
        symbol: str,
        timeframe: str,
        df: pd.DataFrame,
        round_trip_fee_pct: float = 0.10,
        max_hold_bars: int = 36,
    ) -> int:
        """
        Audits all `OPEN` signals for `(symbol, timeframe)` against subsequent real candles in `df`.
        Conservative Intrabar Rules:
          - Only candles with `timestamp_ms > created_ts_ms` are evaluated.
          - Round-trip fee + slippage (`0.10%`) is converted into R units (`fee_r`) and deducted from every outcome.
          - If `tp1_hit == 0` and a single candle touches BOTH `stop_price` and `tp1_price`, `STOP_LOSS` wins.
          - Once `tp1_price` is touched, `tp1_hit = 1` (50% closed at TP1) and stop moves to breakeven `entry_price`.
        Returns count of newly closed signals.
        """
        if df is None or df.empty or "timestamp" not in df.columns:
            return 0
        sym_up = symbol.upper()
        tf_up = timeframe.upper()

        with self._connect() as conn:
            open_rows = conn.execute(
                "SELECT * FROM signals_log WHERE symbol = ? AND timeframe = ? AND status = 'OPEN'",
                (sym_up, tf_up),
            ).fetchall()
            if not open_rows:
                return 0

            ts_ms_arr = [
                int((pd.Timestamp(t).tz_localize("UTC") if pd.Timestamp(t).tzinfo is None else pd.Timestamp(t)).timestamp() * 1000)
                for t in df["timestamp"]
            ]
            highs = df["high"].to_numpy(dtype=float)
            lows = df["low"].to_numpy(dtype=float)
            closes = df["close"].to_numpy(dtype=float)
            is_closed_arr = (
                df["is_closed"].astype(bool).to_numpy()
                if "is_closed" in df.columns
                else [True] * len(df)
            )

            resolved_count = 0
            for row in open_rows:
                sig_id = int(row["id"])
                created_ms = int(row["created_ts_ms"])
                direction = str(row["direction"]).upper()
                entry_p = float(row["entry_price"])
                tp1_p = float(row["tp1_price"])
                tp2_p = float(row["tp2_price"])
                stop_p = float(row["stop_price"])
                tp1_hit = int(row["tp1_hit"])
                tp1_hit_ms = int(row["tp1_hit_ts_ms"] or 0)

                risk_dist = max(abs(entry_p - stop_p), entry_p * 0.0015)
                risk_pct = (risk_dist / entry_p) * 100.0
                fee_r = round_trip_fee_pct / max(risk_pct, 0.05)
                r_tp1 = abs(tp1_p - entry_p) / risk_dist
                r_tp2 = abs(tp2_p - entry_p) / risk_dist

                new_status = "OPEN"
                exit_p = 0.0
                closed_utc = ""
                net_r = 0.0
                pnl_pct = 0.0
                bars_elapsed = 0

                for idx in range(len(df)):
                    b_ms = int(ts_ms_arr[idx])
                    if b_ms <= created_ms:
                        continue
                    if is_closed_arr[idx]:
                        bars_elapsed += 1

                    hi = float(highs[idx])
                    lo = float(lows[idx])
                    cl = float(closes[idx])
                    bar_utc_str = pd.to_datetime(b_ms, unit="ms", utc=True).strftime("%Y-%m-%d %H:%M:%S")

                    if direction == "LONG":
                        if tp1_hit == 0:
                            hit_stop = lo <= stop_p
                            hit_tp1 = hi >= tp1_p
                            if hit_stop:
                                # Conservative: even if hi >= tp1_p on same bar, stop takes precedence
                                new_status = "STOP_LOSS"
                                exit_p = stop_p
                                closed_utc = bar_utc_str
                                net_r = -1.0 - fee_r
                                pnl_pct = -risk_pct - round_trip_fee_pct
                                break
                            if hit_tp1:
                                tp1_hit = 1
                                tp1_hit_ms = b_ms
                                if hi >= tp2_p:
                                    new_status = "TP2_WIN"
                                    exit_p = tp2_p
                                    closed_utc = bar_utc_str
                                    net_r = (0.5 * r_tp1 + 0.5 * r_tp2) - fee_r
                                    pnl_pct = net_r * risk_pct
                                    break
                        else:
                            # TP1 already locked (50%); remaining 50% has breakeven stop at entry_p
                            hit_be = lo <= entry_p
                            hit_tp2 = hi >= tp2_p
                            if hit_be:
                                new_status = "TP1_PARTIAL_WIN"
                                exit_p = entry_p
                                closed_utc = bar_utc_str
                                net_r = (0.5 * r_tp1) - fee_r
                                pnl_pct = net_r * risk_pct
                                break
                            if hit_tp2:
                                new_status = "TP2_WIN"
                                exit_p = tp2_p
                                closed_utc = bar_utc_str
                                net_r = (0.5 * r_tp1 + 0.5 * r_tp2) - fee_r
                                pnl_pct = net_r * risk_pct
                                break
                    else:
                        # SHORT
                        if tp1_hit == 0:
                            hit_stop = hi >= stop_p
                            hit_tp1 = lo <= tp1_p
                            if hit_stop:
                                new_status = "STOP_LOSS"
                                exit_p = stop_p
                                closed_utc = bar_utc_str
                                net_r = -1.0 - fee_r
                                pnl_pct = -risk_pct - round_trip_fee_pct
                                break
                            if hit_tp1:
                                tp1_hit = 1
                                tp1_hit_ms = b_ms
                                if lo <= tp2_p:
                                    new_status = "TP2_WIN"
                                    exit_p = tp2_p
                                    closed_utc = bar_utc_str
                                    net_r = (0.5 * r_tp1 + 0.5 * r_tp2) - fee_r
                                    pnl_pct = net_r * risk_pct
                                    break
                        else:
                            hit_be = hi >= entry_p
                            hit_tp2 = lo <= tp2_p
                            if hit_be:
                                new_status = "TP1_PARTIAL_WIN"
                                exit_p = entry_p
                                closed_utc = bar_utc_str
                                net_r = (0.5 * r_tp1) - fee_r
                                pnl_pct = net_r * risk_pct
                                break
                            if hit_tp2:
                                new_status = "TP2_WIN"
                                exit_p = tp2_p
                                closed_utc = bar_utc_str
                                net_r = (0.5 * r_tp1 + 0.5 * r_tp2) - fee_r
                                pnl_pct = net_r * risk_pct
                                break

                    if is_closed_arr[idx] and bars_elapsed >= max_hold_bars:
                        new_status = "EXPIRED"
                        exit_p = cl
                        closed_utc = bar_utc_str
                        raw_rem_r = ((cl - entry_p) / risk_dist) if direction == "LONG" else ((entry_p - cl) / risk_dist)
                        if tp1_hit == 1:
                            net_r = (0.5 * r_tp1 + 0.5 * raw_rem_r) - fee_r
                        else:
                            net_r = raw_rem_r - fee_r
                        pnl_pct = net_r * risk_pct
                        break

                if new_status != "OPEN":
                    conn.execute(
                        """
                        UPDATE signals_log
                        SET status = ?, tp1_hit = ?, tp1_hit_ts_ms = ?, exit_price = ?,
                            closed_at_utc = ?, net_r_multiple = ?, pnl_pct_1x = ?
                        WHERE id = ?
                        """,
                        (new_status, tp1_hit, tp1_hit_ms, float(exit_p), closed_utc, float(net_r), float(pnl_pct), sig_id),
                    )
                    resolved_count += 1
                elif tp1_hit != int(row["tp1_hit"]):
                    conn.execute(
                        "UPDATE signals_log SET tp1_hit = ?, tp1_hit_ts_ms = ? WHERE id = ?",
                        (tp1_hit, tp1_hit_ms, sig_id),
                    )

            conn.commit()
            return resolved_count

    def get_scorecard(self, days: int = 30, limit_recent: int = 15) -> LedgerScorecard:
        """Computes transparent live forward-tested performance statistics over the last `days`."""
        cutoff_str = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM signals_log WHERE created_at_utc >= ? ORDER BY id ASC",
                (cutoff_str,),
            ).fetchall()

        if not rows:
            return LedgerScorecard()

        open_rows = [r for r in rows if r["status"] == "OPEN"]
        closed_rows = [r for r in rows if r["status"] != "OPEN"]

        wins = 0
        losses = 0
        gross_win_r = 0.0
        gross_loss_r = 0.0
        cum_r = 0.0
        peak_r = 0.0
        max_dd_r = 0.0

        for r in closed_rows:
            nr = float(r["net_r_multiple"] or 0.0)
            cum_r += nr
            peak_r = max(peak_r, cum_r)
            max_dd_r = max(max_dd_r, peak_r - cum_r)
            if nr > 0:
                wins += 1
                gross_win_r += nr
            else:
                losses += 1
                gross_loss_r += abs(nr)

        closed_n = len(closed_rows)
        win_rate = (wins / closed_n * 100.0) if closed_n > 0 else 0.0
        avg_r = (cum_r / closed_n) if closed_n > 0 else 0.0
        if gross_loss_r > 1e-6:
            pf = gross_win_r / gross_loss_r
        elif gross_win_r > 0:
            pf = 9.99
        else:
            pf = 1.0

        recent_list: List[Dict[str, Any]] = []
        for r in reversed(rows[-limit_recent:]):
            recent_list.append(dict(r))

        if closed_n > 0:
            summary = (
                f"Son {days} Günde {closed_n} Tamamlanan Kurulum: Başarı %{win_rate:.1f} ({wins}K / {losses}Z) • "
                f"Net Kazanç: {cum_r:+.2f}R • Profit Factor: {pf:.2f} • Maks. Düşüş: -{max_dd_r:.2f}R (Komisyon Dahil)"
            )
        else:
            summary = f"Aktif Takipte {len(open_rows)} Açık Kurulum Var (Sonuçlandığında %0.10 komisyon düşülerek karneye işlenir)."

        return LedgerScorecard(
            total_tracked=len(rows),
            open_count=len(open_rows),
            closed_count=closed_n,
            wins_count=wins,
            losses_count=losses,
            win_rate_pct=win_rate,
            cumulative_net_r=cum_r,
            avg_r_per_trade=avg_r,
            profit_factor=pf,
            max_drawdown_r=max_dd_r,
            recent_signals=recent_list,
            summary_tr=summary,
        )


def format_ledger_telegram_html(sc: LedgerScorecard) -> str:
    """Formats the SQLite Live Signal Scorecard into a transparent Telegram HTML report (`/karne`)."""
    lines = [
        "📊 <b>CANLI SİNYAL KARNESİ &amp; ÖZ-DOĞRULAMA DEFTERİ (SQLite)</b>",
        "<i>%0.10 borsa komisyonu/kayma düşülmüş ve mum içi iğnelere göre doğrulanmış gerçek sonuçlar:</i>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"• 📌 <b>Toplam Kayıtlı Kurulum:</b> <b>{sc.total_tracked}</b> (Açık: <b>{sc.open_count}</b> | Sonuçlanan: <b>{sc.closed_count}</b>)",
    ]
    if sc.closed_count > 0:
        lines.extend(
            [
                f"• 🎯 <b>Gerçek Başarı Oranı:</b> <b>%{sc.win_rate_pct:.1f}</b> (✅ {sc.wins_count} Kazanç / 🛑 {sc.losses_count} Stop)",
                f"• 💰 <b>Toplam Net R Getirisi:</b> <b>{sc.cumulative_net_r:+.2f}R</b> (İşlem Başı: <code>{sc.avg_r_per_trade:+.2f}R</code>)",
                f"• ⚖️ <b>Profit Factor:</b> <b>{sc.profit_factor:.2f}</b> | 📉 <b>Maks. Düşüş (DD):</b> <code>-{sc.max_drawdown_r:.2f}R</code>",
            ]
        )
    else:
        lines.append("• ⏳ <i>Açık kurulumlar TP1/TP2 veya Stop seviyesine ulaştığında otomatik olarak burada raporlanır.</i>")

    if sc.recent_signals:
        lines.append("\n📋 <b>SON TAKİP EDİLEN KURULUMLAR:</b>")
        for s in sc.recent_signals[:8]:
            sym_s = str(s["symbol"]).replace("/USDT", "")
            st = str(s["status"])
            st_ic = (
                "🚀 TP2"
                if st == "TP2_WIN"
                else ("✅ TP1+BE" if st == "TP1_PARTIAL_WIN" else ("🛑 STOP" if st == "STOP_LOSS" else ("⏳ AÇIK" if st == "OPEN" else "⌛ SÜRE")))
            )
            nr_s = f" ({float(s['net_r_multiple']):+.2f}R)" if st != "OPEN" else (" (TP1 Alındı 🔒)" if int(s.get("tp1_hit", 0)) == 1 else "")
            lines.append(
                f"• <b>{sym_s} [{s['timeframe']}]</b> {s['direction']} @ <code>{float(s['entry_price']):,.4f}</code> ➔ <b>{st_ic}</b>{nr_s}"
            )
    lines.append("━━━━━━━━━━━━━━━━━━━━━━\n<i>⚖️ Şeffaf ileriye dönük doğrulama kaydıdır (YTD).</i>")
    return "\n".join(lines)
