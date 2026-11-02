import pandas as pd
import numpy as np
import yfinance as yf
import ccxt
import streamlit as st
from datetime import timedelta


@st.cache_data(ttl=900, show_spinner=False)
def fetch_ccxt_window(exchange_id: str, symbol: str, base_tf: str, start_dt: pd.Timestamp, end_dt: pd.Timestamp) -> pd.DataFrame:
    """
    Lädt historische OHLCV-Daten über CCXT mit automatischer Pagination für einen Zeitraum.
    """
    exchange_class = getattr(ccxt, exchange_id)
    exchange = exchange_class({"enableRateLimit": True})

    since_ms = int((start_dt - pd.Timedelta(days=2)).timestamp() * 1000)
    end_ms = int((end_dt + pd.Timedelta(days=2)).timestamp() * 1000)

    all_ohlcv = []
    limit = 1000 if exchange_id != "kraken" else 720
    tf_ms = 3600 * 1000 if base_tf == "1h" else 86400 * 1000

    max_requests = 80
    req_count = 0

    while since_ms < end_ms and req_count < max_requests:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=base_tf, since=since_ms, limit=limit)
        if not ohlcv:
            break
        all_ohlcv.extend(ohlcv)
        last_ts = ohlcv[-1][0]
        if last_ts <= since_ms:
            since_ms += tf_ms * limit
        else:
            since_ms = last_ts + tf_ms
        req_count += 1
        if len(ohlcv) < limit // 2 and last_ts >= end_ms:
            break

    if not all_ohlcv:
        return pd.DataFrame()

    df = pd.DataFrame(all_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df


@st.cache_data(ttl=900, show_spinner=False)
def fetch_yfinance_window(ticker: str, base_tf: str, start_dt: pd.Timestamp, end_dt: pd.Timestamp) -> tuple[pd.DataFrame, str]:
    """
    Lädt Daten von Yahoo Finance für das angeforderte Zeitfenster.
    Gibt (DataFrame, Warnhinweis_falls_limitiert) zurück.
    """
    warning_msg = ""
    now_utc = pd.Timestamp.now(tz="UTC")

    # Yahoo Finance 1h-Limit Prüfung (730 Kalendertage rückwirkend ab heute)
    if base_tf == "1h" and (now_utc - start_dt).days > 728:
        warning_msg = (
            f"Hinweis: Yahoo Finance stellt kostenlose 1h-Intraday-Daten nur für die letzten 730 Tage bereit "
            f"(angefordert ab {start_dt.strftime('%Y-%m-%d')}). Nutze für tiefere Intraday-Historien den "
            f"TradingView CSV-Import oder Krypto-Börsen (Binance/Kraken/Coinbase)."
        )

    start_str = (start_dt - pd.Timedelta(days=3)).strftime("%Y-%m-%d")
    end_bound = min(now_utc + pd.Timedelta(days=1), end_dt + pd.Timedelta(days=5))
    end_str = end_bound.strftime("%Y-%m-%d")

    try:
        df = yf.download(
            ticker,
            start=start_str,
            end=end_str,
            interval=base_tf,
            auto_adjust=False,
             prepost=False,
            progress=False
        )
        if df is None or df.empty:
            return pd.DataFrame(), warning_msg

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0].lower() for c in df.columns]
        else:
            df.columns = [str(c).lower() for c in df.columns]

        df = df.rename(columns={"adj close": "adj_close"})
        required_cols = ["open", "high", "low", "close"]
        for col in required_cols:
            if col not in df.columns:
                return pd.DataFrame(), warning_msg
        if "volume" not in df.columns:
            df["volume"] = 0.0

        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")

        return df[["open", "high", "low", "close", "volume"]].sort_index(), warning_msg
    except Exception as e:
        return pd.DataFrame(), f"Yahoo Finance Fehler: {str(e)}"


def parse_tradingview_csv(uploaded_file) -> pd.DataFrame:
    """
    Liest einen CSV-Export aus TradingView (UNIX-Timestamp oder ISO-Datum).
    Erwartete Spalten: time/date/timestamp, open, high, low, close (, volume)
    """
    df = pd.read_csv(uploaded_file)
    col_map = {c.strip().lower(): c for c in df.columns}

    time_col = None
    for candidate in ["time", "timestamp", "date", "datetime", "datum"]:
        if candidate in col_map:
            time_col = col_map[candidate]
            break
    if time_col is None:
        time_col = df.columns[0]

    # Prüfe ob UNIX-Sekunden oder Millisekunden
    if pd.api.types.is_numeric_dtype(df[time_col]):
        max_val = df[time_col].max()
        unit = "ms" if max_val > 1e11 else "s"
        df["timestamp"] = pd.to_datetime(df[time_col], unit=unit, utc=True)
    else:
        df["timestamp"] = pd.to_datetime(df[time_col], utc=True)

    rename_dict = {}
    for std_col in ["open", "high", "low", "close", "volume"]:
        for raw_lower, orig_name in col_map.items():
            if raw_lower == std_col or raw_lower.startswith(std_col):
                rename_dict[orig_name] = std_col
                break

    df = df.rename(columns=rename_dict)
    if "volume" not in df.columns:
        df["volume"] = 0.0

    df = df.set_index("timestamp").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df[["open", "high", "low", "close", "volume"]].astype(float)
