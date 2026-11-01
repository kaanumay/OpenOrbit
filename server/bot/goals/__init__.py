"""Goal modules: each file defines one or more @brain.goal classes. To add a new behavior it is enough to add a module here."""
import importlib, os, pkgutil


def load():
    # registration order = tie-break order among goals with equal scores: fixed, independent of file names (new modules follow alphabetically)
    from . import shopping, resting, duel, quest, group, gate_run, grinding, exploration, mode_run, pvp, selling, assist  # noqa: F401
    for m in pkgutil.iter_modules([os.path.dirname(os.path.abspath(__file__))]):
        importlib.import_module(__name__ + '.' + m.name)
