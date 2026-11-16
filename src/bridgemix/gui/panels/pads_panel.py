"""
Pads panel — the sounds A-D that BridgeMix plays when a pad asks for them,
where they play, and (BRIDGE CAST X) which pads play them.

A pad set to SOUND EFFECTS doesn't play anything itself: the device sends
"play sound n" to the host.  Roland's app plays sounds from its BGM CAST
library; BridgeMix plays the files chosen here (see bridgemix.sounds).
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


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(_HINT_STYLE)
    return label


def _display_name(file: str) -> str:
    """'…/A-airhorn.wav' -> 'airhorn.wav'; '' -> 'No sound'."""
    if not file:
        return "No sound"
    name = Path(file).name
    return name[2:] if len(name) > 2 and name[1] == "-" else name


class PadsPanel(QWidget):
    def __init__(
        self, bridge: BridgeCast, player: SoundPlayer | None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._bridge = bridge
        self._player = player
        self._settings = store.load()
        self._pad_combos: dict[int, ScrollGuardComboBox] = {}
        self._pad_names: dict[int, QLabel] = {}
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
        lay.addWidget(self._sounds_group())
        lay.addWidget(self._output_group())
        self._pads_group = self._make_pads_group()
        lay.addWidget(self._pads_group)
        self._other_models_hint = _hint(
            "On a BRIDGE CAST X, the pads set to a sound below play it. On other "
            "models, a button set to SOUND EFFECTS A–D in Roland's app should play "
            "these sounds too (not tested)."
        )
        lay.addWidget(self._other_models_hint)
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

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh_channels()
        self._refresh_apps()
        self._bridge.request_pads()

    # ── sounds A-D ────────────────────────────────────────────────────────────

    def _sounds_group(self) -> QGroupBox:
        grp = QGroupBox("SOUNDS")
        grid = QGridLayout(grp)
        grid.setContentsMargins(10, 6, 10, 10)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        self._file_labels: list[QLabel] = []
        self._play_btns: list[QPushButton] = []
        for slot in range(store.SLOT_COUNT):
            sound = self._settings.slots[slot]
            letter = QLabel("ABCD"[slot])
            letter.setStyleSheet("font-weight: 700; background: transparent;")
            grid.addWidget(letter, slot, 0)

            name = QLabel(_display_name(sound.file))
            name.setMinimumWidth(160)
            name.setToolTip(sound.file or "Choose a sound file")
            self._file_labels.append(name)
            grid.addWidget(name, slot, 1)

            choose = QPushButton("Choose…")
            choose.clicked.connect(lambda _, s=slot: self._choose(s))
            grid.addWidget(choose, slot, 2)

            play = QPushButton("▶")
            play.setFixedWidth(32)
            play.setToolTip("Preview (only you hear it)")
            play.clicked.connect(lambda _, s=slot: self._preview(s))
            self._play_btns.append(play)
            grid.addWidget(play, slot, 3)

            stop = QPushButton("■")
            stop.setFixedWidth(32)
            stop.setToolTip("Stop")
            stop.setEnabled(self._player is not None)
            stop.clicked.connect(lambda _, s=slot: self._player and self._player.stop(s))
            grid.addWidget(stop, slot, 4)

            volume = Slider(Qt.Orientation.Horizontal)
            volume.setRange(0, 100)
            volume.setValue(sound.volume)
            volume.setFixedWidth(120)
            value = QLabel(f"{sound.volume}%")
            value.setFixedWidth(40)
            volume.valueChanged.connect(lambda v, lbl=value: lbl.setText(f"{v}%"))
            volume.valueChanged.connect(lambda v, s=slot: self._set_volume(s, v))
            grid.addWidget(volume, slot, 5)
            grid.addWidget(value, slot, 6)

            to_end = QCheckBox("Play to end")
            to_end.setChecked(sound.play_to_end)
            to_end.setToolTip("Off: the sound stops when you release the pad")
            to_end.toggled.connect(lambda on, s=slot: self._set_play_to_end(s, on))
            grid.addWidget(to_end, slot, 7)

            clear = QPushButton("✕")
            clear.setFixedWidth(32)
            clear.setToolTip("Remove this sound")
            clear.clicked.connect(lambda _, s=slot: self._clear(s))
            grid.addWidget(clear, slot, 8)
        grid.setColumnStretch(1, 1)
        grid.addWidget(
            _hint(
                "BridgeMix keeps a copy of each file. WAV, FLAC, OGG or MP3. "
                "Pressing a pad again restarts its sound."
            ),
            store.SLOT_COUNT,
            0,
            1,
            9,
        )
        self._update_play_buttons()
        return grp

    def _choose(self, slot: int) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, f"Sound {'ABCD'[slot]}", str(Path.home()), _FILE_FILTER
        )
        if not path:
            return
        try:
            copy = store.import_file(slot, Path(path))
        except OSError as exc:
            QMessageBox.critical(self, "Sound not added", f"Could not copy the file:\n{exc}")
            return
        self._settings = store.load()
        self._settings.slots[slot].file = str(copy)
        store.save(self._settings)
        self._file_labels[slot].setText(_display_name(str(copy)))
        self._file_labels[slot].setToolTip(path)
        self._update_play_buttons()

    def _clear(self, slot: int) -> None:
        if self._player is not None:
            self._player.stop(slot)
        store.remove_file(slot)
        self._settings = store.load()
        self._settings.slots[slot].file = ""
        store.save(self._settings)
        self._file_labels[slot].setText(_display_name(""))
        self._file_labels[slot].setToolTip("Choose a sound file")
        self._update_play_buttons()

    def _preview(self, slot: int) -> None:
        if self._player is not None:
            self._player.play(slot, voice_chat=False)

    def _set_volume(self, slot: int, volume: int) -> None:
        self._settings = store.load()
        self._settings.slots[slot].volume = volume
        store.save(self._settings)

    def _set_play_to_end(self, slot: int, on: bool) -> None:
        self._settings = store.load()
        self._settings.slots[slot].play_to_end = on
        store.save(self._settings)

    def _update_play_buttons(self) -> None:
        for slot, btn in enumerate(self._play_btns):
            btn.setEnabled(self._player is not None and bool(self._settings.slots[slot].file))

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
                "record them along with your mic, so your friends hear them. If "
                "they don't, set Discord's noise suppression to Standard or off."
            )
        )
        return grp

    def _refresh_channels(self) -> None:
        labels = [t.label for t in backend.list_targets()] if backend.available() else []
        if self._settings.channel not in labels:
            labels.append(self._settings.channel)
        self._channel_combo.blockSignals(True)
        self._channel_combo.clear()
        self._channel_combo.addItems(labels)
        self._channel_combo.setCurrentText(self._settings.channel)
        self._channel_combo.blockSignals(False)

    def _on_channel(self, _i: int) -> None:
        self._settings = store.load()
        self._settings.channel = self._channel_combo.currentText()
        store.save(self._settings)

    def _refresh_apps(self) -> None:
        recording = backend.list_recording_apps() if backend.available() else []
        apps = list(dict.fromkeys([*self._settings.voice_apps, *recording]))
        for name in list(self._app_checks):
            if name not in apps:
                self._app_checks.pop(name).deleteLater()
        for name in apps:
            if name not in self._app_checks:
                check = QCheckBox(name)
                check.setChecked(name in self._settings.voice_apps)
                check.toggled.connect(lambda on, n=name: self._on_app(n, on))
                self._apps_lay.insertWidget(self._apps_lay.count() - 2, check)
                self._app_checks[name] = check

    def _on_app(self, name: str, on: bool) -> None:
        self._settings = store.load()
        apps = [a for a in self._settings.voice_apps if a != name]
        self._settings.voice_apps = [*apps, name] if on else apps
        store.save(self._settings)

    # ── pads (BRIDGE CAST X) ──────────────────────────────────────────────────

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
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        for n in range(1, pads.PAD_COUNT + 1):
            grid.addWidget(QLabel(f"PAD {n}"), n - 1, 0)
            name = QLabel("—")
            name.setStyleSheet("color: #9a9aa2; background: transparent;")
            name.setMinimumWidth(110)
            self._pad_names[n] = name
            grid.addWidget(name, n - 1, 1)
            combo = ScrollGuardComboBox()
            combo.setMinimumWidth(200)
            combo.setEnabled(False)
            combo.currentIndexChanged.connect(lambda _i, num=n: self._on_pad_choice(num))
            self._pad_combos[n] = combo
            grid.addWidget(combo, n - 1, 2)
        grid.setColumnStretch(3, 1)
        lay.addLayout(grid)
        lay.addWidget(
            _hint(
                "A pad set to a sound asks BridgeMix to play it. The change is saved "
                "in the current pad set of the device; switch pad sets on the device "
                "to set up the others. The pad's previous function is kept, so you "
                "can give it back."
            )
        )
        self._update_pad_set_label()
        return grp

    def _update_model(self) -> None:
        is_x = self._bridge.is_bridge_cast_x
        self._pads_group.setVisible(is_x)
        self._other_models_hint.setVisible(not is_x)
        if is_x and self.isVisible():
            self._bridge.request_pads()

    def _on_param(self, name: str, _value: int) -> None:
        if name == "pad_set_no":
            self._update_pad_set_label()
            self._bridge.request_pads()  # the device loaded the pads of that set

    def _pad_set(self) -> int:
        try:
            return self._bridge.get_parameter("pad_set_no")
        except KeyError:
            return 0

    def _update_pad_set_label(self) -> None:
        self._pad_set_lbl.setText(f"Pad set {self._pad_set() + 1}")

    def _backup(self, number: int) -> list[int] | None:
        return store.load().pad_backup.get(store.backup_key(self._pad_set(), number))

    def _on_pad(self, pad: pads.Pad) -> None:
        combo = self._pad_combos.get(pad.number)
        if combo is None:
            return
        self._pad_names[pad.number].setText(pad.name or "—")
        backup = self._backup(pad.number)
        combo.blockSignals(True)
        combo.clear()
        if pad.sound_slot is None:
            combo.addItem(f"{pad.describe()} (device)", "keep")
        elif backup is not None:
            previous = pads.Pad(pad.number, "", *backup)
            combo.addItem(f"{previous.describe()} (device)", "restore")
        for slot in range(store.SLOT_COUNT):
            combo.addItem(f"BridgeMix sound {'ABCD'[slot]}", f"sound:{slot}")
        current = "keep" if pad.sound_slot is None else f"sound:{pad.sound_slot}"
        combo.setCurrentIndex(max(0, combo.findData(current)))
        combo.setEnabled(True)
        combo.blockSignals(False)

    def _on_pad_choice(self, number: int) -> None:
        combo = self._pad_combos[number]
        choice = combo.currentData() or "keep"
        pad = self._bridge.control_pads.get(number)
        if pad is None or choice == "keep":
            return
        settings = store.load()
        key = store.backup_key(self._pad_set(), number)
        written = False
        if choice.startswith("sound:"):
            slot = int(choice.split(":")[1])
            if pad.sound_slot == slot:
                return
            if pad.sound_slot is None:  # keep what the pad did on the device
                settings.pad_backup[key] = [pad.func, pad.opt1, pad.opt2]
                store.save(settings)
            written = self._bridge.assign_pad(number, pads.sound_effects_func(), slot, 0)
        elif choice == "restore" and key in settings.pad_backup:
            func, opt1, opt2 = settings.pad_backup[key]
            written = self._bridge.assign_pad(number, func, opt1, opt2)
            if written:
                settings.pad_backup.pop(key, None)
                store.save(settings)
        if written:
            combo.setEnabled(False)  # until the device reads back (pad_changed)
        else:
            self._on_pad(pad)  # not connected: show the pad as it is
