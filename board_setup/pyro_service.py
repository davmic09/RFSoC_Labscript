#!/usr/bin/env python3
"""Generic Pyro4 nameserver + QICK proxy server launcher.

Board-agnostic version of qick's pyro4/pyro_service.py: works for RFSoC4x2,
ZCU216, ZCU111, etc. without editing the bitfile path per board, since
QickSoc(bitfile=None) auto-selects the right bitfile from the BOARD
environment variable (see qick/__init__.py's bitfile_path()).

Must be run as root (binds low-numbered-adjacent system resources / needs
access to /dev/mem, /dev/uio*) on the board itself, with BOARD and the XRT
environment already sourced -- see setup_qick_board.sh in this directory,
which handles all of that and calls this script correctly. Running this file
directly without that environment set up first will fail in confusing ways
(see the "Known gotchas" list in setup_qick_board.sh's header comment).

Configure via environment variables (all optional, defaults shown):
    QICK_NS_PORT=8000       Pyro4 nameserver port
    QICK_PROXY_NAME=rfsoc   registered name of the QickSoc proxy
    QICK_PYRO4_NS_BIN=/usr/local/share/pynq-venv/bin/pyro4-ns
                            full path to the pyro4-ns CLI script (bare
                            `pyro4-ns` is often not on $PATH under sudo/SSH)
"""
import os
import subprocess
import time

from qick.pyro import start_server

NS_PORT = int(os.environ.get("QICK_NS_PORT", "8000"))
PROXY_NAME = os.environ.get("QICK_PROXY_NAME", "rfsoc")
PYRO4_NS_BIN = os.environ.get("QICK_PYRO4_NS_BIN", "/usr/local/share/pynq-venv/bin/pyro4-ns")

# Bind address for the nameserver process itself -- 0.0.0.0 so it's reachable
# from outside the board. Do NOT use this for the ns_host passed to
# start_server() below (see the "localhost" note there).
NS_BIND_HOST = "0.0.0.0"

ns_proc = subprocess.Popen(
    [
        f"PYRO_SERIALIZERS_ACCEPTED=pickle PYRO_PICKLE_PROTOCOL_VERSION=4 "
        f"{PYRO4_NS_BIN} -n {NS_BIND_HOST} -p {NS_PORT}"
    ],
    shell=True,
)

# Give the nameserver a moment to come up.
time.sleep(5)

# start_server()'s own ns_host is how IT finds the nameserver -- always
# 'localhost' since it runs on the same machine as the nameserver we just
# spawned. This is intentionally NOT the same value as NS_BIND_HOST above
# (0.0.0.0 is a bind address, not a valid address to connect to).
start_server(
    ns_host="localhost",
    ns_port=NS_PORT,
    proxy_name=PROXY_NAME,
    # bitfile intentionally omitted -- QickSoc auto-selects qick_<board>.bit
    # via the BOARD environment variable (must be set before this runs).
)
