"""
Sound pad settings: the sound of each pad, where sounds play, and the pad
functions BridgeMix replaced.

Every pad of every pad set can have its own sound; there is no other limit.
The files are copied into ``data_dir()/sounds`` so a sound keeps working if the
original file is moved.  Settings live in ``config_dir()/sounds.json``::

    {
      "pads": {"0:3": {"file": ".../set1-pad3-airhorn.wav", "volume": 80,
                       "press_again_stops": false}},
      "channel": "System",
      "voice_apps": ["Discord"],
      "pad_backup": {"0:3": [4097, 2, 0]}
    }

Keys are "pad set:pad" (pad set 0-4, pad 1-6).  ``pad_backup`` keeps a pad's
previous function (function word, option 1, option 2) so it can be given back.
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


def pad_key(pad_set: int, pad: int) -> str:
    return f"{pad_set}:{pad}"


def _file_prefix(key: str) -> str:
    pad_set, pad = key.split(":")
    return f"set{int(pad_set) + 1}-pad{pad}-"


@dataclass
class PadSound:
    file: str = ""  # copy in sounds_dir(), "" = no sound
    volume: int = 80  # 0-100
    press_again_stops: bool = False  # False: pressing again restarts the sound


@dataclass
class SoundSettings:
    pads: dict[str, PadSound] = field(default_factory=dict)
    channel: str = "System"  # Bridge Cast channel the sounds play on
    voice_apps: list[str] = field(default_factory=lambda: ["Discord"])
    pad_backup: dict[str, list[int]] = field(default_factory=dict)


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
            if isinstance(key, str) and sound is not None:
                settings.pads[key] = sound
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


def import_file(key: str, source: Path) -> Path:
    """Copy *source* into sounds_dir() for pad *key* and return the copy.

    The pad's previous copy is removed.  Raises OSError if the copy fails.
    """
    folder = sounds_dir()
    folder.mkdir(parents=True, exist_ok=True)
    prefix = _file_prefix(key)
    dest = folder / f"{prefix}{source.name}"
    tmp = dest.with_name(dest.name + ".part")
    shutil.copyfile(source, tmp)
    for old in folder.glob(f"{prefix}*"):
        if old != tmp:
            old.unlink(missing_ok=True)
    tmp.rename(dest)
    return dest


def remove_file(key: str) -> None:
    for old in sounds_dir().glob(f"{_file_prefix(key)}*"):
        old.unlink(missing_ok=True)


def display_name(file: str) -> str:
    """'…/set1-pad3-airhorn.wav' -> 'airhorn.wav'."""
    name = Path(file).name
    parts = name.split("-", 2)
    if len(parts) == 3 and parts[0].startswith("set") and parts[1].startswith("pad"):
        return parts[2]
    return name
