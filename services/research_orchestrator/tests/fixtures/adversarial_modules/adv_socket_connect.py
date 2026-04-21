# Adversarial fixture 4: network egress via socket.create_connection
# The sandbox monkey-patches socket.create_connection to raise before the
# user module is loaded, so this will be caught even on Windows.
# Convention: every adversarial module defines run(snapshot, params) -> Any

import socket

def run(snapshot, params):
    conn = socket.create_connection(("example.com", 80), timeout=5)
    conn.sendall(b"GET / HTTP/1.0\r\n\r\n")
    data = conn.recv(4096)
    conn.close()
    return data
