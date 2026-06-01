# CHANGELOG

2026-04-10

- Moved vertical ruler (price) to the right side.
- Made the main graph to occupy all the available space and don't left some space behind it.
- Now every asset in the database has a table only for itself also a table for itself settings.
- Added visibility/invisiblity status in the database for indicators.
- Fixed first presentation of the graph, was showing the most far date in the past, now show the data of current days.
- Fixed the context menu for changing colors of the candles is showing after changing the color.

2026-04-11

- Added new legend of OHLC values when mouse is over candles, including graph indicators.
- Modified the loading order of assets, priorizing the last opened graph, and make the rest open in background.
- Changed icons to zoom in/out, added a new Reset Graph button.
- Restored indicator legends in the main graph.
- Added individual colors for each parameter of the indicator.

2026-04-12

- Now there is a new draw mode to draw trendlines.
- Trendlines have a circle on coordinates.
- Trendlines are editable, it is possible to change color and coordinates with a double click.
- At loading there is a legend that shows the program is loading data.
- Now it is possible to exist draw mode clicking anywhere there is no trendlines, or other drawings.

2026-04-13

- General code sanitization and little improvements in general speed.
- Removed duplicate PriceAxisItem, now uses shared module.
- Extracted _snap_y helper to deduplicate snap-to-OHLC logic.
- Consolidated snap mode maps into shared constants (SNAP_VALUES, SNAP_INDEX_TO_MODE).
- Removed dead code (IndicatorLegendItem, on_indicator_added/removed, restore_session, IndicatorManager instance methods, Manager alias).
- Removed duplicate bear color context menu handler.
- Moved inline imports to top-level.
- Removed unused imports (QPixmap, QPushButton, QLabel, QHBoxLayout, os).
- Charts now automatically apply Reset Graph view on load (last year) instead of showing a compressed view.
- Fixed background tabs loading with compressed/mangled view — view is now applied when tab becomes visible.
- Fixed set_initial_y_range to use actual visible range instead of hardcoded 450 bars.
- Fixed reset_zoom calling autoRange() which overrode the X/Y range.
- Added "Update All Stock Data" button (toolbar + File menu) to batch-refresh all symbols from Yahoo Finance.
- Fixed overlay indicators (e.g. EMA 200) not showing on chart — legend reference was stale after clear(), now properly reset.
- Fixed overlay indicator data length check — now uses min() instead of strict equality, so indicators work even after data updates change bar count.
- Fixed signal connections accumulating on every plot_candlesticks call — now disconnect before reconnecting.
- Fixed "Update All" to recalculate overlay indicators with new data instead of using stale PlotLine arrays.
- Added Horizontal Line and Vertical Line drawings (single click to place, drag to move constrained to one axis).
- Added Draw Horizontal Line and Draw Vertical Line menu items under Draw menu.

2026-04-14

- Renamed "Edit Trendlines" to "Edit Drawings" and "Clear Trendlines" to "Clear Drawings" to reflect all drawing types.
- Drawing settings dialog now shows appropriate fields per drawing type (Y for hline, Bar for vline, 2 points for trendline).
- Added limit lines (dashed horizontal lines) for cyclic indicators (RSI, CCI, STOCH, STOCHRSI, WILLR, MFI) with configurable levels and colors.
- Limit lines can be customized in the Add Indicator dialog with level spinboxes and color pickers.
- Each indicator panel now has its own movable splitter handle — can independently resize chart and each indicator.
- Splitter sizes are saved and restored per symbol from the database.
- Fixed vertical grid alignment between main chart and indicator panels — setXLink syncs X ranges, fixed-width left (45px) and right (65px) axes on all panels ensure identical plot area widths.
- Indicator title moved to upper-left overlay text (no longer takes space from the plot area).
- Indicator values legend moved to upper-right to avoid overlapping the title.
- Chart style (Candlestick, Line, Heikin Ashi) now saved and restored per symbol from the database.
- Chart Style menu checkmarks update correctly when switching between tabs with different styles.
- OHLC legend now shows Heikin Ashi values when chart style is set to Heikin Ashi.
- Volume bar colors now use Heikin Ashi close vs open when in Heikin Ashi mode.

2026-04-15

- Fixed duplicate indicators on startup — load_chart now skips indicator/drawing loading for already-existing tabs.
- Added `_deduplicate_indicators` database migration to clean up any previously corrupted indicator entries.
- Changed default drawing width from 2px to 1px for all drawing tools (trendline, hline, vline).
- Added `pystalker_run.py` convenience launch script.
- Double-click on a stacked indicator panel opens an edit dialog to change all indicator settings (params, colors, limit lines).

2026-04-22

- Background tab loading now uses deferred event-loop scheduling (QTimer.singleShot) so the UI stays fully responsive while remaining tabs load one at a time.
- Right-click on a drawing shows a context menu with type-specific settings ("Trendline Settings", "Horizontal Line Settings", "Vertical Line Settings") and a Remove option. Suppresses the default bull/bear color menu when clicking on a drawing.
- Fixed drawing width not persisting — width is now saved in the database (stored in params JSON) and restored correctly on reload.
- Draw mode cursor changed to bright crosshair (#FFFFFF + #FFAA00) visible on dark backgrounds.
- Drawing tool icons (trend, horizontal, vertical) brightened to #00BFFF for dark mode visibility.
- Download toolbar icon brightened for dark mode.
- Copy Drawing in context menu creates a displaced copy; snap is always set to None on copies.
- Added File → Create Spread: creates a percent-normalized comparison of two assets starting at 100, displayed as two line indicators in a stacked panel.
- Navigator now has Assets and Spreads tabs; spreads are saved in the database and persist across sessions.
- Double-click on drawings opens settings dialog (via viewport eventFilter with proper coordinate mapping using mapToScene).
- Stacked indicator title text now visible on startup (showEvent triggers repositioning for background tabs).

2026-04-23

2026-05-05

- Spreads are fully independent charts with their own database tables (bars, settings, drawings).
- Spread data (both series) is saved to the database and restored on session restart without needing source assets loaded.
- Spread chart renders two native lines (Asset1 and Asset2) starting at 100, both are core parts of the chart — not overlay indicators.
- Spread legend shows each asset name in its line color (blue for Asset1, red for Asset2) in the upper-left corner.
- Spread OHLC legend shows "symbol1:value  symbol2:value" instead of O/H/L/C/V, positioned below the color legend.
- Right-click context menu on spreads shows "Change [Asset1] Color" and "Change [Asset2] Color" instead of bull/bear colors.
- Right-click context menu on spreads also shows "Change Start Date" to recalculate the spread from a new initial date.
- Spreads no longer appear in the Assets tab or in "Update All" downloads — spread names are excluded from the `symbols` table.
- Spread yellow legend now shows % symbol after values and includes the spread difference (e.g. "BTC-USD:105.00%  ETH-USD:102.00%  Spread:+3.00%").
- Overlay indicator values (e.g. EMA 200, EMA 100, EMA 50) now appear in the yellow OHLCV legend on mouse hover.
- Right-click on a horizontal line → "Horizontal Line Settings" now has an editable Y spinbox; same for vertical line with an editable Bar spinbox.
- Spread chart style defaults to Line; volume is hidden for spreads.
- Series2 data stored in separate `series2` column in the symbol's bars table (with auto-migration via ALTER TABLE).
- Spread line colors and asset names stored in settings table via `save_spread_lines` / `load_spread_lines`.
- `BarData` now has `is_spread`, `spread_symbol1/2`, `spread_color1/2` fields.
- `ChartView` now has `is_spread`, `spread_symbol1/2`, `spread_color1/2`, `spread_curve2`, `line_color` attributes.
- Chart style 'line' renders two lines for spreads with a pyqtgraph legend showing both asset names.
- Deleting a spread from the navigator also removes its database tables and in-memory asset data.
- Fixed `NameError: pd` in `on_spread_selected` — added `import pandas as pd` and `import numpy as np` at module level.
- Fixed duplicate `on_current_changed` method in `ChartTabWidget` — merged into single method that handles both tab visibility and signal emission.
- Added `pandas` and `numpy` as top-level imports in `main_window.py`.

2026-06-01

- Added **ML Predict (Random Forest)** overlay indicator (renamed from "ML Predict").
- Added **ML Predict (XGBoost)** overlay indicator using same features but XGBRegressor algorithm.
- Both indicators share common feature engineering (extracted into `_build_ml_features`): daily returns, SMA5/10/20 ratios, rolling volatility, RSI, volume change, high-low range.
- Walk-forward training on configurable `lookback` window (default 200 bars), predicts next bar's close.
- Each produces two lines: **Predicted** (in-sample) and **Future** (extrapolated for `horizon` bars, default 5).
- RF colors: Predicted=#E040FB (purple), Future=#FF6EC7 (pink). XGB colors: Predicted=#00E676 (green), Future=#76FF03 (lime).
- Database migration renames existing "ML Predict" indicators to "ML Predict (Random Forest)".
- Overlay lines that extend beyond data length (future predictions) are now supported in the chart view.


