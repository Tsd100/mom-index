"""保存带标的与复权信息的完整日线；不把情绪快照间隔当作交易日。"""
import argparse
import json
import math
from pathlib import Path
import requests

from mom_index.instruments import SECTORS
from mom_index.provenance import now_local, digest

DEFAULT_ROOT = Path(__file__).resolve().parents[1] / 'data'


def completed_rows(rows, now=None):
    now = now or now_local()
    cutoff = now.date().isoformat()
    complete_today = (now.hour, now.minute) >= (15, 15)
    result = {}
    for row in rows:
        date = row['date']
        __import__('datetime').date.fromisoformat(date)
        if date > cutoff or (date == cutoff and not complete_today):
            continue
        if any(not isinstance(row[k], (int, float)) or not math.isfinite(row[k]) or row[k] <= 0 for k in ('open', 'close')):
            raise ValueError('日线包含非正或无效价格')
        if date in result and result[date] != row:
            raise ValueError('同日行情冲突')
        result[date] = row
    return [result[date] for date in sorted(result)]


def fetch_daily(code, days=180, now=None):
    symbol = ('sh' if code.startswith(('5', '6')) else 'sz') + code
    response = requests.get('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get',
                            params={'param': f'{symbol},day,,,{days},qfq'}, timeout=20)
    response.raise_for_status()
    node = response.json()['data'][symbol]
    # 不将未复权 day 静默标成 qfq。
    rows = node.get('qfqday')
    if rows is None:
        raise ValueError('接口未返回前复权日线')
    parsed = [{'date': r[0], 'open': float(r[1]), 'close': float(r[2])} for r in rows]
    return completed_rows(parsed, now)


def fetch_market(root=DEFAULT_ROOT, days=180):
    root = Path(root)
    codes = {cfg['etf'] for cfg in SECTORS.values()} | {'510300'}
    # 保留旧配置标的用于历史研究，不拿新ETF价格替换旧军工/能源价格。
    history = root / 'production' / 'history.json'
    if history.exists():
        for record in json.loads(history.read_text(encoding='utf-8')).get('records', []):
            for cfg in record.get('provenance', {}).get('definition', {}).get('sectors', {}).values():
                if str(cfg.get('etf', '')).isdigit():
                    codes.add(cfg['etf'])
                if str(cfg.get('code', '')).startswith('of'):
                    codes.add(cfg['code'][2:])
    dataset = {'schema_version': 1, 'source': 'tencent_fqkline', 'adjustment': 'qfq',
               'fetched_at': now_local().isoformat(), 'calendar_code': '510300',
               'calendar_basis': 'observed_benchmark_sessions_not_official_calendar',
               'instruments': {}, 'failures': {}}
    for code in sorted(codes):
        try:
            rows = fetch_daily(code, days)
            if not rows:
                raise ValueError('无已完成日线')
            dataset['instruments'][code] = {'rows': rows, 'rows_hash': digest(rows)}
            print(f'{code}: {len(rows)} 个已完成交易日 {rows[0]["date"]} ~ {rows[-1]["date"]}')
        except (requests.RequestException, ValueError, KeyError, TypeError) as error:
            dataset['failures'][code] = {'type': type(error).__name__,
                                         'reason': str(error) if isinstance(error, ValueError) else '请求或响应结构异常'}
            print(f'{code}: 获取失败 {type(error).__name__}')
    if '510300' not in dataset['instruments']:
        raise RuntimeError('基准行情不可用，未覆盖现有数据集')
    root.mkdir(parents=True, exist_ok=True)
    snapshots = root / 'market_snapshots'
    snapshots.mkdir(exist_ok=True)
    dataset['dataset_id'] = digest(dataset)
    text = json.dumps(dataset, ensure_ascii=False, indent=2)
    (snapshots / (dataset['dataset_id'] + '.json')).write_text(text, encoding='utf-8')
    (root / 'market_history.json').write_text(text, encoding='utf-8')
    return dataset


if __name__ == '__main__':
    import os
    parser = argparse.ArgumentParser(description='获取带标的身份和时间证明的前复权日线')
    parser.add_argument('--days', type=int, default=180)
    parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('MOM_INDEX_DATA_DIR', DEFAULT_ROOT)))
    args = parser.parse_args()
    if not 10 <= args.days <= 1000:
        parser.error('--days 需在 10 到 1000 之间')
    fetch_market(args.data_dir, args.days)
