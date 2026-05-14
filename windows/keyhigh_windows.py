from __future__ import annotations

import json
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from pynput import keyboard
from PySide6.QtCore import (QElapsedTimer, QObject, QPoint, QRect, Qt, QTimer,
                            Signal, QSize, QStandardPaths)
from PySide6.QtGui import QAction, QIcon, QImage, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QMainWindow, QMenu, QMessageBox,
                               QSystemTrayIcon, QWidget)


VIDEO_EXTS = {".mov", ".mp4", ".m4v"}
SIZE_CHOICES = [100, 200, 400, 600]


@dataclass(frozen=True)
class CharacterAssets:
    id: str
    display_name: str
    idle_path: Path
    run_path: Path


class CharacterLibrary:
    @staticmethod
    def load(resource_dir: Path) -> list[CharacterAssets]:
        if not resource_dir.exists():
            return []

        pairs: dict[str, dict[str, Path]] = {}
        for path in resource_dir.iterdir():
            if not path.is_file() or path.suffix.lower() not in VIDEO_EXTS:
                continue
            stem = path.stem
            if stem.endswith("_idle"):
                key = stem[:-5]
                pairs.setdefault(key, {})["idle"] = path
            elif stem.endswith("_run"):
                key = stem[:-4]
                pairs.setdefault(key, {})["run"] = path

        out: list[CharacterAssets] = []
        for key, urls in sorted(pairs.items()):
            idle = urls.get("idle")
            run = urls.get("run")
            if not idle or not run:
                continue
            out.append(
                CharacterAssets(
                    id=key,
                    display_name=key[:1].upper() + key[1:],
                    idle_path=idle,
                    run_path=run,
                )
            )
        return out


class TypingSpeedTracker(QObject):
    stateChanged = Signal(str)
    cpsChanged = Signal(float)

    def __init__(self) -> None:
        super().__init__()
        self._state = "idle"
        self._cps = 0.0
        self._timestamps: list[float] = []
        self._last_keystroke = 0.0
        self._idle_threshold = 0.5
        self._buffer_capacity = 16
        self._cps_window = 8
        self._idle_timer = QTimer(self)
        self._idle_timer.setInterval(100)
        self._idle_timer.timeout.connect(self._evaluate_idle_transition)
        self._idle_timer.start()

    @property
    def state(self) -> str:
        return self._state

    @property
    def cps(self) -> float:
        return self._cps

    def record_keystroke(self) -> None:
        now = time.monotonic()
        self._timestamps.append(now)
        if len(self._timestamps) > self._buffer_capacity:
            del self._timestamps[: len(self._timestamps) - self._buffer_capacity]
        self._last_keystroke = now

        new_cps = self._compute_cps()
        if abs(new_cps - self._cps) > 0.15:
            self._cps = new_cps
            self.cpsChanged.emit(self._cps)

        if self._state != "running":
            self._state = "running"
            self.stateChanged.emit(self._state)

    def _compute_cps(self) -> float:
        if len(self._timestamps) < 2:
            return 0.0
        recent = self._timestamps[-self._cps_window :]
        span = recent[-1] - recent[0]
        if span <= 0:
            return 0.0
        return (len(recent) - 1) / span

    def _evaluate_idle_transition(self) -> None:
        if self._state != "running":
            return
        if time.monotonic() - self._last_keystroke > self._idle_threshold:
            self._state = "idle"
            self._cps = 0.0
            self.stateChanged.emit(self._state)
            self.cpsChanged.emit(self._cps)


class CharacterInstance(QObject):
    changed = Signal()

    def __init__(
        self,
        *,
        character_id: str,
        size_raw: int,
        origin: QPoint,
        library: list[CharacterAssets],
        instance_id: Optional[str] = None,
    ) -> None:
        super().__init__()
        self.id = instance_id or self._make_id()
        self.character_id = character_id
        self.size_raw = size_raw
        self.origin = origin
        self.library = library
        self.click_boost = 0.0
        self._boost_timer = QTimer(self)
        self._boost_timer.setInterval(100)
        self._boost_timer.timeout.connect(self._tick_boost_decay)

    @staticmethod
    def _make_id() -> str:
        return f"inst-{int(time.time() * 1000)}-{os.getpid()}-{threading.get_ident()}"

    @property
    def character(self) -> Optional[CharacterAssets]:
        for item in self.library:
            if item.id == self.character_id:
                return item
        return self.library[0] if self.library else None

    @property
    def size(self) -> QSize:
        return QSize(self.size_raw, self.size_raw)

    def set_character_id(self, new_id: str) -> None:
        if any(item.id == new_id for item in self.library):
            self.character_id = new_id
            self.changed.emit()

    def set_size_raw(self, size_raw: int) -> None:
        self.size_raw = size_raw
        self.changed.emit()

    def update_origin(self, origin: QPoint) -> None:
        self.origin = origin
        self.changed.emit()

    def record_click(self) -> None:
        self.click_boost = min(self.click_boost + 4.0, 10.0)
        self.changed.emit()
        if not self._boost_timer.isActive():
            self._boost_timer.start()

    def _tick_boost_decay(self) -> None:
        if self.click_boost <= 0:
            self._boost_timer.stop()
            return
        self.click_boost = max(0.0, self.click_boost - 0.4)
        self.changed.emit()
        if self.click_boost <= 0:
            self._boost_timer.stop()


class InstancesStore(QObject):
    instancesChanged = Signal()

    def __init__(self, library: list[CharacterAssets], storage_path: Path) -> None:
        super().__init__()
        self.library = library
        self.storage_path = storage_path
        self.instances: list[CharacterInstance] = []
        self._save_pending = False
        self._load_or_seed()

    @property
    def max_instances(self) -> int:
        return 5

    def _load_or_seed(self) -> None:
        loaded = self._load()
        if loaded:
            self.instances = loaded
        else:
            size = SIZE_CHOICES[1]
            self.instances = [
                CharacterInstance(
                    character_id="mouse",
                    size_raw=size,
                    origin=self.default_origin(size, 0),
                    library=self.library,
                )
            ]
        for inst in self.instances:
            inst.changed.connect(self.schedule_save)

    def add(self) -> Optional[CharacterInstance]:
        if len(self.instances) >= self.max_instances:
            return None
        size = SIZE_CHOICES[1]
        inst = CharacterInstance(
            character_id="mouse",
            size_raw=size,
            origin=self.default_origin(size, len(self.instances)),
            library=self.library,
        )
        inst.changed.connect(self.schedule_save)
        self.instances.append(inst)
        self.instancesChanged.emit()
        self.schedule_save()
        return inst

    def remove(self, instance: CharacterInstance) -> None:
        if len(self.instances) <= 1:
            return
        self.instances = [item for item in self.instances if item.id != instance.id]
        self.instancesChanged.emit()
        self.schedule_save()

    def schedule_save(self) -> None:
        if self._save_pending:
            return
        self._save_pending = True
        QTimer.singleShot(0, self._persist)

    def _persist(self) -> None:
        self._save_pending = False
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "instances": [
                {
                    "id": inst.id,
                    "characterID": inst.character_id,
                    "sizeRaw": inst.size_raw,
                    "originX": inst.origin.x(),
                    "originY": inst.origin.y(),
                }
                for inst in self.instances
            ]
        }
        self.storage_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load(self) -> list[CharacterInstance]:
        if not self.storage_path.exists():
            return []
        try:
            payload = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        items = payload.get("instances") if isinstance(payload, dict) else None
        if not isinstance(items, list) or not items:
            return []

        result: list[CharacterInstance] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            instance = CharacterInstance(
                instance_id=str(item.get("id") or ""),
                character_id=str(item.get("characterID") or "mouse"),
                size_raw=int(item.get("sizeRaw") or SIZE_CHOICES[1]),
                origin=QPoint(int(item.get("originX") or 0), int(item.get("originY") or 0)),
                library=self.library,
            )
            result.append(instance)
        return result

    @staticmethod
    def default_origin(size_raw: int, index_offset: int) -> QPoint:
        screen = QApplication.primaryScreen()
        if not screen:
            return QPoint(0, 0)
        visible = screen.availableGeometry()
        margin = 24
        stagger = index_offset * (size_raw + 16)
        return QPoint(visible.right() - size_raw - margin - stagger, visible.bottom() - size_raw - margin)


class TypingMonitor(QObject):
    def __init__(self, tracker: TypingSpeedTracker) -> None:
        super().__init__()
        self._tracker = tracker
        self._listener: Optional[keyboard.Listener] = None
        self._showed_warning = False

    def start(self) -> None:
        if self._listener is not None:
            return
        self._listener = keyboard.Listener(on_press=self._on_press)
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def _on_press(self, _key) -> None:
        self._tracker.record_keystroke()


class VideoClip:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.capture = cv2.VideoCapture(str(path))
        self.fps = self.capture.get(cv2.CAP_PROP_FPS) or 30.0
        if self.fps <= 1:
            self.fps = 30.0
        self.frame_count = int(self.capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self.is_open = self.capture.isOpened()

    def read_frame(self) -> Optional[np.ndarray]:
        if not self.is_open:
            return None
        ok, frame = self.capture.read()
        if ok and frame is not None:
            return frame
        self.capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
        ok, frame = self.capture.read()
        return frame if ok else None

    def reset(self) -> None:
        if self.is_open:
            self.capture.set(cv2.CAP_PROP_POS_FRAMES, 0)


class VideoRenderer(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self._clip: Optional[VideoClip] = None
        self._current_frame: Optional[QImage] = None
        self._playback_rate = 1.0
        self._frame_accum = 0.0
        self._elapsed = QElapsedTimer()
        self._elapsed.start()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def load(self, path: Path) -> None:
        if self._clip and self._clip.path == path:
            return
        self._clip = VideoClip(path)
        self._frame_accum = 0.0
        first = self._clip.read_frame() if self._clip.is_open else None
        self._current_frame = self._to_qimage_with_alpha(first) if first is not None else None
        self._elapsed.restart()
        self.update()

    def set_rate(self, rate: float) -> None:
        self._playback_rate = max(0.1, float(rate))

    def _tick(self) -> None:
        if not self._clip or not self._clip.is_open:
            return
        dt = self._elapsed.restart() / 1000.0
        self._frame_accum += dt * self._clip.fps * self._playback_rate
        frames_to_advance = int(self._frame_accum)
        if frames_to_advance <= 0 and self._current_frame is not None:
            return
        self._frame_accum -= frames_to_advance
        frame = None
        for _ in range(max(1, frames_to_advance)):
            frame = self._clip.read_frame()
        if frame is not None:
            self._current_frame = self._to_qimage_with_alpha(frame)
            self.update()

    @staticmethod
    def _to_qimage_with_alpha(frame: np.ndarray) -> QImage:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        green = rgb[:, :, 1]
        max_rb = np.maximum(rgb[:, :, 0], rgb[:, :, 2])
        green_excess = green - max_rb
        threshold = 0.10
        softness = 0.18
        spill = 1.0
        key_amount = np.clip((green_excess - threshold) / max(softness, 0.0001), 0.0, 1.0)
        alpha = 1.0 - key_amount
        clamped_g = np.minimum(rgb[:, :, 1], max_rb)
        g = rgb[:, :, 1] * (1.0 - spill * key_amount) + clamped_g * (spill * key_amount)
        rgba = np.dstack((rgb[:, :, 0] * alpha, g * alpha, rgb[:, :, 2] * alpha, alpha))
        rgba8 = np.clip(rgba * 255.0, 0, 255).astype(np.uint8)
        h, w, _ = rgba8.shape
        return QImage(rgba8.data, w, h, 4 * w, QImage.Format_RGBA8888).copy()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        if self._current_frame is not None:
            target = self.rect()
            painter.drawImage(target, self._current_frame)
        else:
            painter.setPen(Qt.white)
            painter.drawText(self.rect(), Qt.AlignCenter, "KeyHigh\nWindows build")


class CharacterWindow(QMainWindow):
    def __init__(self, instance: CharacterInstance, tracker: TypingSpeedTracker, store: InstancesStore) -> None:
        super().__init__()
        self.instance = instance
        self.tracker = tracker
        self.store = store
        self._drag_start_mouse: Optional[QPoint] = None
        self._drag_start_origin: Optional[QPoint] = None
        self._dragged = False
        self._click_threshold = 4

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.NoFocus)

        self.renderer = VideoRenderer(self)
        self.setCentralWidget(self.renderer)

        self.instance.changed.connect(self.sync_from_instance)
        self.tracker.stateChanged.connect(self.sync_from_instance)
        self.tracker.cpsChanged.connect(self.sync_from_instance)
        self.sync_from_instance()

    def sync_from_instance(self) -> None:
        self.setGeometry(QRect(self.instance.origin, self.instance.size))
        character = self.instance.character
        if character:
            path = character.run_path if self._is_animating() else character.idle_path
            self.renderer.load(path)
        self.renderer.set_rate(self._current_rate())
        self.renderer.resize(self.size())
        self.update()

    def _is_animating(self) -> bool:
        return self.tracker.state == "running" or self.instance.click_boost > 0

    def _current_rate(self) -> float:
        effective_cps = self.tracker.cps + self.instance.click_boost
        if not self._is_animating():
            return 0.7
        return min(max(0.8 + effective_cps * 0.25, 0.8), 4.0)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.RightButton:
            self._show_menu(event.globalPosition().toPoint())
            return
        self._drag_start_mouse = event.globalPosition().toPoint()
        self._drag_start_origin = self.pos()
        self._dragged = False

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_start_mouse is None or self._drag_start_origin is None:
            return
        delta = event.globalPosition().toPoint() - self._drag_start_mouse
        if delta.manhattanLength() > self._click_threshold:
            self._dragged = True
            self.move(self._drag_start_origin + delta)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton:
            return
        if self._dragged:
            self.instance.update_origin(self.pos())
        else:
            self.instance.record_click()
        self._drag_start_mouse = None
        self._drag_start_origin = None
        self._dragged = False

    def contextMenuEvent(self, event) -> None:
        self._show_menu(event.globalPos())

    def _show_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)

        character_menu = menu.addMenu("Character")
        for character in self.instance.library:
            action = character_menu.addAction(character.display_name)
            action.setCheckable(True)
            action.setChecked(character.id == self.instance.character_id)
            action.triggered.connect(lambda _checked=False, cid=character.id: self.instance.set_character_id(cid))

        size_menu = menu.addMenu("Size")
        for size in SIZE_CHOICES:
            action = size_menu.addAction(str(size))
            action.setCheckable(True)
            action.setChecked(size == self.instance.size_raw)
            action.triggered.connect(lambda _checked=False, s=size: self.instance.set_size_raw(s))

        menu.addSeparator()

        add_action = menu.addAction(f"Add Character ({len(self.store.instances)}/{self.store.max_instances})")
        add_action.triggered.connect(self.store.add)
        add_action.setEnabled(len(self.store.instances) < self.store.max_instances)

        remove_action = menu.addAction("Remove This Character")
        remove_action.triggered.connect(lambda: self.store.remove(self.instance))
        remove_action.setEnabled(len(self.store.instances) > 1)

        menu.addSeparator()
        quit_action = menu.addAction("Quit KeyHigh")
        quit_action.triggered.connect(QApplication.instance().quit)

        menu.exec(pos)


def make_app_icon(size: int = 64) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setBrush(Qt.darkGray)
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(10, 14, size - 20, size - 20)
    painter.setBrush(Qt.white)
    painter.drawEllipse(size // 2 - 8, size // 2 - 8, 6, 6)
    painter.drawEllipse(size // 2 + 2, size // 2 - 8, 6, 6)
    painter.end()
    return QIcon(pixmap)


class TrayController(QObject):
    def __init__(self, controller: "Controller") -> None:
        super().__init__()
        self.controller = controller
        self.tray = QSystemTrayIcon(make_app_icon(), controller.app)
        self.menu = QMenu()

        show_action = self.menu.addAction("Show all")
        show_action.triggered.connect(self.controller.show_all)

        hide_action = self.menu.addAction("Hide all")
        hide_action.triggered.connect(self.controller.hide_all)

        self.menu.addSeparator()
        quit_action = self.menu.addAction("Quit KeyHigh")
        quit_action.triggered.connect(QApplication.instance().quit)

        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_activated)
        self.tray.show()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self.controller.toggle_visibility()


class Controller(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.app = QApplication.instance() or QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.tracker = TypingSpeedTracker()
        self.monitor = TypingMonitor(self.tracker)
        self.library = CharacterLibrary.load(resource_dir())
        self.store = InstancesStore(self.library, storage_path())
        self.windows: dict[str, CharacterWindow] = {}
        self.tray: Optional[TrayController] = None
        self.store.instancesChanged.connect(self.sync_windows)
        for instance in self.store.instances:
            instance.changed.connect(self._refresh_all)
        self.sync_windows()
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = TrayController(self)

        if not self.library:
            QMessageBox.warning(
                None,
                "KeyHigh",
                f"No paired videos found in:\n{resource_dir()}\n\nExpected <name>_idle.* and <name>_run.* files.",
            )

    def run(self) -> int:
        self.monitor.start()
        return self.app.exec()

    def sync_windows(self) -> None:
        live_ids = {instance.id for instance in self.store.instances}
        for inst_id in list(self.windows):
            if inst_id not in live_ids:
                self.windows[inst_id].close()
                self.windows.pop(inst_id, None)

        for instance in self.store.instances:
            if instance.id not in self.windows:
                window = CharacterWindow(instance, self.tracker, self.store)
                self.windows[instance.id] = window
                window.show()
                window.raise_()
            else:
                self.windows[instance.id].sync_from_instance()

    def _refresh_all(self) -> None:
        for window in self.windows.values():
            window.sync_from_instance()

    def show_all(self) -> None:
        for window in self.windows.values():
            window.show()
            window.raise_()

    def hide_all(self) -> None:
        for window in self.windows.values():
            window.hide()

    def toggle_visibility(self) -> None:
        visible = any(window.isVisible() for window in self.windows.values())
        if visible:
            self.hide_all()
        else:
            self.show_all()


def resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
        return base / "Resources"
    return Path(__file__).resolve().parents[1] / "Resources"


def storage_path() -> Path:
    appdata = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    if appdata:
        return Path(appdata) / "instances.json"
    return Path.home() / ".keyhigh" / "instances.json"


def main() -> int:
    controller = Controller()
    return controller.run()


if __name__ == "__main__":
    sys.exit(main())
