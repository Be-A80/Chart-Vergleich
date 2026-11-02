# 📈 Multi-Asset Chart Cycle Comparator

Eine Streamlit-Webanwendung zum präzisen visuellen Vergleich zweier historischer Chart-Abschnitte (Krypto, Aktien, Rohstoffe, Forex) auf einer normierten Kalender-Zeitachse im TradingView-Stil.

## Features
- **Echte Kalenderzeit-Synchronisation:** Versatz `X` (auch > 33.000 Einheiten) zählt exakte Kalendertage/-stunden. Außerbörsliche Zeiten und Wochenenden bei Aktien/Forex bleiben als echte zeitliche Lücken sichtbar.
- **Custom Timeframes mit 00:00 UTC Anker:** Unterstützt `1M, 2W, 1W, 1D, 2D, 4D, 8D, 16D, 1h, 2h, 4h, 8h, 16h, 18h, 20h` mit täglichem Anker um `00:00 UTC`.
- **Multi-Source Daten:**
  - Krypto über `ccxt` (Binance, Kraken, Coinbase) inkl. automatischer Pagination
  - Aktien, Rohstoffe & Forex über `yfinance`
  - **TradingView CSV-Import** für beliebig tiefe Intraday-Historien
- **Vertikale Vergleichslinien & Zeichenwerkzeuge:** Gekoppelte X-Achse, durchgehendes Fadenkreuz, freie Zeichenwerkzeuge (`Draw Line`) und synchronisierte Index-Referenzlinien.
- **Speichern & Drucken:** Export als interaktive HTML-Datei, hochauflösendes PNG, CSV-Tabelle oder direkter Browser-Druck.

## Installation & Start

```bash
git clone [https://github.com/DEIN-USERNAME/chart-cycle-comparator.git](https://github.com/DEIN-USERNAME/chart-cycle-comparator.git)
cd chart-cycle-comparator
pip install -r requirements.txt
streamlit run app.py
