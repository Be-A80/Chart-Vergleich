import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone

# Definition der unterstützten Timeframes
TIMEFRAME_CONFIG = {
    "1h":  {"base": "1h", "type": "intraday", "hours": 1},
    "2h":  {"base": "1h", "type": "intraday", "hours": 2},
    "4h":  {"base": "1h", "type": "intraday", "hours": 4},
    "8h":  {"base": "1h", "type": "intraday", "hours": 8},
    "16h": {"base": "1h", "type": "intraday", "hours": 16},
    "18h": {"base": "1h", "type": "intraday", "hours": 18},
    "20h": {"base": "1h", "type": "intraday", "hours": 20},
    "1D":  {"base": "1d", "type": "daily",    "days": 1},
    "2D":  {"base": "1d", "type": "daily",    "days": 2},
    "4D":  {"base": "1d", "type": "daily",    "days": 4},
    "8D":  {"base": "1d", "type": "daily",    "days": 8},
    "16D": {"base": "1d", "type": "daily",    "days": 16},
    "1W":  {"base": "1d", "type": "weekly",   "days": 7},
    "2W":  {"base": "1d", "type": "weekly",   "days": 14},
    "1M":  {"base": "1d", "type": "monthly",  "months": 1},
}


def generate_calendar_timestamps(anchor_dt: pd.Timestamp, n_candles: int, tf: str, include_remainder_candle: bool = False) -> pd.DatetimeIndex:
    """
    Erzeugt exakt n_candles Kalender-Zeitstempel ab anchor_dt,
    wobei Intraday-Timeframes jeden Tag um 00:00 UTC neu ankern.
    """
    cfg = TIMEFRAME_CONFIG[tf]
    anchor_dt = anchor_dt.tz_convert("UTC") if anchor_dt.tzinfo else anchor_dt.tz_localize("UTC")

    if cfg["type"] == "intraday":
        hours = cfg["hours"]
        # Offsets innerhalb eines 24h-Tages ab 00:00 UTC
        if 24 % hours == 0:
            daily_offsets = list(range(0, 24, hours))
        else:
            # Nicht-Teiler wie 16h, 18h, 20h -> Anker um 00:00 UTC
            daily_offsets = [0, hours] if include_remainder_candle else [0]

        timestamps = []
        current_day = anchor_dt.floor("D")
        while len(timestamps) < n_candles + 5:
            for h in daily_offsets:
                ts = current_day + pd.Timedelta(hours=h)
                if ts >= anchor_dt:
                    timestamps.append(ts)
                    if len(timestamps) == n_candles:
                        return pd.DatetimeIndex(timestamps, tz="UTC")
            current_day += pd.Timedelta(days=1)
        return pd.DatetimeIndex(timestamps[:n_candles], tz="UTC")

    elif cfg["type"] in ("daily", "weekly"):
        days = cfg["days"]
        start = anchor_dt.floor("D")
        return pd.date_range(start=start, periods=n_candles, freq=f"{days}D", tz="UTC")

    elif cfg["type"] == "monthly":
        start = anchor_dt.floor("D")
        return pd.date_range(start=start, periods=n_candles, freq="MS", tz="UTC")


def calculate_past_start_date(start_dt: pd.Timestamp, offset_candles: int, tf: str, include_remainder_candle: bool = False) -> pd.Timestamp:
    """
    Berechnet das exakte historische Kalender-Startdatum vor `offset_candles` Zeiteinheiten.
    """
    cfg = TIMEFRAME_CONFIG[tf]
    start_dt = start_dt.tz_convert("UTC") if start_dt.tzinfo else start_dt.tz_localize("UTC")

    if cfg["type"] == "intraday":
        hours = cfg["hours"]
        if 24 % hours == 0:
            total_hours = offset_candles * hours
            return start_dt - pd.Timedelta(hours=total_hours)
        else:
            # Bei täglichem 00:00 UTC Reset für 16h, 18h, 20h
            candles_per_day = 2 if include_remainder_candle else 1
            days_back = offset_candles // candles_per_day
            rem = offset_candles % candles_per_day
            target_day = start_dt.floor("D") - pd.Timedelta(days=days_back)
            if rem == 1 and include_remainder_candle:
                # Einen Slot weiter zurück
                if start_dt.hour >= hours:
                    return start_dt.floor("D") - pd.Timedelta(days=days_back)
                else:
                    return (target_day - pd.Timedelta(days=1)) + pd.Timedelta(hours=hours)
            return target_day + pd.Timedelta(hours=start_dt.hour if start_dt.hour in (0, hours) else 0)

    elif cfg["type"] in ("daily", "weekly"):
        days = cfg["days"]
        return start_dt.floor("D") - pd.Timedelta(days=offset_candles * days)

    elif cfg["type"] == "monthly":
        return start_dt.floor("D") - pd.DateOffset(months=offset_candles)


def resample_and_align_to_calendar(
    raw_df: pd.DataFrame,
    window_start: pd.Timestamp,
    n_candles: int,
    tf: str,
    include_remainder_candle: bool = False
) -> pd.DataFrame:
    """
    Resampled die Rohdaten (1h oder 1D) auf das gewünschte Timeframe mit 00:00 UTC Anker
    und legt sie auf ein lückenloses Kalender-Zeitraster (damit außerbörsliche Zeiten als Platzhalter bleiben).
    """
    cfg = TIMEFRAME_CONFIG[tf]
    grid_index = generate_calendar_timestamps(window_start, n_candles, tf, include_remainder_candle)

    if raw_df is None or raw_df.empty:
        empty = pd.DataFrame(index=grid_index, columns=["open", "high", "low", "close", "volume"], dtype=float)
        empty["candle_index"] = np.arange(len(empty))
        empty["timestamp"] = empty.index
        return empty.reset_index(drop=True)

    df = raw_df.copy()
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")

    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]

    # Filtere groben Zeitraum für schnelle Verarbeitung
    end_bound = grid_index[-1] + pd.Timedelta(days=35)
    start_bound = grid_index[0] - pd.Timedelta(days=35)
    df = df.loc[(df.index >= start_bound) & (df.index <= end_bound)]

    agg_dict = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum"
    }

    if cfg["type"] == "intraday":
        hours = cfg["hours"]
        if df.empty:
            resampled = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        elif 24 % hours == 0:
            # Teiler von 24h: origin='start_day' garantiert Anker um 00:00 UTC
            resampled = df.resample(f"{hours}h", origin="start_day", label="left", closed="left").agg(agg_dict)
        else:
            # 16h, 18h, 20h mit hartem Reset um 00:00 UTC jeden Tag
            records = []
            for day_date, day_group in df.groupby(df.index.floor("D")):
                # Hauptkerze: 00:00 bis `hours`:00 UTC
                w1 = day_group[(day_group.index >= day_date) & (day_group.index < day_date + pd.Timedelta(hours=hours))]
                if not w1.empty:
                    records.append({
                        "timestamp": day_date,
                        "open": w1["open"].iloc[0],
                        "high": w1["high"].max(),
                        "low": w1["low"].min(),
                        "close": w1["close"].iloc[-1],
                        "volume": w1["volume"].sum()
                    })
                # Optional: Restkerze von `hours`:00 bis 24:00 UTC
                if include_remainder_candle:
                    w2_start = day_date + pd.Timedelta(hours=hours)
                    w2_end = day_date + pd.Timedelta(hours=24)
                    w2 = day_group[(day_group.index >= w2_start) & (day_group.index < w2_end)]
                    if not w2.empty:
                        records.append({
                            "timestamp": w2_start,
                            "open": w2["open"].iloc[0],
                            "high": w2["high"].max(),
                            "low": w2["low"].min(),
                            "close": w2["close"].iloc[-1],
                            "volume": w2["volume"].sum()
                        })
            if records:
                resampled = pd.DataFrame(records).set_index("timestamp")
            else:
                resampled = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    elif cfg["type"] in ("daily", "weekly"):
        days = cfg["days"]
        if df.empty:
            resampled = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        else:
            # Auf Tagesbasis ab exakt grid_index[0] resamplen
            daily_df = df.resample("1D", origin="start_day").agg(agg_dict).dropna(subset=["open"])
            # Reindex auf volles Tagesraster vor Multi-Day-Gruppierung, damit Kalender-Tage zählen
            full_days = pd.date_range(start=grid_index[0], end=grid_index[-1] + pd.Timedelta(days=days), freq="1D", tz="UTC")
            aligned_daily = daily_df.reindex(full_days)
            resampled = aligned_daily.resample(f"{days}D", origin=grid_index[0], label="left", closed="left").agg(agg_dict)

    elif cfg["type"] == "monthly":
        if df.empty:
            resampled = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        else:
            resampled = df.resample("MS", label="left", closed="left").agg(agg_dict)

    # Reindex auf das exakte Kalender-Grid (erhält NaN für Wochenenden / außerbörsliche Stunden!)
    aligned = resampled.reindex(grid_index)
    aligned.loc[aligned["open"].isna(), ["high", "low", "close", "volume"]] = np.nan
    aligned["candle_index"] = np.arange(len(aligned))
    aligned["timestamp"] = aligned.index
    return aligned.reset_index(drop=True)
