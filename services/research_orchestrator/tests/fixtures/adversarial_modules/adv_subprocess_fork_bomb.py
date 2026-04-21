# Adversarial fixture 1: subprocess fork-bomb
# Convention: every adversarial module defines run(snapshot, params) -> Any
# The sandbox must kill this via builtins __import__ strip (import subprocess
# is caught) and/or wall-clock timeout.

def run(snapshot, params):
    import subprocess  # noqa: F401 — intentionally forbidden
    while True:
        subprocess.Popen(["python", "-c", "while True: pass"])
