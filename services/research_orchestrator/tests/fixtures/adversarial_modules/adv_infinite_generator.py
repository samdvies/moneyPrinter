# Adversarial fixture 8: infinite generator consumed in a tight loop
# Tests wall-clock timeout; no resource-module dependency.
# Convention: every adversarial module defines run(snapshot, params) -> Any

def _infinite():
    n = 0
    while True:
        yield n
        n += 1


def run(snapshot, params):
    total = 0
    for value in _infinite():
        total += value
    return total
