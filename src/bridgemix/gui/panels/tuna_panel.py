"""
Tuna panel — Voicemod's Tuna site (tuna.voicemod.net) inside BridgeMix.

You browse it as in a web browser: its play buttons preview the sounds, and
its download button (the cloud) saves a sound into BridgeMix's sound library.
From there, one click puts it on a pad of the current bank.  BridgeMix only
shows the site; it sends no requests of its own to Voicemod.  Voicemod's terms
of use allow Tuna sounds for personal, non-commercial use only.

Needs PyQt6-WebEngine, an optional dependency, and the Qt attribute
AA_ShareOpenGLContexts set before the QApplication is created (__main__ does).
The web view starts the first time the page is shown.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QCoreApplication, QProcess, Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bridgemix.gui.widgets.controls import ScrollGuardComboBox
from bridgemix.paths import data_dir
from bridgemix.sounds import store

if TYPE_CHECKING:
    from bridgemix.gui.panels.pads_panel import PadsPanel
    from bridgemix.sounds.player import SoundPlayer

log = logging.getLogger(__name__)

HOME_URL = "https://tuna.voicemod.net/"
# Hosts the page may navigate to; other links open in the default browser.
# Voicemod's own sites, and the sign-in providers its login page offers.
_ALLOWED_HOSTS = (
    "voicemod.net",
    "voicemod.com",
    "google.com",
    "discord.com",
    "twitch.tv",
    "apple.com",
    "facebook.com",
)
_HINT_STYLE = "font-size: 12px; color: #9a9aa2; background-color: transparent;"


def library_dir() -> Path:
    """Sounds downloaded from Tuna, before (and after) they go on a pad."""
    return data_dir() / "sounds" / "library"


def _web_engine_usable() -> bool:
    """PyQt6-WebEngine installed, and the app started in a way that allows it."""
    if not QCoreApplication.testAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts):
        return False
    try:
        import PyQt6.QtWebEngineWidgets  # noqa: F401
    except ImportError:
        return False
    return True


def _allowed(host: str) -> bool:
    host = host.lower()
    return any(host == h or host.endswith("." + h) for h in _ALLOWED_HOSTS)


class TunaPanel(QWidget):
    def __init__(
        self, pads_panel: PadsPanel, player: SoundPlayer | None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._pads = pads_panel
        self._player = player
        self._view = None  # the QWebEngineView, created on first show
        self._web_tried = False
        self._pad_buttons: list[QPushButton] = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        bar = QHBoxLayout()
        self._back = QPushButton("<")
        self._back.setFixedWidth(36)
        self._back.setToolTip("Back")
        bar.addWidget(self._back)
        home = QPushButton("Tuna home")
        home.clicked.connect(lambda: self._view and self._view.setUrl(QUrl(HOME_URL)))
        bar.addWidget(home)
        reload_btn = QPushButton("Reload")
        reload_btn.clicked.connect(lambda: self._view and self._view.reload())
        bar.addWidget(reload_btn)
        self._url = QLabel(HOME_URL)
        self._url.setStyleSheet(_HINT_STYLE)
        bar.addWidget(self._url, stretch=1)
        lay.addLayout(bar)

        self._web_box = QVBoxLayout()
        lay.addLayout(self._web_box, stretch=1)

        lay.addWidget(self._make_library_bar())
        note = QLabel(
            "Use the play buttons on the site to listen, and its download button (the "
            "cloud) to add a sound to the library below. Tuna is Voicemod's site: its "
            "sounds are for personal, non-commercial use."
        )
        note.setWordWrap(True)
        note.setStyleSheet(_HINT_STYLE)
        lay.addWidget(note)
        self._refresh_library()
        pads_panel.pads_changed.connect(self._refresh_pad_buttons)

    # ── web view ──────────────────────────────────────────────────────────────

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._web_tried:
            self._web_tried = True
            self._start_web_view()
        self._refresh_pad_buttons()

    def _start_web_view(self) -> None:
        if not _web_engine_usable():
            self._show_missing_web_engine()
            return
        from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
        from PyQt6.QtWebEngineWidgets import QWebEngineView

        class _Page(QWebEnginePage):
            def acceptNavigationRequest(self, url, _type, is_main_frame) -> bool:
                if url.scheme() not in ("http", "https"):
                    return False  # e.g. "Try in App" (voicemod://): not available here
                if not is_main_frame or _allowed(url.host()):
                    return True
                QDesktopServices.openUrl(url)  # other sites: the default browser
                return False

            def createWindow(self, _type):
                return self  # links meant for a new tab open here

        storage = data_dir() / "tuna-web"
        self._profile = QWebEngineProfile("bridgemix-tuna", self)
        self._profile.setPersistentStoragePath(str(storage / "storage"))
        self._profile.setCachePath(str(storage / "cache"))
        self._profile.downloadRequested.connect(self._on_download)
        self._view = QWebEngineView(self)
        self._view.setPage(_Page(self._profile, self._view))
        self._view.urlChanged.connect(lambda u: self._url.setText(u.toString()))
        self._back.clicked.connect(self._view.back)
        self._web_box.addWidget(self._view)
        self._view.setUrl(QUrl(HOME_URL))

    def _show_missing_web_engine(self) -> None:
        box = QWidget()
        col = QVBoxLayout(box)
        col.addStretch()
        text = QLabel(
            "Showing Tuna needs Qt WebEngine (the PyQt6-WebEngine package, about "
            "200 MB), which isn't installed."
        )
        text.setWordWrap(True)
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(text)
        in_venv = sys.prefix != sys.base_prefix and not getattr(sys, "frozen", False)
        if in_venv:
            install = QPushButton("Install Qt WebEngine")
            install.clicked.connect(lambda: self._install_web_engine(install, text))
            col.addWidget(install, alignment=Qt.AlignmentFlag.AlignCenter)
        browser = QPushButton("Open Tuna in the browser")
        browser.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(HOME_URL)))
        col.addWidget(browser, alignment=Qt.AlignmentFlag.AlignCenter)
        col.addStretch()
        self._web_box.addWidget(box)

    def _install_web_engine(self, button: QPushButton, text: QLabel) -> None:
        button.setEnabled(False)
        text.setText("Installing Qt WebEngine…")
        proc = QProcess(self)
        proc.finished.connect(
            lambda code, _status: text.setText(
                "Qt WebEngine is installed: restart BridgeMix to show Tuna."
                if code == 0
                else "The installation failed; see the terminal or the logs."
            )
        )
        proc.start(sys.executable, ["-m", "pip", "install", "PyQt6-WebEngine"])

    # ── downloads → library ───────────────────────────────────────────────────

    def _on_download(self, request) -> None:
        name = Path(request.downloadFileName() or "sound.mp3").name
        if Path(name).suffix.lower() not in store.SUPPORTED_SUFFIXES:
            request.cancel()
            self._status.setText(f"{name} isn't a sound file BridgeMix can play.")
            return
        folder = library_dir()
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / name
        n = 2
        while dest.exists():
            dest = folder / f"{Path(name).stem}-{n}{Path(name).suffix}"
            n += 1
        request.setDownloadDirectory(str(folder))
        request.setDownloadFileName(dest.name)
        request.isFinishedChanged.connect(lambda: self._download_done(request, dest))
        request.accept()
        self._status.setText(f"Downloading {dest.name}…")

    def _download_done(self, request, dest: Path) -> None:
        from PyQt6.QtWebEngineCore import QWebEngineDownloadRequest

        if request.state() != QWebEngineDownloadRequest.DownloadState.DownloadCompleted:
            self._status.setText(f"{dest.name}: download failed.")
            return
        self._refresh_library(select=dest)
        self._status.setText(f"{dest.name} is in the library: put it on a pad.")

    # ── library bar ───────────────────────────────────────────────────────────

    def _make_library_bar(self) -> QWidget:
        box = QWidget()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 4, 0, 0)
        col.setSpacing(6)

        row = QHBoxLayout()
        row.addWidget(QLabel("Library:"))
        self._library = ScrollGuardComboBox()
        self._library.setMinimumWidth(260)
        row.addWidget(self._library, stretch=1)
        play = QPushButton("Play")
        play.setToolTip("Preview: only you hear it")
        play.clicked.connect(self._preview)
        play.setEnabled(self._player is not None)
        row.addWidget(play)
        stop = QPushButton("Stop")
        stop.clicked.connect(lambda: self._player and self._player.stop(self._player.PREVIEW_KEY))
        stop.setEnabled(self._player is not None)
        row.addWidget(stop)
        delete = QPushButton("Delete")
        delete.setToolTip("Delete this sound from the library (pads keep their own copy)")
        delete.clicked.connect(self._delete)
        row.addWidget(delete)
        col.addLayout(row)

        pads_row = QHBoxLayout()
        self._bank = QLabel()
        pads_row.addWidget(self._bank)
        for n in range(1, 7):
            btn = QPushButton(f"PAD {n}")
            btn.clicked.connect(lambda _c, num=n: self._put_on_pad(num))
            pads_row.addWidget(btn)
            self._pad_buttons.append(btn)
        pads_row.addStretch()
        col.addLayout(pads_row)

        self._status = QLabel()
        self._status.setStyleSheet(_HINT_STYLE)
        col.addWidget(self._status)
        return box

    def _refresh_library(self, select: Path | None = None) -> None:
        folder = library_dir()
        files = (
            sorted(
                (p for p in folder.iterdir() if p.suffix.lower() in store.SUPPORTED_SUFFIXES),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if folder.is_dir()
            else []
        )
        self._library.clear()
        for f in files:
            self._library.addItem(f.name, str(f))
        if select is not None:
            self._library.setCurrentIndex(max(0, self._library.findData(str(select))))
        has = bool(files)
        for btn in self._pad_buttons:
            btn.setEnabled(has)

    def _refresh_pad_buttons(self) -> None:
        """Offer the pads of the current bank, except the bank pads."""
        self._bank.setText(f"Put on a pad of {self._pads.bank_label()}:")
        for n, btn in enumerate(self._pad_buttons, start=1):
            btn.setVisible(not self._pads.is_bank_pad(n))
            btn.setToolTip(f"PAD {n} now: {self._pads.pad_label(n)}")

    def _selected_file(self) -> Path | None:
        data = self._library.currentData()
        return Path(data) if data else None

    def _preview(self) -> None:
        path = self._selected_file()
        if path is not None and self._player is not None:
            self._player.preview_file(path)

    def _delete(self) -> None:
        path = self._selected_file()
        if path is None:
            return
        answer = QMessageBox.question(self, "Delete sound", f"Delete {path.name} from the library?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("Could not delete %s: %s", path, exc)
        self._refresh_library()

    def _put_on_pad(self, number: int) -> None:
        path = self._selected_file()
        if path is None:
            return
        if self._pads.assign_file(number, path):
            self._status.setText(f"{path.name} is on pad {number} of {self._pads.bank_label()}.")
        self._refresh_pad_buttons()
