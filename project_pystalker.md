---
name: pystalker
description: a Python QT and TALib program to emulate the old qtstalker based on Qtstalker old code
---

## DESCRIPTION ##

This is a port to python of Qtstalker, in the directory qtstalker-0.36/ is all the source code of the original qtstalker, you must read and understand all its parts and deploy the same in python using:

- PyQT6 library <-- For the general graphic interface and program.
- PyTA library <-- For all the trading indicators.

The program is used to download and analyze trading graphs in many timeframes: 1m, 5m, 10m, 15m, 30m, 1H, 1D, 1W, 1m, maybe more timeframes will be added in the future, but these are the initial requirement.

The program has a left panel list with all the assets to analyze, a central box with a graph of the prices and some stackable boxes behind central graph to show indicators.

Also the program can download data from Yahoo Finance API and CSV files, for Yahoo Finance it is needed a ticker name, for CSV need a CSV format and a file name.


## CONSTRAINTS ##

- By default you must show a candle graph in the central box of the program.
- All previous assets loaded from Yahoo or CSV must be visible at left vertical panel.
- All indicators from TALib must be available in the program, some are to be shown in the central graph, like moving averages (and others), other indicators like MACD, RSI, CCI, etc. must be stacked in small horizontal boxes at the borttom of central graph box.
- Don't take decisions for yourself, ask anything you don't know, I will always answer you.
- The program must be the most similar to original C++ LibQt3 Qtstalker code, use their own icons if you can, bacause it is free source software.


