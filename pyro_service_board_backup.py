#!/usr/bin/env python3
"""This file starts a pyro nameserver and the proxying server."""
from pathlib import Path
import subprocess
import time
from qick.pyro import start_server

HERE = Path(__file__).parent

############
# parameters
############

bitfile = '../qick_lib/qick/qick_4x2.bit'
proxy_name ='rfsoc'
ns_port = 8000
# bind address for the nameserver process -- 0.0.0.0 so it's reachable from outside
ns_bind_host = '0.0.0.0'
# host start_server() itself uses to locate the nameserver -- always localhost,
# since start_server() runs on the same machine as the nameserver
ns_host = 'localhost'

############

# start the nameserver process
# NOTE: full path to pyro4-ns is required here -- this script may be launched
# via sudo/SSH without the pynq-venv's bin/ on $PATH, unlike an interactively
# activated Jupyter terminal.
ns_proc = subprocess.Popen(
    [f'PYRO_SERIALIZERS_ACCEPTED=pickle PYRO_PICKLE_PROTOCOL_VERSION=4 /usr/local/share/pynq-venv/bin/pyro4-ns -n {ns_bind_host} -p {ns_port}'],
    shell=True
)

# wait for the nameserver to start up
time.sleep(5)

# start the qick proxy server
start_server(
    bitfile=str(HERE / bitfile),
    proxy_name=proxy_name,
    ns_host=ns_host,
    ns_port=ns_port
)
