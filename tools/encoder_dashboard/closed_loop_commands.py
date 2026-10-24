"""Versioned FOC command boundary: validation, acknowledgement, and live state.

An ACK never proves calibration or movement. Only a fresh firmware heartbeat
establishes those states; reconnect and render never generate a command.
"""
from math import isfinite
import re
import secrets
from threading import Condition
import time

from commands import CommandError, _uint

STATES = frozenset(('UNCALIBRATED', 'CALIBRATING', 'READY', 'RUNNING', 'FAULT'))
MODES = frozenset(('STOP', 'POSITION', 'VELOCITY', 'SWEEP', 'SPRING'))
FIELDS = {
    'calibrate': (), 'zero': (), 'stop': (), 'reset': (),
    'limits': ('min_deg', 'max_deg'),
    'position': ('target_deg', 'speed_rpm'), 'velocity': ('rpm',),
    'overspeed': ('enabled',),
    'target': ('run_id', 'target_deg'),
}


def _number(value):
    try:
        valid = type(value) in (int, float) and isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError('参数必须是有限数值，不能是字符串或布尔值。')
    return value


def validate_foc(payload):
    if type(payload) is not dict or type(payload.get('action')) is not str:
        raise ValueError('需要指定闭环 action。')
    action = payload['action']
    if action not in FIELDS or set(payload) != {'action', *FIELDS[action]}:
        raise ValueError('闭环动作或参数字段无效。')
    if action == 'overspeed':
        if type(payload['enabled']) is not bool:
            raise ValueError('超速保护 enabled 必须是布尔值。')
        return dict(payload)
    data = {'action': action, **{name: _number(payload[name]) for name in FIELDS[action]}}
    if action == 'target' and (type(data['run_id']) is not int or not 1 <= data['run_id'] <= 0x7FFFFFFF):
        raise ValueError('run_id 必须是有效的正整数。')
    if action == 'limits':
        lower, upper = data['min_deg'], data['max_deg']
        if not -180 <= lower < upper <= 180:
            raise ValueError('角度范围必须在 -180° 到 180° 内，且左端小于右端。')
        if action == 'limits' and (not lower <= 0 <= upper or upper - lower < 10):
            raise ValueError('软限位必须包含零点，宽度至少 10°。')
    for name in ('target_deg',):
        if name in data and not -180 <= data[name] <= 180:
            raise ValueError('相对目标必须在 -180° 到 180° 内。')
    if 'rpm' in data:
        speed = data['rpm']
        if not .1 <= abs(speed) <= 10:
            raise ValueError('速度范围为 0.1～10 rpm；恒速模式可用负数反转。')
    if 'speed_rpm' in data and not .1 <= data['speed_rpm'] <= 10:
        raise ValueError('移动速度范围为 0.1～10 rpm。')
    return data


def parse_status(line):
    fields = line.split(',')
    if not ((len(fields) == 15 and fields[:2] == ['#FOC_STATUS', '1']) or
            (len(fields) == 18 and fields[0] == '#FOC_STATUS' and fields[1] in ('2', '3')) or
            (len(fields) == 19 and fields[0] == '#FOC_STATUS' and fields[1] in ('3', '4'))):
        return None
    version = int(fields[1])
    # New v3 firmware appends the confirmed runtime switch. Older frames remain
    # readable but cannot authorize configuration of a capability they lack.
    overspeed = None
    if len(fields) == 19:
        if fields[18] not in ('0', '1'):
            return None
        overspeed = fields[18] == '1'
    try:
        if fields[2] not in STATES or fields[3] not in MODES:
            return None
        last_id = _uint(fields[4])
        if any(flag not in ('0', '1') for flag in fields[5:8]):
            return None
        values = list(map(float, fields[8:14]))
        if not all(isfinite(value) for value in values):
            return None
        relative, target, velocity, zero, lower, upper = values
        if (not 0 <= zero < 360 or not -180 <= lower <= 0 <= upper <= 180
                or upper - lower < 10 or
                re.fullmatch(r'[A-Z][A-Z0-9_]{0,31}', fields[14]) is None):
            return None
        lease = {}
        if version in (2, 3, 4):
            if fields[3] not in ('STOP', 'POSITION', 'VELOCITY'):
                return None
            run_id, remaining = _uint(fields[15]), _uint(fields[16])
            if (remaining > 1500 or fields[17] not in
                    ('NONE', 'USER_STOP', 'COMM_TIMEOUT', 'LIMIT', 'FAULT')):
                return None
            active = fields[2] in ('CALIBRATING', 'RUNNING')
            if (active != (run_id > 0) or run_id > last_id or
                    (not active and remaining != 0)):
                return None
            if fields[2] == 'RUNNING' and fields[5:8] != ['1', '1', '1']:
                return None
            lease = {'run_id': run_id, 'lease_remaining_ms': remaining, 'stop_reason': fields[17]}
        return {'protocol_version': version, 'overspeed_enabled': overspeed,
                **lease, 'state': fields[2], 'mode': fields[3], 'last_id': last_id,
                'calibrated': fields[5] == '1', 'enabled': fields[6] == '1',
                'sensor_valid': fields[7] == '1', 'relative_deg': relative,
                'target_deg': target, 'velocity_rpm': velocity, 'zero_raw_deg': zero,
                'soft_min_deg': lower, 'soft_max_deg': upper, 'fault': fields[14]}
    except (ValueError, OverflowError):
        return None


class ClosedLoopChannel:
    fresh_seconds = 1.5
    max_run_ms = None
    lease_timeout_ms = 1500

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._condition = Condition()
        self._connected = self._supported = False
        self._seen_at = self._state = None
        self._last_id = 0
        self._next_id = secrets.randbelow(0x7FFFFFFE) + 1
        self._pending = None
        self._owner = self._owner_at = self._owner_started_at = None
        self._settling = False
        self._command = self._idle()

    @staticmethod
    def _idle():
        return {'status': 'idle', 'id': None, 'action': None, 'error': ''}

    def reset(self, connected):
        with self._condition:
            self._connected = connected
            self._owner = self._owner_at = self._owner_started_at = None
            self._supported = False
            self._seen_at = self._state = None
            self._last_id = 0
            self._settling = False
            if self._pending is not None:
                self._finish('error', '串口已断开，闭环请求未确认；不会自动重发。')
            elif connected:
                self._command = self._idle()
            self._condition.notify_all()

    def consume(self, line):
        state = parse_status(line)
        if state is not None:
            with self._condition:
                last_id = state['last_id']
                if (last_id == 0 and state['state'] == 'UNCALIBRATED' and not state['enabled']
                        and not state['calibrated'] and self._state and self._state['last_id']):
                    self._owner = self._owner_at = self._owner_started_at = None
                    if self._pending is not None:
                        self._finish('error', '芯片已复位，旧闭环请求已失效。')
                    else:
                        self._command = self._idle()
                    self._settling = False
                    self._next_id = secrets.randbelow(0x7FFFFFFE) + 1
                self._supported = True
                self._seen_at = self._clock()
                self._state = state
                self._last_id = last_id
                self._next_id = max(self._next_id, last_id + 1)
                self._expire_owner()
                if (self._owner is not None and last_id >= self._owner and
                        (state.get('run_id') != self._owner or state['state'] not in
                         ('CALIBRATING', 'RUNNING') or state['protocol_version'] not in (3, 4))):
                    self._owner = self._owner_at = self._owner_started_at = None
                if self._command['id'] is not None and last_id >= self._command['id']:
                    self._settling = False
            return True
        fields = line.split(',')
        if len(fields) != 3 or fields[0] not in ('#FOC_ACK', '#FOC_NACK'):
            return False
        try:
            request_id = _uint(fields[1])
        except ValueError:
            return False
        with self._condition:
            if request_id != self._pending:
                return False
            if fields[0] == '#FOC_ACK' and fields[2] == self._command['action'].upper():
                self._last_id = max(self._last_id, request_id)
                self._next_id = max(self._next_id, request_id + 1)
                if self._command['action'] in ('calibrate', 'position', 'velocity'):
                    # State may precede ACK. A newer terminal/different run must
                    # not be resurrected by a delayed acknowledgement.
                    current = self._state or {}
                    if (current.get('protocol_version') in (3, 4) and
                            (current.get('last_id', 0) < request_id or
                             (current.get('run_id') == request_id and current.get('state') in
                              ('CALIBRATING', 'RUNNING')))):
                        self._owner = request_id
                        self._owner_at = self._owner_started_at = self._clock()
                if self._command['action'] == 'target':
                    # TARGET cannot enable, change mode, or renew/acquire a lease.
                    # Its matching ACK allows the next coalesced edit immediately.
                    self._settling = False
                self._finish('accepted')
            elif fields[0] == '#FOC_NACK':
                self._settling = False
                self._owner = self._owner_at = self._owner_started_at = None
                self._finish('error', f'芯片拒绝闭环请求：{fields[2][:48]}')
        return False

    def snapshot(self):
        with self._condition:
            self._expire_owner()
            age = None if self._seen_at is None else max(0, self._clock() - self._seen_at)
            available = self._connected and age is not None and age < self.fresh_seconds
            result = dict(self._state) if available else {}
            result.update(supported=self._supported, available=available,
                          age_ms=None if age is None else round(age * 1000),
                          max_run_ms=self.max_run_ms, lease_timeout_ms=self.lease_timeout_ms,
                          owned_run_id=self._owner, settling=self._settling,
                          command=dict(self._command))
            # Invalid sensor values can remain useful in firmware diagnostics,
            # but never display a stale/invalid position as a live measurement.
            if not result.get('sensor_valid'):
                result['relative_deg'] = result['velocity_rpm'] = None
            return result

    def begin(self, payload, sensor_valid):
        data = validate_foc(payload)
        action = data['action']
        with self._condition:
            status = self.snapshot()
            if not self._connected or not self._supported:
                raise CommandError('尚未收到闭环固件状态。')
            if action == 'stop':
                self._owner = self._owner_at = self._owner_started_at = None
            if action != 'stop':
                if status.get('protocol_version') not in (3, 4):
                    raise CommandError('需要 v3/v4 闭环固件，旧协议仅供诊断或停止。')
                if self._pending is not None or self._settling:
                    raise CommandError('上一请求尚待确认或等待新状态。')
                if not status['available'] or not sensor_valid or not status.get('sensor_valid'):
                    raise CommandError('闭环状态或编码器数据无效、已超时。')
                if action == 'target':
                    if (status['protocol_version'] != 4 or status['state'] != 'RUNNING' or
                            status['mode'] != 'POSITION' or not status['calibrated'] or
                            status.get('enabled') is not True or self._owner != data['run_id'] or
                            status.get('run_id') != data['run_id'] or status.get('lease_remaining_ms', 0) <= 0):
                        raise CommandError('实时拖动仅允许更新本页面已启动的位置控制，请先手动启动。')
                elif status.get('enabled') is not False:
                    raise CommandError('请先停止并等待 EN 关闭。')
                if action == 'target':
                    pass  # Live edits retain the existing mode, speed, and owner.
                elif action == 'overspeed':
                    if (type(status.get('overspeed_enabled')) is not bool or
                            (status['state'] not in ('UNCALIBRATED', 'READY') and not
                             (status['state'] == 'FAULT' and status.get('fault') == 'OVERSPEED'))):
                        raise CommandError('超速保护开关需要支持该设置的新固件，并处于停止或超速故障状态。')
                    self._owner = self._owner_at = self._owner_started_at = None
                elif action == 'reset':
                    if status['state'] != 'FAULT' or status.get('fault') != 'OVERSPEED':
                        raise CommandError('手动复位仅用于已停止的超速故障；其他故障需先检查原因。')
                    self._owner = self._owner_at = self._owner_started_at = None
                elif action == 'calibrate':
                    if status['state'] != 'UNCALIBRATED':
                        raise CommandError('校准仅允许在未校准、停机状态开始。')
                elif status['state'] != 'READY' or not status['calibrated']:
                    raise CommandError('请先完成 FOC 校准并停止运动。')
                lower, upper = status['soft_min_deg'], status['soft_max_deg']
                for name in ('target_deg',):
                    if name in data and not lower <= data[name] <= upper:
                        raise CommandError('目标超出芯片当前确认的软限位。')
                if action == 'limits' and not data['min_deg'] <= status['relative_deg'] <= data['max_deg']:
                    raise CommandError('新软限位必须包含当前位置。')
                if self._next_id > 0x7FFFFFFF:
                    raise CommandError('命令编号已耗尽，请复位芯片并重新连接。')
            elif self._pending is not None:
                self._finish('error', '旧请求已被立即停止取代。')
            request_id = min(self._next_id, 0x7FFFFFFF)
            self._next_id = request_id + 1
            self._pending = request_id
            self._settling = True
            self._command = {'status': 'pending', 'id': request_id, 'action': action, 'error': ''}
            parts = ['FOC', str(request_id)]
            if action in ('position', 'velocity'):
                parts.append('START')
            parts.append(action.upper())
            parts.extend(str(data[name]) if name == 'run_id' else format(data[name], '.8g')
                         for name in FIELDS[action])
            return request_id, (','.join(parts) + '\n').encode('ascii')

    def _expire_owner(self):
        if (self._owner_at is not None and
                self._clock() - self._owner_at >= self.lease_timeout_ms / 1000):
            self._owner = self._owner_at = self._owner_started_at = None

    def heartbeat(self, run_id):
        if type(run_id) is not int or not 1 <= run_id <= 0x7FFFFFFF:
            raise CommandError('run_id 必须是有效的正整数。')
        with self._condition:
            self._expire_owner()
            if not self._connected or self._owner != run_id:
                raise CommandError('当前页面未持有已确认的运动租约，请显式重新启动。')
            state = self._state or {}
            age = None if self._seen_at is None else self._clock() - self._seen_at
            valid = state.get('protocol_version') in (3, 4) and age is not None and age < self.fresh_seconds
            if state.get('last_id', 0) >= run_id:
                valid = valid and state.get('run_id') == run_id and state.get('lease_remaining_ms', 0) > 0
            else:
                valid = valid and self._clock() - self._owner_started_at < self.lease_timeout_ms / 1000
            if not valid:
                self._owner = self._owner_at = self._owner_started_at = None
                raise CommandError('闭环反馈超时或运行租约已结束，请显式重新启动。')
            return f'FOC,{run_id},KEEPALIVE\n'.encode('ascii')

    def heartbeat_written(self, run_id):
        with self._condition:
            # Terminal status may arrive while the serial write is in flight.
            # Never restore ownership after the reader has revoked it.
            self.heartbeat(run_id)
            self._owner_at = self._clock()

    def clear_owner(self):
        with self._condition:
            self._owner = self._owner_at = self._owner_started_at = None

    def _finish(self, status, error=''):
        self._command.update(status=status, error=error)
        self._pending = None
        self._condition.notify_all()

    def fail(self, request_id, error):
        with self._condition:
            if self._pending == request_id:
                self._settling = False
                self._owner = self._owner_at = self._owner_started_at = None
                self._finish('error', error)

    def wait(self, request_id, timeout=1.2):
        with self._condition:
            if not self._condition.wait_for(lambda: self._pending != request_id, timeout):
                self._owner = self._owner_at = self._owner_started_at = None
                self._finish('timeout', '未收到芯片确认；不会自动重发，请查看实时状态或停止。')
            if self._command['id'] != request_id or self._command['status'] != 'accepted':
                raise CommandError(self._command['error'] or '闭环请求未确认。')
            return self.snapshot()
