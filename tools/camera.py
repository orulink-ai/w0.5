"""Camera task runner; intentionally contains no automatic flash operation."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'tools/camera_facetrack'
FIRMWARE = ROOT / 'firmware/esp32/examples/imx708_usb'
PROJECT = ROOT / '.camera-sdk/imx708-project'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['setup', 'run', 'dev', 'test', 'check-usb',
                                          'focus', 'prepare-firmware', 'test-firmware', 'build-firmware'])
    parser.add_argument('--port', default='COM15')
    parser.add_argument('--source', help='GUI camera source or upstream Git URL/path for prepare-firmware')
    parser.add_argument('--seconds', type=int, default=25, choices=range(1, 61))
    parser.add_argument('--clang', help='Host Clang executable for firmware tests')
    parser.add_argument('--zig', help='Zig executable for firmware tests')
    args = parser.parse_args()
    venv_python = APP / ('.venv/Scripts/python.exe' if os.name == 'nt' else '.venv/bin/python')
    python = str(venv_python) if venv_python.exists() else sys.executable
    cwd = APP
    if args.action == 'setup':
        if os.name != 'nt':
            parser.error('setup.ps1 requires Windows; see the manual Python setup in the English README.')
        command = ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(APP / 'setup.ps1')]
    elif args.action in ('run', 'dev'):
        command = [python, 'app.py', '--autostart', '--source', args.source or f'serial://{args.port}']
        if args.action == 'dev':
            command.append('--watch')
    elif args.action == 'test':
        command = [python, '-m', 'unittest', 'discover', '-s', 'tests', '-v']
    elif args.action == 'check-usb':
        command = [python, 'tools/check_usb.py', '--port', args.port, '--seconds', str(args.seconds)]
    elif args.action == 'focus':
        command = [python, 'tools/calibrate_focus.py', '--port', args.port]
    elif args.action == 'prepare-firmware':
        command = [sys.executable, str(FIRMWARE / 'prepare.py')]
        if args.source:
            command += ['--source', args.source]
        cwd = ROOT
    elif args.action == 'test-firmware':
        source = FIRMWARE / 'overlay/components/esp_cam_sensor_imx/examples/imx708_wifi_video/main/test/run_host_tests.py'
        command = [sys.executable, str(source)]
        if args.clang:
            command += ['--clang', args.clang]
        if args.zig:
            command += ['--zig', args.zig]
        cwd = ROOT
    else:
        idf = os.environ.get('IDF_PATH')
        if not idf or not PROJECT.exists():
            parser.error('Activate ESP-IDF and run prepare-firmware first.')
        command = [sys.executable, str(Path(idf) / 'tools/idf.py'), '-D',
                   'SDKCONFIG_DEFAULTS=sdkconfig.defaults;sdkconfig.board', 'build']
        cwd = PROJECT
    return subprocess.run(command, cwd=cwd).returncode


if __name__ == '__main__':
    raise SystemExit(main())
