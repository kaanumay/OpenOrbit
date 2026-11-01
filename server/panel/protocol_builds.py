"""Protocol adaptation to a new client from the panel (roadmap "Ongoing work" > Preparing for the client update): the tool
tools/il2cpp/protocol_update.py runs in a separate process (python -I); the panel shows the progress lines, the diff summary and the path of the report.
"Apply" makes the protocol in the version folder active (the active files are backed up); when the game server is restarted it
runs with the new protocol. Only one job at a time."""
import json, os, re, subprocess, threading, time

from lang import t as _


class Adapter:
    def __init__(self, root, python, log=print, no_window=0):
        self.root, self.python, self.log, self.no_window = root, python, log, no_window
        self.tool = os.path.join(root, 'tools', 'il2cpp', 'protocol_update.py')
        self.lock = threading.Lock()
        self.d = {'running': False, 'lines': [], 'summary': None, 'error': None, 'start': None, 'end_time': None, 'is': None}

    def state(self):
        with self.lock:
            return json.loads(json.dumps(self.d))

    def _start(self, kind, args):
        with self.lock:
            if self.d['running']:
                raise RuntimeError(_('The protocol tool is already running.'))
            self.d = {'running': True, 'lines': [], 'summary': None, 'error': None, 'start': time.time(), 'end_time': None,
                      'is': kind}
        threading.Thread(target=self._run, args=(args,), daemon=True).start()
        return self.state()

    def generate(self, folder):
        if not folder or not os.path.isdir(folder):
            raise RuntimeError(_('No client folder.'))
        return self._start('produce', [folder])

    def activate(self, version):
        if not version or not re.match(r'^[0-9A-Za-z._-]+$', version):
            raise RuntimeError(_('Invalid version.'))
        return self._start('apply', ['--activate=' + version])

    def _run(self, args):
        try:
            p = subprocess.Popen([self.python, '-I', '-X', 'utf8', self.tool] + args, cwd=self.root, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, encoding='utf8', errors='replace',
                                 creationflags=self.no_window)
            for line in p.stdout:
                line = line.rstrip()
                with self.lock:
                    self.d['lines'] = (self.d['lines'] + [line])[-80:]
                m = re.search(r'diff: (\{.*\})', line)
                if m:
                    with self.lock:
                        self.d['summary'] = dict(self.d['summary'] or {}, **json.loads(m.group(1)))
                m = re.search(r'report: (.+)$', line)
                if m:
                    with self.lock:
                        self.d['summary'] = dict(self.d['summary'] or {}, report=m.group(1).strip())
                m = re.search(r'^client (\S+) ->', line)
                if m:
                    with self.lock:
                        self.d['summary'] = dict(self.d['summary'] or {}, version=m.group(1))
            code = p.wait()
            if code:
                with self.lock:
                    self.d['error'] = _('The tool failed (exit %d); see the last lines.', code)
        except Exception as e:
            with self.lock:
                self.d['error'] = repr(e)
        finally:
            with self.lock:
                self.d['running'], self.d['end_time'] = False, time.time()
            self.log('protocol tool finished: %s' % (self.d['error'] or 'done'))
