"""The robot invokes vi-agent's real board entry, with bounded cancellation."""
import io
import json
import threading
import unittest
from unittest.mock import patch

from voice_session import VoiceSession


class VoiceSessionTests(unittest.TestCase):
    def test_departure_is_forwarded_once_and_requires_a_clean_park_acknowledgement(self):
        for parked, code in ((True, 0), (False, 0), (True, 1)):
            with self.subTest(parked=parked, code=code):
                finish = threading.Event()
                finish.set()
                activation = (threading.Event(), {'since': 1000})
                activation[0].set()
                class Input(io.StringIO):
                    contents = ''
                    def write(self, text):
                        self.contents += text
                        return super().write(text)
                class Process:
                    stdout = io.StringIO('{"type":"state","text":"正在聆听"}\n' +
                                         ('{"type":"parked","text":"等待人脸"}\n' if parked else ''))
                    stdin = Input()
                    def poll(self): return code
                    def wait(self, timeout=None): return code
                process = Process()
                with patch.dict('voice_session.os.environ', VI_VOICE_PROVIDER='local-cascade'), \
                        patch('voice_session.subprocess.Popen', return_value=process):
                    session = VoiceSession('COM15', 'http://127.0.0.1:8790', lambda *_: None,
                                           threading.Event(), finish_event=finish, activation=activation)
                    if parked and code == 0:
                        session.run()
                    else:
                        with self.assertRaises(RuntimeError):
                            session.run()
                self.assertEqual(process.stdin.contents, 'finish-turn\n')

    def test_visual_stdin_closure_does_not_hide_the_original_model_error(self):
        class Input(io.StringIO):
            def write(self, text):
                raise BrokenPipeError('child stdin closed')
        class Process:
            stdout = io.StringIO('{"type":"error","text":"模型加载失败"}\n')
            stdin = Input()
            def poll(self): return 1
            def wait(self, timeout=None): return 1
        with patch.dict('voice_session.os.environ', {'VI_VOICE_PROVIDER': 'local-cascade'}), \
                patch('voice_session.subprocess.Popen', return_value=Process()):
            with self.assertRaisesRegex(RuntimeError, '模型加载失败'):
                VoiceSession('COM15', 'http://127.0.0.1:8790', lambda *_: None, threading.Event(),
                             mouth_provider=lambda: {}).run()

    def test_cascade_receives_visual_metadata_on_stdin_without_sending_images(self):
        class Input(io.StringIO):
            contents = ''
            def write(self, text):
                self.contents += text
                return super().write(text)
        class Process:
            stdout = io.StringIO('{"type":"done","text":"你好"}\n')
            stdin = Input()
            def poll(self): return 0
            def wait(self, timeout=None): return 0
        process = Process()
        observation = dict(enabled=True, available=True, moving=False, observedAt=1000,
                           lastMotionAt=900, targetId=3)
        with patch.dict('voice_session.os.environ', {'VI_VOICE_PROVIDER': 'local-cascade'}), \
                patch('voice_session.subprocess.Popen', return_value=process):
            VoiceSession('COM15', 'http://127.0.0.1:8790', lambda *_: None, threading.Event(),
                         mouth_provider=lambda: observation).run()
        message = json.loads(process.stdin.contents.splitlines()[0])
        self.assertEqual(message, {'type': 'mouth', **observation})

    def test_cascade_entry_forwards_transcript_and_latency(self):
        events = []
        class Process:
            stdout = io.StringIO('{"type":"user-text","text":"你好"}\n{"type":"latency","text":"{\\"asrMs\\":80}"}\n{"type":"done","text":"你好"}\n')
            stdin = io.StringIO()
            def poll(self): return 0
            def wait(self, timeout=None): return 0
        with patch.dict('voice_session.os.environ', {'VI_VOICE_PROVIDER': 'local-cascade'}), \
                patch('voice_session.subprocess.Popen', return_value=Process()) as spawn:
            VoiceSession('COM15', 'http://127.0.0.1:8790',
                         lambda kind, text: events.append((kind, text)), threading.Event()).run()
        self.assertTrue(any(arg.endswith('board-cascade-main.ts') for arg in spawn.call_args.args[0]))
        self.assertIn(('user-text', '你好'), events)
        self.assertIn(('latency', '{"asrMs":80}'), events)

    def setUp(self):
        node = patch('voice_session.shutil.which', return_value='node')
        entry = patch('voice_session.Path.is_file', return_value=True)
        node.start()
        entry.start()
        self.addCleanup(node.stop)
        self.addCleanup(entry.stop)
        constructor = VoiceSession.__init__
        def with_broker(instance, *args, **kwargs):
            kwargs.setdefault('broker', ('tcp://127.0.0.1:12345', 'test-nonce'))
            constructor(instance, *args, **kwargs)
        broker = patch.object(VoiceSession, '__init__', with_broker)
        broker.start()
        self.addCleanup(broker.stop)

    def test_uses_vi_agent_and_forwards_events_without_audio_copies(self):
        events = []
        class Process:
            stdout = io.StringIO('\n'.join(json.dumps(event, ensure_ascii=False) for event in [
                {'type': 'state', 'text': '正在聆听'},
                {'type': 'text', 'text': '你好'},
                {'type': 'done', 'text': '你好'},
            ]) + '\n')
            stdin = io.StringIO()
            def poll(self): return 0
            def wait(self, timeout=None): return 0
        with patch('voice_session.subprocess.Popen', return_value=Process()) as spawn:
            VoiceSession('COM15', 'http://127.0.0.1:8790',
                         lambda kind, text: events.append((kind, text)), threading.Event()).run()
        args = spawn.call_args.args[0]
        self.assertNotIn('--once', args)
        self.assertIn('--json-events', args)
        self.assertNotIn('--text', args)
        self.assertTrue(any(arg.endswith('board-omni-main.ts') for arg in args))
        self.assertEqual(spawn.call_args.kwargs['env']['VI_BOARD_SPEAKER_PORT'], 'COM15')
        self.assertEqual(spawn.call_args.kwargs['env']['VI_BOARD_BROKER_URL'], 'tcp://127.0.0.1:12345')
        self.assertEqual(spawn.call_args.kwargs['env']['VI_BOARD_BROKER_TOKEN'], 'test-nonce')
        self.assertIn(('state', '正在聆听'), events)
        self.assertIn(('text', '你好'), events)
        self.assertIn(('turn-done', '你好'), events)

    def test_speaker_check_uses_text_instead_of_starting_microphone_turn(self):
        class Process:
            stdout = io.StringIO('{"type":"done","text":"你好"}\n')
            stdin = io.StringIO()
            def poll(self): return 0
            def wait(self, timeout=None): return 0
        with patch('voice_session.subprocess.Popen', return_value=Process()) as spawn:
            VoiceSession('COM15', 'http://127.0.0.1:8790', lambda *_: None,
                         threading.Event(), prompt='请说你好').run()
        args = spawn.call_args.args[0]
        self.assertIn('--once', args)
        self.assertEqual(args[args.index('--text') + 1], '请说你好')

    def test_refuses_non_loopback_model_endpoint(self):
        with self.assertRaisesRegex(ValueError, '本机'):
            VoiceSession('COM15', 'http://example.com', lambda *_: None, threading.Event()).run()

    def test_single_microphone_mode_passes_once_without_text(self):
        class Process:
            stdout = io.StringIO('{"type":"done","text":"你好"}\n')
            stdin = io.StringIO()
            def poll(self): return 0
            def wait(self, timeout=None): return 0
        with patch('voice_session.subprocess.Popen', return_value=Process()) as spawn:
            VoiceSession('COM15', 'http://127.0.0.1:8790', lambda *_: None,
                         threading.Event(), once=True).run()
        self.assertIn('--once', spawn.call_args.args[0])
        self.assertNotIn('--text', spawn.call_args.args[0])

    def test_failure_without_done_cannot_be_reported_as_success(self):
        class Process:
            stdout = io.StringIO('model failed\n')
            stdin = io.StringIO()
            def poll(self): return 1
            def wait(self, timeout=None): return 1
        with patch('voice_session.subprocess.Popen', return_value=Process()):
            with self.assertRaisesRegex(RuntimeError, 'model failed'):
                VoiceSession('COM15', 'http://127.0.0.1:8790', lambda *_: None, threading.Event()).run()

    def test_cancel_requests_graceful_stop_before_returning(self):
        stop = threading.Event()
        class Input(io.StringIO):
            contents = ''
            def write(self, text):
                self.contents += text
                return super().write(text)
        class Process:
            stdout = io.StringIO('{"type":"state","text":"listening"}\n')
            stdin = Input()
            code = None
            def poll(self): return self.code
            def wait(self, timeout=None):
                self.code = 0
                return 0
        process = Process()
        with patch('voice_session.subprocess.Popen', return_value=process):
            VoiceSession('COM15', 'http://127.0.0.1:8790',
                         lambda *_: stop.set(), stop).run()
        self.assertEqual(process.stdin.contents, 'stop\n')
        self.assertEqual(process.code, 0)

    def test_cleanup_disconnect_preserves_original_transport_error(self):
        class Process:
            stdout = io.StringIO('\n'.join(json.dumps(event) for event in [
                {'type': 'error', 'text': 'Board frame #8: AUDIO_ERROR write'},
                {'type': 'error', 'text': 'Board speaker bridge exited'},
            ]) + '\n')
            stdin = io.StringIO()
            def poll(self): return 1
            def wait(self, timeout=None): return 1
        with patch('voice_session.subprocess.Popen', return_value=Process()):
            with self.assertRaisesRegex(RuntimeError, 'Board frame #8: AUDIO_ERROR write'):
                VoiceSession('COM15', 'http://127.0.0.1:8790', lambda *_: None,
                             threading.Event()).run()

    def test_live_listening_heartbeats_keep_a_quiet_conversation_open(self):
        events = [{'type': 'turn-start'}]
        events.extend({'type': 'state', 'text': '正在聆听 · 等待讲话'} for _ in range(6))
        events.append({'type': 'done', 'text': '你好'})
        class Process:
            stdout = io.StringIO('\n'.join(json.dumps(event) for event in events) + '\n')
            stdin = io.StringIO()
            def poll(self): return 0
            def wait(self, timeout=None): return 0
        now = iter(range(0, 1000, 10))
        with patch('voice_session.subprocess.Popen', return_value=Process()), \
                patch('voice_session.time.monotonic', side_effect=lambda: next(now)):
            VoiceSession('COM15', 'http://127.0.0.1:8790', lambda *_: None,
                         threading.Event()).run()


if __name__ == '__main__':
    unittest.main()
