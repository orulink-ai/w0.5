"""Validate the UART provisioning contract without changing device credentials."""
import base64
import threading
import unittest
from unittest.mock import patch

from camera_setup import config_command, read_camera


class FakeSerial:
    def __init__(self, lines):
        self.lines = iter(lines)
        self.written = []
        self.closed = False

    def open(self):
        pass

    def reset_input_buffer(self):
        pass

    def write(self, value):
        self.written.append(value)
        return len(value)

    def readline(self):
        return next(self.lines, b'')

    def close(self):
        self.closed = True


class ProvisionTests(unittest.TestCase):
    def test_unicode_and_open_network_match_firmware_fields(self):
        command = config_command('创客松', '')
        ssid, password = command.removeprefix(b'CONFIG ').rstrip(b'\n').split(b' ')
        self.assertEqual(base64.b64decode(ssid).decode(), '创客松')
        self.assertEqual(base64.b64decode(password), b'')

    def test_reject_invalid_utf8_lengths_and_keys(self):
        for ssid, password in [('中'*11, '12345678'), ('', '12345678'),
                               ('wifi', 'short'), ('wifi', 'g'*64), ('wifi\0x', '')]:
            with self.subTest(ssid=ssid, length=len(password)):
                with self.assertRaises(ValueError):
                    config_command(ssid, password)
        self.assertTrue(config_command('wifi', 'a'*64).endswith(b'\n'))

    def test_read_status_is_passive_and_releases_port(self):
        fake = FakeSerial([b'boot log\n', b'CAMERA_STATUS ip=192.168.1.8 configured=1 fw=wtcc-live-6\n'])
        events = []
        with patch('camera_setup.serial.Serial', return_value=fake):
            read_camera('COM15', threading.Event(), lambda *v: events.append(v), timeout=.1)
        self.assertEqual(fake.written, [b'\nSTATUS\n'])
        self.assertFalse(fake.dtr)
        self.assertFalse(fake.rts)
        self.assertTrue(fake.closed)
        self.assertEqual(events[-1][1]['ip'], '192.168.1.8')

    def test_save_waits_for_ack_and_connected_ip(self):
        fake = FakeSerial([b'CAMERA_STATUS ip=192.168.1.7 configured=1 fw=old\n',
                           b'CAMERA_CONFIG_SAVED\n',
                           b'CAMERA_STATUS ip=0.0.0.0 configured=1 fw=new\n',
                           b'CAMERA_STATUS ip=192.168.1.8 configured=1 fw=new\n'])
        events = []
        with patch('camera_setup.serial.Serial', return_value=fake):
            read_camera('COM15', threading.Event(), lambda *v: events.append(v),
                        config_command('test', '12345678'), timeout=.1)
        connected = [v for kind, v in events if kind == 'connected']
        self.assertEqual([v['ip'] for v in connected], ['192.168.1.8'])
        self.assertTrue(fake.closed)

    def test_save_error_releases_port(self):
        fake = FakeSerial([b'CAMERA_CONFIG_ERROR save_failed\n'])
        with patch('camera_setup.serial.Serial', return_value=fake):
            with self.assertRaises(RuntimeError):
                read_camera('COM15', threading.Event(), lambda *v: None,
                            config_command('test', '12345678'), timeout=.1)
        self.assertTrue(fake.closed)


if __name__ == '__main__':
    unittest.main()
