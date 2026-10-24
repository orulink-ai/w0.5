"""Execute the firmware's portable C logic; needs host Clang/LLD or Zig.

No ESP hardware, firmware flashing, camera images or third-party Python packages.
"""
import argparse
import ctypes
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--clang', default=shutil.which('clang'))
    parser.add_argument('--zig', help='Use zig cc as the native host C compiler')
    args = parser.parse_args()
    if not args.clang and not args.zig:
        parser.error('Supply --clang (host compiler, not ESP-only clang) or --zig.')
    clang = Path(args.clang).resolve() if args.clang else None
    source = Path(__file__).with_name('live_transport_host_test.c')
    with tempfile.TemporaryDirectory(prefix='imx-live-test-') as directory:
        out = Path(directory)
        compiler = [str(Path(args.zig).resolve()), 'cc'] if args.zig else [str(clang)]
        common = compiler + ['-std=c11', '-Wall', '-Wextra', '-Werror',
                  '-I', str(source.parent.parent)]
        if sys.platform == 'win32' and not args.zig:
            obj, dll = out/'test.obj', out/'test.dll'
            subprocess.run(common + ['--target=x86_64-pc-windows-msvc',
                '-ffreestanding', '-fno-stack-protector', '-c', str(source), '-o', str(obj)], check=True)
            subprocess.run([str(clang.with_name('lld.exe')), '-flavor', 'link',
                '/dll', '/noentry', '/nodefaultlib', '/out:'+str(dll), str(obj)], check=True)
            library = ctypes.CDLL(str(dll))
            try:
                failure = library.run_tests()
            finally:
                # Windows cannot remove a DLL until its module is unloaded.
                import _ctypes
                _ctypes.FreeLibrary(library._handle)
            if failure:
                raise RuntimeError(f'C assertion failed at line {failure}')
        else:
            executable = out/('test.exe' if sys.platform == 'win32' else 'test')
            subprocess.run(common + [str(source), '-o', str(executable)], check=True)
            subprocess.run([str(executable)], check=True)
    print('PASS: partial writes, shared deadline, blocked peer, zero/error writes, IDR recovery and PTS wrap')


if __name__ == '__main__':
    main()
