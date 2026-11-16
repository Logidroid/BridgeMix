"""
Sound pad settings: the four sounds (A-D), where they play, and the pad
functions BridgeMix replaced.

The sound files are copied into ``data_dir()/sounds`` so a sound keeps working
if the original file is moved.  Settings live in ``config_dir()/sounds.json``::

    {
      "slots": [{"file": ".../A-airhorn.wav", "volume": 80, "play_to_end": true}, ...],
      "channel": "System",
      "voice_apps": ["Discord"],
      "pad_backup": {"0:3": [4097, 2, 0]}
    }

``pad_backup`` keeps a pad's previous function ("pad set:pad" -> function word,
option 1, option 2) so the pads tab can give it back.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

from bridgemix.paths import config_dir, data_dir

log = logging.getLogger(__name__)

SLOT_COUNT = 4
SUPPORTED_SUFFIXES = (".wav", ".flac", ".ogg", ".oga", ".mp3")


def _settings_path() -> Path:
    return config_dir() / "sounds.json"


def sounds_dir() -> Path:
    return data_dir() / "sounds"


@dataclass
class Slot:
    file: str = ""  # copy in sounds_dir(), "" = no sound
    volume: int = 80  # 0-100
    play_to_end: bool = True  # False: stop when the pad is released


@dataclass
class SoundSettings:
    slots: list[Slot] = field(default_factory=lambda: [Slot() for _ in range(SLOT_COUNT)])
    channel: str = "System"  # Bridge Cast channel the sounds play on
    voice_apps: list[str] = field(default_factory=lambda: ["Discord"])
    pad_backup: dict[str, list[int]] = field(default_factory=dict)


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
    slots = raw.get("slots")
    if isinstance(slots, list):
        for i, s in enumerate(slots[:SLOT_COUNT]):
            if isinstance(s, dict):
                volume = s.get("volume", 80)
                settings.slots[i] = Slot(
                    file=str(s.get("file") or ""),
                    volume=max(0, min(100, volume)) if isinstance(volume, int) else 80,
                    play_to_end=bool(s.get("play_to_end", True)),
                )
    if isinstance(raw.get("channel"), str):
        settings.channel = raw["channel"]
    apps = raw.get("voice_apps")
    if isinstance(apps, list):
        settings.voice_apps = [a for a in apps if isinstance(a, str)]
    backup = raw.get("pad_backup")
    if isinstance(backup, dict):
        settings.pad_backup = {
            k: [int(x) for x in v]
            for k, v in backup.items()
            if isinstance(v, list) and len(v) == 3 and all(isinstance(x, int) for x in v)
        }
    return settings


def save(settings: SoundSettings) -> None:
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")


def import_file(slot: int, source: Path) -> Path:
    """Copy *source* into sounds_dir() for *slot* and return the copy.

    The slot's previous copy is removed.  Raises OSError if the copy fails.
    """
    letter = "ABCD"[slot]
    folder = sounds_dir()
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob(f"{letter}-*"):
        old.unlink(missing_ok=True)
    dest = folder / f"{letter}-{source.name}"
    shutil.copyfile(source, dest)
    return dest


def remove_file(slot: int) -> None:
    for old in sounds_dir().glob(f"{'ABCD'[slot]}-*"):
        old.unlink(missing_ok=True)


def backup_key(pad_set: int, pad: int) -> str:
    return f"{pad_set}:{pad}"
