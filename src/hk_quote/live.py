"""Local, best-effort live transport; durable history stays in SQLite."""
import json
import socket
import threading
from collections import deque
from pathlib import Path


class Publisher:
    def __init__(self, path='data/live.sock'):
        self.path=str(Path(path).resolve())
        self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM)
        self.sock.setblocking(False)

    def send(self, event):
        try:
            self.sock.sendto(json.dumps(event).encode(),self.path)
        except OSError:
            pass  # The dashboard can be offline; database recording is unaffected.


class Hub:
    def __init__(self, path='data/live.sock'):
        self.path=Path(path).resolve()
        self.condition=threading.Condition()
        self.messages=deque(maxlen=2048)
        self.sequence=0
        if self.path.exists(): self.path.unlink()
        self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM)
        self.sock.bind(str(self.path));self.path.chmod(0o600)
        threading.Thread(target=self.receive,daemon=True).start()

    def receive(self):
        while True:
            try:
                event=json.loads(self.sock.recv(65536))
            except (ValueError,OSError):
                continue
            with self.condition:
                self.sequence+=1
                self.messages.append((self.sequence,event))
                self.condition.notify_all()

    def wait(self, after):
        with self.condition:
            if self.sequence<=after:self.condition.wait(10)
            return [(seq,event) for seq,event in self.messages if seq>after]
