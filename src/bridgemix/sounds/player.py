"""
Plays the sound pads' sounds through PipeWire.

A sound pad (see bridgemix.device.pads) sends its own MIDI CC when pressed;
handle_control_change() plays the sound saved for that pad.

A sound plays with ``pw-play`` on a Bridge Cast channel (System by default, as
Roland's app does), so you hear it and the STREAM mix gets it.  It is also
linked straight into the recording streams of the chosen voice chat apps
(Discord by default): PipeWire adds every link into an input port, so the app
records your mic plus the sound, with no virtual device.  The links go away
with the sound.

Linux only: needs PipeWire's ``pw-play``, ``pw-link`` and ``pw-dump``.
"""

from __future__ import annotations

import itertools
import json
import logging
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from bridgemix.device import pads
from bridgemix.routing import backend
from bridgemix.sounds import store

log = logging.getLogger(__name__)

NODE_PREFIX = backend.OWN_SOUND_PREFIX  # node.name prefix of every sound played here
_PORT_WAIT_S = 1.0


def available() -> bool:
    return sys.platform.startswith("linux") and all(
        shutil.which(tool) for tool in ("pw-play", "pw-link", "pw-dump")
    )


def _run(args: list[str], timeout: float = 3) -> str:
    try:
        return subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, check=False
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("%s failed: %s", args[0], exc)
        return ""


def recording_ports(apps: list[str]) -> list[tuple[int, str]]:
    """(port id, channel) of the input ports of recording streams of *apps*.

    An app matches on its process binary or its application name, ignoring case.
    """
    wanted = {a.casefold() for a in apps}
    try:
        objects = json.loads(_run(["pw-dump"]) or "[]")
    except ValueError:
        return []
    nodes = set()
    for o in objects:
        props = (o.get("info") or {}).get("props") or {}
        if not o.get("type", "").endswith("Node"):
            continue
        if props.get("media.class") != "Stream/Input/Audio":
            continue
        names = {
            str(props.get(k, "")).casefold()
            for k in ("application.process.binary", "application.name")
        }
        if names & wanted:
            nodes.add(o["id"])
    ports = []
    for o in objects:
        info = o.get("info") or {}
        props = info.get("props") or {}
        if (
            o.get("type", "").endswith("Port")
            and info.get("direction") == "input"
            and props.get("node.id") in nodes
        ):
            ports.append((o["id"], str(props.get("audio.channel", ""))))
    return ports


class SoundPlayer:
    """Plays one sound per pad; a pad pressed again restarts or stops its sound."""

    def __init__(self) -> None:
        self._procs: dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()
        self._counter = itertools.count(1)

    def handle_control_change(self, channel: int, control: int, value: int) -> None:
        """A sound pad sends its own CC (value 127) when pressed."""
        found = pads.pad_for_cc(channel, control)
        if found is None or value == 0:
            return
        key = store.pad_key(*found)
        sound = store.load().pads.get(key)
        if sound is None or not sound.file:
            log.info("Pad %s of pad set %d has no sound", found[1], found[0] + 1)
            return
        if sound.press_again_stops and self.is_playing(key):
            self.stop(key)
        else:
            self.play(key)

    def play(self, key: str, *, voice_chat: bool = True) -> None:
        """Play the sound of pad *key*; *voice_chat* False plays it only here (preview)."""
        threading.Thread(target=self._play, args=(key, voice_chat), daemon=True).start()

    def is_playing(self, key: str) -> bool:
        with self._lock:
            proc = self._procs.get(key)
        return proc is not None and proc.poll() is None

    def stop(self, key: str) -> None:
        with self._lock:
            proc = self._procs.pop(key, None)
        if proc is not None and proc.poll() is None:
            proc.terminate()

    def stop_all(self) -> None:
        for key in list(self._procs):
            self.stop(key)

    # ── worker thread ─────────────────────────────────────────────────────────

    def _play(self, key: str, voice_chat: bool) -> None:
        settings = store.load()
        sound = settings.pads.get(key)
        if sound is None or not Path(sound.file).is_file():
            log.info("No sound file for pad %s", key)
            return
        self.stop(key)  # pressing again restarts the sound

        name = f"{NODE_PREFIX}-{key.replace(':', '-')}-{next(self._counter)}"
        props = f'{{ node.name = "{name}" media.name = "BridgeMix pad sound" }}'
        cmd = ["pw-play", "--volume", f"{sound.volume / 100:.2f}", "-P", props]
        target = backend.resolve_target(settings.channel, backend.list_targets())
        if target is not None:
            cmd += ["--target", target.sink_name]
        try:
            proc = subprocess.Popen(
                [*cmd, sound.file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except OSError as exc:
            log.warning("Could not play the sound of pad %s: %s", key, exc)
            return
        with self._lock:
            self._procs[key] = proc
        if voice_chat and settings.voice_apps:
            self._link_to_apps(name, settings.voice_apps, proc)

    def _link_to_apps(self, name: str, apps: list[str], proc: subprocess.Popen) -> None:
        outputs: dict[str, str] = {}  # channel -> "node:port"
        deadline = time.monotonic() + _PORT_WAIT_S
        while not outputs and time.monotonic() < deadline and proc.poll() is None:
            for line in _run(["pw-link", "-o"]).splitlines():
                if line.startswith(f"{name}:output_"):
                    outputs[line.rsplit("_", 1)[-1]] = line.strip()
            if not outputs:
                time.sleep(0.01)
        if not outputs:
            return
        fallback = outputs.get("FL") or outputs.get("MONO") or next(iter(outputs.values()))
        for port_id, channel in recording_ports(apps):
            source = outputs.get(channel, fallback)
            _run(["pw-link", source, str(port_id)])
