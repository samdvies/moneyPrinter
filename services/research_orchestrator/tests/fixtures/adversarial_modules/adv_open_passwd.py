# Adversarial fixture 5: filesystem read via open()
# The sandbox strips 'open' from __builtins__ before loading the user module.
# Convention: every adversarial module defines run(snapshot, params) -> Any

def run(snapshot, params):
    # Attempt to read a sensitive file.  __builtins__['open'] is stripped in
    # the sandbox child before this code is executed.
    content = open("/etc/passwd").read()
    return content[:100]
