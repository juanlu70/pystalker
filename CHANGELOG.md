# CHANGELOG

2026-10-24

- Fixed the **Automatic channel anchoring on ES=F** (user follow-up: the drawn channel began on 2025-11-21 while the year's true minimum was the lower low of 2026-03-31, so the ascending base line was cut by that price; "it should begin on the 2026-03-31 because is the lower minimum of all the year"): the containment had been measuring bars the drawing never covers - a channel's lines are drawn FROM the anchor bar to the right edge, so the evaluation now covers exactly that range (the base line may be touched but never pierced from the anchor on; the parallel line contains everything from the anchor by construction) instead of the whole window, which had rejected the 2026-03-31 anchor for "leaks" on earlier bars outside the drawn channel. And the **yearly extremes are now tried on BOTH windows** - the standard one and the one including the current month - before any other candidate, so a standard-window extreme channel broken by the current price no longer loses to a pivot-anchored one (the extended window's extreme channel contains the newest prices). The best-effort fallback walks the candidates in their priority order instead of by leak.
  - Verified: ES=F now draws an ascending channel **begun on 2026-03-31** - the year's absolute minimum, low 6353 - fully clean from its anchor (base 0.0%, top 0.0%) on the extended window; the battery over the 133 live assets now finds a **clean channel for every single asset** (133/133, previously 113 clean + 16 best-effort + 4 none), worst base-line pierce 0.3% of the range, all anchored on the yearly extreme; synthetic channelable years still anchor on the absolute extreme with best_effort 0; and a deep-lower-low regression guarantees no drawn channel is ever pierced from its anchor.
  - Also caught while finishing this: a unit bug from the best-effort refactor (the containment compared a leak fraction against a points-based tolerance, silently disabling strictness) - fixed to fraction-vs-fraction before these measurements.

- Fixed **ES=F's "No automatic channel was drawn"** (user report: 26 years of data, a clean-looking chart, yet no channel): the tool analyses **only the last year by design**, and ES=F's last year is an accelerating bull run that **admits no containing straight channel at all** (the best possible one leaks 13.4% of the year's range) - so the strict rule rejected everything. Added the **best-effort fallback**: when no containing channel exists in either window, the channel that **leaks the least** is drawn, capped at 15% of the window's price range (and still rejected when the current price has broken it), trying the standard window first and then the extended one so the channel contains the newest prices. The result's new `best_effort` key carries the leak fraction (0.0 for clean channels).
  - While verifying this, a **unit bug from the best-effort refactor was caught and fixed**: the containment check compared the leak fraction against a points-based tolerance, disabling strict containment entirely (a 35%-leaking channel passed as "clean"); it now compares fraction against fraction.
  - Verified: ES=F draws an ascending best-effort channel (13.4% leak - the minimum possible - anchored 2025-11-21, containing the current month); the battery over the 133 live assets keeps its 113 clean channels (worst leak 0.3%) and gains 16 best-effort channels (all between 2% and 14.2%), leaving only 4 truly unchannelable assets; synthetic channelable years still anchor on the absolute extreme with leak 0; clean console.

- Fixed the **Automatic channel: it now starts on the absolute maximum/minimum and never leaks prices** (user report with a screenshot: the channel "doesn't start on an absolute maximum or minimum" and "has some prices above the lower line"): the candidate order changed - **the window's yearly extremes are tried first** (the yearly low anchors an ascending channel, the yearly high a descending one), with the year-start swing and the other pivots only as fallbacks; and a channel is only valid when it **contains the whole window** - no bar may fall outside its two lines (a low may touch the rising base line, never pierce it; leaks up to 1% of the window's price range count as touches, a tolerance tuned against the live data). The supports are tried in cleanliness order until one produces a containing channel; a candidate without one is rejected.
  - Verified against the live database (133 assets, running the previous version from git for comparison): the old algorithm drew 133 channels of which **48 leaked more than 5% of the price range** (up to 162% - whole price sections outside the lines, the user's screenshot complaint) and usually anchored away from the extremes; the new version draws 113 channels with a **worst leak of 0.3%** and **all 113 anchored on the window's absolute minimum/maximum**. The 20 assets that now draw nothing are exactly the worst old leakers (70-160%) - their last year forms no containing channel, and no drawing beats a wrong drawing. Synthetic channelable rising/falling years anchor on their absolute extreme with full containment; clean console.

- Added **fix_garbage_bars.py, the garbage-bar cleaner** (user request: "how can I clean all garbage bars in all assets?"; in console_programs/ beside fix_duplicate_bars.py): scans every asset's bars and deletes rows that cannot be real prices - non-numeric/non-positive prices, impossible candles (high < low or the body far outside the range, with a generous 5% relative tolerance because providers store high/low with less precision than open/close on old history), and **isolated extreme spikes/dips** (a bar priced more than --factor, default 50, times its neighbours' median - which a genuine gradual rally never triggers). Every removed bar is printed (date + values + reason), the database is **backed up first** (consistent SQLite snapshot), `--dry-run` reports without changing anything, `--asset` cleans a single asset and `--factor` tunes the spike threshold; the removed days come back on the next update if the provider serves them.
  - Verified (seeded matrix): all five garbage kinds flagged, while a genuine 100x gradual rally, a single-day 5x jump, precision-slop bars (close 12.555 vs high 12.55) and pre-split price blocks are correctly kept; --dry-run changes nothing and writes no backup; the real run backs up and removes exactly the flagged rows; --factor, --asset (including special-character symbols), and the missing-database paths.
  - **Dry run on a copy of the live database**: 20 garbage bars in 6 of 158 assets (all impossible candles on old futures history: BZ=F 6, PL=F 6, HG=F 3, CL=F 2, GC=F 2, NG=F 1). The AGPU bar with a 3,375,000 high initially suspected as garbage turned out to be **genuine pre-split history** (a contiguous 2011 block of million-scale prices) - the isolation check rightly keeps it, and the earlier observation is corrected.

- Fixed the **price ruler showing 0.50 / 0.70-style values on the first load of a chart** (user report: loading an already existent asset showed fractional values until the ruler was adjusted with the mouse): the chart's ViewBox had **pyqtgraph's auto-range left enabled on the Y axis**, and while the chart is rebuilt on load (clear, re-added items, new axis items, the deferred first layout) the auto-range re-fired with partial/no bounds and clobbered the manually set ranges - sometimes to the pyqtgraph default [0, 1] (the fractional ruler), sometimes to the full-history range (the current tab even had a bogus X). Every range in this program is set by hand (initial view, mouse, zoom), so `plot_candlesticks()` now **disables auto-range on both axes for good** (re-disabled on every rebuild) and the manually set ranges stick: the real prices show from the first load.
  - Verified against a copy of the live database with the real session: the startup restore loads all 20 tabs and the current one opens with the correct last-year window (X and Y matching the bars actually visible, auto-range off), clicking through every tab shows real prices everywhere (no 0-1 rulers anywhere), a fresh visible load matches its window, a hidden load still fixes itself at show time, and manual redraws keep the prices; clean console.
  - Observation (not touched): the live AGPU history contains one garbage bar (high = 3,375,000) - it can distort zoomed-out views of that asset; cleaning it would touch the live database, so it waits for the user's go-ahead.

- **Personalized names and column sorting in the channel scanner** (user request): both the application's dialog and the CLI listings show the **personalized display names** of the assets (like Operations) wherever an asset appears - the near-line ASSET column and the broken-channels lines - falling back to the official symbol when the asset has no display name. In the application the official symbol rides along hidden in the cell (data role), so double-clicking a row still opens the official chart and draws the right indicator lines even after sorting; the CLI resolves the names through the shared core accessor (`get_display_name`) before closing the connection.
  - The application's two tables now **sort by clicking a column header, like the Operations list** (the numeric columns PROXIMITY, LAST CLOSE, LINE VALUE and DISTANCE BEYOND sort numerically through the Operations NumericItem); the default orders are kept (near table by proximity, broken by asset). The row-indexed evaluation maps were re-keyed by official symbol (sorting reorders rows), and the now-unused plain cell helper was removed.
  - Verified (temp database with proof-pair prices - 9.5 vs 10.2 and 7.52% vs 14.20%, where a text sort would order them differently): the display names and hidden official symbols in both tables; the numeric sorts (with Qt's case-insensitive text sort covered for the ASSET column); the double-click opening the official chart with its upper/lower indicator lines after re-sorting; the CLI names in the table and the broken prose with `--lower-than` unaffected; both CLI entry points byte-identical (colors stripped); clean console.

2026-10-23

- Grouped the **Operations in the Open / Planned / Closed groups - tabs in the application, titled sections in the CLI** (user request): three mutually exclusive groups - **Open** (running and not planned), **Planned** (all the planned operations, open or closed) and **Closed** (done and not planned).
  - The application's Operations dialog got a **tab bar above the list** (with tooltips): switching tabs re-filters the list, the tabs show the group counts ("Open (12)"), the summary counts the groups, and the PLANNED checkbox toggle still moves an operation between the groups live (unchecking it on the Planned tab moves the started row to the Open group).
  - The CLI (`pystalker_cli.py operations` and the standalone) **lists all the operations by default, split into the same three titled sections** ("OPEN OPERATIONS (12)", "PLANNED OPERATIONS (8)", "CLOSED OPERATIONS (3)" - the channel scanner's near/broken precedent; empty sections are skipped), and the existing `--open` / `--planned` / `--closed` flags now select one group alone (mutually exclusive; their semantics upgraded to the groups: `--open` excludes planned operations, and a planned-closed operation belongs to `--planned`, not `--closed`); `--paper` and `--asset` still compose with any group.
  - New `operation_group()` in the shared core (the groups defined in one place); `list_operations()` gained the `group` parameter (replacing the old status/planned filters) and every row carries its group; the result counts are the group counts (n_open + n_planned + n_closed = len(rows)).
  - Verified (temp database with an open, a planned-open, a planned-closed and a closed operation): the GUI tabs with counts, the planned-closed row staying in the Planned tab, and the toggle moving a started operation to Open (tabs, rows and database all updated); the CLI default's three sections in order with the right rows; the group flags alone and mutually exclusive, composing with `--paper`/`--asset`; the unified output identical to the standalone with intact ANSI alignment; clean console.

- Changed the **Operations' FINAL PNL column into FINAL GAIN %** (user request: "the Final PNL to be the same as GAIN % but name it Final GAIN %", clarified as exit-based; in the application and in the CLI): the last column now shows **the leveraged gain at the exit price - the same kind of percent as GAIN %** - identical to GAIN % for closed operations (both use the exit price there), the projection at the reference exit price for open ones ('-' without an exit price). It is always a percent now: **the money PNL (move x leverage x volume) is gone**, so the volume no longer changes the format. The look rules are unchanged: green/red for real closed operations, plain for the potential gain of open ones ("Potential gain at the reference exit price" tooltip) and for planned projections. The VOLUME column stays as information (its form tooltip no longer promises a money PNL).
  - `operation_metrics()` now returns `(gain, net_gain, final_gain)` (pnl / pnl_money removed; `fmt_pnl` deleted - all three gain columns share `fmt_gain`), and `list_operations()` exposes `final_gain`; the shared core keeps the application and the CLI on identical numbers.
  - Verified (temp database, the application dialog and both CLI entry points): closed operations show FINAL GAIN % == GAIN % (including 'Combined' leverage); an open operation with a 150 reference exit shows +500.00% against the +390.00% live GAIN %; a volume-1000 planned operation shows the +41.67% percent (the old +416.67 money value gone); no-exit rows show '-'; the colors, tooltips and header are right; the CLI output is identical through the unified program and the standalone one with intact ANSI alignment; clean console.

- Made the **Channel Scanner dialog's two sections resizable, and its double-click now opens the chart with draggable channel indicator lines** (user request, clarified as "3:1 default sizes" + "chart indicator lines"):
  - The border between the near-line table and the Broken channels section is now a **draggable splitter**: the near table keeps about 3x the broken section's height by default (the previous 3:1 stretch), the divider moves with the mouse, and the sections never collapse.
  - Double-clicking a row in either table opens the asset's chart with **indicator lines at the channel's line values** - the upper channel line in bright green (#00FF00) and the lower one in bright red (#FF0000), the scanner's color coding. They are normal draggable hline drawings in the Operations entry/exit precedent: moved/deleted by hand like any drawing, persisted in the store, surviving redraws; the next scanner double-click replaces the previous set, whether that chart is open or closed.
  - The Operations line machinery in ChartView was generalized into `add_tagged_hline()` / `remove_tagged_hlines()` (tag-keyed), with `add_operation_hline()` / `remove_operation_hlines()` as thin wrappers - behavior identical.
  - Verified (temp database): the 3:1 splitter default, a simulated drag, no collapsing; a near double-click drawing the green upper / red lower hlines at the evaluated values (persisted); a broken double-click replacing the previous set (live chart and store); the closed-chart removal path; and the Operations lines regression; clean console.

- Colored the **broken-channels "beyond upper/lower line" sentences in the dialog too** (user follow-up): the BROKEN LINE column of the scanner's broken table now shows "beyond upper line" with **white letters on a green background** and "beyond lower line" with **white letters on a red background** - the same color coding as the CHANNEL / NEAR LINE columns; the DISTANCE BEYOND column keeps its red warning text.
  - Verified (temp database with one broken-above and one broken-below asset): the exact backgrounds with white bold letters per sentence, the DISTANCE BEYOND red text and the CHANNEL colors unchanged, and the near table untouched; clean console.

- Colored the **application's Channel Scanner dialog columns with backgrounds** (user request): the CHANNEL column shows Ascending with a **green background** and Descending with a **red** one, and the NEAR LINE column shows Lower with **red** and Upper with **green** - the Operations-list look (colored background with white bold text, the same #2e7d32 / #c62828 tones). The broken-channels table's CHANNEL column uses the same colors (its BROKEN LINE and DISTANCE BEYOND columns keep their red warning text).
  - Verified (temp database with every kind/line combination and both broken kinds): the exact backgrounds per row in both tables, white bold text on the colored cells, the untouched cells (ASSET, the proximity green text, prices, the red warning texts), and the "Lower than" filter / re-scan regression; clean console.

- Added the **"Lower than" input box to the application's Channel Scanner dialog** (Trading > Channel Scanner; user request: the graphical equivalent of the console scanner's `--lower-than`): typing a price (e.g. 15) filters the whole report - the near-line table and the broken-channels table - to the assets whose last price is at that price or lower, and the header shows the active filter ("... of a channel line - price <= 15 - scanned N asset(s)"); empty = all prices. Invalid text warns ("must be a positive number") and keeps the previous results.
  - The filter moved into the **shared core** (`scan_channel_proximity(lower_than=...)`), so the console `--lower-than` flag and the input box use the exact same code path (the CLI's own post-filter block was removed).
  - Verified (temp database): the core filters both sections and composes with `--symbol` (the scanned count stays pre-filter); the GUI dialog shows all assets with the box empty, only the cheap ones with 15 (header and status counts), warns and keeps the previous results on invalid input, and returns to the full list when cleared; and the CLI `--lower-than` regression shows the same results as before, now through the shared core; clean console.

2026-10-22

- Colored the **broken-channels section of the channel scanner too** (user follow-up): each notification line now shows **"Ascending channel" in green / "Descending channel" in red** (the CHANNEL column colors) and **"beyond the upper line" in green / "beyond the lower line" in red** (the NEAR LINE column colors) - in both `pystalker_cli.py scanner` and the standalone program, honoring `--no-color` and surviving the `--lower-than` filter.
  - Verified (temp database with all four combinations - Ascending/Descending channel x broken above/below): the exact colored phrases per line including the reset between them, `--no-color` output equal to the stripped colored output, the standalone output identical to the unified CLI, the near-table colors unchanged, and `--lower-than` still filtering the broken lines; clean console.

- Colored the **channel scanner's CHANNEL and NEAR LINE columns** and added **--lower-than** (user request): in both `pystalker_cli.py scanner` and the standalone `console_programs/channel_scanner.py` (the same module), the CHANNEL column now shows **Ascending in green and Descending in red letters**, and the NEAR LINE column shows **Upper in green and Lower in red**; the new **`--lower-than <price>` flag keeps only the assets whose last price is at that price or lower** - applied to the whole report (the near section and the broken-channels section), with the active filter shown in the report header ("... of a channel line - price <= 15") and in the no-match message. A `--no-color` flag (like operations_list's) prints plain text.
  - The colors are applied after the column padding (the operations_list technique), so the ANSI escapes never break the alignment; the shared scanning core (and with it the Trading menu scanner) is untouched.
  - Verified (temp database with ascending/descending channels near the lower/upper lines and a broken one, through both the unified CLI and the standalone program): the exact green/red letters per row, the `--no-color` output equal to the color-stripped output, the `--lower-than` filter keeping the cheap assets and dropping the expensive ones from both sections, the extended no-match message, and `--help` listing the new flags; on a copy of the live database the real report runs (65 near, 21 broken; `--lower-than 15` narrows it to the assets at $15 or less); clean console.

- Added the **NET GAIN % column** to the operations listings (user request: "the gain but without the leverage, I mean the GAIN 1x"): a new column right before GAIN % in the **application's Operations list, in `pystalker_cli.py operations` and in the standalone `console_programs/operations_list.py`** - the directional move at 1x (entry -> current while open, entry -> exit once closed), so GAIN % keeps showing the leveraged move and NET GAIN % the pure price move (identical to it when the leverage is 1 or 'Combined'). It follows the GAIN % look everywhere: green/red in the application and with ANSI colors in the terminals, plain (no color) for planned operations, '-' when there is no price to compare against. The FINAL PNL is unchanged (it was already computed from the 1x move).
  - `operation_metrics()` now returns the 1x move alongside the leveraged one (`gain, net_gain, pnl, pnl_money`) and `list_operations()` exposes it as `net_gain` - the shared core keeps the application and the terminals on identical numbers. The EXIT, EXIT PRICE and FINAL PNL columns shifted one to the right in both listings.
  - Verified (temp database with the full operation matrix): the math (long/short, 5x/10x leverage, 'Combined', closed basis, no-data rows); the application's column position, values and colors (planned rows plain, real open/closed colored, potential PNL tooltips) with the shifted columns intact and the PAPER/PLANNED toggles unaffected; the CLI output identical through the unified program and the standalone one with the ANSI-stripped colored output equal to the `--no-color` output; clean console.

2026-10-21

- Added **pystalker_cli.py, the unified command-line program** (user request: "a simple CLI program that has commands to make all the already created console programs... so I have a single program to make it all"): one program with a command per tool - `operations` (the trading journal), `update` (update all assets' data, the File > Update All Stock Data twin), `scanner` (the channel scanner) and `list <exchange>` where the second argument is the exchange (`list phemex`, `list pionex`) - exactly the commands the user specified. Every command keeps the flags of its original program, listed with `<command> --help`.
  - The five console programs moved to **console_programs/** (channel_scanner.py, phemex_assets.py, pionex_assets.py, operations_list.py, update_data.py) and refactored so each tool defines its flags once in `build_parser()` with the body in `run(args)` - shared by the standalone program and by the unified CLI, so the two can never drift. The standalone programs still run (`python console_programs/operations_list.py ...`, their import path adjusted to the new location). `prob_target.py` and `fix_duplicate_bars.py` stay untouched at the root per the user's choice (only scanner, update, list and operations became commands).
  - Running the program with no command at all (the user's follow-up request) **prints the help screen with all the commands** (exit 0) instead of the usage error; an unknown command or a bad flag still shows the argparse usage error.
  - Verified: no-command / `list` without an exchange / unknown exchange / unknown flag exit with the usage error; `--help` and `<command> --help` list the commands and their flags; the `operations` output is byte-identical through the unified CLI and the standalone program (filters and colors intact); `update` keeps the exact menu-point semantics (an in-process run with a mocked fetch layer and explicit argv, plus the real end-to-end AAPL update from Yahoo Finance on a copy of the live database); `scanner` runs on the live-database copy both ways; `list phemex`/`list pionex` serve the live product listings with --search/--type; clean console.

- Cleaned up the live database **with the user's consent**: removed the bogus **A_SYM** asset (3 fake bars) that a faulty test run of the previous session had created by accident (the test invoked the update tool before pointing it at the temp database; the fetch layer was fully mocked, so no real asset was ever touched). Removed with the program's own `delete_symbol()` path - bars/settings/drawings tables and the symbols row are all gone, the 153 real symbols remain.

2026-10-20

- Added **update_data.py, the console twin of File > Update All Stock Data** (user request: "a tool to update all assets like the Update All Stock Data menu point", the name chosen by the user): updates every asset in the database from the data source that serves it, merging the fetched daily candles into the database (new bars added, existing ones refreshed - INSERT OR REPLACE, nothing deleted), using the application's own Database + DataManager core so it behaves exactly like the menu point. Per symbol it reports the source, the total bars, the newest bar date and how many bars the update added; failures print in red and never stop the run; copies are skipped (they use their source asset's bars). Flags: `--db` (channel_scanner style), `--symbol` (a single asset), `--no-color`. (Moved to console_programs/ the next day, as the `update` command of the unified CLI.)
  - Verified: per-source routing (yahoo/phemex/pionex), copy skipping, merge-upsert (bars added and an existing bar refreshed in place), red non-fatal errors, the zero-bars path ("no data returned"), `--symbol` single/unknown, empty database and missing file exits, `--no-color`; and the real end-to-end AAPL update from Yahoo Finance on a copy of the live database; clean console. The session was interrupted before this verification completed - it was finished on 2026-10-21 against the tool's new location, same checks.
  - Incident (disclosed to the user at the time): the first test run accidentally targeted the live database - the test called the tool's main() before pointing its arguments at the temp database. The fetch layer was fully mocked, so the only effect was one bogus "A_SYM" asset with 3 fake bars; no real asset was touched (verified read-only). Removed on 2026-10-21 with the user's consent.

2026-10-19

- Added **operations_list.py, the Operations journal as a console program** (user request: "I have the channel scanner as a console program, now I want the operations listing as a console program too", name/colors/filters chosen by the user): prints the trading journal from the terminal with the same columns as the application's list (ENTRY, ASSET, PAPER, PLANNED, LONG/SHORT, ENTRY PRICE, VOLUME, LEVERAGE, CURRENT PRICE, GAIN %, EXIT, EXIT PRICE, FINAL PNL), newest entry first, with **ANSI colors mirroring the application** - green/red Long/Short and GAIN %, FINAL PNL colored for real closed operations, plain for the potential PNL of open ones and the projected PNL of planned ones (planned gains stay plain: no real gains yet); `--no-color` prints plain text. The ASSET column shows the personalized display names like the application; the CURRENT PRICE is the last close stored in the database.
  - **Filters** (the user's choice): `--asset` (case-insensitive substring of the stored name, official symbol or display name), `--open` / `--closed` (mutually exclusive), `--planned` and `--paper`; the header shows the scope ("Operations matching planned - 8 of 25 in the database") and the closing summary counts the listed rows. `--db` selects the database like channel_scanner.py; the database is only read (plain sqlite3 connection: no writes, no migrations, safe while the application runs).
  - The gain/PNL math and the cell formatting moved to a **shared core module `pystalker/core/operations.py`** (the channel_scanner precedent): `leverage_value`, `move_percent`, `fmt_price`, new `fmt_gain`/`fmt_pnl` and the `operation_metrics()` computation extracted from the dialog's `_add_row`, plus the read-only accessors (`list_operations()`, `resolve_asset()`, `get_display_name()`, `last_close()`, `load_operations()` - any column set, so future columns cannot break the CLI). The application's dialog imports the shared math and formatting (refactored, behavior identical), so the terminal listing and the application can never show different numbers.
  - Verified (temp database with the full operation matrix, and a copy of the live database): the CLI values match the application's dialog cell by cell (planned/real x open/closed, volume money and percent PNL, 'Combined' leverage, display names, free-text bot assets without current price); the colored output stripped of its ANSI escapes is exactly the `--no-color` output (the escapes never break the column alignment); every filter, the --open/--closed mutual exclusion, and the empty-database / no-operations-table / missing-file paths; the GUI refactor regression (all values and the green/red/plain coloring unchanged); and the 25 real operations list correctly (8 planned, `--asset AGPU` 2 of 25, `--planned` 8 of 25); clean console.

- Added **planned operations to the Operations journal** (user request: a way to annotate operations that could start soon but are still only a project, which may start or never - the user suggested "Preparation", renamed to the standard trading term **Planned**): a new **"Planned (a project that may or may not start)" checkbox in the New/Edit operation form** (next to Paper trading, tooltip explains it) and a new **PLANNED checkbox column in the Operations list** (after PAPER).
  - A planned operation can have an exit price and a PNL computed from it, but **its GAIN % and FINAL PNL keep the plain look - the same background as the rest of the fields, no green/red** - because it is not a real operation yet and there are no real gains: the cells get "Planned operation - projected gain/PNL, not a real result" tooltips, and this applies to planned **closed** operations too (the projected PNL at the exit price stays plain).
  - The **PLANNED column checkbox is click-to-toggle like PAPER and persists**: unchecking it (the operation actually starts) immediately re-renders the row with the normal colors - green/red gain and the colored final PNL for closed operations - and checking it again returns the plain look. The summary line now counts them ("N operation(s): X open, Y closed, Z planned").
  - New `planned` column in the `operations` table with the automatic migration for existing databases (pre-existing operations stay non-planned); the planned flag round-trips through the edit form (prefilled, off by default for new operations). Planned operations keep drawing their entry/exit lines on the asset's chart like any operation.
  - Verified (temp copy of the live database): the migration adds the column to the real schema keeping the 25 existing operations non-planned; four operations created through the real New-operation path render as expected (planned open and planned closed plain, real closed colored, real open with colored gain and plain potential PNL); the list checkbox uncheck/re-check persists and recolors; the form prefills, defaults off and saves the flag; the paper toggle regression; clean console.

2026-10-17

- Added the **Pionex exchange as a third data source** (user request: "download all assets from it, the same as Phemex and Yahoo"): new **PionexProvider** on their public REST API (no API key) serving the spot pairs (`BTC_USDT`, including their xStocks tokenized stocks `AAPLX_USDT`, `TSLAX_USDT`, `SPYX_USDT`...) and the perpetual futures (`BTC_USDT_PERP`, `TSLAX_USDT_PERP`...). Klines come unscaled with millisecond timestamps; the endpoint serves 500 candles per request, so fetch() **pages back with endTime up to 10,000 daily bars - much deeper than Phemex (BTC_USDT reaches back to October 2017)**. Errors return HTTP 200 with a result/code/message body and raise clean messages. The live API rejects weekly/monthly klines despite its docs (only 1m/5m/15m/30m/1h/1d work, on spot and perpetuals alike), so those raise a clear "not supported" error.
  - The **Download fallback chain is now Yahoo Finance -> Phemex -> Pionex**: Pionex-only symbols like `BTC_USDT` or `BTC_USDT_PERP` simply download, and each asset remembers its source; new **`DataManager.fetch_by_source()`** routes **Update All** by stored source (Yahoo/Phemex/Pionex) replacing the hardcoded two-way branch, and the Rename dialog's data source label shows "Pionex" for Pionex assets. Downloads go through the normal Download prompt (per the user's choice there is no in-app Pionex picker).
  - New **`pionex_assets.py` console lister** (same style as phemex_assets.py): all enabled products (940: 342 spot pairs + 598 perpetuals) with SYMBOL/TYPE/BASE/QUOTE/NAME columns, `--search` (matches symbol, base, quote or name), `--type spot|perp` and `--all` with a STATUS column - spot products carry an enable flag while perpetuals use a TRADING status, both handled; timestamp header like the other tools.
  - Verified (live API): BTC_USDT 3,279 daily bars since 2017 with sane OHLCV and naive dates, BTC_USDT_PERP 1,377 bars, the tokenized TSLAX_USDT at a real price, interval and symbol errors clean; the fallback chain (BTC_USDT -> pionex, the Phemex regression sTSLAONUSDT -> phemex, the combined error on garbage); the full GUI flow (download -> chart, source stored, status bar "from Pionex", Update All routing all three sources, rename label); and the lister runs in all modes; clean console.

- Changed the **Operations to store the official ticker** (user request: "when adding the operation the ticker name must be the official name"): whatever is typed in the Asset field is resolved and - when it matches an asset in the program - the operation is stored with its **official symbol** (new `_with_official_asset()` applied on create and edit); unresolvable names (bots, free text) are stored as typed. The listing keeps displaying the personalized name, which now stays correct even if the user renames the asset's alias later (the link is the official ticker), and the edit form prefills the official ticker.
  - Verified (temp database): typing the personalized name stores BTC-USD, typing the official one too, bot names stay as typed, the listing shows the alias for all official-linked operations, renaming the alias updates the listing automatically, the click still opens the official chart with the operation lines, and the edit form prefills the official ticker; clean console.

- Added the **personalized name to the big graph box title** (user request): the large title inside the chart now shows the display name instead of the official symbol. New `ChartView.title_text` + `set_chart_title()`: `load_chart` sets it from the display name (falling back to the official symbol), every redraw (redraws, timeframe changes, updates, indicator toggles) keeps it, and the rename dialog updates it live - including **clearing** the display name, which now resets the ticker-list item, the tab text and the graph title back to the official symbol (a gap found by the tests).
  - Verified (temp database): an aliased asset shows "my bitcoin" in the graph title with BTC-USD nowhere on it, an unaliased asset falls back to its official symbol, the title survives redraws, display-only and official-ticker renames update it live (the re-keyed tab included), and clearing the alias restores the official symbol everywhere; clean console.

- Added the **data source label to the Rename Asset dialog** (user request): a read-only "Data source" line (gray) shows which provider serves the asset - "Yahoo Finance", "Phemex", or the capitalized name for future sources - as a point of information for the user; the official ticker's tooltip also mentions which provider fetches it, and the label follows the asset through an official-ticker rename (the `data_source` setting travels with the renamed settings table).
  - The rename dialog construction was split into `_build_rename_dialog()` for testability; `on_rename_graph()` behavior is unchanged.
  - Verified (temp database): a Yahoo asset shows "Yahoo Finance", a Phemex asset shows "Phemex" (with the display name prefilled), an unknown future source ('binance') falls back to "Binance", and the label still reads Phemex after re-keying the asset to a new official ticker; clean console.

- Added **official asset symbol vs personalized display name** (user request: renaming an asset broke data updates, because the program fetched the renamed name from the provider; e.g. "SI=F is Silver Futures"):
  - Each asset keeps its **official ticker** (the data provider symbol, used for fetching, Update All, database tables, drawings and operation lines) and can have a **personalized display name** - free text, lower case included - shown in the **ticker list, chart tab titles and the Operations asset column**. The navigator now keys its items by the official symbol (in a data role) with the display name as the visible text, so double-click/selection/context menu still act on the real symbol; the search filter matches the visible name.
  - **Rename is now a two-field dialog**: "Personalized name" (case preserved) and "Official ticker" - the latter only to repair assets renamed in the past (it re-keys the asset with the existing rename machinery: bars/settings/drawings tables, memory, navigator, tab), after which fetching works again. Typing the display name in Operations resolves to the official asset (both directions), and the asset column shows the personalized name.
  - New `Database.set_display_name()` / `get_display_name()` (`display_name` key in the symbol settings), `Navigator.set_asset_display_name()` + symbol-keyed items, `ChartTabManager.update_tab_label(label=...)`, and the display-name-aware `_resolve_asset()` in Operations.
  - Verified (temp database): set/get/clear with lower case; the exact reported bug scenario (a past-renamed asset fixed to its official ticker: Update All then fetches the official symbols only); display-only rename leaving the internal symbol untouched; tab titles and navigator showing the display names; navigator clicks loading by official symbol; Operations typed with the display name resolving, displaying it, opening the official chart and drawing the operation lines there; and a fresh start restoring the display names. Clean console.

- Added **operation entry/exit lines on the asset's chart** (user request): creating an operation draws a **bright green horizontal line at the entry price for longs** (bright red for shorts) and, when the exit price is defined (final or reference), a **bright blue line at the exit price** - RGB(85, 170, 255) / #55AAFF per the user's later adjustment - on the asset's chart if it exists in the program; assets not in the program draw nothing. Editing an operation deletes its old lines and draws them at the new prices (including the long->short color flip and removing the blue line when the exit price is cleared); deleting an operation removes its lines.
  - The lines are normal persisted hline drawings tagged with the operation id in their params (the Automatic Channel precedent: they survive restarts, are listed with the other drawings, and can be recolored/moved/deleted by hand like any hline - the next operation edit re-syncs them to the operation's prices). Two new ChartView methods: `add_operation_hline()` / `remove_operation_hlines()`.
  - Works with the chart open (drawn live and persisted) and with the chart closed (the stored drawings are updated, so the lines appear when the chart is opened later).
  - Verified (temp database, real BTC-USD/AMD data): a long with exit draws green 50000 + blue 60000 on the open chart and persists; a short draws the red entry only; an operation on a not-open chart stores its lines and they appear on the chart restore; editing moves the lines to the new prices with the old ones gone (and drops the blue line when the exit is cleared); deleting removes the lines from chart and store; unknown assets draw nothing without errors; and an unrelated user drawing survives the sync. Clean console.

2026-10-16

- Changed the **FINAL PNL column to show the PNL with the exit price whenever there is one** (user request): open operations with a reference exit price now show their potential PNL at that reference (money with a volume, the leveraged percent without) **plain, without any background** as long as the operation runs (with a "Potential PNL at the reference exit price" tooltip); closed operations keep the green/red background like the GAIN % cells, and rows without an exit price keep '-'.
  - Verified (temp database): an open operation with a 60000 reference shows +1000.00 plain while the identical closed one shows +1000.00 green, no-reference rows show '-', the percent variant (+100.00%) and negative references (-100.00) stay plain for open rows, closed negatives get the red background, and the GAIN % column still tracks the live price for open rows; clean console.

- Added **click-to-open-chart in the Operations list** (user request): clicking the ASSET cell opens that asset's chart through the same path the Channel Scanner uses (`load_chart`), resolving the typed name case-insensitively against the in-memory assets and the database (so 'btc-usd' opens 'BTC-USD'). Unknown assets/bot names show a clear warning ("The asset "..." is not in the program. Download it first to see its chart.") instead. Double-clicking the asset cell opens the chart without triggering the Edit form (Edit stays on the Edit button and on double-clicking any other cell).
  - The asset resolution was refactored into a shared `_resolve_asset()` also used by the current-price lookup.
  - Verified (temp database, real BTC-USD data): clicking BTC-USD opens its chart as the current tab, the lowercase variant resolves to the same chart, the unknown bot name shows the warning without touching the open chart, the double-click skip keeps Edit away from the asset cell, and the regressions (live leveraged gain %, paper checkbox persistence) still pass; clean console.

- Added the **LEVERAGE column and leveraged GAIN %** to the Operations list (user request: a 20% gain at 5x shows as +100%):
  - New **LEVERAGE** column after VOLUME showing the stored leverage ("5x", "10x", "2.5x", "Combined"; numeric sorting, non-numeric values group with the unknowns).
  - **GAIN % now reflects the leverage**: the directional price move (entry->current while open, entry->exit once closed) multiplied by the numeric leverage; the raw move is shown for 'Combined' or free-text leverage. Colors unchanged (green winning / red losing).
  - The **money Final PNL stays exactly the same** as before (the raw price move x leverage x volume - the leverage is applied once), and the no-volume PNL now equals the leveraged gain percent shown in GAIN %.
  - Verified (temp database, real BTC-USD data): the user's exact example (+20% at 5x -> GAIN +100.00%), the same operation with a 1000 USDT volume -> PNL +1000.00 (money), a short at 10x (+166.67% leveraged, +1666.67 money), 'Combined' keeping the raw move, an open operation's live gain multiplied by 10x, unknown-asset rows keeping '-', the 12-header order and numeric leverage sorting; clean console.

- Added the **paper trading checkbox column and the reference exit price to the Operations list** (user request):
  - New **PAPER** column (between ASSET and LONG/SHORT) with a checkbox per operation: checked = paper trading. **Clicking the checkbox in the list toggles the paper flag and persists it immediately**; the column also sorts (paper first).
  - The **exit price can now be written while the operation is open**, as a reference/target: the field is always enabled in the form, and the list shows the reference exit price in the EXIT PRICE column even for open operations (whose GAIN % keeps tracking the live price and FINAL PNL stays '-'). The exit *date* remains the closing timestamp: enabled and stored only once the operation is closed, and closing still requires an exit price (prefilled from the reference when you edit to close).
  - Because the exit price no longer marks the closed state, the open/closed state is now an explicit `"open"` flag in the database (new column, automatic migration: pre-existing rows with an exit price become closed, the rest open; existing operations untouched otherwise). The form's checkbox tooltip documents the new semantics.
  - Verified (temp database): the migration adds both the volume-era and pre-volume schemas' missing columns and classifies old rows by their exit price; the form saves an open operation with a reference exit price (no exit date) and rejects closing without a price; the list shows the reference on the open row with live gain and '-', the closed row with date + price + PNL, and the paper checkbox click persists through a refresh; header order, sort and summary counts verified; clean console.

- Added the **volume (invested amount) to the trading operations**, so the Final PNL becomes a money amount (user request; the volume is almost always USDT per the user):
  - New **Volume** field in the operation form (after the entry price, optional): the invested amount in the quote currency - the margin for futures, the full position value for spot or 'Combined' leverage (explained in the field tooltip). Validated as a positive number when filled; empty keeps the old behavior.
  - Final PNL for closed operations with a volume is now money: **gain % x leverage x volume** (e.g. +20% on 1000 USDT margin at 10x -> +2000.00), shown without the % suffix and colored green/red as before. Operations without a volume keep the percent x leverage PNL (migrated old rows unaffected); open operations keep '-'. A VOLUME column was added to the list between ENTRY PRICE and CURRENT PRICE (numeric sorting, '-' when absent).
  - Database: new nullable `volume REAL` column in the `operations` table, with an automatic migration (`ALTER TABLE ... ADD COLUMN`) for databases created before it - existing operations are untouched and get the fallback percent PNL.
  - Verified (temp database): the migration adds the column to an old-schema database with the row intact; the form accepts/prefills/rejects volumes (+2500, bad text and negatives rejected, empty allowed); the PNL math through the list (+20% x 1000 x 10 -> +2000.00 long, short +16.67% -> +1666.67, spot -10% of 5000 -> -500.00 red, Combined +10% of 5000 -> +500.00, old no-volume row keeps +100.00%, open row '-'); the dialog's VOLUME column, 10 headers, date sorting and money colors; clean console.

- Added **Operations** (Trading > Operations): a trading journal to annotate and list current and past trading operations, stored in a new `operations` table of the database (created automatically on the next start, no other data touched).
  - **New operation** window (`OperationFormDialog`): bot/no bot dropdown (list ready for more options), Spot/Futures dropdown, paper trading checkbox, free-text asset name (accepts assets not in the program or bot names), Long/Short, entry price, leverage (numeric presets with a "Combined" option and free typing), entry date & hour, and - while the operation runs - an "Open operation" checkbox; unchecking it enables the exit price and exit date & hour.
  - Main list (`OperationsDialog`, non-modal, single reusable instance like the Channel Scanner): entry date & time (the sort column, newest first; click any header to re-sort, numeric columns sort numerically), asset, Long/Short with green/red background, entry price, current price, signed percent gain with green/red background (entry->current while open, entry->exit once closed; directional for shorts), exit date & time and exit price for closed operations, and final PNL = percent x leverage for closed operations (raw percent while the leverage is "Combined"; "-" while open). Current price comes from the program's data only (in-memory asset or database last close, case-insensitive; "-" for unknown names - per the user's choice). A summary label counts open/closed, plus Edit (double-click) and Delete (confirmation) to fix mistakes, and a Refresh button.
  - Database API: `save_operation` / `update_operation` / `delete_operation` / `load_operations` on the `operations` table (bot, market, paper, asset, side, entry_price, leverage, entry_date, exit_price, exit_date).
  - Verified (temp database, real BTC-USD data): CRUD round-trip (insert/update/delete/reload), form prefill and save, input validation (empty asset, non-numeric and non-positive prices rejected), row contents and colors (Long/Short backgrounds, gain and PNL colored by winning/losing), Combined vs numeric leverage PNL (+10% raw, +20% x 5 -> +100%), unknown asset showing '-' for current price and gain, date-sorted list including backfilled operations, closing an operation via Edit (PNL appears), Delete with confirmation, menu reopening reusing the dialog, and a clean console.

2026-10-15

- Added the **candle percentage variation to the yellow OHLCV overlay label** (user request): the label now ends with the candle's open->close variation after the volume, keeping the previous OHLCV view exactly as it was, e.g. `O:81729.20  H:84032.30  L:80932.10  C:83043.00  V:61465733  +1.61%` for a positive candle and `-0.34%` for a negative one (+0.00% for flat candles). Added in all four label states: the normal and Heikin Ashi hover labels (mouse over any bar, the variation right after V and before any overlay indicator values) and the normal and Heikin Ashi last-bar legends shown on load (which are OHLC-only, so the variation is simply at the end). The spread label already showed percentage variations and is unchanged.
  - New `ChartView._candle_change_str()` helper: `(close-open)/open*100` formatted `+.2f` (empty string when the variation can't be computed, e.g. zero/NaN open), shared by all four label states.
  - Verified with real BTC-USD data (4,412 bars): unit checks (+1.50%/-1.25%/+0.00%/empty), the exact `V:<volume>  <variation>` position on hover over a positive bar, a negative bar and the last bar (with nothing added between C and V), the Heikin Ashi hover path, the last-bar legend, and a clean console.

- **Verified that every listed Phemex asset downloads through the app** (user report: KORUUSDT failed with "Please try again later" - that was the pre-fix kline route in the still-running app instance; after restarting the app the fixed code serves it). Batch-tested `fetch()` for **all 321 listed symbols**: 319 download OK (74 perp, 71 TradFi, 19 tokenized, 155 crypto; 25-1000 bars each, OHLC sanity checked), including KORUUSDT (Korean index perp, 114 bars) end-to-end through the real window flow (chart rendered, "from Phemex" status bar, data_source stored, console clean). The only 2 failures are spot pairs Phemex marks as listed but that have never traded (sOPINIONUSDT, sBPUSDT - zero candles even on the 1-hour resolution months after listing); their error message is now clearer: "Phemex has no candles for X (the asset may be too new or have no trading activity yet)".

- **Fixed perp futures like BTCUSDT not being found** (user report: "still can't locate assets like BTCUSDT perp future"): Phemex splits its product registry in sections of the same `/public/products` response - the `products` array only holds the spot pairs and the 8 legacy coin-margined perpetuals (BTCUSD, cETHUSD...), while the modern **USDT/USDC-margined perps live in `perpProductsV2`** (891 records, 137 listed) which the provider was not merging in. All of them are now included everywhere (provider, CLI, picker):
  - The USDT/USDC perps also use a different kline route: the provider now queries `/exchange/public/md/v2/kline/last`, which serves every product type (legacy perps, V2 perps and spot) and returns the V2 perp prices already unscaled ("83140.4") while legacy/spot prices keep the priceScale scaling - verified byte-identical values for BTCUSD and sTSLAONUSDT against the old endpoint, and live downloads of BTCUSDT (1000 bars, $81,641.60), TSLAUSDT (258 bars, $364.51) and XAUUSDT gold ($4,122.59).
  - New asset category **TradFi**: the V2 perps on traditional assets (Phemex's `TradFi`/`PreMarket` subtypes - 71 listed) - tokenized stock perps (TSLAUSDT, AAPLUSDT, NVDAUSDT...), indices (NAS100USDT, SPYXUSDT, QQQUSDT), commodities (XAUUSDT gold, XAGUSDT silver, XTIUSDT WTI oil, COPPERUSDT) and pre-IPO names (ANTHROPICUSDT, OPENAIUSDT, SPACEXUSDT). The taxonomy is now: crypto perp futures / TradFi perp futures / tokenized spot assets / normal crypto spot pairs.
  - `phemex_assets.py` default listing grew from 27 to **164 assets** (74 perp, 71 TradFi, 19 tokenized); `--type tradfi` selects the tokenized asset perps, and `--search Tesla` finds both TSLAUSDT (perp) and sTSLAONUSDT (Ondo spot). The Download Phemex Symbol picker now lists all 321 listed products with a CATEGORY column.
  - Verified: fetch matrix across all product types (V2 perp, TradFi perp, legacy perp, spot normal, spot tokenized) with OHLC sanity, classification of 9 representative symbols, Yahoo->Phemex fallback for BTCUSDT/TSLAUSDT, the CLI counts/filters/searches, the picker (321 rows, categories, Tesla search), and a full live download of BTCUSDT through the real window flow (chart rendered, "from Phemex" status, source stored, console clean).

- Added **Phemex as a second data source for daily candles** (public API, no key needed), covering crypto assets Yahoo doesn't serve and the **tokenized stocks** (TSLA, AAPL, NVDA... traded against USDT):
  - New `PhemexProvider` in `pystalker/core/providers.py`: uses `GET /exchange/public/md/v2/kline` (works for both perpetual contracts like `BTCUSD` and spot pairs like `sBTCUSDT` / `sTSLAONUSDT`), descales the per-symbol price scale and spot volumes fetched once from `GET /public/products`, keeps the kline's UTC calendar date as the canonical naive local midnight (consistent with the rest of the app), supports the 1m/5m/15m/30m/1h/1d/1wk/1mo resolutions (10m doesn't exist on Phemex and raises a clear error), and converts HTTP/JSON errors into clean messages. History depth: the most recent 1000 candles (~2.7 years of dailies).
  - **Automatic fallback**: `DataManager.fetch_symbol()` tries Yahoo Finance first and falls back to Phemex when Yahoo errors or returns no data, so Phemex-only symbols just download through the normal Download flow. Both errors are reported if both sources fail.
  - **Per-asset source memory**: `Database.save_data_source()` / `load_data_source()` store the provider in the symbol's settings table (Yahoo stays the implicit default), and **Update All Stock Data** now routes every symbol to the provider it was downloaded from.
  - **File -> Download Phemex Symbol...**: new searchable picker (`pystalker/gui/phemex_dialog.py`) listing every listed Phemex product (1177 total, 184 currently listed) with symbol, description, type and quote currency; search filters as you type and double-click/Download starts the normal download.
  - Verified live against the real API: BTCUSD 1000 daily bars (prices and OHLC sanity, chronological order, midnight timestamps), sTSLAONUSDT 246 bars ($365.35 close, small tokenized-stock volumes), unknown symbols and the 10m interval raise clean errors; and the full GUI path: live download of sTSLAONUSDT through the real window flow (chart rendered, status bar mentions Phemex, source stored), update routing (AAPL -> Yahoo, sTSLAONUSDT -> Phemex), and the picker (search "TSLA", selection, download). Console clean.

- **`phemex_assets.py` now shows the perp futures and the tokenized assets by default** (user request), not the flood of normal crypto spot pairs:
  - New asset classification in `PhemexProvider` (core, shared): `classify_product()` returns `perp` (perpetual contracts), `tokenized` (spot pairs whose base currency is one of Phemex's tokenization programs - the Ondo series "Tesla Ondo Tokenized", "SPDR S&P 500 ETF Ondo Tokenized", "iShares Gold/Silver Trust Ondo Tokenized"..., and the xStocks series "Tesla xStock", "SpaceX tokenized stock"...), or `crypto` (everything else, including gold-backed tokens like PAXG/XAUT which are regular spot pairs); `get_product_name()` exposes the currency's human-readable name ("NVIDIA Ondo Tokenized" for sNVDAONUSDT). The provider now also caches the currencies list.
  - The default listing shows the 8 listed perps + the 19 listed tokenized assets (Apple, Tesla, NVIDIA, Microsoft, Alphabet, Amazon, Meta, AMD, Coinbase, Robinhood, Circle, MicroStrategy, Palantir, Broadcom, Chevron (delisted), SPY, QQQ, iShares gold & silver trusts, SpaceX), each with a CATEGORY and its human-readable NAME; `--type perp|tokenized|crypto|all` picks a category and `--search` now also matches asset names ("Tesla", "gold", "SpaceX"). With `--all` the delisted xStocks series (sTSLAXUSDT...) shows with a STATUS column.
  - The **Download Phemex Symbol picker** got the same treatment: a NAME column (readable asset names) and search now matches names too (search "Tesla" finds sTSLAONUSDT), and it takes the provider directly.
  - Verified live: default listing 27 rows (8 perp + 19 tokenized, no normal crypto), category counts (8/19/157 = 184 listed), search by name ("Tesla" -> the Ondo pair, plus the xStocks pair with --all; "gold" -> the iShares Gold Trust), classification spot checks (BTCUSD=perp, sTSLAONUSDT=tokenized, sPEPEUSDT/sPAXGUSDT=crypto), and regressions: kline fetch (BTCUSD 1000 bars), Yahoo->Phemex fallback, picker (184 rows, searches "Tesla"/"gold"/"SpaceX"/"TSLA", NAME column, selection).

- New **`phemex_assets.py`** standalone console tool: lists every Phemex asset live from the public API, using the same `PhemexProvider` as the application (so the symbols printed are exactly the ones the Download flow accepts). Aligned columns for symbol, description, type and quote currency; `--search` filters by symbol or name, `--type spot|perp` keeps only spot pairs or perpetual contracts, `--quote` filters by quote currency, and `--all` includes the delisted products (adding a STATUS column, e.g. the old `sAAPLXUSDT` next to the listed `sAAPLONUSDT`). Prints the report date & time like the channel scanner. Verified live: default lists the 184 listed products, search/type/quote/all filters, the no-match message, and the network-failure path (clean message, exit code 1).

- Added the **Trading** main menu, with **Channel Scanner** as its first item: the `channel_scanner.py` tool inside the application.
  - New `pystalker/core/channel_scanner.py` holds the shared scanning logic (`scan_channel_proximity`); the standalone CLI script now imports it and produces byte-identical output (verified by diffing full and single-symbol runs before/after the refactor).
  - New `pystalker/gui/channel_scanner_dialog.py`: non-modal dialog with the near-line table (asset, ascending/descending, near lower/upper, proximity %, last close, line value), a broken-channels table in red, the report timestamp, an adjustable max-proximity spinbox (default 10%) with a Scan/refresh button, and a status summary. **Double-clicking a row opens that asset's chart.**
  - Verified with the real database (a copy): the dialog's 26 near rows and 5 broken channels match the shared core exactly (values compared numerically), the 2% proximity filter matches, double-click opens the right chart, reopening reuses the single dialog instance, and the console stays clean.

2026-10-14

- Added **last close price tag on the right price axis** (bright red, TradingView style): always-visible red tag in the ruler showing the last close price of the displayed data, positioned over the axis in scene coordinates (same safe pattern as the crosshair tag), repositioned on every vertical pan/zoom, hidden while the last close is outside the visible price range, and updated on redraws (deferred until the axis layout is valid - the axis' scene transform is stale mid-redraw).
  - The crosshair price tag draws on top of it when both overlap; respects the limit-date view (shows the displayed data's last close, not the full history's).
  - Verified: correct text and exact axis position, vertical-pan tracking, out-of-range hiding/return, 3 redraws with forced garbage collection (no crash), 996 pixel-verified red pixels in the axis strip, coexistence with the crosshair tag, limit-date replot, and a full real-window regression (chart intact, crosshair default-off, automatic channel + S-R, console clean).
- **Fixed the blank chart regression** introduced with the crosshair price tag: the tag was parented to the right price axis, which is destroyed and recreated on every chart redraw - when the old axis was garbage collected the tag's underlying object died with it, so the next redraw crashed with `RuntimeError: wrapped C/C++ object of type TextItem has been deleted` right after clearing the plot, leaving an empty chart. Reproduced deterministically (second redraw with forced GC) and fixed by attaching the tag to the plot scene (which lives as long as the plot) and computing its position over the axis in scene coordinates on every update. Verified across 5 consecutive redraws with forced garbage collection: no crash, chart content intact, price tag still working; full cursor/tag regression suite passes.
- **Crosshair now OFF by default**: every graph starts with the normal mouse cursor; the full-view crosshair appears only when the Crosshair toolbar button is activated (the button now starts unchecked). Toggling off while hovering restores the normal cursor immediately.
- **Crosshair price tag on the right price axis (TradingView style)**: while the crosshair is active, the current crosshair price is shown in the right price ruler as a white price tag that follows the horizontal line (positioned on the axis, re-attached on every chart redraw, hidden with the crosshair).
  - Verified: default cursor state, toggle on/off in both directions, tag text and exact axis position, mouse-following updates, pixel-rendered tag inside the axis strip, redraw survival, draw-mode unaffected, real-window toolbar behaviour; console stays clean.

2026-10-12

- Added **Automatic S-R** (Draw menu): automatic detection of long-term support and resistance levels, drawn as yellow horizontal lines (rules confirmed with the user).
  - Analyses ALL the displayed history: confirmed swing highs/lows (pivots, ±10 bars) are touches; touches within 1% of each other cluster into one level (level price = average of its touches); levels with at least 3 bounces count, and up to the 8 strongest are drawn.
  - Lines are normal horizontal-line drawings in yellow, labelled with price and strength at the left edge (e.g. "6543.65 (4x)"); the touch count persists with the drawing (`label_suffix` in params survives save/restore/copy) and the lines are never recalculated - like every automatic drawing.
  - New `pystalker/core/support_resistance.py` (`find_support_resistance_levels`), `ChartView.add_automatic_sr()`, `HLineItem` label suffix support, and the "Automatic S-R" Draw menu entry.
  - Verified: synthetic series with engineered levels (100 -> 4x support, 150 -> 3x resistance found exactly; a 2-touch level filtered; min_touches/max_levels parameters; short/empty data), real-data invariants on BTC-USD / SAN.MC / AMD (levels within the price range, touches >= 3, strength-sorted, e.g. SAN.MC 2.75 with 19 touches), and the full GUI path (yellow rendering pixel-verified, undo removes all, persistence round trip with labels, immutability across redraws, menu handler with database persistence, console clean).

2026-10-11

- README: new sections for the automatic channel detection (honest "not perfect but near perfect" note, rules summary, demonstration media) and the `channel_scanner.py` tool (assets near channel lines). Features list updated with channels and the new tool. The user-provided screenshot and demonstration video were renamed to `automatic_channel.png` / `automatic_channel.webm` and embedded in the README.
- README video embedding fixed: GitHub's sanitizer strips `<video>` tags pointing to repo files (verified empirically against the rendered README page on github.com - only the fallback link remained). The README now embeds an animated GIF (`automatic_channel.gif`, 925 KB, renders inline exactly like a picture), links the full-quality MP4 (`automatic_channel.mp4`, H.264 - GitHub's recommended format for uploads), and documents the officially supported way to get a real inline player: drag & drop the MP4 into the GitHub web editor, which uploads it to GitHub's CDN and inserts a working player. The original `automatic_channel.webm` is kept in the repo but no longer referenced.
- Fixed "No automatic channel was drawn" on strongly trending assets (e.g. AMD): AMD's October closes went above the year-channel tops and the pullback fell below the recent channel's base, breaking every candidate in the standard window - the message was correct behavior but left nothing drawable (user confirmed the fix).
  - When EVERY candidate of the standard window (excluding the current month) is broken, the calculation is retried once with the window INCLUDING the current month, so the channel reflects the newest prices; the current month's closes still act as the break validation (a channel must contain them).
  - The status bar reports when the retry was used ("Automatic channel created (ascending, including current month)"), and the result carries an `extended` flag.
  - AMD now draws: ascending from the 2025-11-25 low (194.28), support 2026-02-17 (194.83), upper line 658.55 - all October closes (608-649) inside. BTC-USD / SAN.MC / BBVA.MC results are unchanged; genuinely broken markets (wild synthetic closes) still yield the message and nothing.
  - Also fixed a tz regression introduced in the refactor (end_limit was compared before timezone localization for tz-aware indexes).

- `channel_scanner.py` now prints the report's local date & time in the first line ("Report generated: 2026-10-11 10:44:49 CEST"), so it is always clear when each report was made.

2026-10-10

- Added **`channel_scanner.py`** - standalone program that scans all assets (not spreads) in the pystalker database, discards those without channel drawings, and reports assets whose last close is inside a channel and within (default) 10% of a channel line: ticker, ascending/descending, which line the price is near (lower/upper) and the proximity percentage (distance relative to the line's value). Prices beyond a channel line are reported as broken-channel notifications (rules confirmed with the user).
  - Usage: `python channel_scanner.py [--max-proximity 10] [--symbol BTC-USD] [--db PATH]`; copies (BTC-USD-1 etc.) use their source asset's bars.
  - Verified with synthetic databases (near lower/upper, mid-channel filtered, broken beyond upper/lower, copy resolution, degenerate channels, no-channel assets, filters) and against the real database (25 assets near lines, BTC-USD 7.35% from its ascending channel's upper line).

- **Fixed duplicated daily bars in the database** (found while building the scanner): a timezone bug in the download path (yfinance tz-aware timestamps stored as true-UTC epochs, differing from the historical local-midnight epochs) left 29,580 duplicate rows (2 bars per day on BTC-USD, ETH-USD, SOL-USD, USDT-USD, QQQ, ^VIX, SPCX) and 60,955 non-midnight timestamps on US/futures symbols that would double on the next update.
  - Added `fix_duplicate_bars.py` (standalone): backs up the database, keeps one row per calendar day (preferring the local-midnight row), normalizes remaining timestamps to local midnight, deletes duplicates; supports `--dry-run`.
  - The tz normalization in the providers (previous entry) prevents recurrence: downloads now produce the same canonical timestamps the database already uses, so updates REPLACE instead of inserting duplicates.
  - The user's database was cleaned with consent; data integrity verified afterwards (all OHLC values intact by local date, one row per day everywhere, all timestamps at local midnight, and the BTC-USD channel drawing re-aligned - bar 4305 is 2026-07-01 again).

2026-10-09

- Fixed `TypeError: Cannot compare tz-naive and tz-aware datetime-like objects` when clicking Automatic Channel on freshly downloaded charts:
  - Root cause: yfinance returns timezone-aware timestamps (exchange timezone), so freshly downloaded data had tz-aware indexes while the whole app and database work with tz-naive datetimes; the analysis-window comparison crashed. After a restart the same symbol loaded from the database was tz-naive, which is why it only hit fresh downloads.
  - `YahooFinanceProvider` and `CSVProvider` now normalize their data to tz-naive local time, so downloads match database-reloaded data everywhere.
  - `_analysis_window` is additionally tz-safe (window limits are localized to the index timezone), so even a tz-aware chart can never crash the calculation.
  - Verified: the exact crash reproduced and fixed (tz-aware chart computes the same channel as the naive one — BTC ascending anchored on the yearly low 57,747.77), mocked yfinance download returns naive bars, tz-aware CSV normalized, and SAN.MC / BBVA.MC / BTC-USD channels are unchanged.
- **Automatic Channel now anchors on the year's real extremes** (user feedback: it was picking "random points in the last months"): the candidate priority is
  1. the year-start pivot (covers the whole year),
  2. **the window's yearly extremes** — the lowest low and the highest high of the last year, the later one first ("the last top point": a low -> ascending channel, a high -> descending channel),
  3. every other confirmed swing, most recent first.
  Each candidate is still break-validated before drawing (a close beyond either channel line in the current month invalidates it) and the first unbroken one is drawn; if none, nothing is drawn with a message.
  - Results on the user's data: **BTC-USD ascending anchored exactly on the yearly low 2026-07-01 (57,747.77) -> support 2026-08-17 (62,687.10)** (the year-start descending channel from the Oct 2025 high is correctly detected as broken by the current rally); SAN.MC ascending from 2025-10-17 (7.90) and BBVA.MC from 2025-10-16 (14.63), both year-covering.
  - Verified: synthetic tests (year-start channels, broken-start -> yearly-low extreme, all-broken -> None, wick-vs-close, rising year), real-data invariants (extreme anchors are exactly the window's min low / max high, unbroken, direction-consistent, extremal parallel lines), and the GUI regression (rendering, immutability, undo, menu, persistence).
- **Automatic Channel covers the whole last year and self-invalidates when broken** (rules confirmed with the user):
  - The primary candidate anchors at the **year-start pivot**: the confirmed swing point of the first quarter of the window furthest from the window's midrange (a high -> descending channel, a low -> ascending channel), so the channel spans the year.
  - **Break validation before showing**: a candidate channel is invalid if any bar after the analysis window (the current month) **closes beyond either channel line** — wicks do not count.
  - **Walk-back recalculation**: if the year-start channel is broken by the current price, channels are rebuilt from each remaining pivot, most recent first, and the first unbroken one is drawn. If every candidate is broken, nothing is drawn and a message explains it.
  - Base-line direction is enforced: ascending channels have rising supports, descending channels have falling resistances.
  - Results on the user's data: SAN.MC ascending from 2025-10-17 (7.90) and BBVA.MC ascending from 2025-10-16 (14.63) — both year-covering and unbroken; BTC-USD's year-start descending channel (from the Oct 2025 high at 126k) is correctly detected as broken by the current rally, so the walk-back draws the most recent unbroken channel (2026-08-03, 62,226 -> 2026-08-14, 62,488).
  - Verified: synthetic year-start ascending/descending series (exact anchors, score 0), broken-start walk-back, all-broken -> None, wick-vs-close validation, direction consistency; real-data invariants (unbroken, pivot anchors, extremal parallel, cleanest support); full GUI regression (creation, rendering, immutability, undo, menu, persistence).
- **Fixed charts opening "clean/empty" with the Automatic Channel (or anything else) invisible**: a pre-existing timing issue can push the view's right edge far beyond the data (saved state found on BTC-USD: X range [4037, 11342] with 4,405 bars) — the chart opens zoomed out ~2.5x past the data, showing a thin candle band and a mostly empty "clean" graph, and everything else (channel, drawings) looks absent even though it is drawn and saved.
  - `ChartView._repair_corrupted_x_range()` runs on every range change: since the app itself never scrolls past `len(df)+5`, any X range beyond `len(df)*1.5` is corruption and is instantly restored to the default view — fixing both the live occurrence during session restore and any in-session occurrence.
  - `save_session` no longer persists corrupted view ranges, and the view-state restore guard now also rejects ranges extending beyond the data (defense in depth).
  - Verified with the user's actual database copy: session restore now yields a normal ~388-bar view (was 7,305 wide), the automatic channel renders visibly after the click (1,447 px), and legitimate extreme views (full history, scrolling past the right edge) are never "repaired".
  - Regression suite: crosshair, pan performance (~7 ms/frame), automatic channel, spreads, and console cleanliness (including the repair path) all pass.
- "Automatic Channel" click with no chart open now shows a message instead of doing nothing silently.
- Added **Automatic Channel** (Draw menu): a channel that is calculated automatically and placed on the chart as a normal drawing.
  - Analyses the last 12 complete months of the displayed data, excluding the current (partial) month; window is relative to the visible period (works with the limit-date backtesting view).
  - Direction: the last confirmed major swing point decides — if it is a high a descending channel is drawn, if it is a low an ascending channel (swings = High/Low extreme of the surrounding ±10 bars; a same-bar top+bottom tie is resolved by where the bar closed).
  - Ascending: base line from the major low to the cleanest supporting low in the next candles (fewest violations where another low touches/pierces the line; longest span wins ties; supports at least ±10 bars away preferred). The parallel top line goes through the highest high of the window, so no other maximum touches it (one or two touch points = line tests).
  - Descending: mirror image (base on highs, bottom parallel through the lowest low).
  - Best effort: if no perfectly clean support exists the candidate with the fewest violations is used; only fails if two anchor points cannot be placed at all (message shown).
  - The result is a standard `asc_channel`/`desc_channel` drawing: white like manual drawings, editable/copyable/undoable, persisted in the database, and **never recalculated or moved again** — creating a new one simply adds another drawing.
  - New `pystalker/core/auto_channel.py` (`find_automatic_channel`) and `ChartView.add_automatic_channel()`; new "Automatic Channel" entry in the Draw menu.
  - Verified: synthetic ascending/descending series (exact anchors, score 0, top/bottom touch points), direction from the last pivot, current-month spike exclusion, close-based tie-break, fallbacks; real-data invariants on SAN.MC / BBVA.MC / BTC-USD (direction, anchor = last pivot, brute-force optimality of the chosen support, extremal parallel line); GUI tests (rendering, redraw immutability, persistence round trip, undo, multiple channels, spreads) and full menu integration with database persistence.
  - Channels found in the user's data: SAN.MC ascending 2026-08-19 (12.15) -> 2026-09-30 (12.33) clean (score 0); BBVA.MC ascending 2026-09-09 (24.59) -> 2026-09-24 (24.66); BTC-USD ascending 2026-09-15 (74944) -> 2026-09-29 (82739).

2026-10-08

- Crosshair now replaces the mouse cursor when the toolbar Crosshair icon is activated, and the normal mouse cursor is restored when deactivated.
  - Implemented the previously missing `ChartView.set_crosshair_enabled()` (the toolbar Crosshair button existed but raised `AttributeError` when toggled).
  - Icon checked (default): hovering the main graph shows ONLY the full-view crosshair — the OS cursor is hidden (blank) over the plot; leaving the graph restores the normal cursor.
  - Icon unchecked: no crosshair lines, normal mouse cursor over the graph.
  - Draw mode keeps its own crosshair cursor and hides the full-view crosshair; on exit, the crosshair returns on the next mouse move.
  - The toggle applies to the current tab, matching the existing per-tab chart actions.
- Added full-view crosshair to the main graph: two dashed semi-transparent white lines (horizontal + vertical) that span the whole visible chart and follow the mouse, replacing the small pointer-only crosshair — makes it fast to see if a value is above or below another.
  - The vertical line snaps to the bar under the cursor; the horizontal line tracks the exact value level.
  - Hidden automatically when the mouse leaves the graph, when the tab is hidden, and while in draw mode (draw mode keeps its own crosshair cursor).
  - Lines are non-movable (no interference with drawing clicks, context menus, or panning) and added with `ignoreBounds` so they never affect zoom/auto-range.
  - New `ChartView` members: `crosshair_h`, `crosshair_v`, `_update_crosshair()`, `_set_crosshair_visible()`, `leaveEvent`, `hideEvent`.
  - Verified offscreen: visibility, positioning and snapping, hide on leave/draw mode, survival across chart redraws (no duplicates), no range side effects, and actual pixel rendering of both full-span lines; wheel-pan performance unaffected (~5.5 ms/frame).
- Fixed "Create Spread" not offering assets that exist in the database but are not open as chart tabs (e.g. SAN.MC / BBVA.MC): the dialog was fed only in-memory assets, so database-only assets couldn't be selected.
- The spread dialog now lists the union of in-memory assets and all symbols from the database (sorted); the rest of the flow already supported loading the chosen assets from the database on demand.
- Spread creation verified end-to-end offscreen with an isolated database seeded with real SAN.MC/BBVA.MC data: both assets selectable with no tabs open, spread chart opens with both lines and the white diff line.
- **Chart panning/scrolling accelerated ~9x on long-history graphs** (e.g. BTC-USD, 12 years / 4,400+ bars): full-frame render while wheel-scrolling dropped from ~135 ms to ~15 ms in offscreen benchmarks with real BTC-USD data.
  - `CandlestickItem` no longer records/replays a QPicture of the whole history: bars are drawn directly in `paint()`, clipped to the visible X range (with a small margin), using cached pens/brushes — per-frame cost is now proportional to the visible bars, not total history.
  - `VolumeItem.setScale()`/`setYOffset()` are now O(1): scale and offset are applied at paint time instead of re-recording the entire volume picture (the old code re-recorded all volume bars twice on every pan/zoom step — this was the dominant cost, ~88 ms/frame on BTC-USD).
  - Volume bars are also drawn clipped to the visible X range with cached pens/brushes; `boundingRect()` now derives from data + current scale/offset, and `prepareGeometryChange()` is called on scale/offset updates.
  - Fixed console errors `AttributeError: autoRangeEnabled` (pyqtgraph 0.14 traceback printed on every chart redraw/indicator rebuild): they were caused by per-curve `setClipToView(True)`, which triggered pyqtgraph's clip path while the curve was being added to the scene (parentless, so the resolved "view" was the PlotWidget, which lacks `autoRangeEnabled`). Per-curve `setClipToView`/`setDownsampling` calls were removed — `PlotItem.addItem` overrides them anyway, so they never took effect.
  - Curve downsampling is now set at the PlotItem level (`plotItem.setDownsampling(auto=True, mode='peak')` in ChartView and IndicatorPanel), which pyqtgraph applies to every curve on add: auto peak downsampling is now actually active on main chart and indicator panel curves (bounded curve cost when zoomed out). `clipToView` is not used at all.
  - Verified: 0 `autoRangeEnabled` occurrences through real-app flow (chart load, style switches, redraws, indicator panel add/rebuild) and full regression suite; wheel-pan performance unchanged (~6 ms/frame).
  - Rendering verified pixel-against-pixel against the old implementation: identical except ±1px rasterization differences on some candle wick lines at half-pixel boundaries (QPicture replay vs direct draw) and less bleeding of out-of-view candles into the left axis margin.
- Added white "Diff" line to spread charts: a third line in the spread graph showing the difference in points between the two normalized spread lines (series1 - series2, the same value the yellow hover legend shows as "Spread:").
- The diff line is derived at render time (`Close - Series2`), so it needs no database or calculation changes and automatically works for both newly created spreads and spreads restored from the database.
- Added a white "Diff" legend label in the upper-left corner of spread charts, below the two asset name labels.
- Spread initial/reset Y-range (`set_initial_y_range`) now extends down to include the diff line so the white line is visible (it oscillates around 0 while the two normalized lines stay near 100).
- New `ChartView` attributes: `spread_diff_color` (#FFFFFF), `spread_curve_diff`, `spread_legend_diff`.

2026-08-30

- Added Market Cipher B (Cipher B) as a separate indicator panel with WT1, WT2, and MFI lines.
- Default params: wt_channel_len=9, wt_avg_len=12, wt_ma_len=3, rsi_len=14, mfi_period=60, mfi_multiplier=150.
- Horizontal levels at ±53 and ±60 for overbought/oversold zones.
- Default colors: WT1=#3A90FF, WT2=#FF8C00, MFI=#26A69A.
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

