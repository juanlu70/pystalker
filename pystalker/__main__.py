#!/usr/bin/env python3
"""
PyStalker - Main entry point
"""
import sys
import warnings
from PyQt6.QtWidgets import QApplication
from pystalker.gui.main_window import PyStalkerWindow


def qt_message_handler(mode, context, message):
    if 'Painter path exceeds' in message:
        return
    print(message)

def main():
    from PyQt6.QtCore import qInstallMessageHandler
    qInstallMessageHandler(qt_message_handler)
    
    app = QApplication(sys.argv)
    app.setApplicationName("PyStalker")
    app.setApplicationVersion("0.1.0")
    
    window = PyStalkerWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
