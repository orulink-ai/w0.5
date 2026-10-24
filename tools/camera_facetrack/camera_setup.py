"""USB Wi-Fi provisioning for the deployed camera; never stores credentials."""
import base64
import ipaddress
import queue
import re
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk

import serial
from serial_video import SERIAL_BAUD
from serial.tools import list_ports


def config_command(ssid, password):
    name, secret = ssid.encode('utf-8'), password.encode('utf-8')
    if not 1 <= len(name) <= 32 or b'\0' in name:
        raise ValueError('Wi-Fi 名称需为 1–32 字节，不能包含空字符。')
    valid_key = len(secret) == 64 and re.fullmatch(rb'[0-9a-fA-F]{64}', secret)
    if b'\0' in secret or not (len(secret) == 0 or 8 <= len(secret) <= 63 or valid_key):
        raise ValueError('密码需为 8–63 字节或 64 位十六进制；开放网络可留空。')
    return b'CONFIG ' + base64.b64encode(name) + b' ' + base64.b64encode(secret) + b'\n'


def read_camera(port, cancel, emit, command=None, timeout=50):
    """Passive line states avoid toggling the board's boot/reset pins."""
    connection = serial.Serial(port=None, baudrate=SERIAL_BAUD, timeout=.15, write_timeout=2)
    connection.dtr = False
    connection.rts = False
    connection.port = port
    saved = False
    try:
        connection.open()
        if cancel.is_set():
            return
        connection.reset_input_buffer()
        connection.write(b'\n' + (command if command is not None else b'STATUS\n'))
        deadline, next_status = time.monotonic() + timeout, time.monotonic() + 2
        while not cancel.is_set() and time.monotonic() < deadline:
            line = connection.readline().decode('utf-8', errors='replace')
            if 'CAMERA_CONFIG_SAVED' in line:
                saved = True
                emit('progress', '配置已保存，摄像头正在重启并连接 Wi-Fi…')
            if 'CAMERA_CONFIG_ERROR' in line:
                raise RuntimeError('摄像头未能保存配置，请检查网络名称、密码和设备状态。')
            match = re.search(r'CAMERA_STATUS ip=([\d.]+) configured=(\d) fw=([\w.-]+)', line)
            if match:
                ip, configured, firmware = match.groups()
                address = ipaddress.IPv4Address(ip)
                # For CONFIG, only accept status after acknowledgement/reboot.
                if not address.is_unspecified and (command is None or saved):
                    emit('connected', {'ip': ip, 'firmware': firmware})
                    return
                if command is None:
                    emit('progress', '尚未取得 IP；正在等待联网…' if configured == '1' else '摄像头尚未配网，请填写网络信息。')
            if time.monotonic() >= next_status:
                connection.write(b'\nSTATUS\n')
                next_status = time.monotonic() + 2
        if not cancel.is_set():
            raise TimeoutError('配置已保存，但尚未取得 IP。请检查 Wi-Fi 密码与 2.4 GHz 支持，再读取状态。'
                               if saved else '未收到有效状态，请检查 USB 数据线、串口及摄像头供电。')
    finally:
        connection.close()


class SetupDialog:
    def __init__(self, parent, on_connected):
        self.window = tk.Toplevel(parent)
        self.window.title('摄像头配网')
        self.window.configure(bg='#111b2e')
        self.window.resizable(False, False)
        self.window.transient(parent)
        self.on_connected = on_connected
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.worker = None
        self.closed = False
        self.port = tk.StringVar()
        self.ssid = tk.StringVar()
        self.password = tk.StringVar()
        self.message = tk.StringVar(value='正在读取串口和电脑当前 Wi-Fi…')
        panel = ttk.Frame(self.window, padding=24, style='Panel.TFrame')
        panel.pack(fill='both', expand=True)
        ttk.Label(panel, text='连接摄像头到 Wi-Fi', style='Section.TLabel').grid(row=0, column=0, columnspan=2, sticky='w')
        ttk.Label(panel, text='USB 配网完成后，自动切换到 Wi-Fi 视频预览。', style='Muted.TLabel').grid(row=1, column=0, columnspan=2, sticky='w', pady=(6, 22))
        ttk.Label(panel, text='USB 串口', style='Panel.TLabel').grid(row=2, column=0, sticky='w', pady=7)
        self.ports = ttk.Combobox(panel, textvariable=self.port, width=32, state='readonly')
        self.ports.grid(row=2, column=1, sticky='ew')
        ttk.Button(panel, text='刷新串口 / 当前网络', command=self.refresh).grid(row=3, column=1, sticky='e', pady=(2, 12))
        ttk.Label(panel, text='Wi-Fi 名称', style='Panel.TLabel').grid(row=4, column=0, sticky='w', padx=(0, 16), pady=7)
        ttk.Entry(panel, textvariable=self.ssid, width=34).grid(row=4, column=1, sticky='ew')
        ttk.Label(panel, text='Wi-Fi 密码', style='Panel.TLabel').grid(row=5, column=0, sticky='w', pady=7)
        self.secret = ttk.Entry(panel, textvariable=self.password, show='•')
        self.secret.grid(row=5, column=1, sticky='ew')
        show = tk.BooleanVar(value=False)
        ttk.Checkbutton(panel, text='显示密码', variable=show,
                        command=lambda: self.secret.configure(show='' if show.get() else '•')).grid(row=6, column=1, sticky='w', pady=(5, 14))
        ttk.Label(panel, text='选择 2.4 GHz 或双频同名网络；电脑也需接入同一局域网。',
                  style='Muted.TLabel', wraplength=430).grid(row=7, column=0, columnspan=2, sticky='w')
        ttk.Label(panel, textvariable=self.message, style='Panel.TLabel', wraplength=430).grid(row=8, column=0, columnspan=2, sticky='w', pady=(18, 12))
        actions = ttk.Frame(panel, style='Panel.TFrame')
        actions.grid(row=9, column=0, columnspan=2, sticky='ew')
        self.read_button = ttk.Button(actions, text='读取摄像头状态', command=lambda: self.begin(False))
        self.read_button.pack(side='left')
        self.save_button = ttk.Button(actions, text='保存并连接', style='Primary.TButton', command=lambda: self.begin(True))
        self.save_button.pack(side='right')
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.poll_id = self.window.after(100, self.poll)
        self.window.update_idletasks()
        self.window.geometry(f'+{max(0, parent.winfo_rootx() + (parent.winfo_width() - self.window.winfo_reqwidth()) // 2)}'
                             f'+{max(0, parent.winfo_rooty() + (parent.winfo_height() - self.window.winfo_reqheight()) // 2)}')
        self.window.bind('<Escape>', lambda event: self.close())
        self.window.bind('<Return>', lambda event: self.begin(True))
        self.refresh()

    def refresh(self):
        def discover():
            try:
                ports = [p.device for p in list_ports.comports()]
                ssid = ''
                try:
                    result = subprocess.run(['netsh', 'wlan', 'show', 'interfaces'], capture_output=True,
                                            timeout=4, creationflags=subprocess.CREATE_NO_WINDOW)
                    for raw in result.stdout.splitlines():
                        match = re.match(rb'\s*SSID\s*:\s*(.+)', raw)
                        if match:
                            for encoding in ('utf-8', 'gbk'):
                                try:
                                    ssid = match[1].decode(encoding).strip()
                                    break
                                except UnicodeDecodeError:
                                    pass
                            break
                except (OSError, subprocess.TimeoutExpired):
                    pass
                self.events.put(('discovered', (ports, ssid)))
            except Exception:
                self.events.put(('error', '无法枚举串口，请检查 USB 连接。'))
        threading.Thread(target=discover, daemon=True).start()

    def begin(self, save):
        if self.worker and self.worker.is_alive():
            return
        if not self.port.get():
            self.message.set('请先连接开发板并选择 USB 串口。')
            return
        try:
            command = config_command(self.ssid.get(), self.password.get()) if save else None
        except ValueError as exc:
            self.message.set(str(exc))
            return
        # Credentials exist only in this command and the masked form.
        port = self.port.get()
        self.cancel.clear()
        self.read_button.configure(state='disabled')
        self.save_button.configure(state='disabled')
        self.message.set('正在保存配置，摄像头将重新连接…' if save else '正在读取摄像头状态…')
        def run():
            try:
                read_camera(port, self.cancel, lambda *event: self.events.put(event), command,
                            timeout=50 if save else 12)
            except (OSError, ValueError, RuntimeError) as exc:
                self.events.put(('error', str(exc)))
            finally:
                self.events.put(('done', None))
        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def poll(self):
        if self.closed:
            return
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'discovered':
                ports, ssid = value
                self.ports.configure(values=ports)
                if self.port.get() not in ports:
                    self.port.set('COM15' if 'COM15' in ports else ports[0] if ports else '')
                if not self.ssid.get():
                    self.ssid.set(ssid)
                if not self.worker or not self.worker.is_alive():
                    self.message.set('已填入电脑当前网络名称；请输入密码。' if ports else '未发现串口，请连接 USB 数据线后刷新。')
            elif kind == 'connected':
                self.password.set('')
                self.message.set(f"已连接 · {value['ip']} · {value['firmware']}")
                self.on_connected(value['ip'])
            elif kind in ('progress', 'error'):
                self.message.set(value)
            elif kind == 'done':
                self.read_button.configure(state='normal')
                self.save_button.configure(state='normal')
        self.poll_id = self.window.after(100, self.poll)

    def close(self):
        self.closed = True
        self.cancel.set()
        self.password.set('')
        self.window.after_cancel(self.poll_id)
        self.window.destroy()
