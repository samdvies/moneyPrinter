# Adversarial fixture 2: CPU spin
# Tests wall-clock timeout and RLIMIT_CPU (Linux).
# Convention: every adversarial module defines run(snapshot, params) -> Any

def run(snapshot, params):
    while True:
        pass
