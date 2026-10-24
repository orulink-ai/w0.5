"""Prepared voice owns no active turn until the face gate releases it."""
import os
import threading
import unittest
from unittest.mock import patch

from tests.test_voice_panel import panel
from robot_console_server import validate_command


class VoicePrewarmTests(unittest.TestCase):
    def test_prepared_worker_is_reused_without_a_second_spawn_at_face_trigger(self):
        view = panel()
        broker = ('tcp://127.0.0.1:12345', 'test-nonce')
        release = threading.Event()
        with patch.dict(os.environ, VI_VOICE_PROVIDER='local-cascade'), patch('voice_panel.VoiceSession') as session:
            session.return_value.run.side_effect = lambda: release.wait(2)
            view.prepare('COM15', broker)
            self.assertFalse(view.busy)
            thread = view.prepared['thread']
            activation = view.prepared['activation']
            self.assertFalse(activation[0].is_set())
            view.face_since = 1000
            self.assertTrue(view.request('COM15', broker))
            self.assertIs(view.worker, thread)
            self.assertTrue(activation[0].is_set())
            self.assertEqual(activation[1]['since'], 1000)
            view.finish_when_absent()
            self.assertIs(view.finish_event, session.call_args.kwargs['finish_event'])
            self.assertTrue(view.finish_event.is_set())
            self.assertFalse(view.stop_event.is_set())
            view.poll(True)
            session.assert_called_once()
            view.cancel()
            release.set()
            thread.join(1)
            view.poll(True)

    def test_stop_or_camera_loss_disposes_standby_without_opening_a_turn(self):
        view = panel()
        release = threading.Event()
        with patch.dict(os.environ, VI_VOICE_PROVIDER='local-cascade'), patch('voice_panel.VoiceSession') as session:
            session.return_value.run.side_effect = lambda: release.wait(2)
            view.prepare('COM15', ('tcp://127.0.0.1:12345', 'test-nonce'))
            standby = view.prepared
            view.prepare('COM15', None)
            self.assertTrue(standby['stop'].is_set())
            self.assertFalse(view.busy)
            release.set()
            standby['thread'].join(1)
            view.poll(False)
            self.assertIsNone(view.prepared)

    def test_input_options_are_strict_and_cannot_bypass_face_or_change_output_volume(self):
        self.assertEqual(validate_command({'action': 'configure', 'prelisten': True, 'inputGainDb': 6})['inputGainDb'], 6)
        for field, values in [('prelisten', [1, 'true', None]), ('inputGainDb', [True, -1, 13, '6', 1.5])]:
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    validate_command({'action': 'configure', field: value})


if __name__ == '__main__':
    unittest.main()
