"""Camera/voice ownership transitions without Tk windows or real devices."""
import threading
import time
import unittest
from unittest.mock import Mock, patch

from app import App
from face_gate import FaceGate


def app_state(source='serial://COM15', running=True):
    state = App.__new__(App)
    state.closing = False
    state.camera = Mock()
    state.camera.get.return_value = source
    state.worker = Mock()
    state.worker.is_alive.return_value = running
    state.voice = Mock()
    state.voice.busy = False
    state.voice.request.return_value = True
    state.voice.enabled.get.return_value = True
    state.voice.face_trigger.get.return_value = True
    state.voice.mode = 'continuous'
    state.voice.stop_event = threading.Event()
    state.stop_event = threading.Event()
    state.face_gate = FaceGate()
    state.voice_ready_at = 0
    state.last_frame_at = time.monotonic()
    state.face_ids = [1]
    state.face_gate.present_since = time.monotonic() - 2
    state.start_button = Mock()
    state.stop_button = Mock()
    state.status = Mock()
    return state


class AppVoiceTests(unittest.TestCase):
    def setUp(self):
        broker = patch('app.get_audio_broker', return_value=('tcp://127.0.0.1:12345', 'test-nonce'))
        broker.start()
        self.addCleanup(broker.stop)

    def test_face_turn_keeps_camera_running_and_uses_shared_connection(self):
        state = app_state()
        state.request_voice_turn(automatic=True)
        state.voice.request.assert_called_once_with('COM15', ('tcp://127.0.0.1:12345', 'test-nonce'))
        self.assertFalse(state.stop_event.is_set())
        self.assertFalse(state.face_gate.armed)
        self.assertFalse(state.face_gate.update(True, 0))
        self.assertFalse(state.face_gate.update(True, 2))

    def test_manual_turn_without_camera_does_not_open_second_serial_owner(self):
        state = app_state(running=False)
        state.request_voice_turn()
        state.voice.request.assert_not_called()
        self.assertIn('请先启动', state.voice.status.set.call_args.args[0])

    def test_manual_request_cannot_bypass_missing_face(self):
        state = app_state()
        state.face_ids = []
        state.request_voice_turn()
        state.voice.request.assert_not_called()
        self.assertIn('麦克风关闭', state.voice.status.set.call_args.args[0])

    def test_stale_or_unstable_face_cannot_start_microphone(self):
        for stale in (True, False):
            with self.subTest(stale=stale):
                state = app_state()
                if stale:
                    state.last_frame_at -= 2
                else:
                    state.face_gate.present_since = time.monotonic()
                state.request_voice_turn(automatic=True)
                state.voice.request.assert_not_called()

    def test_speaker_check_does_not_require_a_face_or_open_microphone(self):
        state = app_state()
        state.face_ids = []
        state.request_voice_turn(prompt='请说你好')
        state.voice.request.assert_called_once_with(
            'COM15', ('tcp://127.0.0.1:12345', 'test-nonce'), prompt='请说你好')
        self.assertFalse(state.stop_event.is_set())

    def test_stale_camera_cancels_all_stages_in_continuous_mode(self):
        for phase in ('starting', 'listening', 'speaking', 'thinking'):
            with self.subTest(phase=phase):
                state = app_state()
                state.voice.busy = True
                state.voice.requires_face = True
                state.voice.phase = phase
                state.last_frame_at -= 2
                state.enforce_face_presence(time.monotonic())
                state.voice.cancel.assert_called_once()

    def test_face_departure_stops_every_stage_only_in_continuous_mode(self):
        for mode in ('single', 'continuous'):
            for phase in ('starting', 'listening', 'speaking', 'thinking'):
                with self.subTest(mode=mode, phase=phase):
                    state = app_state()
                    state.voice.mode = mode
                    state.voice.busy = state.voice.requires_face = True
                    state.voice.phase = phase
                    state.face_ids = []
                    state.face_gate.absent_since = time.monotonic() - 1
                    state.enforce_face_presence(time.monotonic())
                    self.assertEqual(state.voice.cancel.called, mode == 'continuous')

    def test_speaker_test_is_not_cancelled_when_no_face_is_present(self):
        state = app_state()
        state.voice.busy = True
        state.voice.requires_face = False
        state.voice.phase = 'starting'
        state.last_frame_at -= 2
        state.enforce_face_presence(time.monotonic())
        state.voice.cancel.assert_not_called()

    def test_disabled_face_trigger_never_interrupts_camera(self):
        state = app_state()
        state.voice.face_trigger.get.return_value = False
        state.request_voice_turn(automatic=True)
        state.voice.request.assert_not_called()
        self.assertFalse(state.stop_event.is_set())

    def test_non_board_camera_source_cannot_open_an_arbitrary_serial_port(self):
        state = app_state('0')
        state.request_voice_turn()
        state.voice.request.assert_not_called()
        self.assertFalse(state.stop_event.is_set())
        self.assertIn('serial://COM15', state.voice.status.set.call_args.args[0])

    def test_camera_start_is_rejected_while_audio_owns_usb(self):
        state = app_state(running=False)
        state.voice.busy = True
        state.start()
        state.worker.is_alive.assert_not_called()

    def test_closing_cancels_voice_and_stops_camera(self):
        state = app_state()
        state.setup_dialog = None
        state.close()
        self.assertTrue(state.closing)
        state.voice.cancel.assert_called_once()
        self.assertTrue(state.stop_event.is_set())


if __name__ == '__main__':
    unittest.main()
