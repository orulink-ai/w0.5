"""Run one board conversation through the adjacent vi-agent checkout.

This adapter owns no audio transport or model implementation. vi-agent owns
the microphone, endpoint detection, native model client, and speaker playout.
"""
from collections import deque
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit


class VoiceSession:
    def __init__(self, port, endpoint, on_event, stop_event, broker=None, prompt=None, once=False, mouth_provider=None,
                 activation=None, prelisten=False, input_gain_db=0):
        self.port = port
        self.endpoint = endpoint
        self.on_event = on_event
        self.stop_event = stop_event
        self.broker = broker
        self.prompt = prompt
        self.once = once
        self.mouth_provider = mouth_provider
        self.activation = activation
        self.prelisten = prelisten
        self.input_gain_db = input_gain_db

    def run(self):
        url = urlsplit(self.endpoint)
        if (url.scheme != 'http' or url.hostname not in ('127.0.0.1', 'localhost', '::1')
                or url.username or url.password or url.query or url.fragment):
            raise ValueError('语音模型地址必须为本机 HTTP 服务，例如 http://127.0.0.1:8790')
        if self.stop_event.is_set():
            return
        root = Path(os.environ.get('WTCC_VI_AGENT_ROOT',
                    str(Path(__file__).resolve().parents[3] / 'vi-agent'))).resolve()
        pipeline = os.environ.get('VI_VOICE_PROVIDER', 'local-s2s')
        entry_name = 'board-cascade-main.ts' if pipeline == 'local-cascade' else 'board-omni-main.ts'
        entry = root / 'packages/vi-agent/src/voice' / entry_name
        node = shutil.which('node')
        if not node or not entry.is_file():
            raise RuntimeError('找不到 Node.js 或 vi-agent。请安装 Node.js 并设置 WTCC_VI_AGENT_ROOT。')
        env = os.environ.copy()
        env.update(VI_LOCAL_S2S_URL=self.endpoint, VI_BOARD_SPEAKER_PORT=self.port,
                   VI_BOARD_SPEAKER_PYTHON=sys.executable)
        if self.broker is None:
            raise RuntimeError('请先连接开发板摄像头，共享音频通道尚未就绪。')
        env.update(VI_BOARD_BROKER_URL=self.broker[0], VI_BOARD_BROKER_TOKEN=self.broker[1])
        env.update(VI_BOARD_PRELISTEN=str(self.prelisten).lower(), VI_BOARD_INPUT_GAIN_DB=str(self.input_gain_db))
        command = [node, '--env-file-if-exists=.env', '--import', 'tsx', str(entry),
                   '--json-events']
        if self.once or self.prompt is not None:
            command.append('--once')
        if self.prompt is not None:
            command.extend(['--text', self.prompt])
        if self.activation is not None:
            command.append('--wait-for-face')
        process = subprocess.Popen(command, cwd=root, env=env, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding='utf-8', errors='replace', bufsize=1,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        lines = queue.Queue(maxsize=128)
        reader_stop = threading.Event()

        def read_output():
            try:
                for line in process.stdout:
                    while not reader_stop.is_set():
                        try:
                            lines.put(line, timeout=.1)
                            break
                        except queue.Full:
                            continue
            finally:
                while not reader_stop.is_set():
                    try:
                        lines.put(None, timeout=.1)
                        break
                    except queue.Full:
                        continue

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        diagnostic = deque(maxlen=6)
        done = False
        error = None
        deadline = time.monotonic() + 180
        next_mouth = 0
        activated = False
        try:
            self.on_event('state', '正在启动 vi-agent · 检查本地语音模型…')
            while True:
                if self.stop_event.is_set():
                    break
                if self.activation is not None and self.activation[0].is_set() and not activated:
                    process.stdin.write(json.dumps({'type': 'activate', 'since': self.activation[1]['since']}) + '\n')
                    process.stdin.flush()
                    activated = True
                    deadline = time.monotonic() + 45
                if pipeline == 'local-cascade' and self.mouth_provider is not None and time.monotonic() >= next_mouth:
                    next_mouth = time.monotonic() + .1
                    observation = self.mouth_provider()
                    fields = ('enabled', 'available', 'moving', 'observedAt', 'lastMotionAt', 'targetId')
                    payload = {'type': 'mouth', **{name: observation.get(name) for name in fields}}
                    try:
                        process.stdin.write(json.dumps(payload, allow_nan=False) + '\n')
                        process.stdin.flush()
                    except (OSError, ValueError):
                        # Drain pending child diagnostics even if it has already closed stdin.
                        next_mouth = float('inf')
                if time.monotonic() >= deadline:
                    raise TimeoutError('本轮语音超时，请检查麦克风或本地模型日志。')
                try:
                    line = lines.get(timeout=.1)
                except queue.Empty:
                    continue
                if line is None:
                    break
                try:
                    event = json.loads(line)
                except (ValueError, TypeError):
                    diagnostic.append(line.strip()[:300])
                    continue
                if not isinstance(event, dict):
                    continue
                kind, text = event.get('type'), event.get('text')
                if kind in ('state', 'text', 'error', 'user-text', 'latency', 'input', 'prepared') and isinstance(text, str):
                    self.on_event(kind, text)
                    if kind == 'prepared' and not activated:
                        deadline = float('inf')
                    if kind == 'error':
                        error = error or text
                elif kind == 'turn-start':
                    deadline = time.monotonic() + 45
                    self.on_event('turn-start', '')
                elif kind == 'done':
                    done = True
                    deadline = time.monotonic() + 45
                    self.on_event('turn-done', text if isinstance(text, str) else '')
                if kind == 'state' and isinstance(text, str) and text.startswith('正在思考'):
                    deadline = time.monotonic() + 150
                elif kind == 'state' and isinstance(text, str) and text.startswith('正在聆听'):
                    # Live microphone heartbeats may legitimately continue
                    # while the person is quiet during the same conversation.
                    deadline = time.monotonic() + 45
            code = process.wait(timeout=12) if not self.stop_event.is_set() else None
            if not self.stop_event.is_set() and (code != 0 or not done or error):
                raise RuntimeError(error or 'vi-agent 语音未完成：' + ' | '.join(diagnostic))
        finally:
            reader_stop.set()
            if process.poll() is None:
                try:
                    process.stdin.write('stop\n')
                    process.stdin.flush()
                    process.wait(timeout=12)
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    # Kill only the owned process tree if graceful serial cleanup hangs.
                    if os.name == 'nt':
                        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                       capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                    else:
                        process.kill()
                    process.wait(timeout=5)
            for stream in (process.stdin, process.stdout):
                if stream:
                    stream.close()
            reader.join(timeout=1)
