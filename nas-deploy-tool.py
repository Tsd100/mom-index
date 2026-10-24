#!/usr/bin/env python3
"""生成宝妈指数 NAS 应用包和 Linux wheels；不打包本地数据、凭据或基础镜像。"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent


def package_source(destination, root=ROOT):
    destination, root = Path(destination), Path(root)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('目标目录非空，请选择新的部署包目录，避免覆盖配置或数据')
    destination.mkdir(parents=True, exist_ok=True)
    source = root / 'src' / 'mom_index'
    for path in sorted(source.rglob('*')):
        relative = path.relative_to(source)
        if not path.is_file() or path.is_symlink() or any(part in ('data', '__pycache__') for part in relative.parts):
            continue
        if path.suffix not in ('.py', '.html', '.js') and path.name != 'LICENSE.chartjs':
            continue
        target = destination / 'src' / 'mom_index' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    for name in ('docker-compose.yml', 'docker/Dockerfile', 'docker/entrypoint.sh',
                 'requirements-nas.txt', '.dockerignore', '.env.example'):
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / name, target)
    shutil.copy2(root / 'docs' / 'nas-deployment.md', destination / '部署说明.md')
    return destination


def download_wheels(destination):
    wheels = Path(destination) / 'offline-deps' / 'wheels'
    wheels.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, '-m', 'pip', 'download', '--python-version', '3.12',
                    '--platform', 'manylinux2014_x86_64', '--only-binary=:all:',
                    '--dest', str(wheels), '-r', str(Path(destination) / 'requirements-nas.txt')], check=True)
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--dry-run', '--ignore-installed',
                    '--no-index', '--find-links', str(wheels), '--python-version', '3.12',
                    '--platform', 'manylinux2014_x86_64', '--only-binary=:all:',
                    '-r', str(Path(destination) / 'requirements-nas.txt')], check=True)


def finalize(destination):
    destination = Path(destination)
    files = {p.relative_to(destination).as_posix(): {'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
                                                  'size': p.stat().st_size}
             for p in sorted(destination.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
    has_wheels = any((destination / 'offline-deps' / 'wheels').glob('*.whl'))
    manifest = {'package_type': 'application_with_linux_wheels' if has_wheels else 'source_only',
                'version': '2026.10.24.3', 'platform': 'linux/amd64',
                'python': '3.12', 'base_image': 'python:3.12-slim-bookworm', 'base_image_included': False,
                'runtime_data_included': False, 'files': files}
    (destination / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    archive = destination.with_suffix('.zip')
    if archive.exists():
        raise FileExistsError(archive)
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
        for path in sorted(destination.rglob('*')):
            if path.is_file():
                output.write(path, path.relative_to(destination).as_posix())
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--source-only', action='store_true', help='只生成源码包，不下载Linux依赖')
    args = parser.parse_args()
    target = args.output or ROOT / 'output' / ('mom-index-nas-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    package_source(target)
    if not args.source_only:
        download_wheels(target)
    archive = finalize(target)
    print(f'应用包：{archive.resolve()}')
    print('未包含本地生产数据、凭据或基础镜像；基础镜像需已存在于NAS。')


if __name__ == '__main__':
    main()
