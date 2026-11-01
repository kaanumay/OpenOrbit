"""OpenOrbit local server panel: double-click to start (no console window). The game, settings and saves are managed here.

The panel opens in a local window; the first launch runs a setup wizard (language, game folder, first pilot, game settings). PLAY
starts the servers and opens the game. Linux and macOS: python3 "OpenOrbit Panel.pyw" (the game runs under Wine or Proton). Details:
README.md, server/panel/panel.py.
"""
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PANEL = os.path.join(HERE, 'server', 'panel', 'panel.py')

if sys.version_info < (3, 10):
    v = sys.version.split()[0]
    msg = ('OpenOrbit Panel için Python 3.10 ya da daha yenisi gerekir.\nBu Python: %s\n\n'
           'OpenOrbit Panel needs Python 3.10 or newer.\nThis Python: %s' % (v, v))
    if os.name == 'nt':
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, 'OpenOrbit Panel', 0x10)
    else:                                       # Linux / macOS: started from a terminal (python3 "OpenOrbit Panel.pyw")
        print(msg, file=sys.stderr)
    sys.exit(1)
sys.argv = [PANEL] + sys.argv[1:]
runpy.run_path(PANEL, run_name='__main__')
