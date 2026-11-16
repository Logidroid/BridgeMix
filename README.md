<div align="center">

<img src="assets/icon.svg" width="88" alt="BridgeMix logo"/>

# BridgeMix

**A sleek, unofficial cross-platform controller for the Roland BRIDGE CAST audio mixer.**

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
![Linux](https://img.shields.io/badge/Linux-1793D1?logo=linux&logoColor=white)
![Windows](https://img.shields.io/badge/Windows-0078D6?logo=windows&logoColor=white)
![macOS](https://img.shields.io/badge/macOS-000000?logo=apple&logoColor=white)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)
![GUI: PyQt6](https://img.shields.io/badge/GUI-PyQt6-41CD52?logo=qt&logoColor=white)

<img src="doc/screenshots/screenshot_mixer.png" width="860" alt="BridgeMix mixer view"/>

</div>

---

## About this fork

This is a fork of [Ex0danify/BridgeMix](https://github.com/Ex0danify/BridgeMix) focused on
the **Roland BRIDGE CAST X**. It is tested on Linux with one BRIDGE CAST X, first on firmware
1.02 (build 67), then on firmware 3.00. The rest of this README comes from the original
project; its links point to this fork.

> **A firmware update story.** Roland updates the X's firmware only from its Windows and
> macOS app. The [firmware download page](https://www.roland.com/global/support/by_product/bridge_cast_x/updates_drivers/ee518cda-d94c-447b-b2ff-bfb6c6192d93/)
> has nothing to download: it tells you to install the app. The app's changelog for version
> 4.01 says: *"Fixed an issue that prevented connection to BRIDGE CAST X Ver. 1.02."* This X
> stayed on 1.02 for a while, because Windows 11 and the app never agreed on an update. When
> the update to 3.00 finally went through (on the USB II port, as Roland requires), the X came
> back with a new name, a new USB ID and every fader at 100. Linux recognised it straight
> away, with no driver. This fork supports both firmwares.

Changes from the original project:

| Area | Change |
|---|---|
| **BRIDGE CAST X knobs** | The four knobs are freely assignable, as in Roland's app. BridgeMix now writes the X's own knob registers (`7F 03 08 60`–`66`) instead of the base model's, so changing a knob source takes effect on the device. INPUTS shows the X layout (MIC, CHAT, HDMI, GAME) and offers HDMI as a source on every knob. |
| **BRIDGE CAST X meters** | Some X inputs report a single level instead of left and right: CHAT, GAME and MUSIC on firmware 1.02, only GAME on 3.00. BridgeMix shows that level on both bars, and real left and right as soon as the device sends them. |
| **App Audio Routing** | The channel list follows the device's audio outputs while the panel is open. Rules are saved by channel (Chat, Music…), so they keep working when the device appears under another name (other USB port, firmware update), and a rule whose channel is missing no longer logs an error every 1.5 s. |
| **Sound pads (PADS tab)** | The six BRIDGE CAST X control pads drawn as on the device. Give any pad a sound that BridgeMix keeps, in as many sound banks as you like, and change each pad's light colour. Two pads (or the arrows in the tab) go to the previous and next bank. Banks 1–5 are the device's pad sets 1–5, saved in the device; banks 6 and up use the functions of a pad set you pick and keep their own colours in BridgeMix. A sound or bank pad sends its own MIDI CC (channel 16); BridgeMix plays the pad's sound of the current bank on a Bridge Cast channel (System by default) and links it into the microphone input of voice chat apps (Discord by default), so the people you talk to hear it. The pad's previous function is kept and can be given back. Linux only (PipeWire). |
| **Linux audio profiles for the X** | ALSA UCM profiles and their install script: one for the X on firmware 1.0x, and a copy of a not-yet-released alsa-ucm-conf fix for the X V2 (see below). |
| **Updates** | The in-app update check and the self-updater follow this fork's releases. |

### Download

Get the packages from this fork's [Releases](https://github.com/Logidroid/BridgeMix/releases/latest):
a Flatpak for Linux, a Windows installer and portable zip, and a macOS `.dmg`. They use the
same app id as the original BridgeMix, so installing one replaces an installed original
BridgeMix and keeps its settings.

### BRIDGE CAST X on Linux: separate channels

What the X needs depends on its firmware. `lsusb | grep Roland` shows its USB ID:

| X firmware | USB ID | Without the script |
|---|---|---|
| 1.0x | `0582:02e8` | alsa-ucm-conf has no profile. PipeWire shows one "Analog Surround 7.1" output and one 6-channel input, so App Audio Routing has nothing to route to and voice chat apps record the STREAM mix. |
| Recent (3.00 tested), shown as "X V2" | `0582:0321` on USB II, `0582:0320` on USB I | alsa-ucm-conf 1.2.16.1 handles USB II but declares 16 playback channels (the X has 14), so every device name shows "[ALSA UCM error]". It doesn't know USB I. Both are fixed upstream ([commit 7ea2531c](https://github.com/alsa-project/alsa-ucm-conf/commit/7ea2531c)), but no release includes the fix yet. |

The script needs **alsa-ucm-conf 1.2.16 or later**. From a clone of this repository (or the
source archive of a release):

```bash
packaging/linux/install-ucm.sh              # asks for your password (sudo)
packaging/linux/install-ucm.sh --uninstall  # to remove it
```

It copies the profiles to `/usr/share/alsa/ucm2/USB-Audio/conf.d/` and restarts WirePlumber.
The X then appears as:

| X firmware | Outputs (playback) | Inputs (recording) |
|---|---|---|
| 1.0x | Chat, Game, Music, System | Stream, Personal, Mic |
| Recent | Chat, Game, Music, System | Stream Mix, Mic, Sub Mix |

In Discord or any other voice chat app, choose the **Mic** input and the **Chat** output.
The Flatpak can't install these profiles itself; run the script once on the host. The USB I
port of the X V2 (`0582:0320`) hasn't been tested here.

---
> **Notice on AI:** Parts of this project were developed with AI assistance. 
> The code has been reviewed and curated by the maintainer, but you may encounter rough edges. Bug reports are welcome.


## About

Roland's official companion app is closed-source and **Windows/macOS only — there's
no Linux build at all**. **BridgeMix** is an open-source, cross-platform alternative:
full control of the Bridge Cast — mixes, mic FX, voice changer, game FX, output
routing, profiles and live metering — by speaking the device's MIDI SysEx protocol.
It's pure Python/PyQt6, so the same app runs on **Linux, Windows and macOS** with no
custom driver: the Bridge Cast is USB-Audio-class compliant.

It's **Linux-first** — that's where it's built and tested, and the one platform Roland
leaves unserved — but everything runs just as well on Windows and macOS for anyone who
wants a free, scriptable alternative to the stock app.

## Features

| Area | Highlights |
|---|---|
| **Mixer** | Stream + Personal buses · all 7 channels (volume + mute) · Mix Mode · Mix Link · live level meters |
| **Outputs** | Sub-Mix volume · output mutes (Stream / Sub-Mix / Phones / Line) · Output Delay · Line / USB / Sub-Mix modes |
| **Profiles** | 5 slots — select, rename, save |
| **Mic input** | Source (XLR / headset) · +48 V phantom · gain |
| **Mic FX** | Low Cut · Noise Suppressor (Gate / Adaptive / Expander) · De-esser · Compressor (Legacy + Modern LA-2A) · 10-band EQ **with live spectrum analyzer** |
| **Voice FX** | Pitch · Formant · Avatar / Sing · Reverb · 5 preset slots |
| **Game FX** | 10-band EQ · Limiter · Virtual Surround · 5 preset slots |
| **Chat FX** | De-esser · Compressor |
| **Hardware** | Strip channel assignment · strip button actions · LED ring colours · HOT KEY button 1 |
| **System** | LED brightness · phones gain · indicator type · mute display · SFX A/B volume |
| **Tools** | Device auto-detect · JSON preset save / load · live MIDI monitor |
| **Remote API** | Optional local REST API (read/set any parameter) · Swagger UI · for Stream Deck, OBS, scripts |

### Not implemented yet

| Feature | Why |
|---|---|
| Game EQ spectrum analyzer | The host-side SUB MIX capture is unresolved on Linux — the **Mic EQ** analyzer ships and works |
| HOT KEY buttons 2–4 · SFX A/B trigger · Beep | SysEx addresses not yet mapped |
| Voice Transformer extras (Robot, Megaphone, consonant mode) | Stored in preset banks; live addresses unknown |
| Some fine Mic-FX params (NS Adaptive attack/release, a few LA-2A controls) | Addresses not yet captured |
| Per-strip LED on/off · per-preset LED colours | Write path unknown |
| BGM · HDMI controls (Bridge Cast X)  | Out of current scope |
| Firmware update | Intentionally **not** supported (too risky) |

## Screenshots

<details>
<summary><b>Show the rest of the app</b></summary>

<br/>

| Mic FX | Voice FX |
|:---:|:---:|
| <img src="doc/screenshots/screenshot_mic_fx.png" width="410"/> | <img src="doc/screenshots/screenshot_voice_fx.png" width="410"/> |
| **Game FX** | **Chat FX** |
| <img src="doc/screenshots/screenshot_game_fx.png" width="410"/> | <img src="doc/screenshots/screenshot_chat_fx.png" width="410"/> |
| **Mic Setup** | **Output** |
| <img src="doc/screenshots/screenshot_mic_setup.png" width="410"/> | <img src="doc/screenshots/screenshot_output.png" width="410"/> |
| **System** | **MIDI Monitor** |
| <img src="doc/screenshots/screenshot_system.png" width="410"/> | <img src="doc/screenshots/screenshot_midi_monitor.png" width="410"/> |

</details>

## Install & Run
The original project was developed on an original Roland BRIDGE CAST. This fork is tested on
a BRIDGE CAST X. The BRIDGE CAST ONE is not tested.

**Requirements:**

- A **Roland BRIDGE CAST** (original, V2) on **FW 3.00 (115)**, or a **BRIDGE CAST X** on
  **FW 1.02 (67)** or **FW 3.00**, the firmwares this fork is tested on
- On Linux with a BRIDGE CAST X: the audio profiles described in
  [BRIDGE CAST X on Linux](#bridge-cast-x-on-linux-separate-channels)
- **Python 3.11+**, or conda

```bash
git clone https://github.com/Logidroid/BridgeMix.git
cd BridgeMix
./setup.sh       # Linux / macOS
setup.bat        # Windows
```

> **macOS** uses the same `./setup.sh` — it sets up the environment and launches the
> app fine, but doesn't add a Dock/Launchpad entry (that integration is Linux- and
> Windows-only for now). It's the least-tested of the three platforms; reports welcome.

Run from a terminal, `setup.sh` (Linux) and `setup.bat` (Windows) show a friendly menu:

| Option | What it does |
|---|---|
| **Install & Launch** | Sets things up, adds BridgeMix to your apps/Start menu, and starts it |
| **Launch** | Starts BridgeMix without adding a menu entry |
| **Uninstall** | Removes the apps/Start-menu entry |

Prefer flags? `--install` · `--launch` · `--uninstall` (works on both `./setup.sh` and `setup.bat`).

It sets itself up automatically — a `bridgemix` conda env if you have conda, otherwise
a self-contained Python venv (`.venv`). The first run downloads dependencies (about a
minute); after that it's instant. Force a backend with `BRIDGEMIX_BACKEND=conda|venv`.

> **New to Linux?** If your file manager asks what to do with `setup.sh`, choose
> **“Run in Terminal”** to see the menu. Once installed, just launch BridgeMix from your
> applications menu like any other app.

### Flatpak (Linux)

Each release has a `BridgeMix-<version>-linux-x86_64.flatpak` bundle, which runs without Python or any setup:

```bash
flatpak install --user BridgeMix-<version>-linux-x86_64.flatpak
flatpak run io.github.ex0danify.BridgeMix
```

It needs the KDE runtime from [Flathub](https://flathub.org/setup). In the sandbox the in-app updater and the plugin
dependency installer are off; install a newer bundle to update.

### Windows and macOS builds

Releases also have a Windows installer (`…-windows-x64-setup.exe`, plus a portable zip) and a macOS `.dmg` for Apple Silicon.
Neither is code-signed, so Windows SmartScreen and macOS Gatekeeper warn on first launch: choose *Run anyway* on Windows, and
right-click the app and choose *Open* on macOS.

## Using it

1. Connect the Bridge Cast over USB.
2. Open BridgeMix — it auto-detects the correct MIDI ports and connects to the device.
3. Tweak away; everything applies to the device live.

## Plugins

The **Extras** tab is a plugin host: drop a plugin folder into the plugins
directory (shown in the panel), hit **Rescan**, and it adds its own card. Want to
write one? See [`doc/PLUGINS.md`](doc/PLUGINS.md). The Remote API below is itself a
built-in plugin and doubles as a complete worked example.

### Remote API (REST)

An **optional** local HTTP API lets third-party tools — Stream Deck, OBS, or your
own scripts — read and set any device parameter. It is **off by default** and
**bound to `127.0.0.1`** (loopback only; never exposed to the network).

**Enable it** in the **Extras** tab → *Remote API (REST)*: tick **Enable REST API**
and pick a port (default `8765`). The dependencies (`fastapi`, `uvicorn`) aren't
part of the base install — the plugin declares them, so if they're missing the
panel shows an **Install dependencies** button that fetches them into the running
environment.

Once running, open the **interactive Swagger docs** at `http://127.0.0.1:8765/docs`
(ReDoc at `/redoc`, raw schema at `/openapi.json`).

> **Security.** The API is loopback-only and **unauthenticated** — anything that
> can reach `127.0.0.1` can drive your mixer. To stop a web page in your browser
> from quietly poking the local API, a built-in guard rejects requests with an
> unexpected `Host` header (DNS-rebinding) or a cross-site `Origin` (CSRF). Local
> tools that send neither (curl, Stream Deck) and the Swagger page itself are
> unaffected. Treat the port as trusted-local only; don't bind it to a public
> interface!

| Method & path | Does |
|---|---|
| `GET /api/v1/status` | Connection status (connected, model, firmware) |
| `GET /api/v1/parameters` | List every parameter with its range and current value |
| `GET /api/v1/parameters/{name}` | Read one parameter |
| `PUT /api/v1/parameters/{name}` | Set one parameter (`{"value": …}`) |
| `GET /api/v1/state` | Flat `name → value` map of all cached values |

```bash
# Discover parameters
curl http://127.0.0.1:8765/api/v1/parameters

# Mute the stream mic channel (parameter names come from the list above)
curl -X PUT http://127.0.0.1:8765/api/v1/parameters/st_mic_mute \
     -H 'Content-Type: application/json' -d '{"value": 1}'
```

## Disclaimer

**BridgeMix is an independent, unofficial project.** It is **not affiliated with,
authorized, maintained, sponsored, or endorsed by Roland Corporation**, or any of
its subsidiaries or affiliates. "Roland" and "BRIDGE CAST" are trademarks of
Roland Corporation, used here solely to identify the hardware this software
interoperates with. The control protocol was determined through independent
observation.

The software is provided **"as is", without warranty of any kind**, express or
implied (see the [LICENSE](LICENSE) for the full terms). Behaviour described here
may not work on every platform, operating system, or device/firmware
configuration. Interacting with your audio hardware is **at your own risk.**


## License

BridgeMix is licensed under the **GNU General Public License v3.0 or later**
(GPL-3.0-or-later). See [LICENSE](LICENSE).
