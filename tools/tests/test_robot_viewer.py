"""Offline model delivery must work without exposing arbitrary local files."""
import hashlib
import json
import math
import struct
from pathlib import Path
import sys
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "encoder_dashboard"))
from server import SerialReader, make_server
from telemetry import TelemetryStore


class RobotViewerTests(unittest.TestCase):
    def setUp(self):
        store = TelemetryStore()
        self.server = make_server(SerialReader(store), store, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_viewer_dependencies_are_served_locally(self):
        for path, mime in [("/robot-viewer.js", "application/javascript"),
                           ("/robot-viewer.css", "text/css"),
                           ("/model-loader.mjs", "application/javascript"),
                           ("/robot-finishes.mjs", "application/javascript"),
                           ("/robot-eyes.js", "application/javascript"),
                           ("/robot-desktop.js", "application/javascript"),
                           ("/robot-warm-desktop.js", "application/javascript"),
                           ("/robot-scene-config.mjs", "application/javascript"),
                           ("/robot-replica.js", "application/javascript"),
                           ("/robot-rig.js", "application/javascript"),
                           ("/robot-motion.mjs", "application/javascript"),
                           ("/robot-motion-clock.mjs", "application/javascript"),
                           ("/vendor/three/RoomEnvironment.js", "application/javascript"),
                           ("/models/robot-screen.json", "application/json"),
                           ("/models/robot-screen.bin", "application/octet-stream"),
                           ("/vendor/three/three.module.min.js", "application/javascript"),
                           ("/vendor/three/three.core.min.js", "application/javascript"),
                           ("/vendor/three/OrbitControls.js", "application/javascript"),
                           ("/models/robot.json", "application/json"),
                           ("/models/robot.bin", "application/octet-stream")]:
            with self.subTest(path=path), urlopen(self.base + path) as response:
                self.assertEqual(response.headers.get_content_type(), mime)
                self.assertGreater(len(response.read()), 100)

    def test_only_allowlisted_files_are_readable(self):
        for path in ["/models/../../server.py", "/vendor/three/../../../server.py", "/models/missing.bin"]:
            with self.subTest(path=path), self.assertRaises(HTTPError) as error:
                urlopen(self.base + path)
            self.assertEqual(error.exception.code, 404)

    def test_mesh_buffers_and_motor_references_are_valid(self):
        for stem, source in [("robot", "robot-camera.step"), ("robot-screen", "robot-screen.step")]:
            with self.subTest(model=stem):
                self.check_model(stem, source)

    def check_model(self, stem, source_name):
        root = Path(__file__).resolve().parents[1] / "encoder_dashboard/static/models"
        model = json.loads((root / f"{stem}.json").read_text())
        binary = (root / f"{stem}.bin").read_bytes()
        source = Path(__file__).resolve().parents[2] / "hardware/models" / source_name
        self.assertEqual(model["sourceSha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(model["units"], "mm")
        self.assertEqual(len(model["joints"]), 2)
        for mesh in model["meshes"]:
            for key in ["position", "normal", "index"]:
                accessor = mesh[key]
                self.assertLessEqual(accessor["offset"] + accessor["count"] * 4, len(binary))
                self.assertEqual(accessor["offset"] % 4, 0)
            positions = mesh["position"]
            normals = mesh["normal"]
            indices = mesh["index"]
            self.assertEqual(positions["count"] % 3, 0)
            self.assertEqual(normals["count"], positions["count"])
            self.assertEqual(indices["count"] % 3, 0)
            points = struct.unpack_from(f'<{positions["count"]}f', binary, positions["offset"])
            self.assertTrue(all(math.isfinite(value) for value in points))
            triangles = struct.unpack_from(f'<{indices["count"]}I', binary, indices["offset"])
            self.assertLess(max(triangles), positions["count"] // 3)
        for joint in model["joints"]:
            self.assertTrue(joint["meshes"])
            self.assertTrue(all(0 <= i < len(model["meshes"]) for i in joint["meshes"]))
