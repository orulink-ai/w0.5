"""FOC protocol tests: no connected hardware and no motor is commanded."""
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
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'encoder_dashboard'))
from commands import CommandError
from closed_loop_commands import ClosedLoopChannel, parse_status, validate_foc
from server import SerialReader, make_server
from telemetry import TelemetryStore


def status(state='READY', mode='STOP', last=0, calibrated=1, enabled=0,
           sensor=1, position=0, target=0, rpm=0, zero=120, lower=-90, upper=90, fault='NONE',
           version=3, run_id=None, remaining=None, reason='NONE', overspeed=1):
    base = f'#FOC_STATUS,{version},{state},{mode},{last},{calibrated},{enabled},{sensor},{position},{target},{rpm},{zero},{lower},{upper},{fault}'
    active = state in ('CALIBRATING','RUNNING')
    if version == 1: return base
    run_id = last if run_id is None and active else (0 if run_id is None else run_id)
    remaining = (1500 if active else 0) if remaining is None else remaining
    extension = f',{overspeed}' if version == 3 and overspeed is not None else ''
    return f'{base},{run_id},{remaining},{reason}{extension}'


class ValidationTests(unittest.TestCase):
    def test_overspeed_switch_validation_and_feedback(self):
        for enabled in (True, False):
            payload={'action':'overspeed','enabled':enabled}
            self.assertEqual(validate_foc(payload),payload)
        for enabled in (0, 1, 'false', None, [], float('nan')):
            with self.assertRaises(ValueError): validate_foc({'action':'overspeed','enabled':enabled})
        self.assertTrue(parse_status(status())['overspeed_enabled'])
        self.assertFalse(parse_status(status(overspeed=0))['overspeed_enabled'])
        self.assertIsNone(parse_status(status(overspeed=None))['overspeed_enabled'])
        for value in ('true', 2, -1, ''):
            self.assertIsNone(parse_status(status(overspeed=value)))

    def test_actions_and_numeric_boundaries(self):
        for payload in ({'action':'calibrate'}, {'action':'zero'}, {'action':'stop'},
                        {'action':'limits','min_deg':-180,'max_deg':180},
                        {'action':'limits','min_deg':0,'max_deg':10},
                        {'action':'position','target_deg':-180,'speed_rpm':1},
                        {'action':'velocity','rpm':-.1},
                        {'action':'position','target_deg':0,'speed_rpm':.1},
                        {'action':'position','target_deg':30,'speed_rpm':10},
                        {'action':'velocity','rpm':10}, {'action':'velocity','rpm':-10}):
            self.assertEqual(validate_foc(payload), payload)
        bad = [None, [], True, {}, {'action':'START'}, {'action':'stop','extra':0},
               {'action':'position'}, {'action':'velocity','rpm':0},
               {'action':'velocity','rpm':10.01}, {'action':'velocity','rpm':-10.01},
               {'action':'velocity','rpm':.09}, {'action':'velocity','rpm':-.09}, {'action':'limits','min_deg':1,'max_deg':90},
               {'action':'limits','min_deg':-4,'max_deg':4},
               {'action':'sweep','min_deg':0,'max_deg':4,'rpm':1},
               {'action':'sweep','min_deg':0,'max_deg':5,'rpm':-1},
               {'action':'position','target_deg':0,'speed_rpm':10.01},
               {'action':'position','target_deg':0,'speed_rpm':.09},
               {'action':'position','target_deg':0,'speed_rpm':-.1}]
        for value in (True, '10', None, [], {}, float('nan'), float('inf'), -float('inf'), 10**500):
            bad.append({'action':'position','target_deg':value,'speed_rpm':1})
        for payload in bad:
            with self.subTest(payload=payload), self.assertRaises(ValueError): validate_foc(payload)

    def test_status_shape_finite_flags_and_versions(self):
        self.assertEqual(parse_status(status())['state'], 'READY')
        for line in (status().replace(',3,READY', ',5,READY'), status(calibrated=2), status(sensor='true'), status(run_id=5), status(remaining=1501),
                     status(reason='bad'), status('RUNNING','POSITION',last=5,enabled=0),
                     status(position='nan'), status(rpm='inf'), status(zero=360), status(lower=10),
                     status().replace('READY','BOGUS'), status(mode='JOG'), status(last=-1),
                     status(last=2147483648), status()+',extra'):
            with self.subTest(line=line): self.assertIsNone(parse_status(line))

    def test_fault_codes_are_bounded_protocol_tokens(self):
        for fault in ('NONE', 'SENSOR_LOST', 'OUTPUT_FAULT_2'):
            self.assertIsNotNone(parse_status(status(fault=fault)))
        for fault in ('', 'low_voltage', 'FAULT\x00', 'FAULT\n', 'A' * 33, '故障'):
            with self.subTest(fault=fault):
                self.assertIsNone(parse_status(status(fault=fault)))


class ChannelTests(unittest.TestCase):
    def setUp(self):
        self.now = 10
        self.channel = ClosedLoopChannel(clock=lambda:self.now)
        self.channel.reset(True)

    def test_manual_reset_stays_stopped_and_waits_for_status(self):
        c = self.channel
        c.consume(status('FAULT', fault='OVERSPEED', reason='FAULT'))
        request_id, packet = c.begin({'action':'reset'}, True)
        self.assertEqual(packet, f'FOC,{request_id},RESET\n'.encode())
        c.consume(f'#FOC_ACK,{request_id},RESET')
        self.assertEqual(c.wait(request_id,.01)['state'], 'FAULT')
        self.assertIsNone(c.snapshot()['owned_run_id'])
        with self.assertRaises(CommandError):
            c.begin({'action':'position','target_deg':0,'speed_rpm':1}, True)
        c.consume(status(last=request_id, reason='USER_STOP'))
        self.assertEqual(c.snapshot()['state'], 'READY')
        self.assertFalse(c.snapshot()['enabled'])
        _, packet = c.begin({'action':'position','target_deg':0,'speed_rpm':1}, True)
        self.assertIn(b'START,POSITION', packet)

    def test_switch_needs_supported_stopped_feedback_and_ack_is_not_state(self):
        c=self.channel;c.consume(status())
        request_id,packet=c.begin({'action':'overspeed','enabled':False},True)
        self.assertEqual(packet,f'FOC,{request_id},OVERSPEED,0\n'.encode())
        c.consume(f'#FOC_ACK,{request_id},OVERSPEED')
        self.assertTrue(c.wait(request_id,.01)['overspeed_enabled'])
        self.assertIsNone(c.snapshot()['owned_run_id'])
        c.consume(status(last=request_id,overspeed=0))
        self.assertFalse(c.snapshot()['overspeed_enabled'])
        for message in (status('RUNNING','POSITION',last=5,enabled=1),
                        status('FAULT',fault='SENSOR_INVALID'),status(overspeed=None)):
            other=ClosedLoopChannel();other.reset(True);other.consume(message)
            with self.assertRaises(CommandError):other.begin({'action':'overspeed','enabled':False},True)
        other=ClosedLoopChannel();other.reset(True);other.consume(status('FAULT',fault='OVERSPEED'))
        other.begin({'action':'overspeed','enabled':False},True)

    def test_reset_rejects_other_faults_stale_feedback_and_enabled_driver(self):
        for message in (status(), status('FAULT',fault='SENSOR_INVALID'),
                        status('FAULT',fault='OVERSPEED',enabled=1),
                        status('FAULT',fault='OVERSPEED',sensor=0),
                        status('FAULT',fault='OVERSPEED',version=2)):
            c = ClosedLoopChannel(); c.reset(True); c.consume(message)
            with self.subTest(message=message), self.assertRaises(CommandError):
                c.begin({'action':'reset'}, True)
        self.channel.consume(status('FAULT',fault='OVERSPEED'))
        self.now += 2
        with self.assertRaises(CommandError): self.channel.begin({'action':'reset'}, True)

    def test_calibration_ack_not_completion_and_boot_does_not_start(self):
        c = self.channel
        c.consume(status('UNCALIBRATED', calibrated=0))
        request_id, packet = c.begin({'action':'calibrate'}, True)
        self.assertEqual(packet, f'FOC,{request_id},CALIBRATE\n'.encode())
        c.consume(f'#FOC_ACK,{request_id},ZERO')
        self.assertEqual(c.snapshot()['command']['status'], 'pending')
        c.consume(f'#FOC_ACK,{request_id},CALIBRATE')
        self.assertEqual(c.wait(request_id,.01)['state'], 'UNCALIBRATED')
        with self.assertRaises(CommandError): c.begin({'action':'position','target_deg':0,'speed_rpm':1},True)
        c.consume(status('CALIBRATING', last=request_id,calibrated=0,enabled=1))
        with self.assertRaises(CommandError): c.begin({'action':'zero'},True)
        c.consume(status(last=request_id))
        self.assertTrue(c.snapshot()['calibrated'])
        request_id, packet = c.begin({'action':'position','target_deg':45,'speed_rpm':1},True)
        self.assertEqual(packet,f'FOC,{request_id},START,POSITION,45,1\n'.encode())
        c.consume(f'#FOC_ACK,{request_id},POSITION')
        self.assertNotEqual(c.wait(request_id,.01)['state'],'RUNNING')
        c.consume(status('RUNNING','POSITION',request_id,enabled=1,target=45))
        self.assertEqual(c.snapshot()['state'],'RUNNING')
        c.reset(False); c.reset(True)
        self.assertFalse(c.snapshot()['supported'])
        self.assertEqual(c.snapshot()['command']['status'],'idle')

    def test_strict_readiness_and_limits(self):
        for message in (status('UNCALIBRATED',calibrated=0), status('CALIBRATING',last=1,calibrated=0,enabled=1),
                        status('RUNNING','VELOCITY',last=1,enabled=1), status('FAULT',fault='SENSOR'),
                        status(enabled=1),status(sensor=0),status(calibrated=0)):
            self.channel.consume(message)
            with self.assertRaises(CommandError): self.channel.begin({'action':'position','target_deg':0,'speed_rpm':1},True)
        self.channel.consume(status())
        with self.assertRaises(CommandError): self.channel.begin({'action':'velocity','rpm':3},False)
        for payload in ({'action':'position','target_deg':91,'speed_rpm':1},
                        {'action':'spring','center_deg':-91,'stiffness':.5},
                        {'action':'sweep','min_deg':-100,'max_deg':30,'rpm':3}):
            with self.assertRaises(ValueError): self.channel.begin(payload,True)
        self.channel.consume(status(position=50))
        with self.assertRaises(CommandError): self.channel.begin({'action':'limits','min_deg':-30,'max_deg':30},True)
        self.now += 2
        with self.assertRaises(CommandError): self.channel.begin({'action':'zero'},True)
        self.assertNotIn('state',self.channel.snapshot())

    def test_stop_preempts_pending_even_stale_invalid_fault(self):
        c = self.channel; c.consume(status())
        first,_ = c.begin({'action':'velocity','rpm':-3},True)
        self.now += 5
        stop,packet = c.begin({'action':'stop'},False)
        self.assertGreater(stop, first)
        self.assertEqual(packet,f'FOC,{stop},STOP\n'.encode())
        with self.assertRaises(CommandError): c.wait(first,.01)
        c.consume(f'#FOC_ACK,{first},VELOCITY')
        self.assertEqual(c.snapshot()['command']['status'],'pending')
        c.consume(f'#FOC_ACK,{stop},STOP'); c.wait(stop,.01)
        c.consume(status('FAULT',last=stop,fault='SENSOR',sensor=0))
        self.assertIsNone(c.snapshot()['relative_deg'])
        stop,_=c.begin({'action':'stop'},False)
        c.consume(f'#FOC_ACK,{stop},STOP'); c.wait(stop,.01)

    def test_all_packets_nack_timeout_reset_and_highwater(self):
        actions = [({'action':'zero'},'ZERO'),
                   ({'action':'limits','min_deg':-45,'max_deg':45},'LIMITS,-45,45'),
                   ({'action':'velocity','rpm':3},'START,VELOCITY,3'),
                   ({'action':'position','target_deg':30,'speed_rpm':1},'START,POSITION,30,1')]
        for payload,suffix in actions:
            c=ClosedLoopChannel(); c.reset(True); c.consume(status(last=100))
            request_id,packet=c.begin(payload,True)
            self.assertGreater(request_id,100)
            self.assertEqual(packet,f'FOC,{request_id},{suffix}\n'.encode())
            c.consume(f'#FOC_NACK,{request_id},INVALID_STATE')
            with self.assertRaises(CommandError): c.wait(request_id,.01)
        c=self.channel; c.consume(status())
        request_id,_=c.begin({'action':'zero'},True)
        with self.assertRaises(CommandError): c.wait(request_id,.001)
        c.consume(f'#FOC_ACK,{request_id},ZERO')
        self.assertEqual(c.snapshot()['command']['status'],'timeout')
        c.consume(status(last=request_id))
        request_id,_=c.begin({'action':'zero'},True)
        c.reset(False)
        with self.assertRaises(CommandError): c.wait(request_id,.01)
        c.reset(True); c.consume(status())
        self.assertEqual(c.snapshot()['state'],'READY')
        c._next_id=0x80000000
        with self.assertRaises(CommandError): c.begin({'action':'zero'},True)
        stop,_=c.begin({'action':'stop'},False)
        self.assertEqual(stop,0x7fffffff)

    def test_new_capability_is_latched_blocks_old_routes_and_clears_old_controls(self):
        store=TelemetryStore(); store.set_connection(True,'test')
        store.consume('#CONTROL,1,DISABLED,0,-1')
        self.assertTrue(store.snapshot()['control']['available'])
        store.consume(status('UNCALIBRATED',calibrated=0))
        self.assertFalse(store.snapshot()['control']['available'])
        reader=SerialReader(store)
        for method,value in ((reader.send_enable,False),(reader.send_motor,'stop'),(reader.send_target,0)):
            with self.assertRaisesRegex(CommandError,'闭环'): method(value)


class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.channel = ClosedLoopChannel(clock=lambda:self.now)
        self.channel.reset(True)
        self.channel.consume(status())

    def start(self):
        request_id,_=self.channel.begin({'action':'position','target_deg':30,'speed_rpm':1},True)
        return request_id

    def test_v3_required_and_removed_actions_rejected(self):
        c=self.channel
        for version in (1, 2):
            c.consume(status(version=version))
            self.assertEqual(c.snapshot()['protocol_version'],version)
            with self.assertRaises(CommandError): self.start()
            with self.assertRaises(CommandError): c.heartbeat(20)
        for action in ('spring','sweep'):
            with self.assertRaises(ValueError): c.begin({'action':action},True)
        with self.assertRaises(ValueError):
            c.begin({'action':'position','target_deg':0,'speed_rpm':1,'stiffness':1.2},True)
        c.begin({'action':'stop'},False)

    def test_owner_only_matching_ack_and_keepalive_has_no_ack_or_id_side_effects(self):
        c=self.channel; run=self.start()
        with self.assertRaises(CommandError): c.heartbeat(run)
        c.consume(f'#FOC_ACK,{run},VELOCITY')
        with self.assertRaises(CommandError): c.heartbeat(run)
        c.consume(f'#FOC_ACK,{run},POSITION'); c.wait(run,.01)
        before=c.snapshot(); self.assertEqual(before['owned_run_id'],run)
        self.assertIsNone(before['max_run_ms']);self.assertEqual(before['lease_timeout_ms'],1500)
        for bad in (True,False,0,-1,'1',None,run+1,2147483648):
            with self.assertRaises(CommandError): c.heartbeat(bad)
        self.assertEqual(c.heartbeat(run),f'FOC,{run},KEEPALIVE\n'.encode())
        self.now += .3; c.heartbeat_written(run)
        after=c.snapshot()
        self.assertEqual(after['command'],before['command'])
        self.assertEqual(after['last_id'],before['last_id'])
        self.assertEqual(after['settling'],before['settling'])
        self.assertEqual(after['owned_run_id'],run)

    def test_terminal_ordering_old_status_and_no_acquire_from_mcu(self):
        c=self.channel; run=self.start()
        c.consume(status('RUNNING','POSITION',run,enabled=1))
        self.assertIsNone(c.snapshot()['owned_run_id'],'Observed RUNNING before ACK is not ownership')
        c.consume(f'#FOC_ACK,{run},POSITION'); self.assertEqual(c.snapshot()['owned_run_id'],run)
        c.consume(status(last=run-1))
        self.assertEqual(c.snapshot()['owned_run_id'],run,'Queued older terminal cannot clear new accepted owner')
        c.consume(status(last=run)); self.assertIsNone(c.snapshot()['owned_run_id'])
        with self.assertRaises(CommandError): c.heartbeat(run)
        other=ClosedLoopChannel();other.reset(True);other.consume(status('RUNNING','POSITION',last=run,enabled=1))
        with self.assertRaises(CommandError): other.heartbeat(run)
        c.consume(status()); run=self.start()
        c.consume(status(last=run))
        c.consume(f'#FOC_ACK,{run},POSITION')
        self.assertIsNone(c.snapshot()['owned_run_id'],'Terminal before delayed ACK cannot restore ownership')

    def test_expiry_stop_disconnect_failure_and_different_run_revoke_owner(self):
        c=self.channel;run=self.start();c.consume(f'#FOC_ACK,{run},POSITION')
        self.now += 1.5
        with self.assertRaises(CommandError): c.heartbeat(run)
        with self.assertRaises(CommandError): c.heartbeat_written(run)
        self.assertIsNone(c.snapshot()['owned_run_id'])
        c.consume(status(last=run));run=self.start();c.consume(f'#FOC_ACK,{run},POSITION')
        c.consume(status('RUNNING','VELOCITY',last=run+1,enabled=1))
        self.assertIsNone(c.snapshot()['owned_run_id'])
        c.consume(status(last=run));run=self.start();c.consume(f'#FOC_ACK,{run},POSITION')
        c.begin({'action':'stop'},False)
        self.assertIsNone(c.snapshot()['owned_run_id'])
        c.reset(True);c.consume(status(last=run));run=self.start();c.consume(f'#FOC_ACK,{run},POSITION')
        c.reset(False);self.assertIsNone(c.snapshot()['owned_run_id'])

    def test_boot_revokes_active_and_pending_but_ack_then_old_initial_frame_is_not_boot(self):
        c=self.channel;run=self.start();c.consume(f'#FOC_ACK,{run},POSITION')
        c.consume(status(last=0))
        self.assertEqual(c.snapshot()['owned_run_id'],run)
        c.consume(status('RUNNING','POSITION',last=run,enabled=1))
        c.consume(status('UNCALIBRATED',calibrated=0))
        self.assertIsNone(c.snapshot()['owned_run_id'])
        with self.assertRaises(CommandError):c.heartbeat(run)
        c.consume(status(last=10));run=self.start()
        c.consume(status('UNCALIBRATED',calibrated=0))
        with self.assertRaises(CommandError):c.wait(run,.01)
        c.consume(f'#FOC_ACK,{run},POSITION')
        self.assertIsNone(c.snapshot()['owned_run_id'])

    def test_feedback_freshness_remaining_and_bounded_first_state_grace(self):
        c=self.channel;run=self.start();c.consume(f'#FOC_ACK,{run},POSITION')
        self.now += 1.0;c.heartbeat_written(run)
        self.now += .6
        with self.assertRaises(CommandError):c.heartbeat(run)
        c.consume(status(last=run));run=self.start();c.consume(f'#FOC_ACK,{run},POSITION')
        self.now += 1.0;c.consume(status())
        c.heartbeat_written(run)
        self.now += .6;c.consume(status())
        with self.assertRaises(CommandError):c.heartbeat(run)
        c.consume(status(last=run));run=self.start();c.consume(f'#FOC_ACK,{run},POSITION')
        c.consume(status('RUNNING','POSITION',last=run,enabled=1,remaining=0))
        with self.assertRaises(CommandError):c.heartbeat(run)

    def test_calibration_lease_and_transport_write_error(self):
        from unittest.mock import Mock
        store=TelemetryStore();store.set_connection(True,'fake')
        store.consume(status('UNCALIBRATED',calibrated=0))
        run,_=store.closed_loop.begin({'action':'calibrate'},True)
        store.closed_loop.consume(f'#FOC_ACK,{run},CALIBRATE')
        self.assertEqual(store.closed_loop.snapshot()['owned_run_id'],run)
        reader=SerialReader(store);reader._serial=Mock(is_open=True)
        reader._serial.write.side_effect=OSError('disconnected')
        with self.assertRaises(CommandError):reader.send_foc_heartbeat({'run_id':run})
        self.assertIsNone(store.closed_loop.snapshot()['owned_run_id'])
        reader._serial.write.assert_called_once_with(f'FOC,{run},KEEPALIVE\n'.encode())


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.master,self.slave=pty.openpty(); self.device=os.ttyname(self.slave)
        self.store=TelemetryStore(); self.reader=SerialReader(self.store)
        with patch.object(SerialReader,'ports',return_value=[{'device':self.device}]): self.reader.connect(self.device)
        self.server=make_server(self.reader,self.store,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'
        os.write(self.master,(status()+'\nOK,120,0,460,700,2174\n').encode())
        deadline=time.monotonic()+1
        while time.monotonic()<deadline and self.store.snapshot()['signal']!='valid': time.sleep(.01)

    def tearDown(self):
        self.reader.disconnect();self.server.shutdown();self.server.server_close()
        os.close(self.master);os.close(self.slave)

    def post(self,payload,path='/api/foc',origin=None):
        headers={'Content-Type':'application/json'}
        if origin: headers['Origin']=origin
        request=Request(self.url+path,data=json.dumps(payload).encode(),headers=headers)
        try:
            with urlopen(request,timeout=3) as response: return response.status,json.load(response)
        except HTTPError as error: return error.code,json.load(error)

    def packet(self):
        self.assertTrue(select.select([self.master],[],[],1)[0])
        return os.read(self.master,512).decode().strip().split(',')

    def test_http_manual_reset_never_sends_start_or_keepalive(self):
        self.store.consume(status('FAULT',fault='OVERSPEED',reason='FAULT'))
        result=[]
        request=threading.Thread(target=lambda:result.append(self.post({'action':'reset'})))
        request.start()
        packet=self.packet()
        self.assertEqual(packet[0],'FOC')
        self.assertEqual(packet[2:],['RESET'])
        request_id=int(packet[1])
        os.write(self.master,(f'#FOC_ACK,{request_id},RESET\n'+
                             status(last=request_id,reason='USER_STOP')+'\n').encode())
        request.join(2)
        self.assertFalse(request.is_alive())
        self.assertEqual(result[0][0],200)
        self.assertIsNone(self.store.closed_loop.snapshot()['owned_run_id'])
        self.assertFalse(select.select([self.master],[],[],.05)[0])

    def test_http_switch_ack_does_not_change_reported_protection_or_start(self):
        result=[]
        request=threading.Thread(target=lambda:result.append(self.post({'action':'overspeed','enabled':False})))
        request.start();packet=self.packet()
        self.assertEqual(packet[2:],['OVERSPEED','0'])
        request_id=int(packet[1])
        os.write(self.master,f'#FOC_ACK,{request_id},OVERSPEED\n'.encode())
        request.join(2);self.assertFalse(request.is_alive())
        self.assertEqual(result[0][0],200)
        self.assertTrue(self.store.closed_loop.snapshot()['overspeed_enabled'])
        self.assertIsNone(self.store.closed_loop.snapshot()['owned_run_id'])
        self.assertFalse(select.select([self.master],[],[],.05)[0])

    def test_http_waits_for_matching_ack_and_stop_preempts_without_replay(self):
        result=[]
        first=threading.Thread(target=lambda:result.append(self.post({'action':'velocity','rpm':3})))
        first.start(); packet=self.packet()
        self.assertEqual(packet[0],'FOC');self.assertEqual(packet[2:],['START','VELOCITY','3'])
        self.assertEqual(result,[])
        stopped=[]
        stop=threading.Thread(target=lambda:stopped.append(self.post({'action':'stop'})))
        stop.start(); stop_packet=self.packet()
        self.assertEqual(stop_packet[2:],['STOP'])
        os.write(self.master,f'#FOC_ACK,{stop_packet[1]},STOP\n'.encode())
        first.join(2);stop.join(2)
        self.assertEqual(result[0][0],409)
        self.assertEqual(stopped[0][0],200)
        self.assertNotEqual(stopped[0][1]['closed_loop']['state'],'RUNNING')
        self.assertFalse(select.select([self.master],[],[],.05)[0], 'No implicit retry/start')

    def test_heartbeat_http_is_owned_fire_and_forget_and_never_changes_command(self):
        result=[]
        request=threading.Thread(target=lambda:result.append(self.post({'action':'velocity','rpm':1})))
        request.start();packet=self.packet();run=int(packet[1])
        self.assertEqual(self.post({'run_id':run},'/api/foc/heartbeat')[0],409)
        os.write(self.master,f'#FOC_ACK,{run},VELOCITY\n'.encode())
        request.join(2);self.assertEqual(result[0][0],200)
        before=self.store.closed_loop.snapshot()['command']
        response=self.post({'run_id':run},'/api/foc/heartbeat')
        self.assertEqual(response,(200,{'ok':True,'run_id':run}))
        self.assertEqual(self.packet(),['FOC',str(run),'KEEPALIVE'])
        self.assertEqual(self.store.closed_loop.snapshot()['command'],before)
        for payload in ({'run_id':True},{'run_id':run,'extra':1},{'run_id':0},{'run_id':run+1}):
            self.assertEqual(self.post(payload,'/api/foc/heartbeat')[0],409)
        self.assertFalse(select.select([self.master],[],[],.05)[0])

    def test_http_static_validation_origin_and_legacy_isolation(self):
        for payload in ({'action':'position','target_deg':True},{'action':'stop','bad':1},
                        {'action':'velocity','rpm':float('nan')}):
            self.assertEqual(self.post(payload)[0],400)
        self.assertEqual(self.post({'action':'stop'},origin='https://example.com')[0],403)
        self.assertEqual(self.post({'enabled':True},'/api/enable')[0],409)
        self.assertEqual(self.post({'action':'jog'},'/api/motor')[0],409)
        self.assertFalse(select.select([self.master],[],[],.05)[0])
        for path in ('/api.js','/components/closed-loop.js','/components/legacy-controls.js'):
            with urlopen(self.url+path,timeout=2) as response:
                self.assertEqual(response.status,200)
                self.assertIn('javascript',response.headers['Content-Type'])
        with self.assertRaises(HTTPError): urlopen(self.url+'/components/../server.py')


if __name__=='__main__': unittest.main()
