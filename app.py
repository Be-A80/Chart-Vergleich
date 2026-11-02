import streamlit as st
import pandas as pd
from datetime import datetime, time
import streamlit.components.v1 as components

from resampler import (
    TIMEFRAME_CONFIG,
    calculate_past_start_date,
    generate_calendar_timestamps,
    resample_and_align_to_calendar,
)
from data_loader import (
    fetch_crypto_with_fallback,
    fetch_yfinance_window,
    parse_tradingview_csv,
)
from chart_builder import create_comparison_chart

st.set_page_config(
    page_title="TradingView Cycle & Chart Comparator",
    page_icon="📈",
    layout="wide",
)

st.markdown(
    """
    <style>
    .block-container { padding-top: 1.2rem; padding-bottom: 1.5rem; }
    @media print {
        section[data-testid="stSidebar"], header, footer, .stDownloadButton, .no-print {
            display: none !important;
        }
        .block-container { padding: 0 !important; max-width: 100% !important; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("📈 Multi-Asset Chart-Abschnitts-Vergleich (Kalender-Synchronisiert)")

# --- SIDEBAR: EINGABEPARAMETER ---
with st.sidebar:
    st.header("1. Datenquelle & Asset")
    source_type = st.selectbox(
        "Primäre Datenquelle wählen (mit Auto-Fallback)",
        [
            "Krypto Auto-Fallback (Start: Binance)",
            "Krypto Auto-Fallback (Start: Coinbase)",
            "Krypto Auto-Fallback (Start: Kraken)",
            "Krypto Auto-Fallback (Start: Bitstamp)",
            "Aktien / Rohstoffe / Forex (yfinance)",
            "TradingView CSV-Import",
        ],
    )

    uploaded_csv = None
    if source_type == "TradingView CSV-Import":
        uploaded_csv = st.file_uploader(
            "TradingView CSV-Datei hochladen",
            type=["csv"],
            help="Exportiere in TradingView über 'Chart-Daten exportieren...' als CSV.",
        )
        symbol = uploaded_csv.name.replace(".csv", "") if uploaded_csv else "CSV_ASSET"
    elif "Krypto" in source_type:
        symbol = st.text_input(
            "Handelspaar (z. B. BTC/USDT, BTC/USD, ETH/USD)",
            value="BTC/USDT",
            help="Falls eine Börse USDT nicht unterstützt, konvertiert der Fallback automatisch auf USD/USDC.",
        )
    else:
        symbol = st.text_input(
            "Ticker-Symbol (Yahoo Finance)",
            value="AAPL",
            help="Beispiele: AAPL, MSFT, ^GDAXI, GC=F (Gold), CL=F (Öl), EURUSD=X (Forex), BTC-USD",
        )

    st.divider()
    st.header("2. Timeframe & 00:00 UTC Anker")
    tf_list = ["1M", "2W", "1W", "1D", "2D", "4D", "8D", "16D", "1h", "2h", "4h", "8h", "16h", "18h", "20h"]
    timeframe = st.selectbox("Timeframe", tf_list, index=3)

    include_remainder = False
    if timeframe in ("16h", "18h", "20h"):
        include_remainder = st.checkbox(
            f"Reststunden ({timeframe}..24h UTC) als 2. Tageskerze zeigen",
            value=False,
            help="Aktiviert: Tag wird in [00:00 - X:00] und [X:00 - 24:00] geteilt. Deaktiviert: 1 Kerze pro Tag ab 00:00 UTC.",
        )

    st.divider()
    st.header("3. Zeitraum & Kerzen-Versatz")
    col_d, col_t = st.columns(2)
    with col_d:
        start_date = st.date_input("Startdatum (Oberer Chart)", value=datetime(2025, 1, 1).date())
    with col_t:
        start_time = st.time_input("Startzeit (UTC)", value=time(0, 0))

    offset_candles = st.number_input(
        "Versatz X in die Vergangenheit (Kalender-Einheiten)",
        min_value=1,
        max_value=200000,
        value=1335,
        step=10,
        help="Beispiel: 1335 auf dem 1D-Chart = exakt 1335 Kalendertage vor dem Startdatum.",
    )

    visible_candles = st.number_input(
        "Anzahl sichtbarer Kerzen (Fenstergröße N)",
        min_value=10,
        max_value=5000,
        value=180,
        step=10,
        help="Wie viele Kalender-Einheiten ab dem jeweiligen Startpunkt dargestellt werden.",
    )

    st.divider()
    st.header("4. Vergleichslinien & Ansicht")
    sync_lines_str = st.text_input(
        "Vertikale Vergleichslinien bei Kerzen-Index (Komma-getrennt)",
        value="0, 30, 90",
        help="Zieht durchgehende gestrichelte Referenzlinien durch beide Charts bei diesen Kerzen-Indizes.",
    )
    chart_height = st.slider("Chart-Höhe (Pixel)", min_value=550, max_value=1400, value=820, step=50)

# --- PARSE EINGABEN ---
start_upper_dt = pd.Timestamp(datetime.combine(start_date, start_time), tz="UTC")
start_lower_dt = calculate_past_start_date(start_upper_dt, int(offset_candles), timeframe, include_remainder)

grid_upper = generate_calendar_timestamps(start_upper_dt, int(visible_candles), timeframe, include_remainder)
grid_lower = generate_calendar_timestamps(start_lower_dt, int(visible_candles), timeframe, include_remainder)

end_upper_dt = grid_upper[-1]
end_lower_dt = grid_lower[-1]

sync_indices = []
if sync_lines_str.strip():
    for part in sync_lines_str.split(","):
        part = part.strip()
        if part.isdigit():
            sync_indices.append(int(part))

# --- DATEN LADEN (INKL. AUTO-FALLBACK) ---
base_tf = TIMEFRAME_CONFIG[timeframe]["base"]
raw_upper, raw_lower = pd.DataFrame(), pd.DataFrame()
used_source_upper, used_source_lower = "", ""
fallback_notes = []

with st.spinner(f"Lade und synchronisiere Kalenderdaten für {symbol} ({timeframe})..."):
    if source_type == "TradingView CSV-Import":
        if uploaded_csv is not None:
            full_csv_df = parse_tradingview_csv(uploaded_csv)
            raw_upper = full_csv_df
            raw_lower = full_csv_df
            used_source_upper = used_source_lower = "TradingView CSV"
        else:
            st.info("Bitte lade links in der Sidebar eine exportierte TradingView-CSV-Datei hoch.")
            st.stop()

    elif "Krypto" in source_type:
        exchange_map = {
            "Krypto Auto-Fallback (Start: Binance)": "binance",
            "Krypto Auto-Fallback (Start: Coinbase)": "coinbase",
            "Krypto Auto-Fallback (Start: Kraken)": "kraken",
            "Krypto Auto-Fallback (Start: Bitstamp)": "bitstamp",
        }
        pref_ex = exchange_map[source_type]

        raw_upper, used_source_upper, logs_up = fetch_crypto_with_fallback(
            pref_ex, symbol, base_tf, start_upper_dt, end_upper_dt
        )
        raw_lower, used_source_lower, logs_low = fetch_crypto_with_fallback(
            pref_ex, symbol, base_tf, start_lower_dt, end_lower_dt
        )
        fallback_notes = list(dict.fromkeys(logs_up + logs_low))

    else:
        raw_upper, warn1 = fetch_yfinance_window(symbol, base_tf, start_upper_dt, end_upper_dt)
        raw_lower, warn2 = fetch_yfinance_window(symbol, base_tf, start_lower_dt, end_lower_dt)
        used_source_upper = used_source_lower = f"Yahoo Finance ({symbol})"
        if warn1 or warn2:
            fallback_notes.append(warn2 or warn1)

# Falls Fallback ausgelöst wurde (z. B. Binance 451 -> Wechsel auf Coinbase), dezent als Expander anzeigen
if fallback_notes:
    with st.expander(f"ℹ️ Automatischer Quellen-Wechsel aktiv (Geladen von: Oben = {used_source_upper} | Unten = {used_source_lower})", expanded=False):
        for note in fallback_notes:
            st.caption(f"• {note}")

# --- RESAMPLING AUF KALENDER-RASTER ---
df_upper = resample_and_align_to_calendar(
    raw_upper, start_upper_dt, int(visible_candles), timeframe, include_remainder
)
df_lower = resample_and_align_to_calendar(
    raw_lower, start_lower_dt, int(visible_candles), timeframe, include_remainder
)

# --- INFO-METRIKEN ---
m1, m2, m3, m4 = st.columns(4)
m1.metric("Oberer Startpunkt", start_upper_dt.strftime("%Y-%m-%d %H:%M UTC"), delta=used_source_upper, delta_color="off")
m2.metric(f"Unterer Startpunkt (-{offset_candles:,})", start_lower_dt.strftime("%Y-%m-%d %H:%M UTC"), delta=used_source_lower, delta_color="off")
m3.metric("Kalender-Differenz", f"{(start_upper_dt - start_lower_dt).days:,} Tage")
valid_up = int(df_upper["open"].notna().sum())
valid_low = int(df_lower["open"].notna().sum())
m4.metric("Gehandelte Kerzen (Oben / Unten)", f"{valid_up} / {valid_low} von {visible_candles}")

# --- PLOTLY CHART RENDERN ---
fig = create_comparison_chart(
    df_upper=df_upper,
    df_lower=df_lower,
    symbol_label=f"{symbol} [{used_source_upper}]",
    tf=timeframe,
    start_upper=start_upper_dt,
    start_lower=start_lower_dt,
    offset_candles=int(offset_candles),
    sync_line_indices=sync_indices,
    chart_height=chart_height,
)

plotly_config = {
    "scrollZoom": True,
    "displaylogo": False,
    "modeBarButtonsToAdd": [
        "drawline",
        "drawopenpath",
        "drawrect",
        "drawcircle",
        "eraseshape",
    ],
    "toImageButtonOptions": {
        "format": "png",
        "filename": f"chart_vergleich_{symbol.replace('/', '_')}_{timeframe}",
        "height": chart_height,
        "width": 1600,
        "scale": 2,
    },
}

st.plotly_chart(fig, use_container_width=True, config=plotly_config)

st.caption(
    "💡 **Tipp zum Ziehen eigener Vergleichslinien:** Nutze oben rechts in der Chart-Werkzeugleiste das "
    "**Linien-Symbol (`Draw line`)**, um beliebig viele vertikale oder schräge Trend-/Vergleichslinien direkt "
    "mit der Maus über die Charts zu ziehen, anzuklicken und zu verschieben."
)

# --- EXPORT, SPEICHERN & DRUCKEN ---
st.divider()
st.subheader("💾 Analyse speichern, exportieren oder drucken")

exp_col1, exp_col2, exp_col3, exp_col4 = st.columns(4)

html_bytes = fig.to_html(include_plotlyjs="cdn", config=plotly_config).encode("utf-8")
with exp_col1:
    st.download_button(
        label="🌐 Als interaktive HTML speichern",
        data=html_bytes,
        file_name=f"analyse_{symbol.replace('/', '_')}_{timeframe}.html",
        mime="text/html",
    )

with exp_col2:
    try:
        png_bytes = fig.to_image(format="png", width=1600, height=chart_height, scale=2)
        st.download_button(
            label="🖼️ Als HD-Bild (PNG) speichern",
            data=png_bytes,
            file_name=f"analyse_{symbol.replace('/', '_')}_{timeframe}.png",
            mime="image/png",
        )
    except Exception:
        st.info("Für direkten PNG-Download `kaleido` installieren oder Kamera-Icon oben rechts im Chart nutzen.")

merged_export = pd.DataFrame({
    "candle_index": df_upper["candle_index"],
    "upper_timestamp": df_upper["timestamp"],
    "upper_open": df_upper["open"],
    "upper_high": df_upper["high"],
    "upper_low": df_upper["low"],
    "upper_close": df_upper["close"],
    "lower_timestamp": df_lower["timestamp"],
    "lower_open": df_lower["open"],
    "lower_high": df_lower["high"],
    "lower_low": df_lower["low"],
    "lower_close": df_lower["close"],
})
with exp_col3:
    st.download_button(
        label="📊 Vergleichsdaten als CSV",
        data=merged_export.to_csv(index=False).encode("utf-8"),
        file_name=f"daten_{symbol.replace('/', '_')}_{timeframe}.csv",
        mime="text/csv",
    )

with exp_col4:
    if st.button("🖨️ Analyse-Ansicht drucken"):
        components.html("<script>window.parent.print();</script>", height=0, width=0)
