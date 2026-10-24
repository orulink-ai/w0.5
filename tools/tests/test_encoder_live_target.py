"""Live target edits bind to an existing lease; these tests never use hardware."""
import sys
from pathlib import Path
import unittest
import os
import threading
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'encoder_dashboard'))
from closed_loop_commands import ClosedLoopChannel, parse_status, validate_foc
from commands import CommandError
import test_encoder_closed_loop as base_tests


def frame(state='READY', mode='STOP', last=0, run=0, remaining=0,
          version=4, enabled=0, sensor=1, target=0):
    return (f'#FOC_STATUS,{version},{state},{mode},{last},1,{enabled},{sensor},0,{target},0,'
            f'120,-90,90,NONE,{run},{remaining},NONE,1')


class LiveTargetTests(unittest.TestCase):
    def setUp(self):
        self.now = 10
        self.channel = ClosedLoopChannel(clock=lambda: self.now)
        self.channel.reset(True)

    def own_position(self, mode='POSITION', version=4):
        c = self.channel
        c.consume(frame(version=version))
        payload = ({'action': 'position', 'target_deg': 0, 'speed_rpm': 3}
                   if mode == 'POSITION' else {'action': 'velocity', 'rpm': 3})
        run, _ = c.begin(payload, True)
        c.consume(f'#FOC_ACK,{run},{payload["action"].upper()}')
        c.consume(frame('RUNNING', mode, run, run, 1500, version, 1))
        return run

    def test_validation_preserves_exact_integer_run_id(self):
        payload = {'action': 'target', 'run_id': 2147483647, 'target_deg': 12.5}
        self.assertEqual(validate_foc(payload), payload)
        for value in (True, 1.0, '1', 0, -1, 2147483648, float('nan')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_foc({**payload, 'run_id': value})
        for value in (True, None, '3', float('nan'), 181):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_foc({**payload, 'target_deg': value})
        with self.assertRaises(ValueError):
            validate_foc({**payload, 'speed_rpm': 3})

    def test_v4_feedback_is_parsed_without_losing_protection(self):
        state = parse_status(frame())
        self.assertEqual(state['protocol_version'], 4)
        self.assertTrue(state['overspeed_enabled'])
        for message in (frame().rsplit(',', 1)[0], frame() + ',extra', frame().rsplit(',', 1)[0] + ',2'):
            self.assertIsNone(parse_status(message))

    def test_target_ack_keeps_run_and_never_renews_lease(self):
        c = self.channel
        run = self.own_position()
        self.now += .2
        request, packet = c.begin({'action': 'target', 'run_id': run, 'target_deg': 35.5}, True)
        self.assertGreater(request, run)
        self.assertEqual(packet, f'FOC,{request},TARGET,{run},35.5\n'.encode())
        c.consume(f'#FOC_ACK,{request},TARGET')
        self.assertFalse(c.wait(request, .01)['settling'])
        self.assertEqual(c.snapshot()['owned_run_id'], run)
        self.assertEqual(c.heartbeat(run), f'FOC,{run},KEEPALIVE\n'.encode())
        # A second edit can follow the matching ACK before the next status frame.
        request2, _ = c.begin({'action': 'target', 'run_id': run, 'target_deg': -20}, True)
        c.consume(f'#FOC_ACK,{request2},TARGET')
        self.now += 1.3
        self.assertIsNone(c.snapshot()['owned_run_id'], 'TARGET never refreshes the host lease')

    def test_only_owned_live_position_can_retarget(self):
        c = self.channel
        run = self.own_position()
        for payload, valid in (({'action': 'target', 'run_id': run + 1, 'target_deg': 0}, True),
                               ({'action': 'target', 'run_id': run, 'target_deg': 91}, True),
                               ({'action': 'target', 'run_id': run, 'target_deg': 0}, False)):
            with self.assertRaises((CommandError, ValueError)):
                c.begin(payload, valid)
        c.clear_owner()
        with self.assertRaises(CommandError):
            c.begin({'action': 'target', 'run_id': run, 'target_deg': 0}, True)

    def test_old_protocol_velocity_stale_and_stopped_reject(self):
        for mode, version in (('VELOCITY', 4), ('POSITION', 3)):
            self.setUp()
            run = self.own_position(mode, version)
            with self.assertRaises(CommandError):
                self.channel.begin({'action': 'target', 'run_id': run, 'target_deg': 0}, True)
        self.setUp()
        run = self.own_position()
        self.now += 1.6
        with self.assertRaises(CommandError):
            self.channel.begin({'action': 'target', 'run_id': run, 'target_deg': 0}, True)
        self.setUp()
        self.channel.consume(frame())
        with self.assertRaises(CommandError):
            self.channel.begin({'action': 'target', 'run_id': 1, 'target_deg': 0}, True)

    def test_stop_preempts_target_and_late_ack_never_owns(self):
        c = self.channel
        run = self.own_position()
        request, _ = c.begin({'action': 'target', 'run_id': run, 'target_deg': 30}, True)
        stop, _ = c.begin({'action': 'stop'}, True)
        c.consume(f'#FOC_ACK,{request},TARGET')
        self.assertEqual(c.snapshot()['command']['id'], stop)
        self.assertIsNone(c.snapshot()['owned_run_id'])
        c.consume(f'#FOC_ACK,{stop},STOP')
        c.consume(frame(last=stop))
        with self.assertRaises(CommandError):
            c.begin({'action': 'target', 'run_id': run, 'target_deg': 45}, True)


class LiveTargetHTTPTests(unittest.TestCase):
    setUp = base_tests.HTTPTests.setUp
    tearDown = base_tests.HTTPTests.tearDown
    post = base_tests.HTTPTests.post
    packet = base_tests.HTTPTests.packet

    def test_live_wire_and_stop_preemption_with_real_serial_transport(self):
        self.store.consume(frame())
        started = []
        thread = threading.Thread(target=lambda: started.append(self.post(
            {'action': 'position', 'target_deg': 0, 'speed_rpm': 3})))
        thread.start()
        run = int(self.packet()[1])
        os.write(self.master, (f'#FOC_ACK,{run},POSITION\n' +
                              frame('RUNNING', 'POSITION', run, run, 1500, enabled=1) + '\n').encode())
        thread.join(2)
        self.assertEqual(started[0][0], 200)
        edited = []
        thread = threading.Thread(target=lambda: edited.append(self.post(
            {'action': 'target', 'run_id': run, 'target_deg': 24.5})))
        thread.start()
        packet = self.packet()
        edit = int(packet[1])
        self.assertEqual(packet[2:], ['TARGET', str(run), '24.5'])
        self.assertFalse(edited, 'HTTP waits for matching MCU acknowledgement')
        stopped = []
        stop = threading.Thread(target=lambda: stopped.append(self.post({'action': 'stop'})))
        stop.start()
        stop_id = int(self.packet()[1])
        os.write(self.master, (f'#FOC_ACK,{edit},TARGET\n#FOC_ACK,{stop_id},STOP\n' +
                              frame(last=stop_id) + '\n').encode())
        thread.join(2)
        stop.join(2)
        self.assertEqual(edited[0][0], 409)
        self.assertEqual(stopped[0][0], 200)
        self.assertIsNone(self.store.closed_loop.snapshot()['owned_run_id'])
        with urlopen(self.url + '/components/live-position.js', timeout=2) as response:
            self.assertEqual(response.status, 200)


if __name__ == '__main__':
    unittest.main()
