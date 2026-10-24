"""Authenticated loopback audio proxy; these tests never open a board."""
import json
import socket
import base64
import unittest

from board_broker import AudioBroker, get_audio_broker


class Owner:
    def __init__(self):
        self.commands = []
        self.callback = None

    def audio_request(self, operation, encoded=''):
        self.commands.append((operation, encoded))

    def subscribe_microphone(self, callback):
        self.callback = callback


def send(connection, value):
    connection.sendall((json.dumps(value) + '\n').encode())


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.owner = Owner()
        self.broker = AudioBroker('TEST-COM', self.owner)
        self.broker.start()
        self.connection = socket.create_connection(('127.0.0.1', self.broker.port), timeout=2)
        self.lines = self.connection.makefile('rb')

    def tearDown(self):
        self.lines.close()
        self.connection.close()
        self.broker.close()

    def receive(self):
        return json.loads(self.lines.readline())

    def authenticate(self):
        send(self.connection, {'id': 0, 'token': self.broker.token})
        self.assertEqual(self.receive(), {'id': 0, 'ok': True, 'volume': 80, 'sampleRate': 24000})

    def test_registry_is_memory_only_and_removed_on_close(self):
        self.assertEqual(get_audio_broker('test-com'),
                         (f'tcp://127.0.0.1:{self.broker.port}', self.broker.token))
        self.broker.close()
        self.assertIsNone(get_audio_broker('TEST-COM'))

    def test_wrong_token_cannot_initialize_audio(self):
        send(self.connection, {'id': 0, 'token': 'wrong'})
        self.assertFalse(self.receive()['ok'])
        self.assertEqual(self.owner.commands, [])

    def test_audio_responses_disable_tcp_small_packet_delay(self):
        self.authenticate()
        with self.broker.connections_lock:
            connections = list(self.broker.connections)
        self.assertEqual(len(connections), 1)
        self.assertEqual(connections[0].getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY), 1)

    def test_requests_and_microphone_events_share_connection(self):
        self.authenticate()
        send(self.connection, {'id': 1, 'op': 'mic-start'})
        self.assertEqual(self.receive(), {'id': 1, 'ok': True})
        self.owner.callback({'type': 'mic', 'sequence': 1, 'pcm': 'AAEAAg=='})
        self.assertEqual(self.receive(), {'type': 'mic', 'sequence': 1, 'pcm': 'AAEAAg=='})
        send(self.connection, {'id': 2, 'op': 'frame', 'pcm': 'AAEAAg=='})
        self.assertEqual(self.receive(), {'id': 2, 'ok': True})
        self.assertIn(('frame', 'AAEAAg=='), self.owner.commands)
        self.assertFalse(any('VIDEO' in op or 'BAUD' in op for op, _ in self.owner.commands))

    def test_unknown_operation_and_oversized_pcm_are_rejected(self):
        self.authenticate()
        send(self.connection, {'id': 1, 'op': 'baud'})
        self.assertFalse(self.receive()['ok'])
        self.assertNotIn(('baud', ''), self.owner.commands)
        send(self.connection, {'id': 2, 'op': 'frame',
                               'pcm': base64.b64encode(b'\0' * 962).decode()})
        self.assertFalse(self.receive()['ok'])
        self.assertFalse(any(operation == 'frame' for operation, _ in self.owner.commands))

    def test_initialization_failure_is_reported_and_does_not_hang(self):
        def fail(*_): raise RuntimeError('codec unavailable')
        self.owner.audio_request = fail
        send(self.connection, {'id': 0, 'token': self.broker.token})
        response = self.receive()
        self.assertFalse(response['ok'])
        self.assertIn('codec unavailable', response['error'])

    def test_second_client_is_rejected_without_reinitializing_device(self):
        self.authenticate()
        count = len(self.owner.commands)
        with socket.create_connection(('127.0.0.1', self.broker.port), timeout=2) as other:
            with other.makefile('rb') as lines:
                self.assertFalse(json.loads(lines.readline())['ok'])
        self.assertEqual(len(self.owner.commands), count)


if __name__ == '__main__':
    unittest.main()
