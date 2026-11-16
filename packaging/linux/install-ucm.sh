#!/usr/bin/env bash
# Install or remove the ALSA UCM profiles for the Roland BRIDGE CAST X.
#
# - X with firmware 1.0x (USB 0582:02e8): alsa-ucm-conf has no profile, so
#   PipeWire shows one 8-channel output ("Analog Surround 7.1") and one 6-channel
#   input. The profile gives outputs Chat, Game, Music, System and inputs
#   Stream, Personal, Mic.
# - X V2, recent firmware (0582:0320 on USB I, 0582:0321 on USB II):
#   alsa-ucm-conf 1.2.16.1 declares 16 playback channels (the X has 14), so every
#   device name shows "[ALSA UCM error]", and it doesn't know USB I at all. This
#   installs a copy of the upstream fix (commit 7ea2531c). Outputs Chat, Game,
#   Music, System; inputs Stream Mix, Mic, Sub Mix.
# Voice chat apps (Discord, ...) should use the "Mic" input and the "Chat" output.
#
# Needs alsa-ucm-conf 1.2.16 or later, the first release that reads USB-Audio/conf.d.
#
# usage: install-ucm.sh [--uninstall] [--no-restart]
#   --uninstall   remove the profiles
#   --no-restart  copy or remove the files only; don't restart WirePlumber
#   UCM_DIR       ucm2 directory (default: /usr/share/alsa/ucm2)
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
src="$here/ucm2/USB-Audio/conf.d"
ucm_dir="${UCM_DIR:-/usr/share/alsa/ucm2}"
dest="$ucm_dir/USB-Audio/conf.d"
files=(
	0582-02e8.conf Roland-BridgeCastX.conf Roland-BridgeCastX-Hifi.conf
	0582-0320.conf 0582-0321.conf Roland-BridgeCastXV2.conf Roland-BridgeCastXV2-Hifi.conf
)

uninstall=0
restart=1
for arg in "$@"; do
	case "$arg" in
	--uninstall) uninstall=1 ;;
	--no-restart) restart=0 ;;
	-h | --help)
		awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"
		exit 0
		;;
	*)
		echo "Unknown option: $arg (see --help)" >&2
		exit 2
		;;
	esac
done

if [ ! -f "$ucm_dir/USB-Audio/USB-Audio.conf" ]; then
	echo "No ALSA UCM configuration in $ucm_dir. Install alsa-ucm-conf, or set UCM_DIR." >&2
	exit 1
fi

# The system directory belongs to root: use sudo only when it is not writable.
need_sudo=0
if [ ! -w "$ucm_dir/USB-Audio" ]; then
	if ! command -v sudo >/dev/null; then
		echo "$ucm_dir/USB-Audio is not writable and sudo is not installed. Run this as root." >&2
		exit 1
	fi
	need_sudo=1
fi
as_root() {
	if [ "$need_sudo" -eq 1 ]; then sudo "$@"; else "$@"; fi
}

x_connected() {
	local d
	for d in /sys/bus/usb/devices/*; do
		if [ "$(cat "$d/idVendor" 2>/dev/null)" = 0582 ]; then
			case "$(cat "$d/idProduct" 2>/dev/null)" in
			02e8 | 0320 | 0321) return 0 ;;
			esac
		fi
	done
	return 1
}

if [ "$uninstall" -eq 1 ]; then
	for f in "${files[@]}"; do
		as_root rm -f "$dest/$f"
	done
	as_root rmdir "$dest" 2>/dev/null || true # only if nothing else is in it
	echo "Removed the BRIDGE CAST X profiles from $dest."
else
	if ! grep -q 'USB-Audio/conf.d/' "$ucm_dir/USB-Audio/USB-Audio.conf"; then
		echo "This alsa-ucm-conf does not read USB-Audio/conf.d (it needs 1.2.16 or later)." >&2
		echo "Update alsa-ucm-conf first; nothing was installed." >&2
		exit 1
	fi
	as_root install -d -m 755 "$dest"
	for f in "${files[@]}"; do
		as_root install -m 644 "$src/$f" "$dest/$f"
	done
	echo "Installed the BRIDGE CAST X profiles in $dest."
	if ! x_connected; then
		echo "No BRIDGE CAST X seems connected; the profile applies once it is."
	fi
fi

if [ "$restart" -eq 0 ]; then
	exit 0
fi
if [ "$(id -u)" -eq 0 ] || ! systemctl --user is-active --quiet wireplumber 2>/dev/null; then
	echo "Restart your sound server (or log out and back in) to apply the change."
	exit 0
fi

systemctl --user restart wireplumber
echo "Restarted WirePlumber."
if [ "$uninstall" -eq 0 ] && command -v pactl >/dev/null; then
	sleep 3 # let WirePlumber probe the card again
	pactl list short cards | awk '/BRIDGE_CAST_X/ {print $2}' | while read -r card; do
		pactl set-card-profile "$card" HiFi 2>/dev/null || true
	done
	echo "BRIDGE CAST X devices:"
	pactl list short sinks | awk '/BRIDGE_CAST_X/ {print "  output " $2}'
	pactl list short sources | awk '/BRIDGE_CAST_X/ && !/\.monitor/ {print "  input  " $2}'
fi
