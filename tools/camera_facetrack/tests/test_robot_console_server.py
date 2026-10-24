"""Exercise the real loopback HTTP server without any board or model access."""
import http.client
import json
import queue
import threading
import unittest

from robot_console_server import MAX_BODY, MAX_JPEG, RobotConsoleServer, validate_command


class RobotConsoleServerTests(unittest.TestCase):
    def test_optional_mouth_assistance_accepts_only_boolean_values(self):
        self.assertEqual(validate_command({'action': 'configure', 'mouthAssist': True})['mouthAssist'], True)
        self.assertEqual(validate_command({'action': 'configure', 'mouthAssist': False})['mouthAssist'], False)
        for value in (1, 'true', None, {}):
            with self.assertRaises(ValueError):
                validate_command({'action': 'configure', 'mouthAssist': value})

    def setUp(self):
        self.commands = queue.Queue(maxsize=1)
        self.server = RobotConsoleServer(self.commands.put_nowait, port=0)
        self.server.start()
        self.addCleanup(self.server.close)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.port, timeout=2)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result

    def test_snapshot_is_copied_and_commands_only_acknowledge_queue_acceptance(self):
        status = {'revision': 1, 'voice': {'phase': 'listening'}}
        self.server.publish(status)
        status['voice']['phase'] = 'done'
        code, body = self.request('GET', '/api/robot/status')
        self.assertEqual(code, 200)
        self.assertEqual(body['voice']['phase'], 'listening')
        code, body = self.request('POST', '/api/robot/control',
                                  json.dumps({'action': 'start', 'volume': 80}),
                                  {'Content-Type': 'application/json'})
        self.assertEqual(code, 202)
        self.assertEqual(body, {'accepted': True, 'action': 'start'})
        self.assertEqual(self.commands.get_nowait(), {'action': 'start', 'volume': 80})

    def test_rejects_external_origins_and_unexpected_hosts(self):
        for headers in ({'Origin': 'https://evil.example'}, {'Host': 'evil.example'}):
            self.assertEqual(self.request('GET', '/api/robot/status', headers=headers)[0], 403)
        self.assertEqual(self.request('GET', '/api/robot/status',
                                     headers={'Origin': 'http://localhost:5173'})[0], 200)

    def test_rejects_invalid_commands_and_oversize_requests(self):
        headers = {'Content-Type': 'application/json'}
        for body in ({'action': 'listen', 'volume': 100}, {'action': 'rotate', 'turns': True},
                     {'action': 'mirror'}, {'action': 'start', 'endpoint': 'http://evil'},
                     {'action': 'configure', 'enabled': 1}, []):
            self.assertEqual(self.request('POST', '/api/robot/control', json.dumps(body), headers)[0], 400)
        self.assertEqual(self.request('POST', '/api/robot/control',
                                      '{"action":"configure","faceTrigger":false}', headers)[0], 400)
        self.assertEqual(self.request('POST', '/api/robot/control', 'x' * (MAX_BODY + 1), headers)[0], 413)
        self.assertEqual(self.request('POST', '/api/robot/control', '{}')[0], 415)

    def test_queue_overflow_is_not_reported_as_accepted(self):
        self.commands.put_nowait({'action': 'cancel'})
        code, _ = self.request('POST', '/api/robot/control', '{"action":"cancel"}',
                               {'Content-Type': 'application/json'})
        self.assertEqual(code, 503)

    def test_speaker_test_accepts_only_the_fixed_action_without_arbitrary_text(self):
        code, body = self.request('POST', '/api/robot/control', '{"action":"test-speaker"}',
                                   {'Content-Type': 'application/json'})
        self.assertEqual(code, 202)
        self.assertEqual(body, {'accepted': True, 'action': 'test-speaker'})
        self.assertEqual(self.commands.get_nowait(), {'action': 'test-speaker'})
        for field, value in (('text', 'unrequested content'), ('volume', 100), ('volume', 80)):
            with self.assertRaises(ValueError):
                validate_command({'action': 'test-speaker', field: value})

    def test_mjpeg_is_latest_only_and_shutdown_releases_streams(self):
        self.server.publish({'revision': 1}, b'\xff\xd8first\xff\xd9')
        self.server.publish({'revision': 2}, b'\xff\xd8latest\xff\xd9')
        connection = http.client.HTTPConnection('127.0.0.1', self.server.port, timeout=2)
        self.addCleanup(connection.close)
        connection.request('GET', '/api/robot/camera.mjpeg')
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.readline(), b'--frame\r\n')
        self.assertEqual(response.readline(), b'Content-Type: image/jpeg\r\n')
        size = int(response.readline().split(b':')[1])
        self.assertEqual(response.readline(), b'\r\n')
        self.assertEqual(response.read(size), b'\xff\xd8latest\xff\xd9')
        with self.assertRaises(ValueError):
            self.server.publish({}, b'x' * (MAX_JPEG + 1))
        thread = threading.Thread(target=self.server.close)
        thread.start()
        thread.join(timeout=3)
        self.assertFalse(thread.is_alive())

    def test_camera_configuration_and_fixed_volume_contract(self):
        for command in ({'action': 'configure', 'faceTrigger': True, 'enabled': False, 'volume': 80},
                        {'action': 'rotate', 'turns': 3}, {'action': 'mirror', 'enabled': True},
                        {'action': 'camera-start'}, {'action': 'camera-stop'}):
            self.assertEqual(validate_command(command), command)

    def test_conversation_mode_is_a_validated_configuration_option(self):
        for mode in ('single', 'continuous'):
            command = {'action': 'configure', 'mode': mode}
            self.assertEqual(validate_command(command), command)
        for mode in (None, True, [], {}, 'unknown'):
            with self.assertRaises(ValueError):
                validate_command({'action': 'configure', 'mode': mode})


if __name__ == '__main__':
    unittest.main()
