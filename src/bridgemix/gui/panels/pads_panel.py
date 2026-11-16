"""
Pads panel — gives each BRIDGE CAST X control pad a sound that BridgeMix keeps
and plays, and sets where the sounds play.

A sound pad sends its own MIDI CC (see bridgemix.device.pads); BridgeMix plays
the file saved for that pad.  Every pad of every pad set can have its own
sound; the tab shows the pads of the pad set that is active on the device.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
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
    QVBoxLayout,
    QWidget,
)

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


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(_HINT_STYLE)
    return label


class _PadRow:
    """The widgets of one pad, in the pads grid."""

    def __init__(self, panel: PadsPanel, number: int, grid: QGridLayout) -> None:
        self.number = number
        row = number - 1
        grid.addWidget(QLabel(f"PAD {number}"), row, 0)

        self.name = QLabel("—")
        self.name.setStyleSheet("color: #9a9aa2; background: transparent;")
        self.name.setMinimumWidth(90)
        grid.addWidget(self.name, row, 1)

        self.function = ScrollGuardComboBox()
        self.function.setMinimumWidth(170)
        self.function.setEnabled(False)
        self.function.currentIndexChanged.connect(lambda _i: panel._on_function(number))
        grid.addWidget(self.function, row, 2)

        self.file = QLabel("No sound")
        self.file.setMinimumWidth(140)
        grid.addWidget(self.file, row, 3)

        self.choose = QPushButton("Choose…")
        self.choose.clicked.connect(lambda: panel._choose(number))
        grid.addWidget(self.choose, row, 4)

        self.play = QPushButton("▶")
        self.play.setFixedWidth(32)
        self.play.setToolTip("Preview (only you hear it)")
        self.play.clicked.connect(lambda: panel._preview(number))
        grid.addWidget(self.play, row, 5)

        self.stop = QPushButton("■")
        self.stop.setFixedWidth(32)
        self.stop.setToolTip("Stop")
        self.stop.clicked.connect(lambda: panel._stop(number))
        grid.addWidget(self.stop, row, 6)

        self.volume = Slider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setFixedWidth(100)
        self.volume_value = QLabel()
        self.volume_value.setFixedWidth(40)
        self.volume.valueChanged.connect(lambda v: self.volume_value.setText(f"{v}%"))
        self.volume.valueChanged.connect(lambda v: panel._set_volume(number, v))
        grid.addWidget(self.volume, row, 7)
        grid.addWidget(self.volume_value, row, 8)

        self.press_again = QCheckBox("Press again stops")
        self.press_again.setToolTip("Off: pressing the pad again restarts the sound")
        self.press_again.toggled.connect(lambda on: panel._set_press_again(number, on))
        grid.addWidget(self.press_again, row, 9)

        self.clear = QPushButton("✕")
        self.clear.setFixedWidth(32)
        self.clear.setToolTip("Remove the sound and give the pad its previous function back")
        self.clear.clicked.connect(lambda: panel._clear(number))
        grid.addWidget(self.clear, row, 10)

    def show_sound(self, sound: store.PadSound | None, can_play: bool) -> None:
        for w in (self.volume, self.press_again):
            w.blockSignals(True)
        has_file = sound is not None and bool(sound.file)
        self.file.setText(store.display_name(sound.file) if has_file else "No sound")
        self.file.setToolTip(sound.file if has_file else "Choose a sound file")
        volume = sound.volume if sound is not None else store.PadSound().volume
        self.volume.setValue(volume)
        self.volume_value.setText(f"{volume}%")
        self.press_again.setChecked(bool(sound and sound.press_again_stops))
        self.play.setEnabled(can_play and has_file)
        self.stop.setEnabled(can_play and has_file)
        self.clear.setEnabled(has_file)
        for w in (self.volume, self.press_again):
            w.blockSignals(False)


class PadsPanel(QWidget):
    def __init__(
        self, bridge: BridgeCast, player: SoundPlayer | None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._bridge = bridge
        self._player = player
        self._rows: dict[int, _PadRow] = {}
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
        bridge.device_info_updated.connect(lambda *_: self._update_model())
        bridge.connected.connect(lambda _c: self._update_model())
        self._update_model()
        self._show_sounds()

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

    def _show_sounds(self) -> None:
        settings = store.load()
        for number, row in self._rows.items():
            row.show_sound(settings.pads.get(self._key(number)), self._player is not None)

    # ── pads ──────────────────────────────────────────────────────────────────

    def _make_pads_group(self) -> QGroupBox:
        grp = QGroupBox("PADS")
        lay = QVBoxLayout(grp)
        lay.setContentsMargins(10, 6, 10, 10)
        lay.setSpacing(8)

        top = QHBoxLayout()
        self._pad_set_lbl = QLabel()
        top.addWidget(self._pad_set_lbl)
        top.addStretch()
        refresh = QPushButton("Read pads")
        refresh.setToolTip("Read the pads from the device again")
        refresh.clicked.connect(self._bridge.request_pads)
        top.addWidget(refresh)
        lay.addLayout(top)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        for n in range(1, pads.PAD_COUNT + 1):
            self._rows[n] = _PadRow(self, n, grid)
        grid.setColumnStretch(3, 1)
        lay.addLayout(grid)
        lay.addWidget(
            _hint(
                "Choose a file to make the pad play it. BridgeMix keeps a copy "
                "(WAV, FLAC, OGG or MP3), and every pad of every pad set can have "
                "its own sound: switch pad sets on the device to set up the others. "
                "The pad's previous function is kept, so ✕ or the function list "
                "gives it back."
            )
        )
        self._update_pad_set_label()
        return grp

    def _update_model(self) -> None:
        is_x = self._bridge.is_bridge_cast_x
        self._pads_group.setVisible(is_x)
        self._not_x_hint.setVisible(not is_x)
        if is_x and self.isVisible():
            self._bridge.request_pads()

    def _on_param(self, name: str, _value: int) -> None:
        if name == "pad_set_no":
            self._update_pad_set_label()
            self._show_sounds()
            self._bridge.request_pads()  # the device loaded the pads of that set

    def _update_pad_set_label(self) -> None:
        self._pad_set_lbl.setText(f"Pad set {self._pad_set() + 1}")

    def _on_pad(self, pad: pads.Pad) -> None:
        row = self._rows.get(pad.number)
        if row is None:
            return
        row.name.setText(pad.name or "—")
        is_sound = pad.is_sound_pad(self._pad_set())
        backup = store.load().pad_backup.get(self._key(pad.number))
        combo = row.function
        combo.blockSignals(True)
        combo.clear()
        if not is_sound:
            combo.addItem(f"{pad.describe()} (device)", "keep")
        elif backup is not None:
            previous = pads.Pad(pad.number, "", *backup)
            combo.addItem(f"{previous.describe()} (device)", "restore")
        combo.addItem(_SOUND_ITEM, "sound")
        combo.setCurrentIndex(max(0, combo.findData("sound" if is_sound else "keep")))
        combo.setEnabled(True)
        combo.blockSignals(False)

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
        self._rows[number].function.setEnabled(False)  # until the device reads back
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
            self._rows[number].function.setEnabled(False)

    def _on_function(self, number: int) -> None:
        choice = self._rows[number].function.currentData()
        if choice == "sound":
            ok = self._make_sound_pad(number)
        elif choice == "restore":
            self._restore_pad(number)
            ok = True
        else:
            return
        pad = self._bridge.control_pads.get(number)
        if not ok and pad is not None:
            self._on_pad(pad)  # not connected: show the pad as it is

    # ── sounds ────────────────────────────────────────────────────────────────

    def _choose(self, number: int) -> None:
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
        self._show_sounds()
        if not self._make_sound_pad(number):
            QMessageBox.warning(
                self,
                "Pad not changed",
                "The sound is saved, but the pad could not be changed: is the "
                "BRIDGE CAST X connected?",
            )

    def _clear(self, number: int) -> None:
        key = self._key(number)
        if self._player is not None:
            self._player.stop(key)
        store.remove_file(key)
        settings = store.load()
        settings.pads.pop(key, None)
        store.save(settings)
        self._show_sounds()
        self._restore_pad(number)

    def _preview(self, number: int) -> None:
        if self._player is not None:
            self._player.play(self._key(number), voice_chat=False)

    def _stop(self, number: int) -> None:
        if self._player is not None:
            self._player.stop(self._key(number))

    def _set_volume(self, number: int, volume: int) -> None:
        settings = store.load()
        settings.pads.setdefault(self._key(number), store.PadSound()).volume = volume
        store.save(settings)

    def _set_press_again(self, number: int, on: bool) -> None:
        settings = store.load()
        settings.pads.setdefault(self._key(number), store.PadSound()).press_again_stops = on
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
        refresh = QPushButton("↻")
        refresh.setFixedWidth(32)
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
