"""Motor channel isolation over one shared UART, preserving motor 1 API."""
import sys
from pathlib import Path
from unittest.mock import Mock
import unittest
import json
import os
import pty
import select
import threading
import time
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'encoder_dashboard'))
from telemetry import TelemetryStore
from server import SerialReader, make_server
from commands import CommandError


def status(motor, *, phase='READY', run=0, last=0, enabled=0):
    prefix = '#FOC_STATUS' if motor == 1 else '#FOC2_STATUS'
    mode = 'POSITION' if phase == 'RUNNING' else 'STOP'
    remaining = 1500 if run else 0
    return f'{prefix},4,{phase},{mode},{last},1,{enabled},1,0,0,0,120,-90,90,NONE,{run},{remaining},NONE,1'


class DualMotorTests(unittest.TestCase):
    def setUp(self):
        self.store = TelemetryStore(clock=lambda:10)
        self.store.set_connection(True, 'test')
        self.store.consume('OK,30,0,460,700,2174')
        self.store.consume('#ENCODER_AUX,1,2,OK,220,0,460,700,2174')
        self.store.consume(status(1))
        self.store.consume(status(2))

    def test_two_motor_statuses_and_ack_ids_are_independent(self):
        self.assertEqual(self.store.snapshot()['encoder_mode'], 'dual_control')
        one, two = self.store.foc_channel(1), self.store.foc_channel(2)
        one._next_id = two._next_id = 42
        for channel in (one,two): channel.begin({'action':'position','target_deg':10,'speed_rpm':1},True)
        self.store.consume('#FOC2_ACK,42,POSITION')
        self.assertEqual(one.snapshot()['command']['status'], 'pending')
        self.assertEqual(two.snapshot()['command']['status'], 'accepted')
        self.store.consume('#FOC_ACK,42,POSITION')
        for motor in (1,2): self.store.consume(status(motor, phase='RUNNING',run=42,last=42,enabled=1))
        self.assertEqual(one.snapshot()['owned_run_id'],42)
        self.assertEqual(two.snapshot()['owned_run_id'],42)
        two.begin({'action':'stop'},False)
        self.assertEqual(one.snapshot()['owned_run_id'],42)
        self.assertIsNone(two.snapshot()['owned_run_id'])
        self.assertEqual(one.heartbeat(42),b'FOC,42,KEEPALIVE\n')

    def test_selected_feedback_and_serial_prefix(self):
        reader = SerialReader(self.store)
        reader._serial = Mock(is_open=True)
        def write(packet):
            prefix, request, *_ = packet.decode().strip().split(',')
            self.assertEqual(prefix,'FOC2')
            self.store.consume(f'#FOC2_ACK,{request},STOP')
            return len(packet)
        reader._serial.write.side_effect = write
        reader.send_foc({'action':'stop'}, motor_id=2)
        self.assertEqual(self.store.foc_channel(1).snapshot()['command']['status'],'idle')
        self.store.consume('#ENCODER_AUX,1,2,NO_PWM_OR_INVALID,nan,nan,nan,0,0')
        with self.assertRaises(CommandError):
            reader.send_foc({'action':'position','target_deg':0,'speed_rpm':1},motor_id=2)
        self.assertTrue(self.store.foc_channel(1).snapshot()['available'])
        self.store.foc_channel(1).begin({'action':'position','target_deg':0,'speed_rpm':1}, True)

    def test_disconnect_clears_both_and_invalid_channel_is_rejected(self):
        self.store.set_connection(False)
        for motor in (1,2): self.assertFalse(self.store.foc_channel(motor).snapshot()['available'])
        for motor in (0,3,True,'2'):
            with self.assertRaises(ValueError): self.store.foc_channel(motor)

    def test_motor_two_heartbeat_never_renews_motor_one(self):
        reader=SerialReader(self.store)
        reader._serial=Mock(is_open=True,write=lambda packet:len(packet))
        channel=self.store.foc_channel(2)
        run,_=channel.begin({'action':'position','target_deg':10,'speed_rpm':1},True)
        self.store.consume(f'#FOC2_ACK,{run},POSITION')
        self.store.consume(status(2,phase='RUNNING',run=run,last=run,enabled=1))
        packets=[]
        reader._serial.write=lambda packet:packets.append(packet) or len(packet)
        self.assertEqual(reader.send_foc_heartbeat({'run_id':run},motor_id=2),{'ok':True,'run_id':run})
        self.assertEqual(packets,[f'FOC2,{run},KEEPALIVE\n'.encode()])
        with self.assertRaises(CommandError):reader.send_foc_heartbeat({'run_id':run},motor_id=1)
        self.assertEqual(len(packets),1)


class DualMotorHTTPTests(unittest.TestCase):
    def test_second_endpoint_requires_second_ack_even_with_same_request_id(self):
        master,slave=pty.openpty()
        store=TelemetryStore();reader=SerialReader(store)
        device=os.ttyname(slave)
        reader.ports=lambda:[{'device':device}]
        reader.connect(device)
        store.consume(status(1));store.consume(status(2))
        server=make_server(reader,store,0)
        serving=threading.Thread(target=server.serve_forever,daemon=True);serving.start()
        result=[]
        def post():
            request=Request(f'http://127.0.0.1:{server.server_port}/api/foc/2',data=b'{"action":"stop"}',
                            headers={'Content-Type':'application/json'})
            with urlopen(request,timeout=3) as response:result.append(json.load(response))
        sending=threading.Thread(target=post)
        try:
            sending.start()
            self.assertTrue(select.select([master],[],[],1)[0])
            prefix,request_id,action=os.read(master,512).decode().strip().split(',')
            self.assertEqual((prefix,action),('FOC2','STOP'))
            os.write(master,f'#FOC_ACK,{request_id},STOP\n'.encode())
            time.sleep(.03)
            self.assertFalse(result,'First motor ACK cannot complete second motor request')
            os.write(master,f'#FOC2_ACK,{request_id},STOP\n'.encode())
            sending.join(2)
            self.assertFalse(sending.is_alive())
            self.assertEqual(result[0]['motors'][1]['closed_loop']['command']['status'],'accepted')
            self.assertEqual(result[0]['closed_loop']['command']['status'],'idle')
        finally:
            sending.join(3);reader.disconnect();server.shutdown();server.server_close()
            serving.join();os.close(master);os.close(slave)


if __name__ == '__main__': unittest.main()
