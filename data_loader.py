import pandas as pd
import numpy as np
import yfinance as yf
import ccxt
import streamlit as st


# Reihenfolge der Fallback-Börsen, falls die primäre Quelle (z. B. Binance HTTP 451) blockiert
CRYPTO_FALLBACK_ORDER = [
    "binance",
    "coinbase",
    "kraken",
    "bitstamp",
    "okx",
    "kucoin",
]


def _get_symbol_candidates(symbol: str, exchange_id: str) -> list[str]:
    """
    Erzeugt passende Symbol-Varianten, falls eine Börse z. B. USD statt USDT verwendet.
    """
    s = symbol.strip().upper().replace("-", "/")
    candidates = [s]

    if "/" in s:
        base, quote = s.split("/", 1)
        if quote == "USDT":
            candidates.append(f"{base}/USD")
            candidates.append(f"{base}/USDC")
        elif quote == "USD":
            candidates.append(f"{base}/USDT")
            candidates.append(f"{base}/USDC")
    else:
        candidates = [f"{s}/USDT", f"{s}/USD"]

    # Duplikate entfernen unter Beibehaltung der Reihenfolge
    return list(dict.fromkeys(candidates))


def _symbol_to_yfinance(symbol: str) -> str:
    """
    Konvertiert ein Krypto-Symbol wie 'BTC/USDT' oder 'ETH/USD' in das Yahoo-Finance-Format 'BTC-USD'.
    """
    s = symbol.strip().upper().replace("/", "-")
    if s.endswith("-USDT") or s.endswith("-USDC"):
        base = s.split("-")[0]
        return f"{base}-USD"
    return s


@st.cache_data(ttl=900, show_spinner=False)
def fetch_ccxt_single_exchange(
    exchange_id: str,
    symbol: str,
    base_tf: str,
    start_dt: pd.Timestamp,
    end_dt: pd.Timestamp
) -> tuple[pd.DataFrame, str]:
    """
    Versucht Daten von einer einzelnen CCXT-Börse zu laden (inkl. Symbol-Varianten).
    Wirft eine Exception bei Geoblocking (451), Netzwerkfehlern oder wenn das historische Fenster fehlt.
    """
    exchange_class = getattr(ccxt, exchange_id)
    exchange = exchange_class({"enableRateLimit": True, "timeout": 15000})

    since_ms = int((start_dt - pd.Timedelta(days=2)).timestamp() * 1000)
    end_ms = int((end_dt + pd.Timedelta(days=2)).timestamp() * 1000)
    tf_ms = 3600 * 1000 if base_tf == "1h" else 86400 * 1000

    # Börsenspezifische Limits pro Request
    limit_map = {"kraken": 720, "coinbase": 300, "bitstamp": 1000, "okx": 300}
    limit = limit_map.get(exchange_id, 1000)

    last_error = None
    for sym_candidate in _get_symbol_candidates(symbol, exchange_id):
        try:
            all_ohlcv = []
            curr_since = since_ms
            max_requests = 90
            req_count = 0

            while curr_since < end_ms and req_count < max_requests:
                ohlcv = exchange.fetch_ohlcv(sym_candidate, timeframe=base_tf, since=curr_since, limit=limit)
                if not ohlcv:
                    break
                all_ohlcv.extend(ohlcv)
                last_ts = ohlcv[-1][0]

                # Falls die Börse (wie Kraken OHLC) nur aktuelle Daten zurückgibt und nicht historisch paginiert:
                if req_count == 0 and ohlcv[0][0] > end_ms:
                    break

                if last_ts <= curr_since:
                    curr_since += tf_ms * limit
                else:
                    curr_since = last_ts + tf_ms

                req_count += 1
                if last_ts >= end_ms:
                    break

            if not all_ohlcv:
                continue

            df = pd.DataFrame(all_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df = df.set_index("timestamp").sort_index()
            df = df[~df.index.duplicated(keep="last")]

            # Prüfen, ob tatsächlich Daten im angeforderten Zeitraum [start_dt, end_dt] liegen
            in_window = df.loc[(df.index >= start_dt - pd.Timedelta(days=5)) & (df.index <= end_dt + pd.Timedelta(days=5))]
            if not in_window.empty:
                return df, f"{exchange_id.capitalize()} ({sym_candidate})"

        except Exception as e:
            last_error = e
            # Bei HTTP 451 (Geoblocking) ist die gesamte Börse gesperrt -> sofort abbrechen und nächste Börse testen
            if "451" in str(e) or "restricted location" in str(e).lower():
                raise RuntimeError(f"{exchange_id} Geoblocking (HTTP 451)") from e
            continue

    raise RuntimeError(f"Keine Daten im Zeitraum bei {exchange_id} ({last_error})")


@st.cache_data(ttl=900, show_spinner=False)
def fetch_yfinance_window(ticker: str, base_tf: str, start_dt: pd.Timestamp, end_dt: pd.Timestamp) -> tuple[pd.DataFrame, str]:
    """
    Lädt Daten von Yahoo Finance für das angeforderte Zeitfenster.
    """
    warning_msg = ""
    now_utc = pd.Timestamp.now(tz="UTC")

    if base_tf == "1h" and (now_utc - start_dt).days > 728:
        warning_msg = (
            f"Hinweis: Yahoo Finance stellt kostenlose 1h-Intraday-Daten nur für die letzten 730 Tage bereit "
            f"(angefordert ab {start_dt.strftime('%Y-%m-%d')})."
        )

    start_str = (start_dt - pd.Timedelta(days=4)).strftime("%Y-%m-%d")
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


def fetch_crypto_with_fallback(
    preferred_exchange: str,
    symbol: str,
    base_tf: str,
    start_dt: pd.Timestamp,
    end_dt: pd.Timestamp
) -> tuple[pd.DataFrame, str, list[str]]:
    """
    Probiert zuerst `preferred_exchange` und wechselt bei Fehlern (z. B. HTTP 451 bei Binance)
    oder fehlender Historie automatisch durch alle verfügbaren Fallback-Quellen inkl. yfinance.
    Gibt zurück: (DataFrame, Verwendete_Quelle, Liste_der_Fallback_Hinweise)
    """
    # Reihenfolge aufbauen: Bevorzugte Börse zuerst, danach der Rest
    exchanges_to_try = [preferred_exchange] + [ex for ex in CRYPTO_FALLBACK_ORDER if ex != preferred_exchange]
    logs = []

    for ex_id in exchanges_to_try:
        try:
            df, used_label = fetch_ccxt_single_exchange(ex_id, symbol, base_tf, start_dt, end_dt)
            if not df.empty:
                return df, used_label, logs
        except Exception as e:
            logs.append(f"{ex_id.capitalize()} übersprungen ({str(e)[:80]})")

    # Letzter automatischer Fallback: Yahoo Finance (z. B. BTC-USD)
    yf_ticker = _symbol_to_yfinance(symbol)
    df_yf, yf_warn = fetch_yfinance_window(yf_ticker, base_tf, start_dt, end_dt)
    if not df_yf.empty:
        if yf_warn:
            logs.append(yf_warn)
        return df_yf, f"Yahoo Finance ({yf_ticker})", logs

    return pd.DataFrame(), "Keine Quelle verfügbar", logs


def parse_tradingview_csv(uploaded_file) -> pd.DataFrame:
    """
    Liest einen CSV-Export aus TradingView (UNIX-Timestamp oder ISO-Datum).
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
