# CHANGELOG

2026-08-30

- Fixed indicator panel sizes resetting to default after data update/redraw.
- Added `save_splitter_state()`/`restore_splitter_state()` to ChartTab to preserve user-adjusted panel sizes across data updates.
- Added per-line visibility for overlay indicators (e.g., hide Up/Down lines in SuperTrend independently).
- Added `line_visibility` dict persisted in database alongside indicator data.
- Fixed line name mismatch: `PlotLine.key` property strips parameter suffix (e.g., `Up(10,3.0)` → `Up`) for consistent `line_visibility` lookups.
- Added `line_visibility_changed` signal in ChartView to sync per-line visibility changes to indicator data.
- Added `line_visibility` field to `add_indicator()` in ChartTab.
- Added per-line visibility checkboxes in IndicatorDialog color section.
- Added Donchian Channel overlay indicator (params: period=20).

2026-07-27

- Added SuperTrend overlay indicator (params: period=10, multiplier=3.0).
- SuperTrend rendered as two colored lines: Up (green #00FF7F) and Down (red #FF6B6B), plus Upper and Lower bands.
- SuperTrend uses proper ratchet logic: lower band only ratchets up during uptrend, upper band only ratchets down during downtrend; opposite band resets each period.
- Added Donchian Channel overlay indicator (params: period=20) with 3 lines: Upper, Middle, Lower.
- Default colors: Upper=#FF6B6B, Middle=#4ECDC4, Lower=#95E1D3.
- Fixed indicator edit dialog crashing when param types didn't match widget types (e.g., float value on QSpinBox).
- Fixed `redraw_all_indicators` and `on_indicator_panel_double_clicked` to use `_resolve_df()` instead of `asset.to_dataframe()`.
- Fixed `add_indicator_to_chart` to use `_resolve_df()` for copies/spreads.
- Added null/empty dataframe checks before recalculating indicators.
- Fixed window minimize/maximize flash on startup: geometry is now restored before show(), maximizing only when no saved geometry exists.

2026-07-04

- SQLite database performance optimizations:
  - Enabled WAL mode (`PRAGMA journal_mode=WAL`) for better concurrent read/write performance.
  - Set `PRAGMA synchronous=NORMAL` (was FULL) for faster writes with minimal risk.
  - Set `PRAGMA cache_size=-64000` (64MB) and `PRAGMA temp_store=MEMORY` for faster queries.
  - Set `PRAGMA busy_timeout=5000` to avoid immediate failures on lock contention.
  - Replaced row-by-row `INSERT` loop in `save_bars()` with `executemany()` — eliminates 10,000+ individual SQL round-trips.
  - Removed unnecessary `DELETE FROM` before `INSERT OR REPLACE` in `save_bars()` — upserts handle updates correctly.
  - Replaced row-by-row `INSERT` loop in `save_drawings()` with `executemany()`.
  - Replaced row-by-row `INSERT` loop in `save_settings()` with `executemany()`.
  - Cached `_ensure_symbol_tables()` and `_ensure_bars_table()` — skip CREATE TABLE/ALTER TABLE if table was already ensured this session.
  - Added migration version flag (`db_version=2` in settings table) to skip already-run migrations on startup.
  - Fixed `chart_tab.py` creating new `Database()` instances for single writes — now uses shared `self._database` reference.
  - Combined `load_chart_colors()` two separate queries into one `SELECT ... WHERE key IN (?, ?)`.
  - Combined `load_session()` two separate queries into one `SELECT ... WHERE key IN (?, ?)`.
  - Fixed SQL injection risk in `delete_symbol()` and `rename_symbol()` LIKE patterns — now uses parameterized `?` binding.
  - Moved `import json` to module level (was imported inside loops).
  - Removed redundant `INSERT OR REPLACE` for `source_symbol` in `load_bars()` (write-on-read removed).

- Added `prob_target.py`: command-line tool that computes risk/reward probabilities for all assets in the pystalker database.
- Shows LONG (take profit +target% vs stop loss -stop%) and SHORT (take profit -target% vs stop loss +stop%) for each asset.
- Three models: Closer (empirical frequency), Lognormal (lognormal assumption with recent volatility), and GradientBoosting (sklearn GBClassifier).
- Edge ratio = P(target) / P(stop) — above 1.0x means favourable risk/reward.
- Default: 20% target, 5% stop, 10-day horizon. Configurable via `--target-pct`, `--stop-pct`, `--horizon`.
- `--symbol` flag restricts to one asset; without it, all assets with enough data are processed.
- `--date` flag allows backtesting at a historical reference date.
- `--db` flag allows specifying an alternative database path.

2026-06-26

- Fixed timeframe switching (1wk, 1mo): changing timeframe now reloads the current tab with the new interval data instead of creating a new tab or loading wrong data.
- Tab labels update to show interval when non-daily (e.g., "BTC-USD (1wk)").
- Switching tabs syncs the timeframe combo to the active tab's interval.
- Database stores bars per interval in separate tables (`{symbol}_bars` for daily, `{symbol}_{interval}_bars` for others) so weekly/monthly data doesn't overwrite daily.
- `on_timeframe_changed` tries cached data first, falls back to download; clears and recalculates indicators on reload.
- `on_download_finished` properly reconnects signals and recalculates indicators for existing tabs.
- `delete_symbol` drops all interval-specific bars tables.
- `rename_symbol` renames all interval-specific bars tables.

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

2026-06-04

- Horizontal line drawings now show a price label at the left edge of the chart, in the same color as the line.
- Label updates live when the line is dragged, edited (Settings dialog), or copied.
- Label position tracks the chart's horizontal scroll/zoom automatically via `sigXRangeChanged`.
- Labels are removed when horizontal lines are deleted.
- Fixed drawings disappearing after downloading/updating data — `plot_candlesticks` now saves and restores drawings across chart rebuilds.
- `get_drawings()` now includes `width` field so drawings are restored with correct line width.
- Overlay lines that extend beyond data length (future predictions) are now supported in the chart view.

2026-06-05

- Added "Limit" date filter to toolbar: QDateEdit + "Set" and "Clear" buttons to restrict chart display to a specific end date.
- When a limit date is set, the chart, overlay indicators, and separate indicator panels all display data only up to (and including) the limit date.
- Full data is preserved in `_full_df`; clearing the limit restores the complete view.
- `ChartView` now has `_limit_date`, `set_limit_date()`, `clear_limit_date()`, and `_apply_limit_date()` methods.
- Tab switching updates the toolbar QDateEdit to reflect the current chart's limit date.
- Fixed: `plot_candlesticks` now uses `self.df` (filtered) instead of the raw `df` parameter for all rendering (candlesticks, line chart, volume, spread lines).

2026-06-05b

- Trendline Settings dialog now has editable Bar+Y spinboxes for both points (was read-only QLabels).
- `DrawingSettingsDialog` adds `get_point1()` and `get_point2()` methods for trendline point editing.
- `on_drawing_double_clicked` applies trendline point changes via `update_point()`.

2026-06-06

- "Copy Graph" button added at the bottom of the left navigator panel.
- Copies only OHLCV data (no indicators, no drawings) from the selected asset to a new symbol with auto-incremented name (e.g. BTC-USD -> BTC-USD-1, BTC-USD-2...).
- Creates all new DB tables (`_bars`, `_settings`, `_drawings`) for the copied asset as if it were a brand-new asset.
- `AssetNavigator` emits `copy_graph(str)` signal; `on_copy_graph()` in main_window handles the copy logic.
- Fixed RuntimeWarning divide-by-zero and invalid-value in `_build_ml_features()`: replaced `np.where` divisions with `np.divide(..., where=...)` for `vol_change`, `high_low_range`, `sma5_ratio`, `sma10_ratio`, `sma20_ratio`.
- "Rename" button added at the bottom of the left navigator panel.
- "Rename" action added to asset right-click context menu in the navigator.
- `on_rename_graph()` prompts for a new name, renames DB tables (`_bars`, `_settings`, `_drawings`) via `ALTER TABLE RENAME TO`, updates the `symbols` table, `ChartAssets`, navigator list text, and open chart tab label/symbol.
- `Database.rename_symbol()` method added for atomic table+row rename.
- `AssetNavigator.rename_asset()` updates the in-memory list item text.
- "Advance 1 day" Play button (▶ icon) added to the limit date toolbar, between the QDateEdit and the "Set" button.
- `on_limit_date_advance()` finds the next trading day after the current limit date in `_full_df` and advances the limit to it.
- `play.xpm` icon added to assets directory.
- Ascending Channel and Descending Channel drawing tools added.
- Channels are drawn by clicking two points to define the bottom trend line; automatic default height creates the channel.
- Channel has 3 parallel trend lines: bottom (solid), top (solid), middle (dashed) — all share the same slope.
- Data model: 3 stored points = bottom-line-start (BL), bottom-line-end (BR), (0, height) where height is vertical offset from bottom to top.
- 8 control points: 4 corners (BL, BR, TL, TR) + 4 edge midpoints (mid-bottom, mid-top, mid-left, mid-right).
- Dragging BL/BR changes slope (all 3 lines maintain parallelism). Dragging TL/TR changes height only.
- Dragging mid-bottom shifts the bottom line vertically (preserving slope). Dragging mid-top changes height.
- Dragging mid-left moves the BL point. Dragging mid-right moves the BR point. Whole-body drag moves everything.
- Descending channels default to negative height (top below bottom for descenders).
- `ChannelItem` extends trend lines from the left box edge to x_max (right-open, left-cut at the box).
- Channel snap: "Low" snaps only the bottom line (BL, BR) to Low prices; "High" adjusts height so the top line touches High prices at BL/BR bar positions.
- Channel types stored as `asc_channel` and `desc_channel` in DB; fully persisted with save/restore.
- Toolbar buttons with `asc_channel.xpm` and `desc_channel.xpm` icons; menu entries under Draw menu.
- Context menu, double-click settings, copy drawing, and snap all work for channels.
- Settings dialog shows BL Point, BR Point, and Height for channels.
- `asc_channel.xpm` and `desc_channel.xpm` icons added to assets directory.
- Copy Graph now shares the same price data (bars) as the original symbol via `source_symbol` in the DB settings table.
- Price updates to the original symbol automatically propagate to all copies.
- Drawings and indicators remain independent per copy (each copy has its own `_settings` and `_drawings` tables).
- `BarData.source_symbol` attribute added to track the source symbol for copied graphs.
- `_refresh_copies_of()` method added to refresh all open chart copies when the source symbol is updated.
- `asset_removed` signal added to `AssetNavigator`; emitted when removing an asset from the list.
- `on_asset_removed()` handler in MainWindow: closes tab, removes from assets, deletes symbol from database (bars/settings/drawings tables).
- `delete_symbol()` now also drops the `_drawings` table for the deleted symbol.
- Copies with `source_symbol` are properly inserted into the `symbols` DB table on `save_bars()`.
- Copied graphs no longer store any bars data — they always read data from the source asset in-memory or from the source's DB table.
- `database.load_bars()` for copies returns a `BarData` with empty bars and `source_symbol` set; the source asset is resolved at runtime.
- `_get_source_asset()` and `_resolve_df()` helpers added to MainWindow to resolve source asset data for copies.
- `load_chart()` resolves source asset data for copies; loads source from DB if not already in memory.
- `_refresh_copies_of()` uses `_resolve_df()` to get data from the source asset instead of copying bars.
- Fixed drawing settings dialog requiring multiple clicks: signal connections in `load_chart()` are now only made for new tabs (`is_new`), preventing duplicate connections.
- Fixed `desc_channel` context menu label showing "Vertical Line Settings" instead of "Descending Channel Settings".
- `add_indicator_to_chart()` now uses `_resolve_df()` so indicators work correctly on copied graphs (which have empty bars).
- `_refresh_copies_of()` now also recreates stacked (non-overlay) indicator panels, not just overlays.
- `on_update_all()` now also recreates stacked indicator panels and skips copied symbols (which are not real tickers).
- Added `database.is_copy()` method to check if a symbol is a copy with `source_symbol`.
- Both `on_update_all()` and `_refresh_copies_of()` now call `tab.clear_indicator_panels()` before rebuilding indicator panels.
- Undo feature for drawings: stores up to 10 snapshots of all drawing state (points, color, width, snap, type).
- `push_undo()` called before every drawing modification: drag start, creation, copy, removal, settings dialog, edit dialog, clear.
- `undo()` in `ChartView` restores the last snapshot by clearing all current drawings and recreating them from the snapshot.
- Undo toolbar button and `Ctrl+Z` shortcut added to `PyStalkerWindow`.
- `_snapshot_drawings()` serializes drawing state without `item` references; `restore_drawings()` recreates visual items.
- Channel middle line now defaults to grey (`#808080`) instead of the channel color.
- `middle_color` attribute added to `ChannelItem`; stored in drawing dict and DB params.
- `DrawingSettingsDialog` shows "Middle Line" color picker for channels (asc/desc).
- `EditDrawingsDialog` shows "Middle Color" row for channels; applied on "Apply Changes".
- `middle_color` saved/loaded via `params` in `database.save_drawings`/`load_drawings`.
- `on_drawing_double_clicked` applies `middle_color` changes to `ChannelItem` and regenerates picture.

2026-07-11

- Fixed drawing "Settings" context menu not opening the settings dialog on freshly downloaded symbols. `on_download_finished` now routes through `load_chart` so the `drawingDoubleClicked` signal (and other chart signals) get connected for new tabs, instead of creating a bare tab via `add_chart_tab` + `load_data` with no signal wiring.

