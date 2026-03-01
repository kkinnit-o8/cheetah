import sys
import cv2
import numpy as np
import mss
import argparse
import threading
import ctypes
import time
from ctypes import wintypes

from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import Qt, QTimer, QPoint
from PyQt6.QtGui import QPainter, QColor, QBrush, QPen


# ── Win32 helpers ─────────────────────────────────────────────────────────────
def force_topmost(hwnd):
    ctypes.windll.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0002 | 0x0001)


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx",          wintypes.LONG),
        ("dy",          wintypes.LONG),
        ("mouseData",   wintypes.DWORD),
        ("dwFlags",     wintypes.DWORD),
        ("time",        wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]
    _anonymous_ = ("_input",)
    _fields_    = [("type", wintypes.DWORD), ("_input", _INPUT)]

MOUSEEVENTF_MOVE        = 0x0001
MOUSEEVENTF_LEFTDOWN    = 0x0002
MOUSEEVENTF_LEFTUP      = 0x0004
MOUSEEVENTF_ABSOLUTE    = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

def _send_input(*inputs):
    arr = (INPUT * len(inputs))(*inputs)
    ctypes.windll.user32.SendInput(len(arr), arr, ctypes.sizeof(INPUT))

def move_and_click(phys_x: int, phys_y: int, click: bool = True):
    """
    Move mouse using PHYSICAL pixel coordinates (what mss captures).
    SendInput ABSOLUTE maps 0-65535 across the physical virtual desktop.
    """
    # These return PHYSICAL pixels on high-DPI systems
    vw = ctypes.windll.user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN (physical)
    vh = ctypes.windll.user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN (physical)
    vx = ctypes.windll.user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN  (physical)
    vy = ctypes.windll.user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN  (physical)

    norm_x = int((phys_x - vx) * 65535 / vw)
    norm_y = int((phys_y - vy) * 65535 / vh)

    move = INPUT(type=0)
    move.mi.dx      = norm_x
    move.mi.dy      = norm_y
    move.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK

    if click:
        down = INPUT(type=0)
        down.mi.dwFlags = MOUSEEVENTF_LEFTDOWN
        up = INPUT(type=0)
        up.mi.dwFlags   = MOUSEEVENTF_LEFTUP
        _send_input(move, down, up)
    else:
        _send_input(move)


# ── Detection thread ──────────────────────────────────────────────────────────
class DetectionThread(threading.Thread):
    def __init__(self, template_bgr: np.ndarray, threshold: float,
                 skip_frames: int, roi: tuple | None,
                 dpi_ratio: float, min_scale: float, max_scale: float,
                 scale_steps: int):
        super().__init__(daemon=True)

        self.threshold   = threshold
        self.skip_frames = max(1, skip_frames)
        self.roi         = roi
        self.dpi_ratio   = dpi_ratio
        self._running    = True

        self._lock    = threading.Lock()
        self._found   = False
        self._phys_cx = -1   # physical pixels (for mouse)
        self._phys_cy = -1
        self._log_cx  = -1   # logical pixels  (for Qt drawing)
        self._log_cy  = -1

        tmpl_gray = cv2.cvtColor(template_bgr, cv2.COLOR_BGR2GRAY)
        self.tmpl_h, self.tmpl_w = tmpl_gray.shape[:2]

        scales = np.geomspace(min_scale, max_scale, num=scale_steps)
        self.scaled_tmpls = []
        for s in scales:
            w = max(4, int(self.tmpl_w * s))
            h = max(4, int(self.tmpl_h * s))
            resized = cv2.resize(tmpl_gray, (w, h), interpolation=cv2.INTER_AREA)
            edges   = self._edges(resized)
            self.scaled_tmpls.append((s, edges, w, h))

        self.tmpl_hist = self._hist(template_bgr)

        print(f"[INFO] Template: {self.tmpl_w}x{self.tmpl_h}px")
        print(f"[INFO] Scales: {scale_steps} steps {min_scale:.2f}x → {max_scale:.2f}x")
        print(f"[INFO] DPI ratio: {dpi_ratio:.4f}  (physical/logical)")

    @staticmethod
    def _edges(gray):
        return cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 30, 100)

    @staticmethod
    def _hist(bgr):
        hsv  = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [18, 16], [0, 180, 0, 256])
        cv2.normalize(hist, hist)
        return hist

    def read(self):
        """Returns (found, phys_cx, phys_cy, log_cx, log_cy)"""
        with self._lock:
            return self._found, self._phys_cx, self._phys_cy, self._log_cx, self._log_cy

    def stop(self):
        self._running = False

    def run(self):
        sct     = mss.mss()
        monitor = sct.monitors[1]
        frame_count = 0

        while self._running:
            frame_count += 1

            raw       = sct.grab(monitor)
            frame_bgr = cv2.cvtColor(
                np.frombuffer(raw.raw, dtype=np.uint8).reshape(raw.height, raw.width, 4),
                cv2.COLOR_BGRA2BGR
            )
            gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)

            if frame_count % self.skip_frames != 0:
                continue

            if self.roi:
                x1, y1, x2, y2 = self.roi
                s_gray = gray[y1:y2, x1:x2]
                s_bgr  = frame_bgr[y1:y2, x1:x2]
                ox, oy = x1, y1
            else:
                s_gray = gray
                s_bgr  = frame_bgr
                ox, oy = 0, 0

            s_edges  = self._edges(s_gray)
            sh, sw   = s_edges.shape[:2]
            best_val = -1.0
            best_phys_cx = -1
            best_phys_cy = -1

            for (s, tmpl_edges, tw, th) in self.scaled_tmpls:
                if tw >= sw or th >= sh:
                    continue

                result = cv2.matchTemplate(s_edges, tmpl_edges, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(result)

                if max_val <= best_val:
                    continue

                rx, ry = max_loc
                region = s_bgr[ry:ry+th, rx:rx+tw]
                if region.size == 0:
                    continue
                sim = cv2.compareHist(self.tmpl_hist, self._hist(region), cv2.HISTCMP_CORREL)
                if sim < 0.25:
                    continue

                best_val     = max_val
                # These are PHYSICAL pixel coords (mss space)
                best_phys_cx = int((rx + tw / 2) + ox)
                best_phys_cy = int((ry + th / 2) + oy)

            if best_val < self.threshold:
                with self._lock:
                    self._found = False
                continue

            # Physical → logical for Qt
            log_cx = int(best_phys_cx / self.dpi_ratio)
            log_cy = int(best_phys_cy / self.dpi_ratio)

            print(f"[DEBUG] val={best_val:.3f}  "
                  f"phys=({best_phys_cx},{best_phys_cy})  "
                  f"logical=({log_cx},{log_cy})")

            with self._lock:
                self._found   = True
                self._phys_cx = best_phys_cx
                self._phys_cy = best_phys_cy
                self._log_cx  = log_cx
                self._log_cy  = log_cy


# ── Qt overlay ────────────────────────────────────────────────────────────────
class Overlay(QWidget):
    def __init__(self, template_path: str, fps: int, threshold: float,
                 skip_frames: int, roi: tuple | None, dpi_ratio: float,
                 min_scale: float, max_scale: float, scale_steps: int,
                 debug: bool, shoot: bool, shoot_delay: float):
        super().__init__()

        self.dot_radius  = 10
        self.dot_center  = QPoint(-100, -100)
        self.debug       = debug
        self.shoot       = shoot
        self.shoot_delay = shoot_delay
        self._last_shot  = 0.0

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.showFullScreen()

        try:
            force_topmost(int(self.winId()))
            print("[INFO] Win32 HWND_TOPMOST set")
        except Exception as e:
            print(f"[WARN] Win32 topmost failed: {e}")

        tmpl = cv2.imread(template_path, cv2.IMREAD_COLOR)
        if tmpl is None:
            print(f"[ERROR] Cannot load: '{template_path}'")
            sys.exit(1)

        self.detector = DetectionThread(
            template_bgr=tmpl,
            threshold=threshold,
            skip_frames=skip_frames,
            roi=roi,
            dpi_ratio=dpi_ratio,
            min_scale=min_scale,
            max_scale=max_scale,
            scale_steps=scale_steps,
        )
        self.detector.start()

        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._poll)
        self.poll_timer.start(max(1, 1000 // fps))

        self.top_timer = QTimer(self)
        self.top_timer.timeout.connect(lambda: force_topmost(int(self.winId())))
        self.top_timer.start(500)

        if shoot:
            print(f"[INFO] --shoot enabled  delay={shoot_delay}s  ESC to quit")

    def _poll(self):
        found, phys_cx, phys_cy, log_cx, log_cy = self.detector.read()

        if found:
            # Qt draws using logical coords
            self.dot_center = QPoint(log_cx, log_cy)

            if self.shoot:
                now = time.monotonic()
                do_click = now - self._last_shot >= self.shoot_delay
                if do_click:
                    self._last_shot = now
                threading.Thread(
                    target=move_and_click,
                    # Mouse uses PHYSICAL coords — no dpi division needed
                    args=(phys_cx, phys_cy, do_click),
                    daemon=True
                ).start()
        else:
            self.dot_center = QPoint(-100, -100)

        self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.detector.stop()
            QApplication.quit()

    def closeEvent(self, event):
        self.detector.stop()
        super().closeEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        if self.dot_center.x() < 0:
            return

        r  = self.dot_radius
        cx = self.dot_center.x()
        cy = self.dot_center.y()

        if self.debug:
            pen = QPen(QColor(0, 255, 0, 220))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLine(cx - 60, cy, cx + 60, cy)
            painter.drawLine(cx, cy - 60, cx, cy + 60)
            painter.drawEllipse(cx - 30, cy - 30, 60, 60)

        painter.setPen(Qt.PenStyle.NoPen)

        glow = QColor(255, 220, 0, 120) if self.shoot else QColor(255, 60, 60, 100)
        painter.setBrush(QBrush(glow))
        painter.drawEllipse(cx - r*2, cy - r*2, r*4, r*4)

        painter.setBrush(QBrush(QColor(255, 255, 255, 230)))
        painter.drawEllipse(cx - r - 2, cy - r - 2, (r+2)*2, (r+2)*2)

        dot_col = QColor(255, 180, 0) if self.shoot else QColor(220, 30, 30)
        painter.setBrush(QBrush(dot_col))
        painter.drawEllipse(cx - r, cy - r, r*2, r*2)

        hr = max(2, r // 3)
        painter.setBrush(QBrush(QColor(255, 240, 180, 160)))
        painter.drawEllipse(cx - hr, cy - r + 2, hr, hr)


# ── CLI ───────────────────────────────────────────────────────────────────────
def parse_roi(s):
    try:
        parts = [int(v) for v in s.split(",")]
        assert len(parts) == 4
        return tuple(parts)
    except Exception:
        raise argparse.ArgumentTypeError("ROI must be x1,y1,x2,y2")


def detect_dpi_ratio() -> float:
    with mss.mss() as sct:
        mss_w = sct.monitors[1]["width"]
    qt_w  = QApplication.primaryScreen().size().width()
    ratio = mss_w / qt_w
    print(f"[INFO] mss={mss_w}px  Qt={qt_w}px  DPI ratio={ratio:.4f}")
    return ratio


def main():
    p = argparse.ArgumentParser(description="Any-size multi-scale edge overlay tracker")
    p.add_argument("template",       nargs="?", default="target.png")
    p.add_argument("--fps",          type=int,   default=60)
    p.add_argument("--threshold",    type=float, default=0.3)
    p.add_argument("--skip",         type=int,   default=2)
    p.add_argument("--min-scale",    type=float, default=0.3)
    p.add_argument("--max-scale",    type=float, default=2.0)
    p.add_argument("--scale-steps",  type=int,   default=20)
    p.add_argument("--roi",          type=parse_roi, default=None)
    p.add_argument("--dpi",          type=float, default=None)
    p.add_argument("--debug",        action="store_true")
    p.add_argument("--shoot",        action="store_true",
                   help="Move mouse to target and click. ESC to quit.")
    p.add_argument("--shoot-delay",  type=float, default=0.1,
                   help="Seconds between clicks (default 0.1)")
    args = p.parse_args()

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    dpi_ratio = args.dpi if args.dpi else detect_dpi_ratio()

    overlay = Overlay(
        template_path=args.template,
        fps=args.fps,
        threshold=args.threshold,
        skip_frames=args.skip,
        roi=args.roi,
        dpi_ratio=dpi_ratio,
        min_scale=args.min_scale,
        max_scale=args.max_scale,
        scale_steps=args.scale_steps,
        debug=args.debug,
        shoot=args.shoot,
        shoot_delay=args.shoot_delay,
    )
    overlay.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()