# Adversarial fixture 3: memory balloon
# Allocates a huge bytearray to test RLIMIT_AS (Linux) or wall-clock (Windows).
# Convention: every adversarial module defines run(snapshot, params) -> Any

def run(snapshot, params):
    # Attempt to allocate 4 GB — should be killed by RLIMIT_AS on Linux.
    # On Windows, relies on wall-clock timeout.
    data = bytearray(4 * 1024 * 1024 * 1024)
    return len(data)
