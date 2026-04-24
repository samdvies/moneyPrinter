# Adversarial fixture 3: memory balloon — touches pages so RLIMIT_AS can bite.
# Convention: every adversarial module defines run(snapshot, params) -> Any

_PAGE = 4096
_CHUNK = 8 * 1024 * 1024  # 8 MiB


def run(snapshot, params):
    """Allocate and touch >128 MiB RSS; child has mem_mb=128 in the test."""
    for _ in range(24):  # 192 MiB touched
        b = bytearray(_CHUNK)
        for i in range(0, _CHUNK, _PAGE):
            b[i] = 1
