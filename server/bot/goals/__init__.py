"""Hedef modülleri: her dosya bir ya da birkaç @beyin.hedef sınıfı tanımlar. Yeni davranış için buraya bir modül eklemek yeter."""
import importlib, os, pkgutil


def load():
    # kayıt sırası = eşit puanlı hedeflerde seçim sırası: dosya adlarından bağımsız sabit (yeni modüller ardından alfabetik)
    from . import shopping, resting, duel, quest, group, gate_run, grinding, exploration, mode_run, pvp, selling, assist  # noqa: F401
    for m in pkgutil.iter_modules([os.path.dirname(os.path.abspath(__file__))]):
        importlib.import_module(__name__ + '.' + m.name)
