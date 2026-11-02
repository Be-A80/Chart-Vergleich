import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np


def create_comparison_chart(
    df_upper: pd.DataFrame,
    df_lower: pd.DataFrame,
    symbol_label: str,
    tf: str,
    start_upper: pd.Timestamp,
    start_lower: pd.Timestamp,
    offset_candles: int,
    sync_line_indices: list[int],
    chart_height: int = 820
) -> go.Figure:
    """
    Erzeugt zwei synchronisierte Candlestick-Charts untereinander im TradingView-Dark-Design.
    """
    end_upper = df_upper["timestamp"].iloc[-1] if not df_upper.empty else start_upper
    end_lower = df_lower["timestamp"].iloc[-1] if not df_lower.empty else start_lower

    title_upper = (
        f"<b>Aktueller/Referenz-Abschnitt ({symbol_label} | {tf})</b> — "
        f"Start: {start_upper.strftime('%Y-%m-%d %H:%M UTC')} bis {end_upper.strftime('%Y-%m-%d %H:%M UTC')}"
    )
    title_lower = (
        f"<b>Historischer Abschnitt (vor {offset_candles:,} Kalender-Einheiten | {tf})</b> — "
        f"Start: {start_lower.strftime('%Y-%m-%d %H:%M UTC')} bis {end_lower.strftime('%Y-%m-%d %H:%M UTC')}"
    )

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.07,
        subplot_titles=(title_upper, title_lower),
        row_heights=[0.5, 0.5]
    )

    def build_hover_text(df: pd.DataFrame) -> list[str]:
        texts = []
        for _, row in df.iterrows():
            ts_str = row["timestamp"].strftime("%Y-%m-%d %H:%M UTC") if pd.notna(row["timestamp"]) else "N/A"
            idx = int(row["candle_index"])
            if pd.isna(row["open"]):
                texts.append(f"<b>Kerzen-Index #{idx}</b><br>Zeit: {ts_str}<br><i>Außerbörslich / Kein Handel</i>")
            else:
                texts.append(
                    f"<b>Kerzen-Index #{idx}</b><br>"
                    f"Datum: {ts_str}<br>"
                    f"Open: {row['open']:.4f}<br>"
                    f"High: {row['high']:.4f}<br>"
                    f"Low: {row['low']:.4f}<br>"
                    f"Close: {row['close']:.4f}"
                )
        return texts

    # Oberer Candlestick-Chart
    fig.add_trace(
        go.Candlestick(
            x=df_upper["candle_index"],
            open=df_upper["open"],
            high=df_upper["high"],
            low=df_upper["low"],
            close=df_upper["close"],
            name="Startdatum",
            increasing_line_color="#26a69a",
            increasing_fillcolor="#26a69a",
            decreasing_line_color="#ef5350",
            decreasing_fillcolor="#ef5350",
            hovertext=build_hover_text(df_upper),
            hoverinfo="text"
        ),
        row=1, col=1
    )

    # Unsichtbarer Scatter-Trace für lückenlosen Crosshair-Hover auch über außerbörslichen Lücken
    upper_mid = df_upper["close"].ffill().bfill().fillna(0)
    fig.add_trace(
        go.Scatter(
            x=df_upper["candle_index"],
            y=upper_mid,
            mode="markers",
            marker=dict(opacity=0, size=1),
            hovertext=build_hover_text(df_upper),
            hoverinfo="text",
            showlegend=False
        ),
        row=1, col=1
    )

    # Unterer Candlestick-Chart (vor X Einheiten)
    fig.add_trace(
        go.Candlestick(
            x=df_lower["candle_index"],
            open=df_lower["open"],
            high=df_lower["high"],
            low=df_lower["low"],
            close=df_lower["close"],
            name=f"Vor {offset_candles} Kerzen",
            increasing_line_color="#26a69a",
            increasing_fillcolor="#26a69a",
            decreasing_line_color="#ef5350",
            decreasing_fillcolor="#ef5350",
            hovertext=build_hover_text(df_lower),
            hoverinfo="text"
        ),
        row=2, col=1
    )

    lower_mid = df_lower["close"].ffill().bfill().fillna(0)
    fig.add_trace(
        go.Scatter(
            x=df_lower["candle_index"],
            y=lower_mid,
            mode="markers",
            marker=dict(opacity=0, size=1),
            hovertext=build_hover_text(df_lower),
            hoverinfo="text",
            showlegend=False
        ),
        row=2, col=1
    )

    # Synchronisierte vertikale Vergleichslinien über beide Charts hinweg
    for idx in sync_line_indices:
        if 0 <= idx < len(df_upper):
            t_up = df_upper["timestamp"].iloc[idx].strftime("%Y-%m-%d %H:%M")
            t_low = df_lower["timestamp"].iloc[idx].strftime("%Y-%m-%d %H:%M")
            fig.add_vline(
                x=idx,
                line_width=1.8,
                line_dash="dash",
                line_color="#f5c542",
                row="all",
                col=1,
                annotation_text=f"#{idx} ({t_up} | {t_low})",
                annotation_position="top left",
                annotation_font=dict(color="#f5c542", size=11)
            )

    # TradingView Dark-Theme Layout & durchgehendes Fadenkreuz (Spike-Lines)
    fig.update_layout(
        height=chart_height,
        template="plotly_dark",
        paper_bgcolor="#131722",
        plot_bgcolor="#131722",
        font=dict(color="#d1d4dc", family="Inter, sans-serif"),
        margin=dict(l=55, r=35, t=65, b=45),
        showlegend=False,
        hovermode="x unified",
        dragmode="pan",
        newshape=dict(
            line_color="#2962ff",
            line_width=2,
            line_dash="solid"
        ),
    )

    # X-Achsen Konfiguration (mit Spike-Lines über beide Subplots)
    fig.update_xaxes(
        gridcolor="#1e222d",
        zeroline=False,
        rangeslider_visible=False,
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikecolor="#787b86",
        spikethickness=1,
        spikedash="dot",
    )
    fig.update_xaxes(title_text="Relativer Kerzen-Index (Kalender-normiert: 0 .. N-1)", row=2, col=1)

    # Y-Achsen Konfiguration (Preisskala rechts wie bei TradingView optional oder links)
    fig.update_yaxes(
        gridcolor="#1e222d",
        zeroline=False,
        side="right",
        showspikes=True,
        spikemode="across",
        spikecolor="#787b86",
        spikethickness=1,
        spikedash="dot",
        fixedrange=False
    )

    return fig
