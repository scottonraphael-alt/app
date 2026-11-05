"""Router modules are loaded on demand, including by the isolated music worker."""
from importlib import import_module

__all__ = ["admin", "auth", "members", "profiles", "resources", "tickets"]


def __getattr__(name):
    if name in __all__:
        module = import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
