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
from enable_commands import EnableChannel, validate_enabled
from server import SerialReader, make_server
from telemetry import TelemetryStore


class EnableTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.channel = EnableChannel(clock=lambda: self.now)
        self.channel.reset(True)

    def test_strict_boolean_and_protocol_isolation(self):
        for value in (None, 0, 1, 'true', [], {}):
            with self.assertRaises(ValueError): validate_enabled(value)
        for value in (True, False): self.assertIs(validate_enabled(value), value)
        for line in ('#CONTROL,1,DISABLED,0,-1', '#JOG_STATUS,1,READY,MANUAL_EN,1.0V,0.5rad_s,3000ms',
                     '#ENABLE_STATUS,2,READY,0,0', '#ENABLE_STATUS,1,READY,2,0',
                     '#ENABLE_STATUS,1,READY,0,2147483648'):
            self.channel.consume(line)
        self.assertFalse(self.channel.snapshot()['available'])
        with self.assertRaises(CommandError): self.channel.begin(False, False)

    def test_ready_sensor_freshness_and_off_without_sensor(self):
        self.channel.consume('#ENABLE_STATUS,1,READY,0,0')
        with self.assertRaises(CommandError): self.channel.begin(True, False)
        self.now += 3
        self.assertIsNone(self.channel.snapshot()['enabled'])
        with self.assertRaises(CommandError): self.channel.begin(True, True)
        request_id, packet = self.channel.begin(False, False)
        self.assertEqual(packet, f'ENABLE,{request_id},0\n'.encode())
        self.channel.consume(f'#ENABLE_ACK,{request_id},0')
        self.assertFalse(self.channel.wait(request_id, timeout=.01)['enabled'])
        self.assertEqual(self.channel.snapshot()['max_on_ms'], 5000)

    def test_matching_ack_only_fault_readback_and_watchdog_status(self):
        self.channel.consume('#ENABLE_STATUS,1,READY,0,0')
        request_id, packet = self.channel.begin(True, True)
        self.assertEqual(packet, f'ENABLE,{request_id},1\n'.encode())
        self.channel.consume(f'#ENABLE_ACK,{request_id + 1},1')
        self.channel.consume(f'#ENABLE_ACK,{request_id},0')
        self.assertFalse(self.channel.snapshot()['enabled'])
        self.assertEqual(self.channel.snapshot()['command']['status'], 'pending')
        self.channel.consume(f'#ENABLE_ACK,{request_id},1')
        self.assertTrue(self.channel.wait(request_id, timeout=.01)['enabled'])
        self.channel.consume(f'#ENABLE_STATUS,1,READY,0,{request_id}')
        self.assertFalse(self.channel.snapshot()['enabled'])
        self.channel.consume(f'#ENABLE_STATUS,1,FAULT,1,{request_id}')
        state = self.channel.snapshot()
        self.assertTrue(state['available'])
        self.assertTrue(state['enabled'])
        self.assertFalse(state['ready'])
        with self.assertRaises(CommandError): self.channel.begin(True, True)
        request_id, _ = self.channel.begin(False, False)
        self.channel.consume(f'#ENABLE_NACK,{request_id},PIN_READBACK')
        with self.assertRaises(CommandError): self.channel.wait(request_id, timeout=.01)
        self.assertTrue(self.channel.snapshot()['enabled'])

    def test_timeout_disconnect_and_reset_invalidate_confirmation(self):
        self.channel.consume('#ENABLE_STATUS,1,READY,0,12')
        request_id, _ = self.channel.begin(True, True)
        with self.assertRaises(CommandError): self.channel.wait(request_id, timeout=.001)
        self.assertEqual(self.channel.snapshot()['command']['status'], 'timeout')
        self.channel.consume(f'#ENABLE_ACK,{request_id},1')
        self.assertFalse(self.channel.snapshot()['enabled'])
        request_id, _ = self.channel.begin(True, True)
        self.channel.consume('#ENABLE_STATUS,1,READY,0,0')
        with self.assertRaises(CommandError): self.channel.wait(request_id, timeout=.01)
        self.assertFalse(self.channel.snapshot()['enabled'])
        self.channel.consume(f'#ENABLE_ACK,{request_id},1')
        self.assertFalse(self.channel.snapshot()['enabled'])
        request_id, _ = self.channel.begin(False, False)
        self.channel.reset(False)
        with self.assertRaises(CommandError): self.channel.wait(request_id, timeout=.01)
        self.assertIsNone(self.channel.snapshot()['enabled'])

    def test_first_pending_request_survives_boot_sentinel_heartbeat(self):
        self.channel.consume('#ENABLE_STATUS,1,READY,0,0')
        request_id, _ = self.channel.begin(True, True)
        # The periodic boot sentinel can have been queued just before the MCU
        # receives the first command. It does not establish a reset boundary.
        self.channel.consume('#ENABLE_STATUS,1,READY,0,0')
        self.assertEqual(self.channel.snapshot()['command']['status'], 'pending')
        self.channel.consume(f'#ENABLE_ACK,{request_id},1')
        self.assertTrue(self.channel.wait(request_id, timeout=.01)['enabled'])
        # Once a nonzero request has been observed, zero does establish reset.
        next_id, _ = self.channel.begin(False, False)
        self.channel.consume('#ENABLE_STATUS,1,READY,0,0')
        with self.assertRaises(CommandError): self.channel.wait(next_id, timeout=.01)
        self.assertFalse(self.channel.snapshot()['enabled'])

    def test_enable_protocol_disables_previous_target_and_manual_jog(self):
        store = TelemetryStore()
        store.set_connection(True, 'test')
        store.consume('#CONTROL,1,DISABLED,0,-1')
        self.assertTrue(store.snapshot()['control']['available'])
        store.consume('#JOG_STATUS,1,READY,MANUAL_EN,1.0V,0.5rad_s,3000ms')
        store.consume('#ENABLE_STATUS,1,READY,0,0')
        state = store.snapshot()
        self.assertTrue(state['enable']['available'])
        self.assertIsNone(state['jog'])
        self.assertFalse(state['control']['available'])
        store.consume('#CONTROL,1,DISABLED,0,-1')
        store.consume('#JOG_STATUS,1,READY,MANUAL_EN,1.0V,0.5rad_s,3000ms')
        self.assertFalse(store.snapshot()['control']['available'])
        self.assertIsNone(store.snapshot()['jog'])
        store.set_connection(False)
        self.assertFalse(store.snapshot()['enable']['available'])


class EnableHttpTests(unittest.TestCase):
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

    def post(self, data, origin=None):
        headers = {'Content-Type': 'application/json'}
        if origin: headers['Origin'] = origin
        return urlopen(Request(self.base + '/api/enable', data=json.dumps(data).encode(),
                               headers=headers), timeout=3)

    def advertise(self, valid=True):
        sample = 'OK,60,0,460,400,2175' if valid else 'NO_PWM_OR_INVALID,nan,nan,nan,0,0'
        os.write(self.master, f'#ENABLE_STATUS,1,READY,0,0\n{sample}\n'.encode())
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            state = self.store.snapshot()
            if state['enable']['available'] and state['signal'] == ('valid' if valid else 'invalid'):
                return
            time.sleep(.01)
        self.fail('PTY telemetry did not arrive')

    def test_ack_wait_off_with_invalid_sensor_and_no_retransmit(self):
        self.advertise()
        for enabled in (True, False):
            if not enabled: self.advertise(valid=False)
            results, failures = [], []
            def send():
                try:
                    with self.post({'enabled': enabled}) as response: results.append(json.load(response))
                except Exception as error: failures.append(error)
            sender = threading.Thread(target=send)
            sender.start()
            self.assertTrue(select.select([self.master], [], [], 1)[0])
            packet = os.read(self.master, 256).decode().strip().split(',')
            self.assertEqual((packet[0], packet[2]), ('ENABLE', str(int(enabled))))
            self.assertTrue(sender.is_alive())
            os.write(self.master, f'#ENABLE_ACK,{packet[1]},{int(enabled)}\n'.encode())
            sender.join(2)
            self.assertFalse(sender.is_alive())
            self.assertEqual(failures, [])
            self.assertIs(results[0]['enable']['enabled'], enabled)
        self.advertise()
        with self.assertRaises(HTTPError) as error: self.post({'enabled': True})
        self.assertEqual(error.exception.code, 409)
        self.assertEqual(self.store.snapshot()['enable']['command']['status'], 'timeout')
        self.assertTrue(select.select([self.master], [], [], .1)[0])
        self.assertEqual(os.read(self.master, 256).count(b'ENABLE,'), 1)
        self.assertFalse(select.select([self.master], [], [], .1)[0], 'No automatic retry or keepalive')

    def test_bad_bool_origin_and_firmware_gate(self):
        for value in (None, 0, 1, 'true', [], {}):
            with self.assertRaises(HTTPError) as error: self.post({'enabled': value})
            self.assertEqual(error.exception.code, 400)
        with self.assertRaises(HTTPError) as error: self.post({'enabled': True}, 'https://example.com')
        self.assertEqual(error.exception.code, 403)
        with self.assertRaises(HTTPError) as error: self.post({'enabled': False})
        self.assertEqual(error.exception.code, 409)
        self.assertFalse(select.select([self.master], [], [], .1)[0])
