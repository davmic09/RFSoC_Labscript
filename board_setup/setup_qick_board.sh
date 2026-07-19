#!/bin/bash
# Sets up and launches the QICK Pyro4 server on a PYNQ-based RFSoC board
# (RFSoC4x2, ZCU216, ZCU111, ...), so a labscript QICKBoard device on a
# separate control PC can reach it over the network.
#
# Run this ON THE BOARD ITSELF (e.g. via SSH, or a JupyterLab terminal), as
# root or a sudo-capable user. Usage:
#
#   sudo ./setup_qick_board.sh /path/to/qick/checkout/on/this/board
#
# The qick checkout path must contain a qick_lib/ directory and be pip
# installable (a setup.py at its root) -- e.g. a clone of
# github.com/openquantumhardware/qick or a fork of it.
#
# Environment variables (all optional):
#   QICK_NS_PORT      Pyro4 nameserver port (default 8000)
#   QICK_PROXY_NAME    registered proxy name (default rfsoc)
#   PYNQ_VENV          path to the PYNQ venv (default /usr/local/share/pynq-venv)
#
# ---------------------------------------------------------------------------
# Known gotchas this script exists to avoid (discovered the hard way getting
# an RFSoC4x2 working -- see repo memory/notes for the full debugging story):
#
#   1. The board's own nameserver must bind to 0.0.0.0, not localhost, or it's
#      unreachable from an external control PC.
#   2. `pyro4-ns` is a PYNQ-venv console script -- it's not on $PATH under a
#      plain `sudo`/non-interactive SSH shell (only an interactively-activated
#      venv shell has it). Must be invoked by full path.
#   3. The BOARD environment variable (e.g. RFSoC4x2, ZCU216) and the XRT
#      environment are normally set up by /etc/profile.d/*.sh for login
#      shells -- NOT sourced automatically by a non-interactive SSH command.
#      Without BOARD set, QickSoc import fails silently and later crashes
#      with a confusing NameError. Without XRT sourced, PYNQ can't find the
#      FPGA device at all.
#   4. The installed `qick` Python package MUST match the bitstream being
#      loaded -- an unrelated/older qick install can silently produce
#      DefaultIP driver-binding failures instead of a clear version error.
#   5. A stale nameserver process from a previous failed attempt can keep
#      squatting on the port across restarts (spawned detached via
#      subprocess.Popen) -- check `ss -tlnp` for who's actually bound, not
#      just `ps aux`, which can show stale/misleading entries.
# ---------------------------------------------------------------------------
set -euo pipefail

QICK_REPO_PATH="${1:?Usage: $0 /path/to/qick/checkout}"
PYNQ_VENV="${PYNQ_VENV:-/usr/local/share/pynq-venv}"
NS_PORT="${QICK_NS_PORT:-8000}"
PROXY_NAME="${QICK_PROXY_NAME:-rfsoc}"

if [ "$EUID" -ne 0 ]; then
    echo "This script must be run as root (sudo) -- the QICK overlay/device access needs it." >&2
    exit 1
fi

if [ ! -d "$QICK_REPO_PATH/qick_lib" ]; then
    echo "ERROR: $QICK_REPO_PATH does not look like a qick checkout (no qick_lib/ subdirectory)." >&2
    exit 1
fi

# --- 1. Source the same environment an interactive login/Jupyter shell would get ---
# (BOARD identity + XRT device environment). Paths below match a standard PYNQ
# image; adjust if your board's image differs.
for f in /etc/profile.d/boardname.sh /etc/profile.d/xrt_setup.sh /etc/profile.d/pynq_venv.sh; do
    if [ -f "$f" ]; then
        # shellcheck disable=SC1090
        source "$f"
    else
        echo "WARNING: expected profile script not found: $f (continuing anyway)" >&2
    fi
done

if [ -z "${BOARD:-}" ]; then
    echo "ERROR: BOARD environment variable is still unset after sourcing profile.d scripts." >&2
    echo "Set it manually, e.g.: export BOARD=ZCU216" >&2
    exit 1
fi
echo "BOARD=$BOARD"

# --- 2. Install the qick package matching the bitstream you want to run ---
# This REPLACES whatever qick package is currently importable in this venv --
# if another workflow (e.g. an existing interactive Jupyter setup) depends on
# a different installed qick version, this will affect it. Comment out this
# block if you've already confirmed the right qick package is installed.
echo "Installing $QICK_REPO_PATH as the active qick package (editable)..."
"$PYNQ_VENV/bin/python3" -m pip install -e "$QICK_REPO_PATH"

# --- 3. Clear any stale nameserver holding our target port ---
STALE_PID="$(ss -tlnp 2>/dev/null | grep ":$NS_PORT " | grep -oP 'pid=\K[0-9]+' || true)"
if [ -n "$STALE_PID" ]; then
    echo "Killing stale process on port $NS_PORT (pid $STALE_PID)..."
    kill -9 "$STALE_PID" || true
    sleep 1
fi

# --- 4. Launch the server, detached, surviving this shell's exit ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$SCRIPT_DIR/pyro_service.log"
echo "Launching pyro_service.py (BOARD=$BOARD, port=$NS_PORT, proxy_name=$PROXY_NAME)..."
QICK_NS_PORT="$NS_PORT" QICK_PROXY_NAME="$PROXY_NAME" \
    nohup "$PYNQ_VENV/bin/python3" "$SCRIPT_DIR/pyro_service.py" > "$LOG_FILE" 2>&1 &
disown

sleep 10
echo "--- last lines of $LOG_FILE ---"
tail -n 20 "$LOG_FILE" || true
echo "--- listening on port $NS_PORT? ---"
ss -tlnp 2>/dev/null | grep ":$NS_PORT " || echo "(nothing listening yet -- check the log above)"

echo ""
echo "If the port is listening, verify from the control PC with:"
echo "  Pyro4.config.SERIALIZER='pickle'; Pyro4.config.PICKLE_PROTOCOL_VERSION=4"
echo "  Pyro4.locateNS(host='<this board's IP>', port=$NS_PORT)"
