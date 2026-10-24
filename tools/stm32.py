#!/usr/bin/env python3
"""Build/test/upload the isolated STM32 encoder example from any directory."""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "firmware/stm32/examples/encoder_read"


def run(*command: str) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "upload", "monitor", "test", "dashboard"))
    parser.add_argument("--port", help="Serial device path (required for monitor)")
    parser.add_argument("--env", default="g431_as5600_usb",
                        choices=("g431_as5600_usb", "g431_as5600_uart", "g431_pwm_loopback",
                                 "g431_motor_jog", "g431_enable_uart", "g431_motor_gpio", "g431_closed_loop",
                                 "g431_dual_encoder", "g431_dual_motor"))
    args = parser.parse_args()
    if args.action == "dashboard":
        python = ROOT / ".venv/bin/python"
        if not python.is_file():
            parser.error("Create .venv and install tools/requirements-stm32.txt first")
        command = [str(python), str(ROOT / "tools/encoder_dashboard/server.py")]
        if args.port:
            command.extend(("--serial-port", args.port))
        run(*command)
        return
    if args.action == "test":
        for suite in ("as5600_pwm", "angle_target", "motor_jog", "enable_control", "motor_gpio", "closed_loop"):
            source = ROOT / "firmware/stm32/tests" / suite
            build = source / "build"
            run("cmake", "-S", str(source), "-B", str(build), "-G", "Ninja")
            run("cmake", "--build", str(build))
            run("ctest", "--test-dir", str(build), "--output-on-failure")
        return
    pio = ROOT / ".venv/bin/pio"
    if not pio.is_file():
        parser.error("PlatformIO missing: create .venv and install tools/requirements-stm32.txt")
    if args.action == "monitor":
        if not args.port:
            parser.error("monitor requires --port, e.g. /dev/cu.usbserial-...")
        run(str(pio), "device", "monitor", "--port", args.port, "--baud", "115200")
    else:
        command = [str(pio), "run", "-d", str(PROJECT), "-e", args.env]
        if args.action == "upload":
            command.extend(("--target", "upload"))
        run(*command)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        sys.exit(error.returncode)
