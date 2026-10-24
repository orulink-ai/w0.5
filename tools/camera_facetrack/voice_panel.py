"""Tk controls and worker handoff. Workers communicate through a private queue."""
import json
import queue
import os
import re
import threading
import time
import tkinter as tk
import uuid
from tkinter import ttk

from voice_session import VoiceSession


class VoicePanel:
    def __init__(self, parent, request_turn, change_mode=None):
        self.events = queue.Queue()
        self.worker = None
        self.stop_event = threading.Event()
        self.pending = None
        self.in_turn = False
        self.requires_face = False
        self.cancel_reason = None
        self.finished = False
        self.failed = False
        self.phase = 'idle'
        self.turn_id = None
        self.started_at = None
        self.updated_at = time.time() * 1000
        self.input_seconds = None
        self.error = None
        self.answer_text = ''
        self.user_text = ''
        self.latency = None
        self.reply_complete = False
        self.mode = 'continuous'
        self.mode_label = tk.StringVar(value='在场连续对话')
        self.enabled = tk.BooleanVar(value=False)
        self.face_trigger = tk.BooleanVar(value=True)
        self.endpoint = tk.StringVar(value=os.environ.get('VI_LOCAL_S2S_URL', 'http://127.0.0.1:8790'))
        self.status = tk.StringVar(value='语音已关闭 · 人脸稳定 1 秒开启连续会话')
        self.reply = tk.StringVar(value='AI 回复将显示在这里')
        self.frame = ttk.Frame(parent, style='Panel.TFrame')
        ttk.Separator(self.frame).pack(fill='x', pady=(4, 12))
        title = ttk.Frame(self.frame, style='Panel.TFrame')
        title.pack(fill='x')
        ttk.Label(title, text='语音交流', style='Section.TLabel').pack(side='left')
        ttk.Label(title, text='音量 80 · 持续预览', style='Badge.TLabel').pack(side='right')
        top = ttk.Frame(self.frame, style='Panel.TFrame')
        top.pack(fill='x', pady=(10, 8))
        ttk.Checkbutton(top, text='开启语音', variable=self.enabled,
                        command=self.toggle).pack(side='left')
        ttk.Label(top, text='人脸稳定后聆听', style='Muted.TLabel').pack(side='left', padx=12)
        ttk.Label(top, text='本机模型 · 共享 USB 连接',
                  style='Muted.TLabel').pack(side='right')
        mode_row = ttk.Frame(self.frame, style='Panel.TFrame')
        mode_row.pack(fill='x', pady=(0, 8))
        ttk.Label(mode_row, text='对话模式', style='Muted.TLabel').pack(side='left')
        mode_select = ttk.Combobox(mode_row, textvariable=self.mode_label,
                                  values=('单轮触发', '在场连续对话'), state='readonly', width=18)
        mode_select.pack(side='left', padx=8)
        mode_select.bind('<<ComboboxSelected>>', lambda _: (change_mode or self.set_mode)(
            'single' if self.mode_label.get() == '单轮触发' else 'continuous'))
        row = ttk.Frame(self.frame, style='Panel.TFrame')
        row.pack(fill='x', pady=(0, 5))
        ttk.Label(row, text='模型服务', style='Muted.TLabel').pack(side='left')
        self.endpoint_entry = ttk.Entry(row, textvariable=self.endpoint)
        self.endpoint_entry.pack(side='left', fill='x', expand=True, padx=8)
        self.once_button = ttk.Button(row, text='等待人脸聆听', style='Primary.TButton', command=lambda: request_turn(False))
        self.once_button.pack(side='left')
        self.cancel_button = ttk.Button(row, text='取消语音', command=self.cancel, state='disabled')
        self.cancel_button.pack(side='left', padx=(6, 0))
        ttk.Label(self.frame, textvariable=self.status, style='Panel.TLabel',
                  wraplength=700).pack(anchor='w', pady=(5, 7))
        self.reply_box = tk.Text(self.frame, height=3, wrap='word', state='disabled',
                                 bg='#f3f8f7', fg='#2a4c47', relief='flat',
                                 selectbackground='#cce8e0', selectforeground='#183b33',
                                 font=('Microsoft YaHei UI', 10), padx=12, pady=10)
        self.reply_box.pack(fill='x', pady=(0, 5))
        self.reply.trace_add('write', self.refresh_reply)
        self.refresh_reply()

    def refresh_reply(self, *_):
        self.reply_box.configure(state='normal')
        self.reply_box.delete('1.0', 'end')
        self.reply_box.insert('1.0', self.reply.get())
        self.reply_box.configure(state='disabled')

    @property
    def busy(self):
        return self.in_turn

    def set_mode(self, mode):
        if mode not in ('single', 'continuous'):
            raise ValueError('未知对话模式')
        if self.mode == mode:
            return False
        self.mode = mode
        self.mode_label.set('单轮触发' if mode == 'single' else '在场连续对话')
        self.cancel(reason='对话模式已切换')
        if not self.busy:
            self.phase = 'waiting_face' if self.enabled.get() else 'idle'
            self.status.set('对话模式已切换 · 等待人脸稳定后开始' if self.enabled.get() else '语音已关闭')
        return True

    def toggle(self):
        if not self.enabled.get():
            self.cancel()
            if not self.busy:
                self.status.set('语音已关闭 · 摄像头继续预览')
                self.phase = 'idle'
        elif not self.busy:
            self.status.set('等待人脸稳定 1 秒后开始聆听')
            self.phase = 'waiting_face'
        self.updated_at = time.time() * 1000

    def request(self, port, broker, prompt=None):
        if self.busy:
            return False
        if prompt is None:
            self.enabled.set(True)
        self.in_turn = True
        self.requires_face = prompt is None
        self.finished = False
        self.failed = False
        self.pending = (port, self.endpoint.get().strip(), broker, prompt, self.mode == 'single')
        self.turn_id = uuid.uuid4().hex
        self.started_at = self.updated_at = time.time() * 1000
        self.input_seconds = None
        self.error = None
        self.cancel_reason = None
        self.answer_text = ''
        self.user_text = ''
        self.latency = None
        self.reply_complete = False
        self.phase = 'starting'
        self.stop_event = threading.Event()
        self.status.set('正在连接 vi-agent · 摄像头持续预览')
        self.reply.set('等待本轮 AI 回复')
        self.once_button.configure(state='disabled')
        self.cancel_button.configure(state='normal')
        self.endpoint_entry.configure(state='disabled')
        return True

    def cancel(self, reason='收到停止指令'):
        self.stop_event.set()
        if self.pending is not None:
            self.pending = None
            self.events.put(('done', 'cancelled'))
        if self.in_turn:
            self.cancel_reason = reason
            self.status.set('正在取消语音 · 摄像头继续预览…')
            self.phase = 'cancelling'
            self.updated_at = time.time() * 1000

    def poll(self, camera_alive):
        """Called by Tk; the camera remains the sole UART owner during speech."""
        if self.in_turn and not camera_alive and not self.stop_event.is_set():
            self.stop_event.set()
            self.events.put(('error', '开发板摄像头连接中断，语音已取消；正在等待设备重连。'))
        if self.pending is not None and not self.stop_event.is_set():
            port, endpoint, broker, prompt, once = self.pending
            self.pending = None
            events, stop = self.events, self.stop_event

            def work():
                try:
                    VoiceSession(port, endpoint, lambda kind, text: events.put((kind, text)), stop,
                                 broker=broker, prompt=prompt, once=once).run()
                except Exception as exc:
                    events.put(('error', str(exc)))
                finally:
                    events.put(('done', ''))

            self.worker = threading.Thread(target=work, daemon=True)
            self.worker.start()
        elif self.pending is not None:
            self.pending = None
            self.events.put(('done', 'cancelled'))
        completed = None
        while True:
            try:
                kind, text = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'user-text':
                self.user_text = str(text)[:2000]
            elif kind == 'latency':
                try:
                    value = json.loads(text)
                    if isinstance(value, dict):
                        self.latency = value
                except (ValueError, TypeError):
                    pass
            elif kind == 'text':
                self.answer_text = str(text)[:2000]
                self.reply.set(str(text)[:2000])
            elif kind == 'turn-start':
                self.input_seconds = None
                self.phase = 'listening'
            elif kind == 'turn-done':
                self.reply_complete = True
                self.phase = 'done'
            elif kind == 'error':
                self.failed = True
                # Process cleanup may report a generic disconnect after the
                # firmware's precise failure; keep the original cause visible.
                if self.error is None:
                    self.error = str(text)
                self.phase = 'error'
                self.status.set('语音错误：' + self.error)
            elif kind == 'state':
                self.status.set(str(text))
                for prefix, phase in (('正在启动', 'starting'), ('正在聆听', 'listening'),
                                      ('录音完成', 'recorded'), ('正在思考', 'thinking'),
                                      ('正在播放', 'speaking')):
                    if str(text).startswith(prefix):
                        self.phase = phase
                        break
                duration = re.fullmatch(r'录音完成 (\d+(?:\.\d+)?) 秒', str(text))
                if duration:
                    if self.reply_complete:
                        self.turn_id = uuid.uuid4().hex
                        self.started_at = time.time() * 1000
                        self.answer_text = ''
                        self.user_text = ''
                        self.latency = None
                        self.reply_complete = False
                    self.input_seconds = float(duration[1])
            elif kind == 'done':
                self.finished = True
            self.updated_at = time.time() * 1000
        if self.finished and (self.worker is None or not self.worker.is_alive()):
            self.in_turn = False
            self.finished = False
            self.worker = None
            self.once_button.configure(state='normal')
            self.cancel_button.configure(state='disabled')
            self.endpoint_entry.configure(state='normal')
            completed = True
            if not self.failed:
                if self.stop_event.is_set():
                    self.phase = 'cancelled'
                    self.status.set('已取消：' + (self.cancel_reason or '收到停止指令') + ' · 摄像头继续预览')
                else:
                    self.phase = 'done'
                    self.status.set('本轮完成 · 摄像头继续预览 · 等待人脸开启下一轮')
            self.updated_at = time.time() * 1000
        return completed
