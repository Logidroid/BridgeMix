"""
Pads panel — the six BRIDGE CAST X control pads drawn as on the device, a
sound for each, and where the sounds play.

A sound pad sends its own MIDI CC (see bridgemix.device.pads); BridgeMix plays
the file saved for that pad.  Every pad of every pad set can have its own
sound; the tab shows the pads of the pad set that is active on the device.
Click a pad to edit it; a pad lights up when you press it on the device.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from bridgemix import theme
from bridgemix.device import pads
from bridgemix.gui.widgets.controls import ScrollGuardComboBox, Slider
from bridgemix.routing import backend
from bridgemix.sounds import store

if TYPE_CHECKING:
    from bridgemix.device.bridge_cast import BridgeCast
    from bridgemix.sounds.player import SoundPlayer

_HINT_STYLE = "font-size: 12px; color: #9a9aa2; background-color: transparent;"
_FILE_FILTER = "Sounds (" + " ".join(f"*{s}" for s in store.SUPPORTED_SUFFIXES) + ")"
_SOUND_ITEM = "BridgeMix sound"
_COLUMNS = 2  # pads 1-2 on the first row, 3-4 on the second, 5-6 on the third
_FLASH_MS = 300


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(_HINT_STYLE)
    return label


def _pad_color(pad: pads.Pad | None) -> QColor:
    """The pad's light colour (device values 0-32), grey if it has none."""
    if pad is None or not any(pad.color):
        return QColor(theme.TEXT_FAINT)
    r, g, b = (min(255, c * 255 // 32) for c in pad.color)
    return QColor(r, g, b)


class _PadTile(QWidget):
    """One on-screen pad: coloured like its light, with its name and function."""

    clicked = pyqtSignal(int)

    def __init__(self, number: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.number = number
        self.pad: pads.Pad | None = None
        self.detail = ""
        self.selected = False
        self._lit = False
        self.setMinimumSize(150, 96)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._unlight)

    def set_pad(self, pad: pads.Pad, detail: str) -> None:
        self.pad, self.detail = pad, detail
        self.setToolTip(f"PAD {self.number}: {detail}")
        self.update()

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        self.update()

    def flash(self) -> None:
        self._lit = True
        self._flash_timer.start(_FLASH_MS)
        self.update()

    def _unlight(self) -> None:
        self._lit = False
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.number)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = _pad_color(self.pad)
        rect = QRectF(self.rect()).adjusted(3, 3, -3, -3)

        fill = QColor(color)
        fill.setAlpha(200 if self._lit else 38)
        p.setBrush(fill)
        border = QColor(theme.ACCENT) if self.selected else color
        p.setPen(QPen(border, 3 if self.selected else 2))
        p.drawRoundedRect(rect, 10, 10)

        text_rect = rect.adjusted(10, 6, -10, -6)
        font = QFont(self.font())
        font.setPointSizeF(8.5)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor(theme.TEXT if self._lit else theme.TEXT_MUTED))
        p.drawText(
            text_rect, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, f"PAD {self.number}"
        )

        font.setPointSizeF(11.5)
        p.setFont(font)
        p.setPen(QColor(theme.TEXT))
        name = self.pad.name if self.pad and self.pad.name else "—"
        p.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, name)

        font.setPointSizeF(8.5)
        font.setBold(False)
        p.setFont(font)
        p.setPen(QColor(theme.TEXT if self._lit else theme.TEXT_MUTED))
        detail = p.fontMetrics().elidedText(
            self.detail, Qt.TextElideMode.ElideRight, int(text_rect.width())
        )
        p.drawText(text_rect, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, detail)
        p.end()


class PadsPanel(QWidget):
    def __init__(
        self, bridge: BridgeCast, player: SoundPlayer | None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._bridge = bridge
        self._player = player
        self._tiles: dict[int, _PadTile] = {}
        self._selected = 1
        self._app_checks: dict[str, QCheckBox] = {}

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(12)
        if player is None:
            lay.addWidget(
                _hint(
                    "Playing sounds needs PipeWire (pw-play, pw-link, pw-dump), "
                    "so it only works on Linux."
                )
            )
        self._pads_group = self._make_pads_group()
        lay.addWidget(self._pads_group)
        self._not_x_hint = _hint("Sound pads use the control pads of a BRIDGE CAST X.")
        lay.addWidget(self._not_x_hint)
        lay.addWidget(self._output_group())
        lay.addStretch()
        scroll.setWidget(inner)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        bridge.pad_changed.connect(self._on_pad)
        bridge.parameter_changed.connect(self._on_param)
        bridge.control_change.connect(self._on_control_change)
        bridge.device_info_updated.connect(lambda *_: self._update_model())
        bridge.connected.connect(lambda _c: self._update_model())
        self._update_model()
        self._select(1)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh_channels()
        self._refresh_apps()
        self._bridge.request_pads()

    # ── helpers ───────────────────────────────────────────────────────────────

    def _pad_set(self) -> int:
        try:
            return self._bridge.get_parameter("pad_set_no")
        except KeyError:
            return 0

    def _key(self, number: int) -> str:
        return store.pad_key(self._pad_set(), number)

    def _detail(self, pad: pads.Pad) -> str:
        """What the pad does, for its tile: its sound or its device function."""
        if pad.is_sound_pad(self._pad_set()):
            sound = store.load().pads.get(self._key(pad.number))
            if sound and sound.file:
                return f"Sound: {store.display_name(sound.file)}"
            return "Sound: none yet"
        return pad.describe()

    # ── pads ──────────────────────────────────────────────────────────────────

    def _make_pads_group(self) -> QGroupBox:
        grp = QGroupBox("PADS")
        lay = QVBoxLayout(grp)
        lay.setContentsMargins(10, 6, 10, 10)
        lay.setSpacing(10)

        top = QHBoxLayout()
        self._pad_set_lbl = QLabel()
        self._pad_set_lbl.setStyleSheet("font-weight: 700; background: transparent;")
        top.addWidget(self._pad_set_lbl)
        top.addStretch()
        refresh = QPushButton("Read pads")
        refresh.setToolTip("Read the pads from the device again")
        refresh.clicked.connect(self._bridge.request_pads)
        top.addWidget(refresh)
        lay.addLayout(top)

        body = QHBoxLayout()
        body.setSpacing(16)
        grid = QGridLayout()
        grid.setSpacing(10)
        for n in range(1, pads.PAD_COUNT + 1):
            tile = _PadTile(n)
            tile.clicked.connect(self._select)
            self._tiles[n] = tile
            grid.addWidget(tile, (n - 1) // _COLUMNS, (n - 1) % _COLUMNS)
        grid_box = QWidget()
        grid_box.setLayout(grid)
        grid_box.setFixedWidth(_COLUMNS * 175)
        body.addWidget(grid_box, alignment=Qt.AlignmentFlag.AlignTop)
        body.addWidget(self._make_editor(), stretch=1, alignment=Qt.AlignmentFlag.AlignTop)
        lay.addLayout(body)

        lay.addWidget(
            _hint(
                "Click a pad to set it up. Choose a file and the pad plays it: "
                "BridgeMix keeps a copy (WAV, FLAC, OGG or MP3), and every pad of "
                "every pad set can have its own sound. Switch pad sets on the device "
                "to set up the others. The pad's previous function is kept, so "
                "Remove or the function list gives it back. A pad lights up here "
                "when you press it on the device."
            )
        )
        self._update_pad_set_label()
        return grp

    def _make_editor(self) -> QGroupBox:
        self._editor = QGroupBox()
        form = QFormLayout(self._editor)
        form.setContentsMargins(12, 8, 12, 10)
        form.setSpacing(10)

        self._function = ScrollGuardComboBox()
        self._function.setEnabled(False)
        self._function.currentIndexChanged.connect(lambda _i: self._on_function())
        form.addRow("Function:", self._function)

        sound_row = QHBoxLayout()
        self._file_lbl = QLabel("No sound")
        self._file_lbl.setMinimumWidth(160)
        sound_row.addWidget(self._file_lbl, stretch=1)
        choose = QPushButton("Choose…")
        choose.clicked.connect(self._choose)
        sound_row.addWidget(choose)
        self._remove_btn = QPushButton("Remove")
        self._remove_btn.setToolTip("Remove the sound and give the pad its previous function back")
        self._remove_btn.clicked.connect(self._clear)
        sound_row.addWidget(self._remove_btn)
        form.addRow("Sound:", sound_row)

        play_row = QHBoxLayout()
        self._play_btn = QPushButton("Play")
        self._play_btn.setToolTip("Preview: only you hear it")
        self._play_btn.clicked.connect(self._preview)
        play_row.addWidget(self._play_btn)
        self._stop_btn = QPushButton("Stop")
        self._stop_btn.clicked.connect(self._stop)
        play_row.addWidget(self._stop_btn)
        play_row.addStretch()
        form.addRow("Preview:", play_row)

        volume_row = QHBoxLayout()
        self._volume = Slider(Qt.Orientation.Horizontal)
        self._volume.setRange(0, 100)
        self._volume_lbl = QLabel()
        self._volume_lbl.setFixedWidth(44)
        self._volume.valueChanged.connect(lambda v: self._volume_lbl.setText(f"{v}%"))
        self._volume.valueChanged.connect(self._set_volume)
        volume_row.addWidget(self._volume, stretch=1)
        volume_row.addWidget(self._volume_lbl)
        form.addRow("Volume:", volume_row)

        self._press_again = QCheckBox("Pressing the pad again stops the sound")
        self._press_again.setToolTip("Off: pressing the pad again restarts the sound")
        self._press_again.toggled.connect(self._set_press_again)
        form.addRow("", self._press_again)
        return self._editor

    def _select(self, number: int) -> None:
        self._selected = number
        for n, tile in self._tiles.items():
            tile.set_selected(n == number)
        self._editor.setTitle(f"PAD {number}")
        self._show_function()
        self._show_sound()

    def _show_sound(self) -> None:
        sound = store.load().pads.get(self._key(self._selected))
        has_file = sound is not None and bool(sound.file)
        for w in (self._volume, self._press_again):
            w.blockSignals(True)
        self._file_lbl.setText(store.display_name(sound.file) if has_file else "No sound")
        self._file_lbl.setToolTip(sound.file if has_file else "")
        volume = sound.volume if sound is not None else store.PadSound().volume
        self._volume.setValue(volume)
        self._volume_lbl.setText(f"{volume}%")
        self._press_again.setChecked(bool(sound and sound.press_again_stops))
        can_play = self._player is not None and has_file
        self._play_btn.setEnabled(can_play)
        self._stop_btn.setEnabled(can_play)
        self._remove_btn.setEnabled(has_file)
        for w in (self._volume, self._press_again):
            w.blockSignals(False)

    def _show_function(self) -> None:
        pad = self._bridge.control_pads.get(self._selected)
        combo = self._function
        combo.blockSignals(True)
        combo.clear()
        if pad is None:
            combo.addItem("Not read yet", "none")
            combo.setEnabled(False)
            combo.blockSignals(False)
            return
        is_sound = pad.is_sound_pad(self._pad_set())
        backup = store.load().pad_backup.get(self._key(pad.number))
        if not is_sound:
            combo.addItem(f"{pad.describe()} (device)", "keep")
        elif backup is not None:
            previous = pads.Pad(pad.number, "", *backup)
            combo.addItem(f"{previous.describe()} (device)", "restore")
        combo.addItem(_SOUND_ITEM, "sound")
        combo.setCurrentIndex(max(0, combo.findData("sound" if is_sound else "keep")))
        combo.setEnabled(True)
        combo.blockSignals(False)

    def _update_model(self) -> None:
        is_x = self._bridge.is_bridge_cast_x
        self._pads_group.setVisible(is_x)
        self._not_x_hint.setVisible(not is_x)
        if is_x and self.isVisible():
            self._bridge.request_pads()

    def _on_param(self, name: str, _value: int) -> None:
        if name == "pad_set_no":
            self._update_pad_set_label()
            self._show_sound()
            self._bridge.request_pads()  # the device loaded the pads of that set

    def _update_pad_set_label(self) -> None:
        self._pad_set_lbl.setText(f"Pad set {self._pad_set() + 1}")

    def _on_pad(self, pad: pads.Pad) -> None:
        tile = self._tiles.get(pad.number)
        if tile is None:
            return
        tile.set_pad(pad, self._detail(pad))
        if pad.number == self._selected:
            self._show_function()

    def _refresh_tile(self, number: int) -> None:
        pad = self._bridge.control_pads.get(number)
        if pad is not None:
            self._tiles[number].set_pad(pad, self._detail(pad))

    def _on_control_change(self, channel: int, control: int, value: int) -> None:
        found = pads.pad_for_cc(channel, control)
        if found is not None and value and found[0] == self._pad_set():
            self._tiles[found[1]].flash()

    def _make_sound_pad(self, number: int) -> bool:
        """Turn pad *number* into a sound pad, keeping its previous function."""
        pad = self._bridge.control_pads.get(number)
        if pad is None:
            return False
        pad_set = self._pad_set()
        if pad.is_sound_pad(pad_set):
            return True
        settings = store.load()
        settings.pad_backup[self._key(number)] = [pad.func, pad.opt1, pad.opt2]
        store.save(settings)
        if not self._bridge.assign_pad(number, *pads.sound_pad_function(pad_set, number)):
            return False
        self._function.setEnabled(False)  # until the device reads back
        return True

    def _restore_pad(self, number: int) -> None:
        """Give pad *number* its function from before it became a sound pad."""
        settings = store.load()
        backup = settings.pad_backup.get(self._key(number))
        if backup is None:
            return
        if self._bridge.assign_pad(number, *backup):
            settings.pad_backup.pop(self._key(number), None)
            store.save(settings)
            self._function.setEnabled(False)

    def _on_function(self) -> None:
        number = self._selected
        choice = self._function.currentData()
        if choice == "sound":
            ok = self._make_sound_pad(number)
        elif choice == "restore":
            self._restore_pad(number)
            ok = True
        else:
            return
        if not ok:
            self._show_function()  # not connected: show the pad as it is

    # ── the selected pad's sound ──────────────────────────────────────────────

    def _choose(self) -> None:
        number = self._selected
        path, _ = QFileDialog.getOpenFileName(
            self, f"Sound for pad {number}", str(Path.home()), _FILE_FILTER
        )
        if not path:
            return
        key = self._key(number)
        try:
            copy = store.import_file(key, Path(path))
        except OSError as exc:
            QMessageBox.critical(self, "Sound not added", f"Could not copy the file:\n{exc}")
            return
        settings = store.load()
        settings.pads.setdefault(key, store.PadSound()).file = str(copy)
        store.save(settings)
        self._show_sound()
        self._refresh_tile(number)
        if not self._make_sound_pad(number):
            QMessageBox.warning(
                self,
                "Pad not changed",
                "The sound is saved, but the pad could not be changed: is the "
                "BRIDGE CAST X connected?",
            )

    def _clear(self) -> None:
        number = self._selected
        key = self._key(number)
        if self._player is not None:
            self._player.stop(key)
        store.remove_file(key)
        settings = store.load()
        settings.pads.pop(key, None)
        store.save(settings)
        self._show_sound()
        self._refresh_tile(number)
        self._restore_pad(number)

    def _preview(self) -> None:
        if self._player is not None:
            self._player.play(self._key(self._selected), voice_chat=False)
            self._tiles[self._selected].flash()

    def _stop(self) -> None:
        if self._player is not None:
            self._player.stop(self._key(self._selected))

    def _set_volume(self, volume: int) -> None:
        settings = store.load()
        settings.pads.setdefault(self._key(self._selected), store.PadSound()).volume = volume
        store.save(settings)

    def _set_press_again(self, on: bool) -> None:
        settings = store.load()
        sound = settings.pads.setdefault(self._key(self._selected), store.PadSound())
        sound.press_again_stops = on
        store.save(settings)

    # ── where the sounds play ─────────────────────────────────────────────────

    def _output_group(self) -> QGroupBox:
        grp = QGroupBox("OUTPUT")
        form = QFormLayout(grp)
        form.setContentsMargins(10, 6, 10, 10)
        form.setSpacing(8)

        self._channel_combo = ScrollGuardComboBox()
        self._channel_combo.currentIndexChanged.connect(self._on_channel)
        form.addRow("Play on:", self._channel_combo)

        apps_row = QWidget()
        self._apps_lay = QHBoxLayout(apps_row)
        self._apps_lay.setContentsMargins(0, 0, 0, 0)
        self._apps_lay.setSpacing(12)
        refresh = QPushButton("Refresh")
        refresh.setToolTip("Look again for apps that are recording")
        refresh.clicked.connect(self._refresh_apps)
        self._apps_lay.addWidget(refresh)
        self._apps_lay.addStretch()
        form.addRow("Also send to:", apps_row)

        form.addRow(
            _hint(
                "You hear the sounds on the chosen channel, and so does your stream "
                "if that channel is in the STREAM mix. The apps ticked here also "
                "record them along with your mic, so the people you talk to hear "
                "them. If they don't, set Discord's noise suppression to Standard "
                "or off."
            )
        )
        return grp

    def _refresh_channels(self) -> None:
        current = store.load().channel
        labels = [t.label for t in backend.list_targets()] if backend.available() else []
        if current not in labels:
            labels.append(current)
        self._channel_combo.blockSignals(True)
        self._channel_combo.clear()
        self._channel_combo.addItems(labels)
        self._channel_combo.setCurrentText(current)
        self._channel_combo.blockSignals(False)

    def _on_channel(self, _i: int) -> None:
        settings = store.load()
        settings.channel = self._channel_combo.currentText()
        store.save(settings)

    def _refresh_apps(self) -> None:
        saved = store.load().voice_apps
        recording = backend.list_recording_apps() if backend.available() else []
        apps = list(dict.fromkeys([*saved, *recording]))
        for name in list(self._app_checks):
            if name not in apps:
                self._app_checks.pop(name).deleteLater()
        for name in apps:
            if name not in self._app_checks:
                check = QCheckBox(name)
                check.setChecked(name in saved)
                check.toggled.connect(lambda on, n=name: self._on_app(n, on))
                self._apps_lay.insertWidget(self._apps_lay.count() - 2, check)
                self._app_checks[name] = check

    def _on_app(self, name: str, on: bool) -> None:
        settings = store.load()
        apps = [a for a in settings.voice_apps if a != name]
        settings.voice_apps = [*apps, name] if on else apps
        store.save(settings)
