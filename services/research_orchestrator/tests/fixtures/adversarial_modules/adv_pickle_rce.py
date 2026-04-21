# Adversarial fixture 9: pickle RCE via malicious __reduce__
# The run() function returns an instance of MaliciousResult whose __reduce__
# would execute os.system("echo pwned") when unpickled.
#
# The sandbox parent MUST NOT blindly unpickle the child's result.  In
# sandbox_runner.py the parent wraps queue.get() in a try/except and catches
# any exception raised during unpickling — the malicious __reduce__ fires only
# at unpickle time, so if the parent never calls pickle.loads on untrusted
# bytes the RCE is contained.
#
# This fixture proves the boundary: the child can put an evil object on the
# queue, but the parent's defensive get() catches the PicklingError / any
# exception and returns SandboxResult(status="error", ...) instead of executing
# the payload.
#
# Convention: every adversarial module defines run(snapshot, params) -> Any

import os  # noqa: F401


class MaliciousResult:
    """When unpickled, attempts to run a shell command."""

    def __reduce__(self):
        # os.system("echo pwned") would run in the process that unpickles this.
        return (os.system, ("echo pwned",))


def run(snapshot, params):
    return MaliciousResult()
