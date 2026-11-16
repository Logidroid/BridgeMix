"""
Sound pad settings: BridgeMix's sound banks, the sound of each pad in each
bank, where sounds play, and the pad functions BridgeMix replaced.

There is no limit on banks: the bank pads (or the tab) step through them, and
each sound pad plays its sound in the current bank.  The files are copied into
``data_dir()/sounds`` so a sound keeps working if the original file is moved.
Settings live in ``config_dir()/sounds.json``::

    {
      "pads": {"0:1": {"file": ".../bank1-pad1-airhorn.wav", "volume": 80,
                       "press_again_stops": false}},
      "bank": 0,
      "bank_count": 3,
      "bank_names": {"0": "Memes"},
      "channel": "System",
      "voice_apps": ["Discord"],
      "pad_backup": {"0:3": [4097, 2, 0]}
    }

``pads`` keys are "bank:pad" (bank from 0, pad 1-6).  ``pad_backup`` keys are
"device pad set:pad": a pad's function before BridgeMix changed it (function
word, option 1, option 2), so it can be given back.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

from bridgemix.paths import config_dir, data_dir

log = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = (".wav", ".flac", ".ogg", ".oga", ".mp3")


def _settings_path() -> Path:
    return config_dir() / "sounds.json"


def sounds_dir() -> Path:
    return data_dir() / "sounds"


def pad_key(bank: int, pad: int) -> str:
    return f"{bank}:{pad}"


def backup_key(pad_set: int, pad: int) -> str:
    return f"{pad_set}:{pad}"


def _split_key(key: str) -> tuple[int, int] | None:
    try:
        bank, pad = (int(x) for x in key.split(":"))
    except ValueError:
        return None
    return bank, pad


@dataclass
class PadSound:
    file: str = ""  # copy in sounds_dir(), "" = no sound
    volume: int = 80  # 0-100
    press_again_stops: bool = False  # False: pressing again restarts the sound


@dataclass
class SoundSettings:
    pads: dict[str, PadSound] = field(default_factory=dict)
    bank: int = 0  # current bank
    bank_count: int = 1
    bank_names: dict[str, str] = field(default_factory=dict)  # "bank" -> name
    channel: str = "System"  # Bridge Cast channel the sounds play on
    voice_apps: list[str] = field(default_factory=lambda: ["Discord"])
    pad_backup: dict[str, list[int]] = field(default_factory=dict)

    def bank_name(self, bank: int) -> str:
        return self.bank_names.get(str(bank), "")


def _pad_sound(raw: object) -> PadSound | None:
    if not isinstance(raw, dict):
        return None
    volume = raw.get("volume", 80)
    return PadSound(
        file=str(raw.get("file") or ""),
        volume=max(0, min(100, volume)) if isinstance(volume, int) else 80,
        press_again_stops=bool(raw.get("press_again_stops", False)),
    )


def load() -> SoundSettings:
    """Saved settings; defaults for anything missing or malformed.  Never raises."""
    try:
        raw = json.loads(_settings_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return SoundSettings()
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        log.warning("Could not read sound settings %s: %s", _settings_path(), exc)
        return SoundSettings()
    if not isinstance(raw, dict):
        return SoundSettings()

    settings = SoundSettings()
    pads = raw.get("pads")
    if isinstance(pads, dict):
        for key, value in pads.items():
            sound = _pad_sound(value)
            if isinstance(key, str) and _split_key(key) and sound is not None:
                settings.pads[key] = sound
    names = raw.get("bank_names")
    if isinstance(names, dict):
        settings.bank_names = {
            k: v for k, v in names.items() if k.isdigit() and isinstance(v, str) and v
        }
    count = raw.get("bank_count")
    used = max((_split_key(k)[0] + 1 for k in settings.pads), default=1)  # type: ignore[index]
    settings.bank_count = max(count if isinstance(count, int) else 1, used, 1)
    bank = raw.get("bank")
    settings.bank = bank if isinstance(bank, int) and 0 <= bank < settings.bank_count else 0
    if isinstance(raw.get("channel"), str):
        settings.channel = raw["channel"]
    apps = raw.get("voice_apps")
    if isinstance(apps, list):
        settings.voice_apps = [a for a in apps if isinstance(a, str)]
    backup = raw.get("pad_backup")
    if isinstance(backup, dict):
        settings.pad_backup = {
            k: list(v)
            for k, v in backup.items()
            if isinstance(v, list) and len(v) == 3 and all(isinstance(x, int) for x in v)
        }
    return settings


def save(settings: SoundSettings) -> None:
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")


def step_bank(step: int) -> int:
    """Go to the previous (-1) or next (+1) bank, wrapping around; returns it."""
    settings = load()
    settings.bank = (settings.bank + step) % settings.bank_count
    save(settings)
    return settings.bank


def import_file(key: str, source: Path) -> Path:
    """Copy *source* into sounds_dir() for pad *key* ("bank:pad"); returns the copy.

    The caller removes the pad's previous file (remove_file).  Raises OSError if
    the copy fails.
    """
    bank, pad = _split_key(key) or (0, 0)
    folder = sounds_dir()
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"bank{bank + 1}-pad{pad}-{source.name}"
    n = 2
    while dest.exists():
        dest = folder / f"bank{bank + 1}-pad{pad}-{source.stem}-{n}{source.suffix}"
        n += 1
    shutil.copyfile(source, dest)
    return dest


def remove_file(file: str) -> None:
    """Delete a sound copy, only if it is one of ours (inside sounds_dir())."""
    if not file:
        return
    path = Path(file)
    try:
        if path.resolve().parent == sounds_dir().resolve():
            path.unlink(missing_ok=True)
    except OSError as exc:
        log.warning("Could not remove %s: %s", path, exc)


def remove_bank(settings: SoundSettings, bank: int) -> None:
    """Delete *bank*'s sounds and move the banks after it down by one."""
    pads: dict[str, PadSound] = {}
    for key, sound in settings.pads.items():
        b, pad = _split_key(key) or (0, 0)
        if b == bank:
            remove_file(sound.file)
        else:
            pads[pad_key(b - 1 if b > bank else b, pad)] = sound
    settings.pads = pads
    names = {}
    for k, v in settings.bank_names.items():
        b = int(k)
        if b != bank:
            names[str(b - 1 if b > bank else b)] = v
    settings.bank_names = names
    settings.bank_count = max(1, settings.bank_count - 1)
    settings.bank = min(settings.bank, settings.bank_count - 1)


def display_name(file: str) -> str:
    """'…/bank1-pad3-airhorn.wav' -> 'airhorn.wav'."""
    name = Path(file).name
    parts = name.split("-", 2)
    if len(parts) == 3 and parts[0].startswith(("bank", "set")) and parts[1].startswith("pad"):
        return parts[2]
    return name
