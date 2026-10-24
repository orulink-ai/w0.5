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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "encoder_dashboard"))
from server import SerialReader, make_server  # noqa: E402
from telemetry import TelemetryStore  # noqa: E402


def wait_until(condition):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for reader")


class ReaderTests(unittest.TestCase):
    def test_partial_lines_disconnect_and_serial_loss(self):
        master, slave = pty.openpty()
        store = TelemetryStore()
        reader = SerialReader(store)
        device = os.ttyname(slave)
        reader.ports = lambda: [{"device": device, "description": "test PTY"}]
        thread_errors = []
        previous_hook = threading.excepthook
        threading.excepthook = lambda args: thread_errors.append(args.exc_value)
        try:
            reader.connect(device)
            os.write(master, b"OK,90,0,920,")
            self.assertEqual(store.snapshot()["samples"], 0)
            os.write(master, b"300,1087\r\n")
            wait_until(lambda: store.snapshot()["samples"] == 1)
            self.assertEqual(store.snapshot()["reading"]["angle_deg"], 90)
            reader.disconnect()
            self.assertEqual(store.snapshot()["signal"], "disconnected")
            reader.connect(device)
            os.close(master)
            master = None
            wait_until(lambda: not store.snapshot()["connected"])
            self.assertIn("串口连接中断", store.snapshot()["error"])
        finally:
            reader.disconnect()
            if master is not None:
                os.close(master)
            os.close(slave)
            threading.excepthook = previous_hook
        self.assertEqual(thread_errors, [])


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.store = TelemetryStore()
        self.reader = SerialReader(self.store)
        self.server = make_server(self.reader, self.store, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def post(self, path, body, origin=None, content_type="application/json"):
        headers = {"Content-Type": content_type}
        if origin:
            headers["Origin"] = origin
        return urlopen(Request(self.base + path, data=body, headers=headers), timeout=2)

    def test_static_and_state(self):
        with urlopen(self.base + "/") as response:
            self.assertIn("AS5600".encode(), response.read())
        with urlopen(self.base + "/api/state") as response:
            self.assertEqual(json.load(response)["signal"], "disconnected")
        with self.assertRaises(HTTPError) as error:
            urlopen(self.base + "/../server.py")
        self.assertEqual(error.exception.code, 404)

    def test_bad_requests_do_not_connect_or_crash(self):
        for body, origin, content_type, status in [
            (b"{}", "https://example.com", "application/json", 403),
            (b"{}", None, "text/plain", 415),
            (b"not-json", None, "application/json", 400),
            (b"[]", None, "application/json", 400),
            (b'{"port":"/not/a/serial/device"}', None, "application/json", 400),
        ]:
            with self.subTest(body=body, origin=origin):
                with self.assertRaises(HTTPError) as error:
                    self.post("/api/connect", body, origin, content_type)
                self.assertEqual(error.exception.code, status)
        self.assertFalse(self.store.snapshot()["connected"])

    def test_target_validation_and_enable_requires_explicit_boolean(self):
        for angle in (None, 18, 360, True, 90.0, "90\nARM"):
            with self.subTest(angle=angle):
                with self.assertRaises(HTTPError) as error:
                    self.post("/api/target", json.dumps({"angle_deg": angle}).encode())
                self.assertEqual(error.exception.code, 400)
        with self.assertRaises(HTTPError) as error:
            self.post("/api/target", b'{"angle_deg":90}')
        self.assertEqual(error.exception.code, 409)
        with self.assertRaises(HTTPError) as error:
            self.post("/api/enable", b'{}')
        self.assertEqual(error.exception.code, 400)
        with self.assertRaises(HTTPError) as error:
            self.post("/api/target", b'{"angle_deg":90}', origin="https://example.com")
        self.assertEqual(error.exception.code, 403)

    def test_four_targets_travel_over_serial_and_require_matching_ack(self):
        master, slave = pty.openpty()
        device = os.ttyname(slave)
        self.reader.ports = lambda: [{"device": device, "description": "test PTY"}]
        try:
            self.reader.connect(device)
            os.write(master, b"#CONTROL,1,DISABLED,0,-1\nOK,60,0,460,400,2175\n")
            wait_until(lambda: self.store.snapshot()["control"]["available"])
            for angle in (0, 90, 180, 270):
                responses, failures = [], []
                def send():
                    try:
                        with self.post("/api/target", json.dumps({"angle_deg": angle}).encode()) as response:
                            responses.append(json.load(response))
                    except Exception as error:
                        failures.append(error)
                sender = threading.Thread(target=send)
                sender.start()
                self.assertTrue(select.select([master], [], [], 1)[0])
                packet = os.read(master, 256).decode().strip().split(",")
                self.assertEqual(packet[0], "TARGET")
                self.assertEqual(int(packet[2]), angle)
                self.assertTrue(sender.is_alive(), "HTTP cannot report success before ACK")
                os.write(master, f"#TARGET_ACK,{packet[1]},STAGED,{angle}\n".encode())
                sender.join(timeout=2)
                self.assertFalse(sender.is_alive())
                self.assertEqual(failures, [])
                self.assertEqual(responses[0]["control"]["target_deg"], angle)
                self.assertFalse(responses[0]["control"]["motor_enabled"])
                self.assertEqual(responses[0]["control"]["command"]["status"], "accepted")
            # A write with no firmware ACK must be a timeout, not success.
            self.reader.store.control.consume("#CONTROL,1,DISABLED,0,-1")
            self.store.consume("OK,60,0,460,400,2175")
            with self.assertRaises(HTTPError) as error:
                self.post("/api/target", b'{"angle_deg":90}')
            self.assertEqual(error.exception.code, 409)
            self.assertEqual(self.store.snapshot()["control"]["command"]["status"], "timeout")
        finally:
            self.reader.disconnect()
            os.close(master)
            os.close(slave)

    def test_sse_serializes_invalid_data_without_nan(self):
        self.store.set_connection(True, "/dev/test")
        self.store.consume("NO_PWM_OR_INVALID,nan,nan,nan,13,45")
        with urlopen(self.base + "/api/events", timeout=2) as response:
            line = response.readline().decode()
            self.assertTrue(line.startswith("data: "))
            state = json.loads(line[6:])
            self.assertEqual(state["signal"], "invalid")
            self.assertIsNone(state["reading"]["angle_deg"])


if __name__ == "__main__":
    unittest.main()
