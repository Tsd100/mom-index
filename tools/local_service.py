"""本机预览/每日采集入口。网页仅监听本机；发布数据位于忽略的output目录。"""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def configure_environment():
    private = ROOT / 'src' / 'data'
    public = ROOT / 'output' / 'local-service' / 'public'
    os.environ['MOM_INDEX_DATA_DIR'] = str(private)
    os.environ['MOM_INDEX_FRONTEND_DATA_DIR'] = str(public)
    os.environ['PYTHONPATH'] = str(ROOT / 'src') + os.pathsep + os.environ.get('PYTHONPATH', '')
    sys.path.insert(0, str(ROOT / 'src'))
    return private, public


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('role', choices=('web', 'collector'))
    args = parser.parse_args()
    private, public = configure_environment()
    from mom_index.nas_runtime import collector, make_web_server
    if args.role == 'web':
        make_web_server(public, host='127.0.0.1', port=8503).serve_forever()
    else:
        collector(private, public, os.environ.get('COLLECTION_TIME', '17:00'), run_on_startup=True)


if __name__ == '__main__':
    main()
