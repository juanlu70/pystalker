from PyQt6.QtCore import Qt
import pyqtgraph as pg


class PriceAxisItem(pg.AxisItem):
    def tickStrings(self, values, scale, spacing):
        return [f'{v:.2f}' for v in values]


SNAP_VALUES = {'': 0, 'open': 1, 'high': 2, 'low': 3, 'close': 4}
SNAP_INDEX_TO_MODE = {v: k for k, v in SNAP_VALUES.items()}
SNAP_LABELS = ["None", "Open", "High", "Low", "Close"]