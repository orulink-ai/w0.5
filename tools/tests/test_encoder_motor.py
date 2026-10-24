import json
import os
from pathlib import Path
import pty
import select
import sys
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'encoder_dashboard'))
from commands import CommandError
from motor_commands import MotorChannel, validate_action
from server import SerialReader, make_server
from telemetry import TelemetryStore

OFF_READY = {'ready': True, 'enabled': False}


class MotorTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.channel = MotorChannel(clock=lambda: self.now)
        self.channel.reset(True)

    def test_strict_actions_and_capability_isolation(self):
        for value in (None, True, 0, {}, [], 'JOG', 'jog\nENABLE', 'run'):
            with self.assertRaises(ValueError): validate_action(value)
        for action in ('jog', 'stop'): self.assertEqual(validate_action(action), action)
        for line in ('#ENABLE_STATUS,1,READY,0,0', '#JOG_STATUS,1,READY,MANUAL_EN,1.0V,0.5rad_s,3000ms',
                     '#MOTOR_STATUS,2,READY,0', '#MOTOR_STATUS,1,READY,-1',
                     '#MOTOR_STATUS,1,READY,2147483648', '#MOTOR_STATUS,1,BOGUS,0'):
            self.channel.consume(line)
        self.assertFalse(self.channel.snapshot()['available'])
        with self.assertRaises(CommandError): self.channel.begin('stop', False, OFF_READY)

    def test_jog_requires_ready_fresh_sensor_and_explicitly_disabled_enable(self):
        self.channel.consume('#MOTOR_STATUS,1,READY,0')
        for sensor, enable in ((False, OFF_READY), (True, {'ready': False, 'enabled': False}),
                               (True, {'ready': True, 'enabled': True}),
                               (True, {'ready': True, 'enabled': None})):
            with self.assertRaises(CommandError): self.channel.begin('jog', sensor, enable)
        self.now += 3
        with self.assertRaises(CommandError): self.channel.begin('jog', True, OFF_READY)
        request_id, packet = self.channel.begin('stop', False, {'ready': False, 'enabled': None})
        self.assertEqual(packet, f'MOTOR,{request_id},STOP\n'.encode())
        self.channel.consume(f'#MOTOR_ACK,{request_id},STOPPED')
        self.assertEqual(self.channel.wait(request_id, .01)['command']['status'], 'accepted')

    def test_ack_matches_id_and_action_completion_only_by_status(self):
        self.channel.consume('#MOTOR_STATUS,1,READY,0')
        request_id, packet = self.channel.begin('jog', True, OFF_READY)
        self.assertEqual(packet, f'MOTOR,{request_id},JOG\n'.encode())
        self.channel.consume(f'#MOTOR_ACK,{request_id + 1},STARTED')
        self.channel.consume(f'#MOTOR_ACK,{request_id},STOPPED')
        self.assertEqual(self.channel.snapshot()['command']['status'], 'pending')
        self.channel.consume(f'#MOTOR_ACK,{request_id},STARTED')
        state = self.channel.wait(request_id, .01)
        self.assertEqual(state['command']['status'], 'accepted')
        self.assertNotEqual(state['state'], 'DONE')
        self.assertFalse(state['ready'], 'An accepted JOG cannot be started again')
        self.channel.consume(f'#MOTOR_STATUS,1,RUNNING,{request_id}')
        self.assertEqual(self.channel.snapshot()['state'], 'RUNNING')
        self.channel.consume(f'#MOTOR_STATUS,1,DONE,{request_id}')
        self.assertEqual(self.channel.snapshot()['state'], 'DONE')
        self.assertEqual(self.channel.snapshot()['max_run_ms'], 3000)
        next_id, _ = self.channel.begin('jog', True, OFF_READY)
        self.assertNotEqual(next_id, request_id)
        self.channel.consume(f'#MOTOR_ACK,{next_id},STARTED')
        self.channel.wait(next_id, .01)
        self.assertEqual(self.channel.snapshot()['state'], 'RUNNING')
        with self.assertRaises(CommandError): self.channel.begin('jog', True, OFF_READY)

    def test_fault_stop_timeout_and_disconnect(self):
        self.channel.consume('#MOTOR_STATUS,1,FAULT,12')
        with self.assertRaises(CommandError): self.channel.begin('jog', True, OFF_READY)
        request_id, _ = self.channel.begin('stop', False, {})
        self.channel.consume(f'#MOTOR_NACK,{request_id},PIN_READBACK')
        with self.assertRaises(CommandError): self.channel.wait(request_id, .01)
        request_id, _ = self.channel.begin('stop', False, {})
        with self.assertRaises(CommandError): self.channel.wait(request_id, .001)
        self.assertEqual(self.channel.snapshot()['command']['status'], 'timeout')
        self.channel.consume(f'#MOTOR_ACK,{request_id},STOPPED')
        self.assertEqual(self.channel.snapshot()['command']['status'], 'timeout')
        request_id, _ = self.channel.begin('stop', False, {})
        self.channel.reset(False)
        with self.assertRaises(CommandError): self.channel.wait(request_id, .01)
        self.assertFalse(self.channel.snapshot()['stop_available'])

    def test_boot_sentinel_race_and_reset_after_known_nonzero_id(self):
        self.channel.consume('#MOTOR_STATUS,1,READY,0')
        request_id, _ = self.channel.begin('jog', True, OFF_READY)
        self.channel.consume('#MOTOR_STATUS,1,READY,0')
        self.assertEqual(self.channel.snapshot()['command']['status'], 'pending')
        self.channel.consume(f'#MOTOR_ACK,{request_id},STARTED')
        self.channel.wait(request_id, .01)
        stop_id, _ = self.channel.begin('stop', False, {})
        self.channel.consume('#MOTOR_STATUS,1,READY,0')
        with self.assertRaises(CommandError): self.channel.wait(stop_id, .01)
        self.assertTrue(self.channel.snapshot()['ready'])
        self.channel.consume(f'#MOTOR_ACK,{stop_id},STOPPED')
        self.assertEqual(self.channel.snapshot()['command']['status'], 'error')

    def test_motor_capability_preserves_enable_but_clears_old_controls(self):
        store = TelemetryStore()
        store.set_connection(True, 'test')
        store.consume('#CONTROL,1,DISABLED,0,-1')
        store.consume('#JOG_STATUS,1,READY,MANUAL_EN,1.0V,0.5rad_s,3000ms')
        store.consume('#MOTOR_STATUS,1,READY,0')
        self.assertFalse(store.snapshot()['control']['available'])
        self.assertIsNone(store.snapshot()['jog'])
        self.assertFalse(store.snapshot()['enable']['available'])
        store.consume('#ENABLE_STATUS,1,READY,0,0')
        self.assertTrue(store.snapshot()['enable']['available'])
        self.assertTrue(store.snapshot()['motor']['available'])
        store.consume('#JOG_STATUS,1,READY,MANUAL_EN,1.0V,0.5rad_s,3000ms')
        self.assertIsNone(store.snapshot()['jog'])
        store.set_connection(False)
        self.assertFalse(store.snapshot()['motor']['available'])

    def test_server_restart_adopts_device_high_water_without_sending(self):
        self.channel._next_id = 7
        self.channel.consume('#MOTOR_STATUS,1,DONE,12000')
        self.assertEqual(self.channel.snapshot()['command']['status'], 'idle')
        self.assertEqual(self.channel._next_id, 12001)
        request_id, _ = self.channel.begin('jog', True, OFF_READY)
        self.assertEqual(request_id, 12001)
        self.channel.consume(f'#MOTOR_ACK,{request_id},STARTED')
        self.channel.wait(request_id, .01)
        self.channel.consume('#MOTOR_STATUS,1,DONE,12001')
        # Delayed or lower status IDs never move the next request backwards.
        self.channel.consume('#MOTOR_STATUS,1,DONE,100')
        request_id, _ = self.channel.begin('jog', True, OFF_READY)
        self.assertEqual(request_id, 12002)

    def test_request_id_exhaustion_never_wraps_and_stop_remains_possible(self):
        self.channel._next_id = 8
        self.channel.consume('#MOTOR_STATUS,1,DONE,2147483646')
        request_id, _ = self.channel.begin('jog', True, OFF_READY)
        self.assertEqual(request_id, 0x7fffffff)
        self.channel.consume(f'#MOTOR_ACK,{request_id},STARTED')
        self.channel.wait(request_id, .01)
        self.channel.consume('#MOTOR_STATUS,1,DONE,2147483647')
        with self.assertRaisesRegex(CommandError, '重新启动'):
            self.channel.begin('jog', True, OFF_READY)
        self.assertEqual(self.channel.snapshot()['command']['status'], 'accepted')
        stop_id, packet = self.channel.begin('stop', False, {})
        self.assertEqual(stop_id, 0x7fffffff)
        self.assertEqual(packet, b'MOTOR,2147483647,STOP\n')
        self.channel.consume('#MOTOR_ACK,2147483647,STOPPED')
        self.channel.wait(stop_id, .01)
        with self.assertRaisesRegex(CommandError, '重新启动'):
            self.channel.begin('jog', True, OFF_READY)
        self.channel.reset(False)
        self.channel.reset(True)
        self.channel.consume('#MOTOR_STATUS,1,READY,0')
        request_id, _ = self.channel.begin('jog', True, OFF_READY)
        self.assertTrue(0 < request_id <= 0x7fffffff)


class MotorHttpTests(unittest.TestCase):
    def setUp(self):
        self.master, self.slave = pty.openpty()
        self.store = TelemetryStore()
        self.reader = SerialReader(self.store)
        device = os.ttyname(self.slave)
        self.reader.ports = lambda: [{'device': device, 'description': 'test PTY'}]
        self.reader.connect(device)
        self.server = make_server(self.reader, self.store, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.reader.disconnect()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        os.close(self.master)
        os.close(self.slave)

    def post(self, body, origin=None):
        headers = {'Content-Type': 'application/json'}
        if origin: headers['Origin'] = origin
        return urlopen(Request(self.base + '/api/motor', data=json.dumps(body).encode(),
                               headers=headers), timeout=3)

    def advertise(self):
        os.write(self.master, b'#ENABLE_STATUS,1,READY,0,0\n#MOTOR_STATUS,1,READY,0\nOK,60,0,460,400,2175\n')
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            state = self.store.snapshot()
            if state['motor']['ready'] and state['signal'] == 'valid': return
            time.sleep(.01)
        self.fail('PTY telemetry did not arrive')

    def test_real_ack_wait_stop_invalid_stale_and_timeout_no_retry(self):
        self.advertise()
        for action, ack in (('jog', 'STARTED'), ('stop', 'STOPPED')):
            if action == 'stop':
                os.write(self.master, b'NO_PWM_OR_INVALID,nan,nan,nan,0,0\n')
                time.sleep(.03)
            results, failures = [], []
            def send():
                try:
                    with self.post({'action': action}) as response: results.append(json.load(response))
                except Exception as error: failures.append(error)
            sender = threading.Thread(target=send)
            sender.start()
            self.assertTrue(select.select([self.master], [], [], 1)[0])
            packet = os.read(self.master, 256).decode().strip().split(',')
            self.assertEqual((packet[0], packet[2]), ('MOTOR', action.upper()))
            self.assertTrue(sender.is_alive())
            os.write(self.master, f'#MOTOR_ACK,{packet[1]},{ack}\n'.encode())
            sender.join(2)
            self.assertFalse(sender.is_alive())
            self.assertEqual(failures, [])
            self.assertEqual(results[0]['motor']['command']['status'], 'accepted')
        with self.assertRaises(HTTPError) as error: self.post({'action': 'stop'})
        self.assertEqual(error.exception.code, 409)
        self.assertEqual(self.store.snapshot()['motor']['command']['status'], 'timeout')
        self.assertTrue(select.select([self.master], [], [], .1)[0])
        self.assertEqual(os.read(self.master, 256).count(b'MOTOR,'), 1)
        self.assertFalse(select.select([self.master], [], [], .1)[0], 'No automatic retry')

    def test_bad_action_origin_and_firmware_gate(self):
        for value in (None, True, 1, {}, [], 'JOG', 'run', 'stop\nENABLE'):
            with self.assertRaises(HTTPError) as error: self.post({'action': value})
            self.assertEqual(error.exception.code, 400)
        with self.assertRaises(HTTPError) as error: self.post({'action': 'jog'}, 'https://example.com')
        self.assertEqual(error.exception.code, 403)
        with self.assertRaises(HTTPError) as error: self.post({'action': 'stop'})
        self.assertEqual(error.exception.code, 409)
        self.assertFalse(select.select([self.master], [], [], .1)[0])

    def test_recreated_backend_adopts_hardware_high_water_only_on_explicit_click(self):
        self.store.motor._next_id = 3
        self.advertise()
        os.write(self.master, b'#MOTOR_STATUS,1,DONE,12000\n')
        deadline = time.monotonic() + 2
        while self.store.snapshot()['motor']['last_id'] != 12000:
            if time.monotonic() > deadline: self.fail('High-water status did not arrive')
            time.sleep(.01)
        self.assertFalse(select.select([self.master], [], [], .1)[0], 'Status cannot trigger a run')
        results = []
        def send():
            with self.post({'action': 'jog'}) as response: results.append(json.load(response))
        sender = threading.Thread(target=send)
        sender.start()
        self.assertTrue(select.select([self.master], [], [], 1)[0])
        self.assertEqual(os.read(self.master, 256), b'MOTOR,12001,JOG\n')
        os.write(self.master, b'#MOTOR_ACK,12001,STARTED\n')
        sender.join(2)
        self.assertFalse(sender.is_alive())
        self.assertEqual(results[0]['motor']['command']['status'], 'accepted')
