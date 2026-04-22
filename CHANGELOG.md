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
- Background tab loading now uses deferred event-loop scheduling (QTimer.singleShot) so the UI stays fully responsive while remaining tabs load one at a time.
- Right-click on a drawing shows a context menu with type-specific settings ("Trendline Settings", "Horizontal Line Settings", "Vertical Line Settings") and a Remove option. Suppresses the default bull/bear color menu when clicking on a drawing.
- Fixed drawing width not persisting — width is now saved in the database (stored in params JSON) and restored correctly on reload.
- Draw mode cursor changed to bright crosshair (#FFFFFF + #FFAA00) visible on dark backgrounds.
- Drawing tool icons (trend, horizontal, vertical) brightened to #00BFFF for dark mode visibility.
- Download toolbar icon brightened for dark mode.
- Color box in Edit Drawings dialog is now clickable — opens color picker directly.
- Double-click on drawings opens settings dialog (via viewport eventFilter with proper coordinate mapping using mapToScene).
- Stacked indicator title text now visible on startup (showEvent triggers repositioning for background tabs).



