"""Create a separate, pinned SDK checkout and install the camera source overlay.

Does not build, flash, change an existing checkout, or touch a serial port.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess

UPSTREAM = 'https://github.com/mushBrainDave/esp32-p4-imx-camera.git'
REVISION = '9a3f8ca28e93526e0854ba45ad3b461b33ef2dac'
EXAMPLE = Path('components/esp_cam_sensor_imx/examples/imx708_wifi_video')


def main():
    here = Path(__file__).resolve().parent
    root = here.parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default=UPSTREAM, help='Upstream URL or local Git clone')
    parser.add_argument('--destination', type=Path, default=root / '.camera-sdk/imx708')
    args = parser.parse_args()
    target = args.destination.resolve()
    project = target.with_name(target.name + '-project')
    if target.exists() or project.exists():
        parser.error(f'Destination already exists; choose new directories: {target}, {project}')
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['git', 'clone', '--no-checkout', '--no-hardlinks', args.source, str(target)], check=True)
    subprocess.run(['git', '-C', str(target), 'checkout', '--detach', REVISION], check=True)
    for source in (here / 'overlay').rglob('*'):
        if source.is_file():
            destination = target / source.relative_to(here / 'overlay')
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    # Keep managed_components out of the deeply nested upstream example on Windows.
    shutil.copytree(target / EXAMPLE, project,
                    ignore=shutil.ignore_patterns('build', 'managed_components', 'sdkconfig', 'sdkconfig.old'))
    component = target / 'components/esp_cam_sensor_imx'
    relative = Path(os.path.relpath(component, project)).as_posix()
    cmake = project / 'CMakeLists.txt'
    original = 'set(imx_component_root "${CMAKE_CURRENT_LIST_DIR}/../..")'
    contents = cmake.read_text(encoding='utf-8')
    if contents.count(original) != 1:
        raise RuntimeError('Unexpected upstream CMake layout')
    cmake.write_text(contents.replace(original, f'set(imx_component_root "${{CMAKE_CURRENT_LIST_DIR}}/{relative}")'), encoding='utf-8')
    manifest = project / 'main/idf_component.yml'
    main_relative = Path(os.path.relpath(component, manifest.parent)).as_posix()
    manifest.write_text(manifest.read_text(encoding='utf-8').replace('override_path: "../../.."',
                        f'override_path: "{main_relative}"'), encoding='utf-8')
    lock = (here / 'dependencies.lock').read_text(encoding='utf-8')
    (project / 'dependencies.lock').write_text(lock.replace('path: ../..\n', f'path: {relative}\n'), encoding='utf-8')
    shutil.copy2(here / 'board.defaults', project / 'sdkconfig.board')
    print(f'Ready: {project}\nNo firmware has been flashed.')


if __name__ == '__main__':
    main()
