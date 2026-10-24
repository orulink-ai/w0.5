"""Dual PWM inputs must never share samples, freshness, or error state."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'encoder_dashboard'))
from telemetry import TelemetryStore


def row(channel, angle=90, state='OK'):
    return f'#ENCODER,1,{channel},{state},{angle},0,460,700,2174'


class DualEncoderTests(unittest.TestCase):
    def setUp(self):
        self.store = TelemetryStore(clock=lambda: 10)
        self.store.set_connection(True, '/dev/test')

    def test_two_angles_and_pins_are_independent(self):
        self.store.consume(row(1, 30), now=10)
        self.store.consume(row(2, 220), now=10)
        state = self.store.snapshot(now=10.1)
        self.assertEqual([x['pin'] for x in state['encoders']], ['PA0', 'PB7'])
        self.assertEqual([x['reading']['angle_deg'] for x in state['encoders']], [30, 220])
        self.assertEqual(state['reading']['angle_deg'], 30, 'legacy control uses encoder 1 only')
        self.assertEqual(state['encoder_mode'], 'dual_diagnostic')
        self.store.consume(row(2, 240), now=10.2)
        state = self.store.snapshot(now=10.3)
        self.assertEqual([x['reading']['angle_deg'] for x in state['encoders']], [30, 240])
        self.assertEqual([x['samples'] for x in state['encoders']], [1, 2])

    def test_stale_and_invalid_are_local_to_one_channel(self):
        self.store.consume(row(1, 30), now=10)
        self.store.consume(row(2, 220), now=11.1)
        state = self.store.snapshot(now=11.2)
        self.assertEqual([x['signal'] for x in state['encoders']], ['stale', 'valid'])
        self.assertIsNone(state['encoders'][0]['reading']['angle_deg'])
        self.store.consume(row(1, 'nan', 'NO_PWM_OR_INVALID'), now=11.3)
        state = self.store.snapshot(now=11.4)
        self.assertEqual([x['signal'] for x in state['encoders']], ['invalid', 'valid'])

    def test_legacy_only_updates_first_and_reconnect_clears_both(self):
        self.store.consume('OK,90,0,460,700,2174', now=10)
        state = self.store.snapshot(now=10.1)
        self.assertEqual([x['signal'] for x in state['encoders']], ['valid', 'waiting'])
        self.assertEqual(state['encoder_mode'], 'single')
        self.store.consume(row(2, 220), now=10)
        self.store.set_connection(False)
        self.assertEqual([x['signal'] for x in self.store.snapshot()['encoders']], ['disconnected'] * 2)
        self.store.set_connection(True, '/dev/new')
        self.assertEqual([x['samples'] for x in self.store.snapshot()['encoders']], [0, 0])

    def test_bad_channel_version_and_values_do_not_create_samples(self):
        for line in (row(0), row(3), row(2).replace('#ENCODER,1,', '#ENCODER,2,'),
                     row(2, 'nan'), row(2, 360), row(2) + ',extra'):
            self.store.consume(line)
        self.assertEqual(self.store.snapshot()['samples'], 0)
        self.assertEqual([x['samples'] for x in self.store.snapshot()['encoders']], [0, 0])

    def test_diagnostic_frames_revoke_previous_motor_capability(self):
        self.store.consume('#FOC_STATUS,3,READY,STOP,0,1,0,1,0,0,0,120,-90,90,NONE,0,0,NONE,1')
        self.assertTrue(self.store.snapshot()['closed_loop']['supported'])
        self.store.consume(row(2, 220))
        state = self.store.snapshot()
        self.assertFalse(state['closed_loop']['supported'])
        self.assertFalse(state['enable']['available'])
        self.assertFalse(state['motor']['available'])
        self.assertFalse(state['control']['available'])
        self.assertEqual(state['encoder_mode'], 'dual_diagnostic')

    def test_auxiliary_encoder_preserves_single_motor_control_and_feedback(self):
        self.store.consume('OK,30,0,460,700,2174')
        self.store.consume('#FOC_STATUS,4,READY,STOP,0,1,0,1,0,0,0,120,-90,90,NONE,0,0,NONE,1')
        before = self.store.snapshot()['closed_loop']
        self.store.consume(row(2, 220).replace('#ENCODER,', '#ENCODER_AUX,'))
        state = self.store.snapshot()
        self.assertEqual(state['closed_loop'], before)
        self.assertTrue(state['closed_loop']['available'])
        self.assertEqual(state['reading']['angle_deg'], 30)
        self.assertEqual(state['encoder_mode'], 'single_with_aux')
        self.assertEqual([x['reading']['angle_deg'] for x in state['encoders']], [30, 220])
        self.store.consume(row(2, 'nan', 'NO_PWM_OR_INVALID').replace('#ENCODER,', '#ENCODER_AUX,'))
        state = self.store.snapshot()
        self.assertEqual(state['signal'], 'valid')
        self.assertEqual(state['encoders'][1]['signal'], 'invalid')
        self.assertEqual(state['closed_loop'], before)
        self.store.consume(row(1, 100).replace('#ENCODER,', '#ENCODER_AUX,'))
        self.assertEqual(self.store.snapshot()['reading']['angle_deg'], 30,
                         'Auxiliary telemetry must not impersonate the motor feedback')


if __name__ == '__main__':
    unittest.main()
