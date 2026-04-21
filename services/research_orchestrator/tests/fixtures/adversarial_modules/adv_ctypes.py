# Adversarial fixture 10: ctypes foreign-function interface
# Attempts to load the C runtime via ctypes.CDLL(None).
# The AST validator would catch 'import ctypes'; the sandbox belt-and-braces
# strips '__import__' from __builtins__, so the dynamic import also fails.
# Convention: every adversarial module defines run(snapshot, params) -> Any

def run(snapshot, params):
    # __builtins__['__import__'] is stripped in the sandbox child, so this
    # dynamic import will raise NameError / TypeError before ctypes loads.
    ctypes = __import__("ctypes")
    libc = ctypes.CDLL(None)
    return libc.getpid()
