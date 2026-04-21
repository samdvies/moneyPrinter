# Adversarial fixture 6: dynamic import via __import__
# The sandbox strips '__import__' from __builtins__ before loading the user
# module, and import of 'os' would also be blocked by the builtins strip.
# Convention: every adversarial module defines run(snapshot, params) -> Any

def run(snapshot, params):
    # Attempt to import 'os' dynamically to run a shell command.
    # __builtins__['__import__'] is stripped in the sandbox child.
    os_mod = __import__("os")
    return os_mod.system("echo pwned")
