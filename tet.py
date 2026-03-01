import mss
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
import sys

QApplication.setHighDpiScaleFactorRoundingPolicy(
    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
)
app = QApplication(sys.argv)
screen = app.primaryScreen()
print(f"Qt logical size:    {screen.size().width()} x {screen.size().height()}")
print(f"Qt physical size:   {screen.geometry().width()} x {screen.geometry().height()}")
print(f"Device pixel ratio: {screen.devicePixelRatio()}")

with mss.mss() as sct:
    m = sct.monitors[1]
    print(f"mss capture size:   {m['width']} x {m['height']}")

ratio = m['width'] / screen.size().width()
print(f"Actual DPI ratio:   {ratio:.4f}")