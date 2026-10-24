"""Concurrent camera/audio lifecycle; no device or model service is opened."""
import queue
import threading
import unittest
from unittest.mock import Mock, patch

from voice_panel import VoicePanel


def panel():
    result = VoicePanel.__new__(VoicePanel)
    result.events = queue.Queue()
    result.worker = None
    result.mouth_provider = None
    result.stop_event = threading.Event()
    result.pending = None
    result.in_turn = False
    result.finished = False
    result.failed = False
    result.phase = 'idle'
    result.turn_id = None
    result.started_at = result.updated_at = None
    result.input_seconds = result.error = None
    result.answer_text = ''
    result.mode = 'continuous'
    result.mode_label = Mock()
    result.enabled = Mock()
    result.endpoint = Mock()
    result.endpoint.get.return_value = 'http://127.0.0.1:8790'
    result.status = Mock()
    result.reply = Mock()
    result.once_button = Mock()
    result.cancel_button = Mock()
    result.endpoint_entry = Mock()
    return result


class VoicePanelTests(unittest.TestCase):
    def test_voice_starts_while_camera_keeps_running(self):
        view = panel()
        release = threading.Event()
        with patch('voice_panel.VoiceSession') as session:
            session.return_value.run.side_effect = lambda: release.wait(1)
            broker = ('tcp://127.0.0.1:12345', 'test-nonce')
            self.assertTrue(view.request('COM15', broker))
            self.assertIsNone(view.poll(camera_alive=True))
            self.assertFalse(view.request('COM15', broker))
            self.assertTrue(view.busy)
            release.set()
            view.worker.join(timeout=1)
            self.assertTrue(view.poll(camera_alive=True))
        session.assert_called_once()
        self.assertEqual(session.call_args.kwargs['broker'], broker)
        self.assertFalse(view.busy)

    def test_cancel_pending_turn_never_opens_audio(self):
        view = panel()
        with patch('voice_panel.VoiceSession') as session:
            view.request('COM15', ('tcp://127.0.0.1:12345', 'test-nonce'))
            view.cancel()
            self.assertTrue(view.poll(camera_alive=True))
            session.assert_not_called()
        self.assertFalse(view.busy)

    def test_speaker_check_does_not_enable_automatic_microphone(self):
        view = panel()
        view.request('COM15', ('tcp://127.0.0.1:12345', 'test-nonce'), prompt='你好')
        self.assertFalse(view.requires_face)
        view.enabled.set.assert_not_called()
        view.cancel()
        view.poll(camera_alive=True)

    def test_model_failure_remains_visible_with_camera_still_running(self):
        view = panel()
        release = threading.Event()
        with patch('voice_panel.VoiceSession') as session:
            def fail():
                release.wait(1)
                raise RuntimeError('model not ready')
            session.return_value.run.side_effect = fail
            view.request('COM15', ('tcp://127.0.0.1:12345', 'test-nonce'))
            view.poll(camera_alive=True)
            release.set()
            view.worker.join(timeout=1)
            self.assertTrue(view.poll(camera_alive=True))
        self.assertIn('model not ready', view.status.set.call_args.args[0])
        self.assertFalse(view.busy)

    def test_done_event_does_not_release_camera_before_voice_thread_exits(self):
        view = panel()
        view.in_turn = True
        view.worker = Mock()
        view.worker.is_alive.return_value = True
        view.events.put(('done', ''))
        self.assertIsNone(view.poll(camera_alive=True))
        self.assertTrue(view.busy)
        view.worker.is_alive.return_value = False
        self.assertTrue(view.poll(camera_alive=True))
        self.assertFalse(view.busy)

    def test_completed_reply_keeps_session_and_next_recording_gets_a_new_turn(self):
        view = panel()
        view.request('COM15', ('tcp://127.0.0.1:12345', 'test-nonce'))
        view.pending = None
        original = view.turn_id
        view.events.put(('text', '第一轮回复'))
        view.events.put(('turn-done', '第一轮回复'))
        view.events.put(('turn-start', ''))
        view.events.put(('state', '正在聆听 · 连续会话'))
        self.assertIsNone(view.poll(camera_alive=True))
        self.assertTrue(view.busy)
        self.assertTrue(view.reply_complete)
        self.assertEqual(view.answer_text, '第一轮回复')
        self.assertEqual(view.turn_id, original)
        view.events.put(('state', '录音完成 1.20 秒'))
        view.poll(camera_alive=True)
        self.assertNotEqual(view.turn_id, original)
        self.assertFalse(view.reply_complete)
        self.assertEqual(view.answer_text, '')

    def test_cleanup_disconnect_does_not_hide_the_original_firmware_error(self):
        view = panel()
        view.events.put(('error', 'AUDIO_ERROR invalid_pcm'))
        view.events.put(('error', 'Board speaker bridge exited'))
        view.poll(camera_alive=True)
        self.assertEqual(view.error, 'AUDIO_ERROR invalid_pcm')
        self.assertIn('invalid_pcm', view.status.set.call_args.args[0])

    def test_single_mode_launches_exactly_one_microphone_round(self):
        view = panel()
        view.set_mode('single')
        release = threading.Event()
        with patch('voice_panel.VoiceSession') as session:
            session.return_value.run.side_effect = lambda: release.wait(1)
            view.request('COM15', ('tcp://127.0.0.1:12345', 'test-nonce'))
            view.poll(camera_alive=True)
            release.set()
            view.worker.join(timeout=1)
            view.poll(camera_alive=True)
        self.assertTrue(session.call_args.kwargs['once'])

    def test_changing_mode_cancels_the_owned_conversation(self):
        view = panel()
        view.request('COM15', ('tcp://127.0.0.1:12345', 'test-nonce'))
        self.assertTrue(view.set_mode('single'))
        self.assertTrue(view.stop_event.is_set())
        self.assertEqual(view.cancel_reason, '对话模式已切换')
        with self.assertRaises(ValueError):
            view.set_mode('unknown')


if __name__ == '__main__':
    unittest.main()
