"""
J.A.R.V.I.S. HUD — Qt-native macOS-style notification card.

Built on PySide6 / Qt6 so that everything renders **anti-aliased** with
real drop shadow, smooth height-resize animations, and translucent
backgrounds — none of which are achievable in tkinter on Windows.

Three height modes (auto-resize with cubic easing 280 ms):

  IDLE     420×96   reactor + title + chip strip + clock
  LISTEN   420×140  + animated mic waveform on the reactor core
  ACTIVE   420×220  + transcript + streaming response

Public API stays the same as the previous tkinter HUD so main.py
doesn't need to know we switched toolkits:

    hud = JarvisHUD(on_pause_toggle=cb)
    hud.set_state("LISTENING")
    hud.set_transcript("hello")
    hud.set_response("hi sir")
    hud.append_response(" — what can I do?")
    hud.run()             # blocks (QApplication.exec)
    hud.quit()            # thread-safe close

Cross-thread calls go through Qt signals with QueuedConnection so the
voice pipeline thread can safely poke the HUD.
"""

from __future__ import annotations

import ctypes
import math
import random
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from PySide6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, QRect,
    QRectF, QPointF, Signal, QSize,
)
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QGuiApplication,
    QPainterPath, QLinearGradient, QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QFrame, QHBoxLayout, QVBoxLayout,
    QTextEdit, QGraphicsDropShadowEffect, QMenu, QSizePolicy,
)


# ─────────────────────────────────────────────────────────────────
# Windows acrylic / Liquid-Glass backdrop API
# ─────────────────────────────────────────────────────────────────
# Two paths, applied in order (best-effort):
#   1) Win 11 22H2+: DwmSetWindowAttribute(DWMWA_SYSTEMBACKDROP_TYPE,
#      DWMSBT_TRANSIENTWINDOW) — Acrylic with hardware composition.
#   2) Fallback Win 10 1803+ / Win 11: undocumented
#      SetWindowCompositionAttribute(ACCENT_ENABLE_ACRYLICBLURBEHIND).
#
# Both make the OS gaussian-blur whatever's behind the window (wallpaper,
# other apps), then composite the window pixels on top. Combined with a
# very-low-alpha tint in our paintEvent, you get true frosted glass.

_DWMWA_SYSTEMBACKDROP_TYPE = 38
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMSBT_TRANSIENTWINDOW = 3   # Acrylic
_DWMSBT_MAINWINDOW      = 2   # Mica (kinder to GPU but less blur)
_DWMWCP_ROUND = 2

_WCA_ACCENT_POLICY = 19
_ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
_ACCENT_ENABLE_BLURBEHIND        = 3


class _ACCENT_POLICY(ctypes.Structure):
    _fields_ = [
        ("AccentState", ctypes.c_int),
        ("AccentFlags", ctypes.c_int),
        ("GradientColor", ctypes.c_uint),
        ("AnimationId", ctypes.c_int),
    ]


class _WCAD(ctypes.Structure):
    _fields_ = [
        ("Attribute", ctypes.c_int),
        ("Data", ctypes.POINTER(_ACCENT_POLICY)),
        ("SizeOfData", ctypes.c_size_t),
    ]


# ─────────────────────────────────────────────────────────────────
# Blocking IO helpers — invoked from background threads only, NEVER
# from the GUI thread. Each one swallows its own exceptions and
# returns a string ("" on failure) or a float for GPU%.
# ─────────────────────────────────────────────────────────────────
def _read_gpu_pct_blocking() -> float:
    try:
        res = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=2,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return float(res.stdout.strip().splitlines()[0])
    except Exception:
        return 0.0


def _fetch_weather_blocking() -> str:
    try:
        import requests
        resp = requests.get(
            "https://wttr.in/Bucharest?format=j1",
            timeout=5,
            headers={"User-Agent": "curl/7.68.0"},
        )
        cur = resp.json()["current_condition"][0]
        return f"{cur['temp_C']}° {cur['weatherDesc'][0]['value'][:18]}"
    except Exception:
        return ""


def _fetch_now_playing_blocking() -> str:
    try:
        from tools.spotify import spotify_now_playing
        raw = str(spotify_now_playing())
        t = raw.replace("Now playing:", "").strip()
        if "nothing" in t.lower() or "not playing" in t.lower():
            return ""
        return t[:32]
    except Exception:
        return ""


def _fetch_next_meeting_blocking() -> str:
    try:
        from tools.calendar_tool import _get_calendar_service
        from datetime import timedelta as _td
        svc = _get_calendar_service()
        now = datetime.now(timezone.utc)
        ev = svc.events().list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=(now + _td(hours=12)).isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=1,
        ).execute().get("items", []) or []
        if not ev:
            return ""
        e = ev[0]
        start = e.get("start", {}).get("dateTime")
        if not start:
            return ""
        ds = datetime.fromisoformat(start)
        if ds.tzinfo is None:
            ds = ds.replace(tzinfo=timezone.utc)
        mins = max(0, int((ds - now).total_seconds() / 60))
        title = (e.get("summary") or "(untitled)")[:22]
        if mins < 60:
            return f"🗓 {title} in {mins}m"
        return f"🗓 {title} {ds.astimezone().strftime('%H:%M')}"
    except Exception:
        return ""


def _fetch_battery_blocking() -> str:
    try:
        import psutil
        bat = psutil.sensors_battery()
        if bat is None:
            return ""
        pct = int(bat.percent or 0)
        return f"🔋 {pct}% ⚡" if bat.power_plugged else f"🔋 {pct}%"
    except Exception:
        return ""


def _enable_native_rounded_corners(hwnd: int) -> None:
    """Ask Win 11 DWM to round the window corners natively (~8 px).
    Cheap, no compositing overhead — unlike acrylic / translucency. Silently
    no-ops on Win 10 / non-Windows."""
    if not sys.platform.startswith("win"):
        return
    try:
        corner = ctypes.c_int(_DWMWCP_ROUND)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd), _DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(corner), ctypes.sizeof(corner),
        )
        dark = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd), _DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(dark), ctypes.sizeof(dark),
        )
    except Exception:
        pass


# ── State constants ───────────────────────────────────────────────
STANDBY   = "STANDBY"
LISTENING = "LISTENING"
THINKING  = "THINKING"
SPEAKING  = "SPEAKING"
PAUSED    = "PAUSED"


# ── Palette (painted glass — no OS blur, more opaque to compensate) ──
PANEL_EDGE  = QColor(180, 210, 240, 90)     # cool-tinted glass edge
HIGHLIGHT   = QColor(255, 255, 255, 140)    # bright top specular
GLOW_INNER  = QColor(120, 200, 255, 38)     # cyan inner glow
TEXT        = QColor(240, 244, 248)
MUTED       = QColor(170, 180, 192)
DIM         = QColor(110, 122, 138)
DIVIDER     = QColor(255, 255, 255, 18)
ACCENT      = QColor(120, 220, 255)
ACCENT_DIM  = QColor(58, 130, 158)
AMBER       = QColor(255, 188, 96)
GREEN       = QColor(110, 225, 124)
RED         = QColor(255, 116, 116)
PURPLE      = QColor(200, 160, 255)


_STATE_COLOR = {
    STANDBY:   DIM,
    LISTENING: GREEN,
    THINKING:  AMBER,
    SPEAKING:  ACCENT,
    PAUSED:    RED,
}
_STATE_LABEL = {
    STANDBY:   "Idle",
    LISTENING: "Listening",
    THINKING:  "Thinking",
    SPEAKING:  "Speaking",
    PAUSED:    "Paused",
}


# ── Geometry ──────────────────────────────────────────────────────
W           = 420
H_IDLE      = 96
H_LISTEN    = 140
H_ACTIVE    = 220
RADIUS      = 22
# SHADOW_PAD must be ≥ drop_shadow_blur + |drop_shadow_offset| or the
# shadow gets clipped at window boundary → visible rectangle artifact.
SHADOW_PAD  = 56
EDGE_MARGIN = 20
BOTTOM_MARGIN = 60


# ─────────────────────────────────────────────────────────────────
# ReactorWidget — custom-painted arc reactor, anti-aliased
# ─────────────────────────────────────────────────────────────────
class ReactorWidget(QWidget):
    """Anti-aliased arc reactor — three concentric arcs (CPU/RAM/GPU),
    rotating outer ticks, breathing core, optional mic waveform overlay."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(64, 64)
        self._cpu = 0.0
        self._ram = 0.0
        self._gpu = 0.0
        self._state_color = DIM
        self._phase = 0.0
        self._wave = [0.0] * 22
        self._show_wave = False
        self._wave_color = GREEN

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        # 60 ms = ~16 fps — smooth enough for slow arc rotation, way cheaper
        # than 30 fps when the parent has acrylic backdrop composition.
        self._timer.start(60)

    def setMetrics(self, cpu: float, ram: float, gpu: float) -> None:
        self._cpu, self._ram, self._gpu = cpu, ram, gpu

    def setStateColor(self, c: QColor) -> None:
        self._state_color = c

    def setShowWave(self, on: bool, color: QColor) -> None:
        self._show_wave = on
        self._wave_color = color

    def _tick(self) -> None:
        self._phase = (self._phase + 0.05) % (2 * math.pi)
        if self._show_wave:
            for i in range(len(self._wave)):
                target = random.uniform(0.20, 0.95)
                self._wave[i] = self._wave[i] * 0.5 + target * 0.5
        else:
            for i in range(len(self._wave)):
                self._wave[i] *= 0.85
        self.update()

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHints(
            QPainter.Antialiasing | QPainter.SmoothPixmapTransform
            | QPainter.TextAntialiasing,
        )
        cx, cy = self.width() / 2, self.height() / 2
        outer_r = min(cx, cy) - 4
        mid_r   = outer_r - 7
        inner_r = mid_r - 6
        gpu_r   = inner_r - 5
        core_r  = 8

        # ── housing disc (the dial / "cadran" behind everything) ─
        # Soft dark well that grounds the reactor visually even on a
        # heavily blurred glass backdrop.
        housing_outer = QRadialGradient(QPointF(cx, cy), outer_r + 3)
        housing_outer.setColorAt(0.0, QColor(0, 0, 0, 90))
        housing_outer.setColorAt(0.7, QColor(0, 0, 0, 60))
        housing_outer.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(housing_outer))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), outer_r + 3, outer_r + 3)

        # Inner darker cup for the core to sit in
        p.setBrush(QBrush(QColor(8, 12, 18, 160)))
        p.drawEllipse(QPointF(cx, cy), mid_r + 2, mid_r + 2)

        # ── soft aura behind the core ────────────────────────────
        aura_r = core_r + 5 + 2 * math.sin(self._phase * 2)
        aura_color = QColor(self._state_color)
        aura_color.setAlpha(70)
        p.setBrush(QBrush(aura_color))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), aura_r, aura_r)

        # ── outer rotating tick marks (8) ────────────────────────
        p.setPen(QPen(ACCENT_DIM, 1.0))
        for i in range(8):
            a = self._phase + i * (math.pi / 4)
            x1 = cx + math.cos(a) * (outer_r - 2)
            y1 = cy + math.sin(a) * (outer_r - 2)
            x2 = cx + math.cos(a) * outer_r
            y2 = cy + math.sin(a) * outer_r
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # outer ring
        p.setPen(QPen(ACCENT_DIM, 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), outer_r, outer_r)

        # ── CPU arc (clockwise, cyan) ────────────────────────────
        cpu_extent = max(0.0, min(360.0, self._cpu * 3.6))
        rect = QRectF(cx - mid_r, cy - mid_r, 2 * mid_r, 2 * mid_r)
        p.setPen(QPen(ACCENT, 2.2))
        p.drawArc(rect, int(90 * 16), int(-cpu_extent * 16))

        # remainder dim
        if cpu_extent < 360:
            p.setPen(QPen(QColor(40, 50, 60, 150), 1.5))
            p.drawArc(rect, int((90 - cpu_extent) * 16),
                      int(-(360 - cpu_extent) * 16))

        # ── RAM arc (counter-clockwise, amber) ───────────────────
        ram_extent = max(0.0, min(360.0, self._ram * 3.6))
        rect = QRectF(cx - inner_r, cy - inner_r, 2 * inner_r, 2 * inner_r)
        p.setPen(QPen(AMBER, 2.0))
        p.drawArc(rect, int(90 * 16), int(ram_extent * 16))

        # ── GPU arc (purple, smallest) ───────────────────────────
        if self._gpu > 0:
            gpu_extent = max(0.0, min(360.0, self._gpu * 3.6))
            rect = QRectF(cx - gpu_r, cy - gpu_r, 2 * gpu_r, 2 * gpu_r)
            p.setPen(QPen(PURPLE, 1.8))
            p.drawArc(rect, int(270 * 16), int(-gpu_extent * 16))

        # ── core (breathing) ─────────────────────────────────────
        breath = 1.0 + 0.10 * math.sin(self._phase * 3)
        cr = core_r * breath
        p.setBrush(QBrush(self._state_color))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), cr, cr)

        # ── waveform overlay (LISTENING/SPEAKING) ────────────────
        if self._show_wave:
            n = len(self._wave)
            bar_w = 2.0
            bar_gap = 1.0
            total_w = n * bar_w + (n - 1) * bar_gap
            x0 = cx - total_w / 2
            max_h = 16
            p.setPen(QPen(self._wave_color, 2.0))
            for i, lvl in enumerate(self._wave):
                h = max(2, lvl * max_h)
                x = x0 + i * (bar_w + bar_gap)
                p.drawLine(QPointF(x, cy - h / 2),
                           QPointF(x, cy + h / 2))


# ─────────────────────────────────────────────────────────────────
# StateLed — small pulsing dot top-left of the card
# ─────────────────────────────────────────────────────────────────
class StateLed(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self._color = DIM
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(150)   # gentle pulse — keeps parent quiet

    def setColor(self, c: QColor) -> None:
        self._color = c

    def _tick(self) -> None:
        self._phase = (self._phase + 0.10) % (2 * math.pi)
        self.update()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2

        # halo (alpha-pulsing)
        halo_alpha = int(60 + 50 * (0.5 + 0.5 * math.sin(self._phase)))
        halo = QColor(self._color)
        halo.setAlpha(halo_alpha)
        p.setBrush(QBrush(halo))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), 6, 6)

        # core dot
        p.setBrush(QBrush(self._color))
        p.drawEllipse(QPointF(cx, cy), 3, 3)


# ─────────────────────────────────────────────────────────────────
# CardFrame — rounded glass card painted entirely in Qt (AA, alpha-correct)
# ─────────────────────────────────────────────────────────────────
class CardFrame(QFrame):
    """Painted glass card. The surrounding parent is translucent, so the
    SHADOW_PAD margin around this widget is fully transparent — the
    QGraphicsDropShadowEffect attached by JarvisHUD lives in that margin.
    """

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHints(
            QPainter.Antialiasing | QPainter.SmoothPixmapTransform
            | QPainter.TextAntialiasing,
        )
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, RADIUS, RADIUS)

        # ── 1) Body — vertical gradient, semi-opaque dark glass ──
        body = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        body.setColorAt(0.0, QColor(34, 40, 50, 235))
        body.setColorAt(0.5, QColor(24, 30, 38, 230))
        body.setColorAt(1.0, QColor(18, 22, 28, 230))
        p.fillPath(path, QBrush(body))

        # ── 2) Subtle inner cyan glow — Stark "charged" feel ────
        glow_path = QPainterPath()
        glow_rect = rect.adjusted(2, 2, -2, -2)
        glow_path.addRoundedRect(glow_rect, RADIUS - 2, RADIUS - 2)
        p.setPen(QPen(GLOW_INNER, 1.5))
        p.drawPath(glow_path)

        # ── 3) Specular sheen — diagonal light sweep ─────────────
        sheen = QLinearGradient(
            rect.topLeft(),
            QPointF(rect.x() + rect.width() * 0.55,
                    rect.y() + rect.height() * 0.55),
        )
        sheen.setColorAt(0.00, QColor(255, 255, 255, 28))
        sheen.setColorAt(0.35, QColor(255, 255, 255, 8))
        sheen.setColorAt(1.00, QColor(255, 255, 255, 0))
        p.fillPath(path, QBrush(sheen))

        # ── 4) Outer cool-tinted border ──────────────────────────
        p.setPen(QPen(PANEL_EDGE, 1.0))
        p.drawPath(path)

        # ── 5) Bright specular highlight on the top arc only ────
        p.setClipRect(QRectF(rect.x(), rect.y(), rect.width(), 16))
        top_path = QPainterPath()
        top_inset = rect.adjusted(1.5, 1.5, -1.5, -1.5)
        top_path.addRoundedRect(top_inset, RADIUS - 1, RADIUS - 1)
        p.setPen(QPen(HIGHLIGHT, 1.2))
        p.drawPath(top_path)
        p.setClipping(False)

        # ── 6) Faint dark line on the bottom arc — anchor ───────
        p.setClipRect(QRectF(rect.x(), rect.y() + rect.height() - 14,
                             rect.width(), 14))
        bot_path = QPainterPath()
        bot_inset = rect.adjusted(1.5, 1.5, -1.5, -1.5)
        bot_path.addRoundedRect(bot_inset, RADIUS - 1, RADIUS - 1)
        p.setPen(QPen(QColor(0, 0, 0, 70), 1.0))
        p.drawPath(bot_path)
        p.setClipping(False)


# ─────────────────────────────────────────────────────────────────
# JarvisHUD — main top-level widget
# ─────────────────────────────────────────────────────────────────
class JarvisHUD(QWidget):
    """Slim macOS-style notification card. Public methods are
    thread-safe — they emit signals that fire on the GUI thread."""

    # Signals (queued connection makes them thread-safe)
    _state_sig = Signal(str)
    _transcript_sig = Signal(str)
    _resp_set_sig = Signal(str)
    _resp_append_sig = Signal(str)
    _quit_sig = Signal()

    # ── lifecycle ────────────────────────────────────────────────
    def __init__(self, on_pause_toggle=None) -> None:
        # Ensure a QApplication exists before any widget construction
        self._app = QApplication.instance() or QApplication(sys.argv)

        super().__init__()
        self._on_pause_toggle = on_pause_toggle
        self._state = STANDBY
        self._mode = "idle"
        self._paused = False
        self._heartbeat_age = 999.0
        self._fade_timer: Optional[QTimer] = None
        self._drag_pos: Optional[QPointF] = None
        self._anim: Optional[QPropertyAnimation] = None

        # ── window flags ────────────────────────────────────────
        # Translucent frameless on-top window. The glass shape is painted
        # by CardFrame inside; the SHADOW_PAD margin holds the drop shadow.
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setWindowTitle("J.A.R.V.I.S.")

        self._corners_applied = False

        # Cached values populated by background pollers — GUI thread reads
        # only these, never blocks on subprocess / HTTP. Default-empty until
        # the first background tick fills them in.
        self._cache_lock = threading.Lock()
        self._cached_gpu = 0.0
        self._cached_weather = ""
        self._cached_playing = ""
        self._cached_meeting = ""
        self._cached_battery = ""
        self._stop_pollers = threading.Event()

        self._build_ui()
        self._reposition(H_IDLE)
        self.setFocusPolicy(Qt.StrongFocus)

        # Wire signals — QueuedConnection makes them thread-safe
        self._state_sig.connect(self._apply_state, Qt.QueuedConnection)
        self._transcript_sig.connect(self._apply_transcript, Qt.QueuedConnection)
        self._resp_set_sig.connect(self._apply_resp_set, Qt.QueuedConnection)
        self._resp_append_sig.connect(self._apply_resp_append, Qt.QueuedConnection)
        self._quit_sig.connect(self.close, Qt.QueuedConnection)

        # Timers (pollers)
        self._t_badges = QTimer(self)
        self._t_badges.timeout.connect(self._tick_badges)
        self._t_badges.start(2500)

        self._t_metrics = QTimer(self)
        self._t_metrics.timeout.connect(self._tick_metrics)
        self._t_metrics.start(1500)

        self._t_clock = QTimer(self)
        self._t_clock.timeout.connect(self._tick_clock)
        self._t_clock.start(1000)

        self._t_extras = QTimer(self)
        self._t_extras.timeout.connect(self._tick_extras)
        self._t_extras.start(8000)

        # Background pollers — run on daemon threads so subprocess + HTTP
        # work never blocks the GUI thread. They drop results into
        # _cached_* via _cache_lock; GUI timers just read.
        threading.Thread(
            target=self._bg_metrics_loop, daemon=True,
            name="hud-bg-metrics",
        ).start()
        threading.Thread(
            target=self._bg_extras_loop, daemon=True,
            name="hud-bg-extras",
        ).start()

        # Initial paint
        self._tick_clock()
        self._tick_metrics()
        self._tick_badges()
        self._tick_extras()
        self._refresh_state_visuals()

    # ─────────────────────────────────────────────────────────────
    # UI build
    # ─────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        # Outer layout reserves SHADOW_PAD around the card so the drop
        # shadow (blur ≤ 40, offset 10) renders fully without being
        # clipped at the window edge.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW_PAD, SHADOW_PAD - 6,
                                 SHADOW_PAD, SHADOW_PAD + 6)
        outer.setSpacing(0)

        # The actual painted glass card
        self._card = CardFrame()
        outer.addWidget(self._card)

        # Real Gaussian-blur drop shadow (lives in the SHADOW_PAD area).
        # blur 40 + offset 10 = max extent 50, well within SHADOW_PAD=56.
        shadow = QGraphicsDropShadowEffect(self._card)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 180))
        self._card.setGraphicsEffect(shadow)

        # Card's content layout (was directly on JarvisHUD before)
        card_h = QHBoxLayout(self._card)
        card_h.setContentsMargins(14, 14, 14, 14)
        card_h.setSpacing(12)

        # ── Left column (LED + reactor) ─────────────────────────
        left = QVBoxLayout()
        left.setSpacing(6)
        left.setContentsMargins(0, 2, 0, 0)
        self._led = StateLed()
        left.addWidget(self._led, 0, Qt.AlignTop | Qt.AlignHCenter)
        self._reactor = ReactorWidget()
        left.addWidget(self._reactor, 0, Qt.AlignHCenter)
        left.addStretch()
        card_h.addLayout(left, 0)

        # ── Right column (text content) ─────────────────────────
        right = QVBoxLayout()
        right.setSpacing(2)
        right.setContentsMargins(0, 0, 0, 0)
        card_h.addLayout(right, 1)

        # Top row: title + clock/date
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        self._title = QLabel("J.A.R.V.I.S.")
        self._title.setStyleSheet(
            "font-family: 'Segoe UI'; font-size: 13pt; "
            "font-weight: 700; color: #e8ecef; letter-spacing: 1px;"
        )
        top.addWidget(self._title, 0, Qt.AlignTop)
        top.addStretch()

        clock_box = QVBoxLayout()
        clock_box.setSpacing(0)
        clock_box.setContentsMargins(0, 0, 0, 0)
        self._clock_lbl = QLabel("--:--")
        self._clock_lbl.setStyleSheet(
            "font-family: 'Consolas'; font-size: 11pt; "
            "font-weight: 700; color: #e8ecef;"
        )
        self._clock_lbl.setAlignment(Qt.AlignRight)
        self._date_lbl = QLabel("")
        self._date_lbl.setStyleSheet(
            "font-family: 'Segoe UI'; font-size: 9pt; color: #9aa3ad;"
        )
        self._date_lbl.setAlignment(Qt.AlignRight)
        clock_box.addWidget(self._clock_lbl)
        clock_box.addWidget(self._date_lbl)
        top.addLayout(clock_box, 0)
        right.addLayout(top)

        # State + pause row
        state_row = QHBoxLayout()
        state_row.setContentsMargins(0, 2, 0, 0)
        self._state_lbl = QLabel("Idle")
        self._state_lbl.setStyleSheet(
            "font-family: 'Segoe UI'; font-size: 9pt; "
            "color: #9aa3ad; letter-spacing: 0.5px;"
        )
        state_row.addWidget(self._state_lbl)
        state_row.addStretch()
        self._pause_btn = QLabel("⏸")
        self._pause_btn.setStyleSheet(
            "font-family: 'Segoe UI'; font-size: 12pt; color: #5b6470;"
        )
        self._pause_btn.setCursor(Qt.PointingHandCursor)
        self._pause_btn.setAttribute(Qt.WA_Hover, True)
        self._pause_btn.mousePressEvent = lambda _e: self._toggle_pause()
        state_row.addWidget(self._pause_btn)
        right.addLayout(state_row)

        # Chips row (rich text — colored separators built into HTML)
        self._chips_lbl = QLabel("")
        self._chips_lbl.setTextFormat(Qt.RichText)
        self._chips_lbl.setStyleSheet(
            "font-family: 'Segoe UI'; font-size: 9pt; "
            "font-weight: 600;"
        )
        self._chips_lbl.setMinimumHeight(18)
        self._chips_lbl.setWordWrap(False)
        right.addWidget(self._chips_lbl)

        # Transcript (italic, hidden in idle)
        self._transcript_lbl = QLabel("")
        self._transcript_lbl.setStyleSheet(
            "font-family: 'Segoe UI'; font-size: 10pt; "
            "font-style: italic; color: #b0b8c0; padding-top: 4px;"
        )
        self._transcript_lbl.setWordWrap(True)
        self._transcript_lbl.setMaximumHeight(40)
        self._transcript_lbl.hide()
        right.addWidget(self._transcript_lbl)

        # Response — read-only QTextEdit so streaming works smoothly
        self._resp = QTextEdit()
        self._resp.setReadOnly(True)
        self._resp.setFrameStyle(QFrame.NoFrame)
        self._resp.setStyleSheet(
            "QTextEdit { background: transparent; border: 0; "
            "color: #e8ecef; font-family: 'Segoe UI'; "
            "font-size: 10pt; padding: 0; } "
            "QScrollBar:vertical { background: transparent; width: 6px; } "
            "QScrollBar::handle:vertical { "
            "background: rgba(154, 163, 173, 100); border-radius: 3px; }"
        )
        self._resp.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._resp.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._resp.hide()
        right.addWidget(self._resp, 1)

        # Right-click menu
        self._menu = QMenu(self)
        self._menu.addAction("Pause / Resume", self._toggle_pause)
        self._menu.addAction("Restart Jarvis", self._restart_jarvis)
        self._menu.addSeparator()
        self._menu.addAction("Close HUD", self.close)

    # ─────────────────────────────────────────────────────────────
    # Geometry / mode resize
    # ─────────────────────────────────────────────────────────────
    def _reposition(self, h: int) -> None:
        screen = QGuiApplication.primaryScreen().availableGeometry()
        full_w = W + 2 * SHADOW_PAD
        full_h = h + 2 * SHADOW_PAD
        x = screen.right() - full_w - EDGE_MARGIN
        y = screen.bottom() - full_h - BOTTOM_MARGIN
        self.setGeometry(x, y, full_w, full_h)

    def _resize_to(self, h: int) -> None:
        # Snap — animating geometry triggers extra paints + cascade layouts.
        self._reposition(h)

    def _resolve_mode(self) -> str:
        if self._state == LISTENING:
            return "listen"
        if (self._transcript_lbl.text() and self._transcript_lbl.isVisible()) \
                or self._resp.toPlainText().strip():
            return "active"
        return "idle"

    def _apply_mode(self) -> None:
        new_mode = self._resolve_mode()
        if new_mode == self._mode:
            return
        self._mode = new_mode

        if new_mode == "idle":
            self._transcript_lbl.hide()
            self._resp.hide()
            self._resize_to(H_IDLE)
        elif new_mode == "listen":
            self._transcript_lbl.hide()
            self._resp.hide()
            self._resize_to(H_LISTEN)
        else:                       # active
            if self._transcript_lbl.text():
                self._transcript_lbl.show()
            if self._resp.toPlainText().strip():
                self._resp.show()
            self._resize_to(H_ACTIVE)

    # ─────────────────────────────────────────────────────────────
    # PUBLIC THREAD-SAFE API (matches old tkinter HUD)
    # ─────────────────────────────────────────────────────────────
    def set_state(self, state: str) -> None:
        self._state_sig.emit(state)

    def set_transcript(self, text: str) -> None:
        self._transcript_sig.emit(text)

    def set_response(self, text: str) -> None:
        self._resp_set_sig.emit(text)

    def append_response(self, chunk: str) -> None:
        self._resp_append_sig.emit(chunk)

    def run(self) -> None:
        self.show()
        self._app.exec()

    def quit(self) -> None:
        self._quit_sig.emit()

    # ─────────────────────────────────────────────────────────────
    # Slot implementations (run on GUI thread)
    # ─────────────────────────────────────────────────────────────
    def _apply_state(self, state: str) -> None:
        self._state = state
        self._refresh_state_visuals()
        if self._fade_timer:
            self._fade_timer.stop()
            self._fade_timer = None
        if state == STANDBY:
            self._fade_timer = QTimer(self)
            self._fade_timer.setSingleShot(True)
            self._fade_timer.timeout.connect(self._fade_content)
            self._fade_timer.start(8000)
        self._apply_mode()

    def _refresh_state_visuals(self) -> None:
        col = _STATE_COLOR.get(self._state, DIM)
        self._led.setColor(col)
        self._reactor.setStateColor(col)
        self._reactor.setShowWave(
            self._state in (LISTENING, SPEAKING),
            GREEN if self._state == LISTENING else ACCENT,
        )
        self._state_lbl.setText(_STATE_LABEL.get(self._state, "Idle"))
        self._state_lbl.setStyleSheet(
            f"font-family: 'Segoe UI'; font-size: 9pt; "
            f"color: rgba({col.red()}, {col.green()}, {col.blue()}, 240);"
        )

    def _apply_transcript(self, text: str) -> None:
        if text:
            self._transcript_lbl.setText(f"“{text}”")
            self._transcript_lbl.show()
        else:
            self._transcript_lbl.setText("")
            self._transcript_lbl.hide()
        self._apply_mode()

    def _apply_resp_set(self, text: str) -> None:
        self._resp.setPlainText(text or "")
        if text:
            self._resp.show()
        else:
            self._resp.hide()
        self._apply_mode()

    def _apply_resp_append(self, chunk: str) -> None:
        cur = self._resp.textCursor()
        cur.movePosition(cur.End)
        cur.insertText(chunk)
        self._resp.setTextCursor(cur)
        self._resp.ensureCursorVisible()
        if not self._resp.isVisible():
            self._resp.show()
        self._apply_mode()

    def _fade_content(self) -> None:
        self._transcript_lbl.setText("")
        self._transcript_lbl.hide()
        self._resp.clear()
        self._resp.hide()
        self._apply_mode()

    # ─────────────────────────────────────────────────────────────
    # Pollers
    # ─────────────────────────────────────────────────────────────
    def _tick_clock(self) -> None:
        now = datetime.now()
        self._clock_lbl.setText(now.strftime("%H:%M"))
        self._date_lbl.setText(now.strftime("%a %d %b"))

    def _tick_metrics(self) -> None:
        """Runs on the GUI thread — only fast reads (psutil + cached GPU).
        nvidia-smi runs on the bg metrics thread; we just read its result."""
        try:
            import psutil
            cpu = float(psutil.cpu_percent(interval=None))
            ram = float(psutil.virtual_memory().percent)
            with self._cache_lock:
                gpu = self._cached_gpu
            self._reactor.setMetrics(cpu, ram, gpu)
        except Exception:
            pass

    # ── Background loops (daemon threads) ────────────────────────
    def _bg_metrics_loop(self) -> None:
        """Run nvidia-smi every 3 s in the background. Results go to
        _cached_gpu — never blocks the GUI."""
        while not self._stop_pollers.is_set():
            gpu = _read_gpu_pct_blocking()
            with self._cache_lock:
                self._cached_gpu = gpu
            if self._stop_pollers.wait(3.0):
                break

    def _bg_extras_loop(self) -> None:
        """HTTP fetches every 30 s on a daemon thread. The GUI thread reads
        the cached strings via _chip_extra()."""
        # Tiny initial delay to let app finish booting
        if self._stop_pollers.wait(2.0):
            return
        while not self._stop_pollers.is_set():
            try:
                w = _fetch_weather_blocking()
            except Exception:
                w = ""
            try:
                np = _fetch_now_playing_blocking()
            except Exception:
                np = ""
            try:
                nm = _fetch_next_meeting_blocking()
            except Exception:
                nm = ""
            try:
                bat = _fetch_battery_blocking()
            except Exception:
                bat = ""
            with self._cache_lock:
                self._cached_weather = w
                self._cached_playing = np
                self._cached_meeting = nm
                self._cached_battery = bat
            if self._stop_pollers.wait(30.0):
                break

    def _tick_badges(self) -> None:
        try:
            self._update_chips()
        except Exception:
            pass

    def _tick_extras(self) -> None:
        try:
            self._update_chips(rotate_extras=True)
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────
    # Chip rendering — single rich-text label, dot separators
    # ─────────────────────────────────────────────────────────────
    def _update_chips(self, rotate_extras: bool = False) -> None:
        chips: list[tuple[str, str]] = []  # (text, hex color)

        # Presence
        chips.append(self._chip_presence())

        # Tasks
        c = self._chip_tasks()
        if c[0]:
            chips.append(c)

        # Watches
        c = self._chip_watches()
        if c[0]:
            chips.append(c)

        # Plan
        c = self._chip_plan()
        if c[0]:
            chips.append(c)

        # Rotating extra (next-meeting / now-playing / weather / battery)
        c = self._chip_extra()
        if c[0]:
            chips.append(c)

        # Build HTML
        parts: list[str] = []
        sep = '<span style="color:#5b6470;"> · </span>'
        for i, (text, color) in enumerate(chips):
            if i > 0:
                parts.append(sep)
            parts.append(
                f'<span style="color:{color};">'
                f'{self._html_escape(text)}</span>'
            )
        self._chips_lbl.setText("".join(parts))

    @staticmethod
    def _html_escape(s: str) -> str:
        return (s.replace("&", "&amp;")
                .replace("<", "&lt;").replace(">", "&gt;"))

    def _chip_presence(self) -> tuple[str, str]:
        try:
            from core import presence
            p = presence.get()
            if p is None:
                return ("—", "#5b6470")
            snap = p.snapshot()
            try:
                self._heartbeat_age = max(0.0, time.time() - p._mobile_last_seen)  # type: ignore[attr-defined]
            except Exception:
                pass
            if snap.quiet_hours:
                return ("Quiet hours", "#bf94ff")
            if snap.state == "at_pc":
                return ("At PC", "#5cd6ff")
            if snap.state == "phone_only":
                return ("On phone", "#ffb454")
            if snap.state == "away":
                return ("Away", "#9aa3ad")
            return ("—", "#5b6470")
        except Exception:
            return ("—", "#5b6470")

    def _chip_tasks(self) -> tuple[str, str]:
        try:
            from core import tasks
            recent = tasks.list_recent(limit=15)
            running = sum(1 for t in recent
                          if t["status"] in ("running", "pending"))
            if running:
                return (f"⚙ {running} running", "#ffb454")
        except Exception:
            pass
        return ("", "")

    def _chip_watches(self) -> tuple[str, str]:
        try:
            from core import watches
            ws = watches.list_all(include_archived=False)
            fired = sum(1 for w in ws if w["status"] == "fired")
            active = sum(1 for w in ws if w["status"] == "active")
            if fired:
                return (f"🔔 {fired} fired", "#ffb454")
            if active:
                return (f"👁 {active}", "#5cd6ff")
        except Exception:
            pass
        return ("", "")

    def _chip_plan(self) -> tuple[str, str]:
        try:
            from core import plans
            pending = plans.most_recent_pending()
            if pending:
                return (f"⚠ Plan #{pending['id']}", "#ffb454")
        except Exception:
            pass
        return ("", "")

    def _chip_extra(self) -> tuple[str, str]:
        """GUI-thread cheap read — pulls from cache only. Background thread
        keeps the cache fresh via _bg_extras_loop()."""
        candidates: list[tuple[str, str]] = []
        with self._cache_lock:
            nm = self._cached_meeting
            np = self._cached_playing
            w = self._cached_weather
            bat = self._cached_battery
        if nm:
            candidates.append((nm, "#bf94ff"))
        if np:
            candidates.append((f"♪ {np}", "#5dd76a"))
        if w:
            candidates.append((w, "#5cd6ff"))
        if bat:
            candidates.append((bat, "#9aa3ad"))
        if not candidates:
            return ("", "")
        idx = int(time.time() // 8) % len(candidates)
        return candidates[idx]

    # ─────────────────────────────────────────────────────────────
    # Pause / restart / drag / menu
    # ─────────────────────────────────────────────────────────────
    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        if self._paused:
            self._pause_btn.setText("▶")
            self._pause_btn.setStyleSheet(
                "font-family: 'Segoe UI'; font-size: 12pt; color: #5dd76a;"
            )
            self._apply_state(PAUSED)
        else:
            self._pause_btn.setText("⏸")
            self._pause_btn.setStyleSheet(
                "font-family: 'Segoe UI'; font-size: 12pt; color: #5b6470;"
            )
            self._apply_state(STANDBY)
        if self._on_pause_toggle:
            self._on_pause_toggle(self._paused)

    def _restart_jarvis(self) -> None:
        import os
        python = sys.executable
        script = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "main.py",
        )
        subprocess.Popen([python, script], cwd=os.path.dirname(script))
        self.close()
        os._exit(0)

    # ── window event overrides ──────────────────────────────────
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.pos()
        elif event.button() == Qt.RightButton:
            self._menu.popup(event.globalPosition().toPoint())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_pos and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.close()
        super().keyPressEvent(event)

    def showEvent(self, event) -> None:
        """First show — apply Win 11 native rounded corners via DWM.
        Cheap (no compositing overhead) and gives a clean ~8 px corner
        radius without the perf hit of translucent / acrylic windows."""
        super().showEvent(event)
        if not self._corners_applied:
            try:
                _enable_native_rounded_corners(int(self.winId()))
            except Exception:
                pass
            self._corners_applied = True
