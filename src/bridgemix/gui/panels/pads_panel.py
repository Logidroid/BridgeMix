"""
Pads panel — the six BRIDGE CAST X control pads drawn as on the device, a
sound for each pad in each of BridgeMix's sound banks, and where sounds play.

A sound pad sends its own MIDI CC (see bridgemix.device.pads); BridgeMix plays
that pad's sound in the current bank.  Two bank pads (or the arrows here) step
through the banks, which have no limit; each bank recalls one of the device's
five pad sets, so the pads keep all their device functions.  Click a pad to
edit it; a pad lights up when you press it on the device.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
_BANK_ITEMS = {"bank_prev": "BridgeMix: previous bank", "bank_next": "BridgeMix: next bank"}
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
        # Once the device is read, put it on the saved bank's pad set and colours.
        bridge.connected.connect(
            lambda c: c and QTimer.singleShot(2500, lambda: self._go_to_bank(store.load().bank))
        )
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
        """Settings key of pad *number*'s sound in the current bank."""
        return store.pad_key(store.load().bank, number)

    def _backup_key(self, number: int) -> str:
        return store.backup_key(self._pad_set(), number)

    def _is_managed(self, pad: pads.Pad) -> bool:
        """True if BridgeMix set this pad's function (sound or bank pad)."""
        return pad.is_sound_pad(self._pad_set()) or pad.bank_step is not None

    def _detail(self, pad: pads.Pad) -> str:
        """What the pad does, for its tile: its sound, bank step or device function."""
        if pad.bank_step is not None:
            return "Previous bank" if pad.bank_step < 0 else "Next bank"
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
        top.setSpacing(8)
        prev_bank = QPushButton("<")
        prev_bank.setFixedWidth(36)
        prev_bank.setToolTip("Previous bank")
        prev_bank.clicked.connect(lambda: self._step_bank(-1))
        top.addWidget(prev_bank)
        self._bank_lbl = QLabel()
        self._bank_lbl.setMinimumWidth(90)
        self._bank_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._bank_lbl.setStyleSheet("font-weight: 700; background: transparent;")
        top.addWidget(self._bank_lbl)
        next_bank = QPushButton(">")
        next_bank.setFixedWidth(36)
        next_bank.setToolTip("Next bank")
        next_bank.clicked.connect(lambda: self._step_bank(1))
        top.addWidget(next_bank)
        self._bank_name = QLineEdit()
        self._bank_name.setPlaceholderText("Bank name")
        self._bank_name.setMaximumWidth(180)
        self._bank_name.editingFinished.connect(self._rename_bank)
        top.addWidget(self._bank_name)
        top.addWidget(QLabel("Pad set:"))
        self._bank_pad_set = ScrollGuardComboBox()
        self._bank_pad_set.addItems([str(i + 1) for i in range(pads.PAD_SET_COUNT)])
        self._bank_pad_set.setToolTip("The device pad set this bank recalls")
        self._bank_pad_set.currentIndexChanged.connect(self._set_bank_pad_set)
        top.addWidget(self._bank_pad_set)
        add_bank = QPushButton("Add bank")
        add_bank.clicked.connect(self._add_bank)
        top.addWidget(add_bank)
        self._remove_bank_btn = QPushButton("Delete bank")
        self._remove_bank_btn.setToolTip("Delete this bank and its sounds")
        self._remove_bank_btn.clicked.connect(self._remove_bank)
        top.addWidget(self._remove_bank_btn)
        top.addStretch()
        self._pad_set_lbl = QLabel()
        self._pad_set_lbl.setStyleSheet(_HINT_STYLE)
        top.addWidget(self._pad_set_lbl)
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
                "Click a pad to set it up. Choose a file and the pad plays it in the "
                "current bank: BridgeMix keeps a copy (WAV, FLAC, OGG or MP3). Set two "
                "pads to the previous and next bank to change banks from the device; "
                "they are set in all five pad sets. There is no limit on banks. Banks "
                "1-5 are the device's pad sets 1-5: their functions and colours are "
                "saved in the device. Banks 6 and up use the functions of the pad set "
                "you pick and keep their own colours in BridgeMix. The pad's previous "
                "function is kept, so Remove or the function list gives it back. A pad "
                "lights up here when you press it on the device."
            )
        )
        self._update_pad_set_label()
        self._show_bank()
        return grp

    # ── banks ─────────────────────────────────────────────────────────────────

    def _show_bank(self) -> None:
        settings = store.load()
        self._bank_lbl.setText(f"Bank {settings.bank + 1} / {settings.bank_count}")
        self._bank_name.setText(settings.bank_name(settings.bank))
        device_bank = store.is_device_bank(settings.bank)
        self._remove_bank_btn.setEnabled(not device_bank)
        self._remove_bank_btn.setToolTip(
            "Banks 1-5 are the device's pad sets and can't be deleted"
            if device_bank
            else "Delete this bank and its sounds"
        )
        self._bank_pad_set.blockSignals(True)
        self._bank_pad_set.setCurrentIndex(settings.bank_pad_set(settings.bank))
        self._bank_pad_set.setEnabled(not device_bank)
        self._bank_pad_set.setToolTip(
            f"Bank {settings.bank + 1} is pad set {settings.bank + 1} of the device"
            if device_bank
            else "The device pad set this bank recalls: its pad functions"
        )
        self._bank_pad_set.blockSignals(False)

    def _bank_changed(self) -> None:
        self._show_bank()
        self._show_sound()
        self._show_color()
        for number in self._tiles:
            self._refresh_tile(number)

    def _go_to_bank(self, bank: int) -> None:
        """Select *bank*: bring its pad set onto the device's pads, lit with the
        bank's colours (banks 6 and up) or the pad set's own (banks 1-5)."""
        settings = store.load()
        settings.bank = bank % settings.bank_count
        store.save(settings)
        colors = {
            int(pad): tuple(rgb)
            for pad, rgb in settings.bank_colors.get(str(settings.bank), {}).items()
        }
        self._bridge.show_pad_set(settings.bank_pad_set(settings.bank), colors)
        self._bank_changed()

    def _step_bank(self, step: int) -> None:
        self._go_to_bank(store.load().bank + step)

    def _add_bank(self) -> None:
        settings = store.load()
        settings.bank_pad_sets[str(settings.bank_count)] = settings.bank_pad_set(settings.bank)
        settings.bank_count += 1
        store.save(settings)
        self._go_to_bank(settings.bank_count - 1)

    def _set_bank_pad_set(self, index: int) -> None:
        settings = store.load()
        settings.bank_pad_sets[str(settings.bank)] = index
        store.save(settings)
        self._go_to_bank(settings.bank)

    def _remove_bank(self) -> None:
        settings = store.load()
        if store.is_device_bank(settings.bank):
            return
        name = settings.bank_name(settings.bank) or f"Bank {settings.bank + 1}"
        answer = QMessageBox.question(
            self, "Delete bank", f"Delete {name} and its sounds? This can't be undone."
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if self._player is not None:
            self._player.stop_all()
        store.remove_bank(settings, settings.bank)
        store.save(settings)
        self._go_to_bank(settings.bank)

    def _rename_bank(self) -> None:
        settings = store.load()
        name = self._bank_name.text().strip()
        if name:
            settings.bank_names[str(settings.bank)] = name
        else:
            settings.bank_names.pop(str(settings.bank), None)
        store.save(settings)

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
        self._choose_btn = QPushButton("Choose…")
        self._choose_btn.clicked.connect(self._choose)
        sound_row.addWidget(self._choose_btn)
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

        color_row = QHBoxLayout()
        self._color_btn = QPushButton()
        self._color_btn.setFixedSize(48, 26)
        self._color_btn.setToolTip("Change the pad's light colour")
        self._color_btn.clicked.connect(self._choose_color)
        color_row.addWidget(self._color_btn)
        self._color_reset = QPushButton("Use the pad set's colour")
        self._color_reset.clicked.connect(self._reset_color)
        color_row.addWidget(self._color_reset)
        self._color_where = QLabel()
        self._color_where.setStyleSheet(_HINT_STYLE)
        color_row.addWidget(self._color_where, stretch=1)
        form.addRow("Colour:", color_row)
        return self._editor

    # ── the selected pad's colour ─────────────────────────────────────────────

    def _show_color(self) -> None:
        settings = store.load()
        pad = self._bridge.control_pads.get(self._selected)
        color = _pad_color(pad)
        self._color_btn.setStyleSheet(
            f"background-color: {color.name()}; border: 1px solid {theme.SURFACE_5};"
        )
        self._color_btn.setEnabled(pad is not None)
        custom = settings.pad_color(settings.bank, self._selected) is not None
        device_bank = store.is_device_bank(settings.bank)
        self._color_reset.setVisible(not device_bank)
        self._color_reset.setEnabled(custom)
        if device_bank:
            self._color_where.setText(f"Saved in the device (pad set {settings.bank + 1})")
        else:
            self._color_where.setText("Saved in BridgeMix for this bank")

    def _choose_color(self) -> None:
        pad = self._bridge.control_pads.get(self._selected)
        if pad is None:
            return
        picked = QColorDialog.getColor(_pad_color(pad), self, f"Colour of pad {self._selected}")
        if not picked.isValid():
            return
        rgb = tuple(round(c * 32 / 255) for c in (picked.red(), picked.green(), picked.blue()))
        settings = store.load()
        if store.is_device_bank(settings.bank):
            # Banks 1-5: the device's pad set keeps the colour.
            ok = self._bridge.set_pad_color(
                self._selected, rgb, memory_sets=[settings.bank], current=True
            )
        else:
            settings.bank_colors.setdefault(str(settings.bank), {})[str(self._selected)] = list(rgb)
            store.save(settings)
            ok = self._bridge.set_pad_color(self._selected, rgb, memory_sets=[], current=True)
        if not ok:
            QMessageBox.warning(self, "Colour not changed", "Is the BRIDGE CAST X connected?")

    def _reset_color(self) -> None:
        """Bank 6+: drop the bank's colour and show the pad set's own again."""
        settings = store.load()
        colors = settings.bank_colors.get(str(settings.bank), {})
        if colors.pop(str(self._selected), None) is None:
            return
        if not colors:
            settings.bank_colors.pop(str(settings.bank), None)
        store.save(settings)
        stored = self._bridge.pad_memory.get((settings.bank_pad_set(settings.bank), self._selected))
        if stored is not None:
            self._bridge.set_pad_color(self._selected, stored.color, memory_sets=[], current=True)
        self._show_color()

    def _select(self, number: int) -> None:
        self._selected = number
        for n, tile in self._tiles.items():
            tile.set_selected(n == number)
        self._editor.setTitle(f"PAD {number}")
        self._show_function()
        self._show_sound()
        self._show_color()

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
        pad = self._bridge.control_pads.get(self._selected)
        is_bank_pad = pad is not None and pad.bank_step is not None
        self._choose_btn.setEnabled(not is_bank_pad)
        self._choose_btn.setToolTip(
            "A bank pad has no sound: set its function to BridgeMix sound first"
            if is_bank_pad
            else ""
        )
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
        backup = store.load().pad_backup.get(self._backup_key(pad.number))
        if not self._is_managed(pad):
            combo.addItem(f"{pad.describe()} (device)", "keep")
            current = "keep"
        else:
            if backup is not None:
                previous = pads.Pad(pad.number, "", *backup)
                combo.addItem(f"{previous.describe()} (device)", "restore")
            if pad.bank_step is not None:
                current = "bank_prev" if pad.bank_step < 0 else "bank_next"
            else:
                current = "sound"
        combo.addItem(_SOUND_ITEM, "sound")
        for data, label in _BANK_ITEMS.items():
            combo.addItem(label, data)
        combo.setCurrentIndex(max(0, combo.findData(current)))
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
        self._pad_set_lbl.setText(f"Device pad set {self._pad_set() + 1}")

    def _on_pad(self, pad: pads.Pad) -> None:
        tile = self._tiles.get(pad.number)
        if tile is None:
            return
        tile.set_pad(pad, self._detail(pad))
        if pad.number == self._selected:
            self._show_function()
            self._show_sound()
            self._show_color()

    def _refresh_tile(self, number: int) -> None:
        pad = self._bridge.control_pads.get(number)
        if pad is not None:
            self._tiles[number].set_pad(pad, self._detail(pad))

    def _on_control_change(self, channel: int, control: int, value: int) -> None:
        """A sound or bank pad was pressed on the device (the player acted first)."""
        if not value:
            return
        for number, pad in self._bridge.control_pads.items():
            if pad.midi_cc == (channel, control):
                self._tiles[number].flash()
        step = pads.bank_step_for_cc(channel, control)
        if step is not None:
            self._step_bank(step)

    def _assign(self, number: int, kind: str) -> bool:
        """Make pad *number* a sound pad (in the current pad set) or a bank pad (in
        every pad set, so the bank pads work whatever set a bank recalls),
        keeping each pad's previous function."""
        pad = self._bridge.control_pads.get(number)
        if pad is None:
            return False
        current = self._pad_set()
        if kind == "sound":
            function = pads.sound_pad_function(current, number)
            pad_sets = [current]
        else:
            function = pads.bank_pad_function(-1 if kind == "bank_prev" else 1)
            pad_sets = list(range(pads.PAD_SET_COUNT))
        memory = self._bridge.pad_memory
        settings = store.load()
        for ps in pad_sets:
            before = pad if ps == current else memory.get((ps, number))
            if before is not None and not (
                before.is_sound_pad(ps) or before.bank_step is not None
            ):  # a device function: keep it
                settings.pad_backup[store.backup_key(ps, number)] = [
                    before.func,
                    before.opt1,
                    before.opt2,
                ]
        store.save(settings)
        if not self._bridge.assign_pad(number, *function, pad_sets=pad_sets):
            return False
        self._function.setEnabled(False)  # until the device reads back
        return True

    def _restore_pad(self, number: int) -> None:
        """Give pad *number* its function from before BridgeMix changed it: in the
        current pad set for a sound pad, in every pad set for a bank pad."""
        pad = self._bridge.control_pads.get(number)
        bank_pad = pad is not None and pad.bank_step is not None
        pad_sets = range(pads.PAD_SET_COUNT) if bank_pad else [self._pad_set()]
        settings = store.load()
        restored = False
        for ps in pad_sets:
            backup = settings.pad_backup.get(store.backup_key(ps, number))
            if backup is not None and self._bridge.assign_pad(number, *backup, pad_sets=[ps]):
                settings.pad_backup.pop(store.backup_key(ps, number), None)
                restored = True
        store.save(settings)
        if restored:
            self._function.setEnabled(False)

    def _on_function(self) -> None:
        number = self._selected
        choice = self._function.currentData()
        if choice in ("sound", *_BANK_ITEMS):
            ok = self._assign(number, choice)
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
        if path:
            self.assign_file(number, Path(path))

    def assign_file(self, number: int, path: Path) -> bool:
        """Put *path* (a copy) on pad *number* in the current bank and make the
        pad a sound pad.  Used by Choose… and by the Tuna page."""
        key = self._key(number)
        try:
            copy = store.import_file(key, path)
        except OSError as exc:
            QMessageBox.critical(self, "Sound not added", f"Could not copy the file:\n{exc}")
            return False
        settings = store.load()
        sound = settings.pads.setdefault(key, store.PadSound())
        previous, sound.file = sound.file, str(copy)
        store.save(settings)
        if previous != sound.file:
            store.remove_file(previous)
        self._select(number)
        self._refresh_tile(number)
        pad = self._bridge.control_pads.get(number)
        if pad is not None and pad.is_sound_pad(self._pad_set()):
            return True
        if not self._assign(number, "sound"):
            QMessageBox.warning(
                self,
                "Pad not changed",
                "The sound is saved, but the pad could not be changed: is the "
                "BRIDGE CAST X connected?",
            )
            return False
        return True

    def bank_label(self) -> str:
        """'Bank 6 (Memes)' for the current bank."""
        settings = store.load()
        name = settings.bank_name(settings.bank)
        return f"Bank {settings.bank + 1}" + (f" ({name})" if name else "")

    def pad_label(self, number: int) -> str:
        """What pad *number* does now, as shown on its tile."""
        tile = self._tiles.get(number)
        return tile.detail if tile is not None and tile.detail else "Not read yet"

    def _clear(self) -> None:
        number = self._selected
        key = self._key(number)
        if self._player is not None:
            self._player.stop(key)
        settings = store.load()
        sound = settings.pads.pop(key, None)
        store.save(settings)
        if sound is not None:
            store.remove_file(sound.file)
        self._show_sound()
        self._refresh_tile(number)
        settings = store.load()
        current = self._pad_set()
        in_use = any(
            k.endswith(f":{number}")
            and s.file
            and settings.bank_pad_set(int(k.split(":")[0])) == current
            for k, s in settings.pads.items()
        )
        if not in_use:  # no other bank on this pad set uses the pad
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
