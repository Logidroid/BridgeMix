"""
BRIDGE CAST X control pads: where each pad lives and what its function word means.

Measured on a BRIDGE CAST X with firmware 3.00:

- The current pads are in SECTION_CHANNEL (0x03), blocks 0x0A–0x0C, two pads
  per block: pad 1 at 0x0A/0x20, pad 2 at 0x0A/0x50, pad 3 at 0x0B/0x20 and so
  on.  Each pad is 0x30 bytes: an 18-byte name, then 14-bit words (MSB first)
  for the function at +0x20, the colour at +0x22/+0x24/+0x26 and the two
  options at +0x28/+0x2A.
- The five pad sets are kept in section 0x12, block (set << 4) + 0..2, with the
  same layout.  Changing a pad persistently means writing both copies; the
  memory copy alone doesn't change the current pad, and the current copy alone
  is lost when another pad set is recalled.
- The function word is 0x1000 + the command number (every pad read so far
  carries 0x1000).  1 = SFX, 2 = SOUND EFFECTS (pressing the pad sends
  7F 7F 7F 1A <slot> to the host, releasing it 7F 7F 7F 1C), 6 = PAD set
  +/-, 10 = REVERB.  The other numbers follow the order of Roland's command
  list and are not confirmed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

PAD_COUNT = 6
PAD_SIZE = 0x30  # bytes per pad, from its name to the end of its options
SECTION_PAD_SET_MEMORY = 0x12
TYPE_PADS_FIRST = 0x0A  # SECTION_CHANNEL block holding pads 1 and 2
ADDR_PAD_SET_NO = 0x36  # SECTION_CHANNEL / TYPE_SWITCH: current pad set, 0-4

NAME_LEN = 18
OFF_FUNC = 0x20
OFF_OPT1 = 0x28
OFF_OPT2 = 0x2A

FUNC_BASE = 0x1000

# Host commands sent by a SOUND EFFECTS pad (SECTION 0x7F, TYPE 0x7F).
CMD_SOUND_EFFECT_PLAY = 0x1A
CMD_SOUND_EFFECT_STOP = 0x1C
SOUND_EFFECT_SLOTS = 4  # A-D


class Command(IntEnum):
    MUTE = 0
    SFX = 1
    SOUND_EFFECTS = 2
    PROFILE = 3
    GAME_EQ = 4
    MIC_EFFECTS = 5
    PAD = 6
    MIDI_CC = 7
    HOTKEY = 8
    REVERB = 10
    BGM_CAST = 11


_COMMAND_LABELS = {
    Command.MUTE: "Mute",
    Command.SFX: "SFX",
    Command.SOUND_EFFECTS: "Sound",
    Command.PROFILE: "Profile",
    Command.GAME_EQ: "Game EQ",
    Command.MIC_EFFECTS: "Mic effects",
    Command.PAD: "Pad set",
    Command.MIDI_CC: "MIDI CC",
    Command.HOTKEY: "Hot key",
    Command.REVERB: "Reverb on/off",
    Command.BGM_CAST: "BGM CAST",
}


def slot_letter(slot: int) -> str:
    return "ABCD"[slot] if 0 <= slot < SOUND_EFFECT_SLOTS else str(slot)


@dataclass(frozen=True)
class Pad:
    number: int  # 1-6
    name: str
    func: int  # raw 14-bit function word
    opt1: int
    opt2: int

    @property
    def command(self) -> int:
        return self.func - FUNC_BASE

    @property
    def sound_slot(self) -> int | None:
        """The BridgeMix sound (0 = A) this pad plays, or None."""
        if self.command == Command.SOUND_EFFECTS and 0 <= self.opt1 < SOUND_EFFECT_SLOTS:
            return self.opt1
        return None

    def describe(self) -> str:
        """Short label for the pad's function, e.g. 'Device SFX A' or 'Pad set +'."""
        cmd = self.command
        label = _COMMAND_LABELS.get(cmd, f"Function {cmd}")  # type: ignore[call-overload]
        if cmd == Command.SFX:
            return f"{label} {('A', 'B', 'Beep')[self.opt1] if self.opt1 < 3 else self.opt1}"
        if cmd == Command.SOUND_EFFECTS:
            return f"{label} {slot_letter(self.opt1)}"
        if cmd in (Command.PROFILE, Command.PAD, Command.GAME_EQ, Command.MIC_EFFECTS):
            choice = {5: "+", 6: "-"}.get(self.opt1, str(self.opt1 + 1))
            return f"{label} {choice}"
        return label


def pad_location(number: int) -> tuple[int, int]:
    """(block type, address of the name) of pad *number* (1-6) in the current pads."""
    if not 1 <= number <= PAD_COUNT:
        raise ValueError(f"pad {number} out of range")
    index = number - 1
    return TYPE_PADS_FIRST + index // 2, 0x20 + (index % 2) * PAD_SIZE


def memory_type(pad_set: int, number: int) -> int:
    """Block type of pad *number* in the memory of *pad_set* (0-4)."""
    return (pad_set << 4) + (number - 1) // 2


def decode_name(data: bytes | tuple[int, ...] | list[int]) -> str:
    """Pad names are stored with each character pair swapped ('FS X' is 'SFX ')."""
    chars = []
    for i in range(0, min(len(data), NAME_LEN) - 1, 2):
        chars += [data[i + 1], data[i]]
    return "".join(chr(c) for c in chars if 32 <= c < 127).strip()


def decode_pad(number: int, data: bytes | tuple[int, ...] | list[int]) -> Pad | None:
    """Decode the PAD_SIZE bytes read from a pad's name address."""
    if len(data) < OFF_OPT2 + 2:
        return None

    def word(off: int) -> int:
        return (data[off] << 7) | data[off + 1]

    return Pad(number, decode_name(data), word(OFF_FUNC), word(OFF_OPT1), word(OFF_OPT2))


def sound_effects_func() -> int:
    return FUNC_BASE + Command.SOUND_EFFECTS
