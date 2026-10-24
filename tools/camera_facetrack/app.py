"""Local camera GUI. Tk is main-thread only; capture and inference have workers."""
import argparse
import json
import ipaddress
import os
from collections import deque
from dataclasses import dataclass
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

import cv2
from PIL import Image, ImageTk

from face_engine import FaceEngine, annotate
from video_source import NetworkCapture
from serial_video import UsbCapture
from camera_setup import SetupDialog


@dataclass(frozen=True)
class Settings:
    camera: int | str
    width: int
    activation: float
    buffer: int


@dataclass
class ViewState:
    turns: int = 0


def rotate_frame(frame, turns):
    rotations = {1: cv2.ROTATE_90_CLOCKWISE, 2: cv2.ROTATE_180,
                 3: cv2.ROTATE_90_COUNTERCLOCKWISE}
    return cv2.rotate(frame, rotations[turns % 4]) if turns % 4 else frame


def saved_camera_source():
    # The current firmware runs exclusively over the USB data cable.
    return 'serial://COM15'


def put_latest(channel, value):
    try:
        channel.put_nowait(value)
    except queue.Full:
        try:
            channel.get_nowait()
        except queue.Empty:
            pass
        channel.put_nowait(value)


def camera_worker(settings, stop, output, events, view=None):
    capture = None
    reader = None
    frames = queue.Queue(maxsize=1)
    try:
        engine = FaceEngine(settings.activation, settings.buffer)
        network = isinstance(settings.camera, str)
        source_name = 'USB 直连摄像头' if network and settings.camera.startswith('serial://') else '网络摄像头'
        if network:
            # Open in the reader so initial network failures also retry.
            capture = None
        else:
            for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF):
                if stop.is_set():
                    return
                capture = cv2.VideoCapture(settings.camera, backend)
                if capture.isOpened():
                    break
                capture.release()
            if capture is None or not capture.isOpened():
                raise RuntimeError('无法打开摄像头。请检查编号、Windows 摄像头权限，以及是否被其他软件占用。')
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            capture.set(cv2.CAP_PROP_FPS, 30)
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        def read_frames():
            nonlocal capture
            try:
                reconnecting = False
                retry_delay = 2
                next_diagnostics = 0
                while not stop.is_set():
                    if capture is None:
                        try:
                            capture = (UsbCapture(settings.camera.removeprefix('serial://').upper(), stop)
                                       if settings.camera.startswith('serial://') else NetworkCapture(settings.camera, stop))
                        except Exception as exc:
                            events.put(('connecting', f'{source_name}暂不可用：{exc} · {retry_delay} 秒后重试'))
                            stop.wait(retry_delay)
                            # Avoid queuing many short-lived requests behind a
                            # blocked single-client camera HTTP handler.
                            retry_delay = min(10, retry_delay * 2)
                            continue
                    ok, frame = capture.read()
                    if network and time.monotonic() >= next_diagnostics:
                        events.put(('transport', capture.diagnostics()))
                        next_diagnostics = time.monotonic() + 1
                    if not ok:
                        if network and not stop.is_set():
                            capture.release()
                            capture = None
                            reconnecting = True
                            put_latest(frames, None)
                            events.put(('connecting', '视频流中断，正在自动重连…'))
                            stop.wait(2)
                            continue
                        if not stop.is_set():
                            events.put(('error', '摄像头读取失败或已断开，请重新连接后启动。'))
                        stop.set()
                        break
                    if reconnecting:
                        events.put(('ready', '视频流已恢复 · 本机检测与追踪'))
                        reconnecting = False
                    retry_delay = 2
                    put_latest(frames, (time.perf_counter(), frame))
            except Exception as exc:
                events.put(('error', f'采集失败：{exc}'))
                stop.set()
            finally:
                if capture is not None:
                    capture.release()

        reader = threading.Thread(target=read_frames, daemon=True)
        reader.start()
        events.put(('connecting', f'正在连接{source_name} · 等待首帧…') if network else ('ready', '正在运行 · 全程本地处理'))
        times = deque()
        fps_started = None
        first_frame = True
        last_rotation = 0
        while not stop.is_set():
            try:
                item = frames.get(timeout=0.2)
            except queue.Empty:
                continue
            if item is None:
                engine = FaceEngine(settings.activation, settings.buffer)
                times.clear()
                fps_started = None
                continue
            captured_at, frame = item
            rotation = view.turns if view is not None else 0
            if rotation != last_rotation:
                engine = FaceEngine(settings.activation, settings.buffer)
                last_rotation = rotation
            frame = rotate_frame(frame, rotation)
            if first_frame:
                events.put(('ready', f'正在运行 · {source_name} · 本机检测与追踪' if network else '正在运行 · 全程本地处理'))
                first_frame = False
            begin = time.perf_counter()
            image, tracked = engine.process(frame, settings.width)
            end = time.perf_counter()
            if fps_started is None:
                fps_started = end
            times.append(end)
            while times and times[0] < end - 3:
                times.popleft()
            window = min(3.0, end - fps_started)
            fps = max(0, len(times) - 1) / window if window > 0 else 0
            put_latest(output, (image, tracked, fps, (end - begin) * 1000,
                                (end - captured_at) * 1000, rotation))
    except Exception as exc:
        events.put(('error', str(exc)))
    finally:
        stop.set()
        if reader is not None:
            # The reader owns release; do not release concurrently with read().
            reader.join()
        elif capture is not None:
            capture.release()
        events.put(('done', '已停止 · 摄像头已释放'))


class App:
    def __init__(self, root, watch=False, autostart=False, source='0'):
        self.root = root
        self.worker = None
        self.stop_event = threading.Event()
        self.output = queue.Queue(maxsize=1)
        self.events = queue.Queue()
        self.last_error = None
        self.closing = False
        self.watch = watch
        self.restart_requested = False
        self.resume_after_reload = False
        self.source_files = [Path(__file__).resolve(), Path(__file__).with_name('face_engine.py'),
                             Path(__file__).with_name('video_source.py')]
        self.source_times = [p.stat().st_mtime_ns for p in self.source_files]
        self.next_watch = time.monotonic() + 1
        self.next_status = 0
        self.view = ViewState()
        self.pending_source = None
        self.transport_stats = {}
        self.setup_pending = False
        self.setup_dialog = None
        try:
            saved_view = json.loads((Path(__file__).parent / 'runtime' / 'view-settings.json').read_text(encoding='utf-8'))
            self.view.turns = int(saved_view.get('turns', 0)) % 4
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        self.source_files.append(Path(__file__).with_name('camera_setup.py'))
        self.source_files.append(Path(__file__).with_name('serial_video.py'))
        self.source_times = [p.stat().st_mtime_ns for p in self.source_files]
        root.title('FaceTrack · 实时人脸检测与追踪' + (' · 热更新' if watch else ''))
        root.geometry(f'{min(1280, root.winfo_screenwidth()-80)}x{min(820, root.winfo_screenheight()-100)}')
        root.minsize(1000, 660)
        root.configure(bg='#0b1220')
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TFrame', background='#0b1220')
        style.configure('Panel.TFrame', background='#111b2e')
        style.configure('TLabel', background='#0b1220', foreground='#dbe6f4', font=('Microsoft YaHei UI', 10))
        style.configure('Panel.TLabel', background='#111b2e', foreground='#dbe6f4')
        style.configure('Muted.TLabel', background='#111b2e', foreground='#8fa2bb', font=('Microsoft YaHei UI', 9))
        style.configure('Title.TLabel', font=('Segoe UI', 24, 'bold'), foreground='#f4f8ff')
        style.configure('Section.TLabel', background='#111b2e', foreground='#eef5ff', font=('Microsoft YaHei UI', 12, 'bold'))
        style.configure('TButton', font=('Microsoft YaHei UI', 10), padding=(10, 8), background='#21324c', foreground='#e3edfc', borderwidth=0)
        style.map('TButton', background=[('active', '#304565'), ('disabled', '#172239')], foreground=[('disabled', '#60748f')])
        style.configure('Primary.TButton', background='#36d3b4', foreground='#092a29', font=('Microsoft YaHei UI', 10, 'bold'))
        style.map('Primary.TButton', background=[('disabled', '#183c40'), ('active', '#6ae7cc')], foreground=[('disabled', '#67908e')])
        style.configure('TCheckbutton', background='#111b2e', foreground='#dbe6f4', font=('Microsoft YaHei UI', 10))
        style.map('TCheckbutton', background=[('active', '#111b2e')])
        style.configure('TEntry', fieldbackground='#1c2a40', foreground='#e6edf8', insertcolor='#ffffff', padding=7)
        style.configure('TCombobox', fieldbackground='#1c2a40', background='#233650', foreground='#e6edf8', padding=6)
        style.map('TCombobox', fieldbackground=[('readonly', '#1c2a40')], foreground=[('readonly', '#e6edf8'), ('disabled', '#71849d')])
        self.camera = tk.StringVar(value=source)
        self.width = tk.StringVar(value='640')
        self.activation = tk.StringVar(value='0.60')
        self.buffer = tk.StringVar(value='30')
        self.mirror = tk.BooleanVar(value=source.isdecimal())
        self.last_frame_at = 0
        self.status = tk.StringVar(value='准备就绪 · 点击「启动预览」')
        self.metrics = tk.StringVar(value='处理速率 — FPS  ·  推理 — ms  ·  读取后耗时不含传输')
        self.identities = tk.StringVar(value='当前 ID：—')
        self.display_fps = tk.StringVar(value='实时帧率：— FPS')
        self.display_times = deque()
        self.display_started = time.monotonic()
        self.display_rate = 0.0
        self.rotation_label = tk.StringVar(value=f'{self.view.turns * 90}°')
        self.track_count = tk.StringVar(value='0 人')
        page = ttk.Frame(root, padding=20)
        page.pack(fill='both', expand=True)
        page.columnconfigure(1, weight=1)
        page.rowconfigure(1, weight=1)
        heading = ttk.Frame(page)
        heading.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 18))
        ttk.Label(heading, text='FaceTrack', style='Title.TLabel').pack(side='left')
        ttk.Label(heading, text=' / 实时人脸追踪', foreground='#8fa2bb').pack(side='left', padx=(10, 0), pady=(10, 0))
        ttk.Label(heading, textvariable=self.display_fps,
                  font=('Segoe UI', 19, 'bold'), foreground='#70e0b4').pack(side='right')
        sidebar = ttk.Frame(page, padding=18, style='Panel.TFrame', width=290)
        sidebar.grid(row=1, column=0, sticky='ns', padx=(0, 16))
        ttk.Label(sidebar, text='摄像头连接', style='Section.TLabel').pack(anchor='w')
        ttk.Label(sidebar, text='USB 串口 / 本机摄像头编号', style='Muted.TLabel').pack(anchor='w', pady=(16, 6))
        self.source_widget = ttk.Combobox(sidebar, textvariable=self.camera, width=26,
            values=['serial://COM15', '0', '1', '2', '3'], state='normal')
        self.source_widget.pack(fill='x')
        buttons = ttk.Frame(sidebar, style='Panel.TFrame')
        buttons.pack(fill='x', pady=(14, 10))
        self.start_button = ttk.Button(buttons, text='启动预览', style='Primary.TButton', command=self.start)
        self.start_button.pack(side='left', fill='x', expand=True)
        self.stop_button = ttk.Button(buttons, text='停止', command=self.stop, state='disabled')
        self.stop_button.pack(side='left', padx=(8, 0))
        ttk.Label(sidebar, text='USB 直连视频 · 无需配网', style='Muted.TLabel').pack(anchor='w', pady=(7, 24))
        ttk.Separator(sidebar).pack(fill='x', pady=(0, 18))
        ttk.Label(sidebar, text='追踪概览', style='Section.TLabel').pack(anchor='w')
        ttk.Label(sidebar, textvariable=self.track_count, style='Panel.TLabel', font=('Microsoft YaHei UI', 28, 'bold'), foreground='#70e0b4').pack(anchor='w', pady=(8, 0))
        ttk.Label(sidebar, textvariable=self.identities, style='Muted.TLabel', wraplength=245).pack(anchor='w', pady=(3, 20))
        controls = ttk.Frame(sidebar, style='Panel.TFrame')
        self.config_widgets = [self.source_widget]
        for row, (label, variable, choices) in enumerate((
            ('推理宽度', self.width, ['320', '480', '640']),
            ('激活阈值', self.activation, ['0.40', '0.50', '0.60', '0.70']),
            ('丢失缓冲/帧', self.buffer, ['15', '30', '60']))):
            ttk.Label(controls, text=label, style='Panel.TLabel').grid(row=row, column=0, sticky='w', padx=(0, 15), pady=5)
            widget = ttk.Combobox(controls, textvariable=variable, values=choices,
                                  width=5, state='readonly')
            widget.grid(row=row, column=1, sticky='e')
            self.config_widgets.append(widget)
        def toggle_advanced():
            if controls.winfo_manager():
                controls.pack_forget()
                advanced.configure(text='检测设置  ▾')
            else:
                controls.pack(fill='x', pady=(10, 0), after=advanced)
                advanced.configure(text='收起设置  ▴')
        advanced = ttk.Button(sidebar, text='检测设置  ▾', command=toggle_advanced)
        advanced.pack(fill='x')
        ttk.Label(sidebar, text='本机处理 · 不保存人脸特征\nID 仅用于本次连续追踪', style='Muted.TLabel', wraplength=245).pack(side='bottom', anchor='w', pady=(14, 0))
        viewer = ttk.Frame(page, padding=14, style='Panel.TFrame')
        viewer.grid(row=1, column=1, sticky='nsew')
        viewer.columnconfigure(0, weight=1)
        viewer.rowconfigure(1, weight=1)
        toolbar = ttk.Frame(viewer, style='Panel.TFrame')
        toolbar.grid(row=0, column=0, sticky='ew', pady=(0, 12))
        ttk.Label(toolbar, text='实时预览', style='Section.TLabel').pack(side='left')
        ttk.Checkbutton(toolbar, text='镜像', variable=self.mirror, command=self.refresh_preview).pack(side='right', padx=(10, 0))
        ttk.Button(toolbar, text='重置', command=lambda: self.turn_view(reset=True)).pack(side='right', padx=(6, 0))
        ttk.Button(toolbar, text='右转 ↻', command=lambda: self.turn_view(1)).pack(side='right', padx=(6, 0))
        ttk.Button(toolbar, text='↶ 左转', command=lambda: self.turn_view(-1)).pack(side='right', padx=(6, 0))
        ttk.Label(toolbar, textvariable=self.rotation_label, style='Muted.TLabel').pack(side='right', padx=(10, 5))
        self.last_preview_frame = None
        self.preview = tk.Label(viewer, text='等待摄像头画面\n\n连接摄像头后，点击「启动预览」',
                                bg='#070d18', fg='#8fa2bb', font=('Microsoft YaHei UI', 14))
        self.preview.grid(row=1, column=0, sticky='nsew')
        self.preview.bind('<Configure>', lambda event: self.refresh_preview())
        ttk.Label(viewer, textvariable=self.metrics, style='Muted.TLabel', wraplength=720).grid(row=2, column=0, sticky='w', pady=(12, 0))
        footer = ttk.Frame(page)
        footer.grid(row=2, column=0, columnspan=2, sticky='ew', pady=(12, 0))
        self.state_dot = ttk.Label(footer, text='●', foreground='#8fa2bb')
        self.state_dot.pack(side='left', padx=(0, 8))
        ttk.Label(footer, textvariable=self.status, wraplength=920).pack(side='left')
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(10, self.poll)
        if autostart:
            root.after(300, self.start)

    def refresh_preview(self):
        if self.last_preview_frame is None:
            return
        frame, tracked, rotation = self.last_preview_frame
        frame = annotate(frame, tracked, self.mirror.get())
        frame = rotate_frame(frame, self.view.turns - rotation)
        image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        image.thumbnail((max(1, self.preview.winfo_width()), max(1, self.preview.winfo_height())))
        photo = ImageTk.PhotoImage(image)
        self.preview.configure(image=photo, text='')
        self.preview.image = photo

    def turn_view(self, step=0, reset=False):
        self.view.turns = 0 if reset else (self.view.turns + step) % 4
        self.rotation_label.set(f'{self.view.turns * 90}°')
        self.refresh_preview()
        try:
            path = Path(__file__).parent / 'runtime' / 'view-settings.json'
            path.parent.mkdir(exist_ok=True)
            path.write_text(json.dumps({'turns': self.view.turns}), encoding='utf-8')
        except OSError:
            pass

    def open_setup(self):
        if self.setup_dialog is not None and not self.setup_dialog.closed:
            self.setup_dialog.window.lift()
            return
        if self.camera.get().startswith('serial://') and self.worker is not None and self.worker.is_alive():
            self.setup_pending = True
            self.stop()
            self.status.set('正在释放 USB 视频串口，随后打开配网…')
            return
        self.setup_dialog = SetupDialog(self.root, self.use_camera_ip)

    def use_camera_ip(self, ip):
        source = f'http://{ip}:81/stream.h264'
        try:
            path = Path(__file__).parent / 'runtime' / 'camera-network.json'
            path.parent.mkdir(exist_ok=True)
            path.write_text(json.dumps({'ip': ip, 'stream_url': source,
                                       'updated_at': time.time()}), encoding='utf-8')
        except OSError:
            pass
        if source == self.camera.get() and self.worker is not None and self.worker.is_alive() and not self.stop_event.is_set():
            self.status.set(f'摄像头已连接：{ip}')
            return
        self.pending_source = source
        self.stop_event.set()
        self.status.set(f'摄像头已联网：{ip} · 正在连接预览…')

    def start(self):
        if self.worker is not None and self.worker.is_alive():
            return
        self.last_error = None
        self.transport_stats = {}
        self.output = queue.Queue(maxsize=1)
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        source = self.camera.get().strip()
        if not source.isdecimal() and not source.startswith(('http://', 'https://', 'serial://')):
            messagebox.showerror('视频输入', '请输入本机编号或 serial://COM15。')
            return
        self.last_frame_at = 0
        self.display_times.clear()
        self.display_started = time.monotonic()
        settings = Settings(int(source) if source.isdecimal() else source, int(self.width.get()),
                            float(self.activation.get()), int(self.buffer.get()))
        self.worker = threading.Thread(target=camera_worker,
                                       args=(settings, self.stop_event, self.output, self.events, self.view), daemon=True)
        self.start_button.configure(state='disabled')
        self.stop_button.configure(state='normal')
        for widget in self.config_widgets:
            widget.configure(state='disabled')
        self.status.set('正在加载模型并连接摄像头…')
        self.worker.start()

    def stop(self):
        self.stop_event.set()
        self.stop_button.configure(state='disabled')
        self.status.set('正在停止并释放摄像头…')

    def poll(self):
        if self.watch and not self.closing and time.monotonic() >= self.next_watch:
            self.next_watch = time.monotonic() + 1
            try:
                changed = [p.stat().st_mtime_ns for p in self.source_files] != self.source_times
            except OSError:
                changed = False
            if changed:
                self.restart_requested = True
                self.resume_after_reload = self.worker is not None and self.worker.is_alive() and not self.stop_event.is_set()
                self.close()
                self.status.set('源码已更新，正在释放摄像头并重新加载…')
        if self.closing and (self.worker is None or not self.worker.is_alive()):
            self.restart_settings = [self.camera.get(), self.width.get(), self.activation.get(),
                                     self.buffer.get(), 'yes' if self.mirror.get() else 'no']
            self.root.destroy()
            return
        while True:
            try:
                kind, text = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'transport':
                self.transport_stats = text
            elif kind == 'error':
                self.last_error = text
                self.status.set('错误：' + text)
                if not self.closing:
                    messagebox.showerror('摄像头运行错误', text)
            elif kind == 'done':
                self.status.set('错误：' + self.last_error if self.last_error else text)
                self.start_button.configure(state='normal')
                self.stop_button.configure(state='disabled')
                for widget in self.config_widgets:
                    widget.configure(state='normal' if widget is self.source_widget else 'readonly')
                self.preview.configure(image='', text='摄像头已停止')
                self.preview.image = None
                self.last_preview_frame = None
                self.metrics.set('处理速率 — FPS  ·  推理 — ms  ·  读取后耗时不含传输')
                self.identities.set('当前 ID：—')
                self.track_count.set('0 人')
            else:
                self.status.set(text)
                if kind == 'connecting':
                    if self.last_preview_frame is None:
                        self.preview.configure(image='', text=text)
                        self.preview.image = None
                        self.last_frame_at = 0
                    else:
                        self.preview.configure(text='正在重连 · 当前显示上一帧', compound='center', fg='#ffd485')
                    self.metrics.set('等待视频帧…')
                    self.identities.set('当前 ID：—')
                    self.track_count.set('— 人')
        if self.pending_source and (self.worker is None or not self.worker.is_alive()):
            self.camera.set(self.pending_source)
            self.pending_source = None
            self.start()
        if self.setup_pending and not self.closing and (self.worker is None or not self.worker.is_alive()):
            self.setup_pending = False
            self.open_setup()
        try:
            frame, tracked, fps, elapsed, age, rotation = self.output.get_nowait()
            if not self.stop_event.is_set():
                if self.last_frame_at and time.monotonic() - self.last_frame_at > 3:
                    self.status.set('视频已恢复 · 本机检测与追踪')
                self.last_frame_at = time.monotonic()
                self.last_preview_frame = (frame, tracked, rotation)
                ids = [int(i) for i in tracked.tracker_id]
                # One local diagnostic frame only when explicitly requested.
                request = Path(__file__).resolve().parent / 'runtime' / 'snapshot.request'
                if request.exists():
                    if cv2.imwrite(str(request.with_name('preview-check.png')), annotate(frame, tracked, self.mirror.get())):
                        request.unlink(missing_ok=True)
                self.refresh_preview()
                self.display_times.append(time.monotonic())
                height, width = frame.shape[:2]
                self.metrics.set(f'画面 {width}×{height}  ·  处理 FPS {fps:.1f}  ·  推理 {elapsed:.0f} ms  ·  读取后耗时 {age:.0f} ms（不含传输）')
                self.identities.set('当前 ID：' + (', '.join(f'Face {i}' for i in ids) or '—'))
                self.track_count.set(f'{len(ids)} 人')
        except queue.Empty:
            pass
        now = time.monotonic()
        while self.display_times and self.display_times[0] <= now - 3:
            self.display_times.popleft()
        active = self.worker is not None and self.worker.is_alive() and not self.stop_event.is_set()
        window = min(3.0, now - self.display_started)
        self.display_rate = len(self.display_times) / window if active and window > 0 else 0.0
        self.display_fps.set(f'实时帧率：{self.display_rate:.1f} FPS' if active else '实时帧率：— FPS')
        healthy = active and self.last_frame_at and now - self.last_frame_at < 3
        self.state_dot.configure(foreground='#ff7a8e' if self.last_error else
                                 '#70e0b4' if healthy else '#eebc68' if active else '#8fa2bb')
        if self.last_frame_at and time.monotonic() - self.last_frame_at > 3 and not self.stop_event.is_set():
            self.status.set('视频帧停滞超过 3 秒 · 正在等待数据，断流后自动重连')
            self.identities.set('画面已停滞 · 当前 ID 暂不更新')
            self.preview.configure(text='画面已停滞 · 当前显示上一帧', compound='center', fg='#ffd485')
        self.root.after(10, self.poll)
        if time.monotonic() >= self.next_status:
            self.next_status = time.monotonic() + 1
            # Diagnostic metadata only: never persist frames or face features.
            directory = Path(__file__).resolve().parent / 'runtime'
            try:
                directory.mkdir(exist_ok=True)
                temporary = directory / f'status-{os.getpid()}.tmp'
                temporary.write_text(json.dumps({'pid': os.getpid(), 'watch': self.watch,
                    'running': self.worker is not None and self.worker.is_alive() and not self.stop_event.is_set(),
                    'status': self.status.get(), 'metrics': self.metrics.get(),
                    'source': self.camera.get(),
                    'transport_stats': self.transport_stats,
                    'display_fps': round(self.display_rate, 2),
                    'rotation_degrees': self.view.turns * 90,
                    'seconds_since_frame': round(time.monotonic() - self.last_frame_at, 2) if self.last_frame_at else None,
                    'updated_at': time.time()}, ensure_ascii=False, indent=2), encoding='utf-8')
                temporary.replace(directory / 'status.json')
            except OSError:
                pass

    def close(self):
        self.closing = True
        if self.setup_dialog is not None and not self.setup_dialog.closed:
            self.setup_dialog.close()
        self.stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--smoke-test', action='store_true', help='加载 GUI 后自动关闭，不打开摄像头')
    parser.add_argument('--watch', action='store_true', help='源码保存后自动重启')
    parser.add_argument('--autostart', action='store_true', help='启动后自动打开摄像头')
    parser.add_argument('--source', default='0', help='serial://串口、摄像头编号、HTTP 地址或 auto（默认 USB 串口）')
    parser.add_argument('--width', default='640', choices=['320', '480', '640'])
    parser.add_argument('--activation', default='0.60')
    parser.add_argument('--buffer', default='30')
    parser.add_argument('--mirror', choices=['yes', 'no'])
    args = parser.parse_args()
    if args.source == 'auto':
        args.source = saved_camera_source()
    root = tk.Tk()
    app = App(root, watch=args.watch, autostart=args.autostart, source=args.source)
    app.width.set(args.width)
    app.activation.set(args.activation)
    app.buffer.set(args.buffer)
    if args.mirror:
        app.mirror.set(args.mirror == 'yes')
    if args.smoke_test:
        root.after(1200, root.destroy)
    root.mainloop()
    if app.restart_requested:
        command = [sys.executable, str(Path(__file__).resolve()), '--watch']
        source, width, activation, buffer, mirror = app.restart_settings
        command += ['--source', source, '--width', width, '--activation', activation,
                    '--buffer', buffer, '--mirror', mirror]
        if app.resume_after_reload:
            command.append('--autostart')
        subprocess.Popen(command, cwd=Path(__file__).resolve().parent,
                         creationflags=subprocess.CREATE_NO_WINDOW)
