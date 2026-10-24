"""NAS 的独立网页服务、每日采集调度与运行状态。"""
import argparse
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
from urllib.parse import urlsplit
from urllib.request import urlopen
from uuid import uuid4

from mom_index.market_data import fetch_market
from mom_index.pipeline import run_pipeline, publish_dashboard
from mom_index.provenance import SHANGHAI, now_local

VERSION = '2026.10.24.3'
FRONTEND = Path(__file__).parent / 'frontend'


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.name + '.' + uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {} if default is None else default


def scheduled_today(now, daily):
    hour, minute = (int(part) for part in daily.split(':'))
    return now.astimezone(SHANGHAI).replace(hour=hour, minute=minute, second=0, microsecond=0)


def next_attempt(now, state, daily='17:00', startup=False):
    now = now.astimezone(SHANGHAI)
    today = scheduled_today(now, daily)
    if startup and str(state.get('last_started_at', ''))[:10] != now.date().isoformat():
        return now
    if now >= today:
        scheduled = now if state.get('scheduled_for') != now.date().isoformat() else today + timedelta(days=1)
    else:
        scheduled = today
    retry = state.get('retry_at')
    if retry:
        try:
            scheduled = min(scheduled, max(now, datetime.fromisoformat(retry).astimezone(SHANGHAI)))
        except (ValueError, TypeError):
            pass
    return scheduled


def collect_once(root, public):
    """行情失败仍采集情绪；仅发布管线过滤后的看板。"""
    root, public = Path(root), Path(public)
    result = {'started_at': now_local().isoformat(), 'invocation_id': os.environ.get('MOM_INDEX_INVOCATION_ID'),
              'status': 'completed', 'market': 'ok'}
    try:
        market = fetch_market(root)
        if market.get('failures'):
            result.update(status='partial', market='partial')
    except Exception as error:
        result.update(status='partial', market=type(error).__name__)
        print(f'日线获取失败：{type(error).__name__}；继续情绪采集', flush=True)
    try:
        dashboard = run_pipeline(publish=False)
        publish_dashboard(dashboard, public)
        sectors = (dashboard.get('latest') or {}).get('sectors', {})
        result['valid_sectors'] = sum(s.get('quality', {}).get('status') == 'ok' for s in sectors.values())
        result['total_sectors'] = len(sectors)
        if result['valid_sectors'] != len(sectors):
            result['status'] = 'partial'
        if sectors and all(s.get('quality', {}).get('status') == 'collection_failed' for s in sectors.values()):
            result.update(status='failed', error_type='AllSourcesFailed')
    except Exception as error:
        result.update(status='failed', error_type=type(error).__name__)
        print(f'采集任务失败：{type(error).__name__}', flush=True)
    result['finished_at'] = now_local().isoformat()
    atomic_json(root / 'collection_result.json', result)
    return result


def publish_status(root, public, state):
    state['heartbeat_at'] = now_local().isoformat()
    atomic_json(Path(root) / 'service_status.json', state)
    # 此状态对象仅含时间、阶段、数量及异常类型，不含配置、凭据和原始帖子。
    atomic_json(Path(public) / 'service_status.json', state)


def collector(root, public, daily='17:00', run_on_startup=True):
    root, public = Path(root), Path(public)
    scheduled_today(now_local(), daily)  # 启动时即验证配置。
    state = read_json(root / 'service_status.json')
    state.update(version=VERSION, timezone='Asia/Shanghai', collection_time=daily)
    if state.get('status') == 'running':
        state.update(status='interrupted', retry_at=now_local().isoformat())
    try:
        from mom_index.analyzer.index_calculator import get_dashboard_data
        from mom_index.analyzer.signal import generate_signals
        dashboard = get_dashboard_data()
        dashboard['signals'] = generate_signals(dashboard)
        publish_dashboard(dashboard, public)
    except Exception as error:
        print(f'启动时恢复看板失败：{type(error).__name__}；保留已发布快照', flush=True)
    stop = threading.Event()
    worker = None

    def shutdown(*_):
        stop.set()
        if worker is not None and worker.poll() is None:
            worker.terminate()

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, shutdown)
    initial = run_on_startup
    while not stop.is_set():
        now = now_local()
        due = next_attempt(now, state, daily, startup=initial)
        initial = False
        state['next_run_at'] = due.isoformat()
        if due > now:
            publish_status(root, public, state)
            stop.wait(min(30, (due - now).total_seconds()))
            continue
        if now >= scheduled_today(now, daily):
            if state.get('scheduled_for') != now.date().isoformat():
                state['retry_count'] = 0
            state['scheduled_for'] = now.date().isoformat()
        invocation = uuid4().hex
        state.update(status='running', last_started_at=now.isoformat(), retry_at=None,
                     next_run_at=None)
        publish_status(root, public, state)
        environment = {**os.environ, 'MOM_INDEX_DATA_DIR': str(root),
                       'MOM_INDEX_FRONTEND_DATA_DIR': str(public), 'MOM_INDEX_INVOCATION_ID': invocation}
        worker = subprocess.Popen([sys.executable, '-m', 'mom_index.nas_runtime', 'collect-once'], env=environment)
        try:
            code = worker.wait(timeout=40 * 60)
        except subprocess.TimeoutExpired:
            worker.kill(); worker.wait(); code = -1
        if stop.is_set():
            state['status'] = 'interrupted'
            publish_status(root, public, state)
            break
        result = read_json(root / 'collection_result.json')
        if result.get('invocation_id') != invocation or (code != 0 and result.get('status') != 'failed'):
            result = {'status': 'failed', 'error_type': 'WorkerFailure', 'finished_at': now_local().isoformat()}
        state.update(status=result['status'], last_finished_at=result['finished_at'], result=result)
        if result['status'] == 'failed':
            count = state.get('retry_count', 0) + 1
            state.update(retry_count=count, retry_at=(now_local() + timedelta(minutes=15)).isoformat() if count <= 2 else None)
        else:
            state.update(retry_count=0, retry_at=None)
        state['next_run_at'] = next_attempt(now_local(), state, daily).isoformat()
        publish_status(root, public, state)
        worker = None


def make_web_server(public, host='0.0.0.0', port=8503):
    public = Path(public)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.respond(False)

        def do_HEAD(self):
            self.respond(True)

        def respond(self, head):
            path = urlsplit(self.path).path
            files = {'/': (FRONTEND / 'dashboard.html', 'text/html; charset=utf-8'),
                     '/dashboard.html': (FRONTEND / 'dashboard.html', 'text/html; charset=utf-8'),
                     '/vendor/chart.umd.min.js': (FRONTEND / 'vendor' / 'chart.umd.min.js', 'application/javascript'),
                     '/data/dashboard_data.json': (public / 'dashboard_data.json', 'application/json; charset=utf-8'),
                     '/data/service_status.json': (public / 'service_status.json', 'application/json; charset=utf-8')}
            if path == '/healthz':
                payload = json.dumps({'status': 'ok', 'version': VERSION}).encode()
                content_type = 'application/json'
            elif path in files and files[path][0].is_file():
                payload = files[path][0].read_bytes(); content_type = files[path][1]
            else:
                self.send_error(404); return
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store' if path.startswith('/data/') else 'no-cache')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            if not head:
                self.wfile.write(payload)

    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(description='NAS 网页服务与每日自动采集')
    parser.add_argument('role', choices=('web', 'collector', 'collect-once', 'health', 'health-collector'))
    args = parser.parse_args()
    root = Path(os.environ.get('MOM_INDEX_DATA_DIR', '/app/output/data'))
    public = Path(os.environ.get('MOM_INDEX_FRONTEND_DATA_DIR', '/app/public-data'))
    if args.role == 'web':
        make_web_server(public, port=int(os.environ.get('WEBSERVER_PORT', '8503'))).serve_forever()
    elif args.role == 'collector':
        collector(root, public, os.environ.get('COLLECTION_TIME', '17:00'), os.environ.get('RUN_ON_STARTUP', '1') == '1')
    elif args.role == 'collect-once':
        sys.exit(1 if collect_once(root, public)['status'] == 'failed' else 0)
    elif args.role == 'health':
        with urlopen('http://127.0.0.1:' + os.environ.get('WEBSERVER_PORT', '8503') + '/healthz', timeout=5) as response:
            sys.exit(0 if response.status == 200 else 1)
    else:
        state = read_json(root / 'service_status.json')
        try:
            age = (now_local() - datetime.fromisoformat(state['heartbeat_at'])).total_seconds()
            sys.exit(0 if 0 <= age < 45 * 60 else 1)
        except (KeyError, ValueError, TypeError):
            sys.exit(1)


if __name__ == '__main__':
    main()
