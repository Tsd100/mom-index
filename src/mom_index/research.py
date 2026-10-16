"""按观测到的交易日、下一日开盘入场的保守研究回测。"""
from collections import Counter, defaultdict
from datetime import datetime
from statistics import mean

from mom_index.instruments import record_instrument
from mom_index.market_data import completed_rows
from mom_index.provenance import verified_record, SHANGHAI, digest


def evaluate(records, market, horizons=(5, 10, 20), allow_reconstructed=False):
    if not horizons or any(type(h) is not int or h <= 0 for h in horizons):
        raise ValueError('观察周期必须是正整数')
    skipped, samples, seen = Counter(), [], set()
    if market:
        if not market.get('dataset_id'):
            raise ValueError('缺失行情批次证明')
        if market['dataset_id'] != digest({k: v for k, v in market.items() if k != 'dataset_id'}):
            raise ValueError('行情批次证明校验失败')
    metadata_ok = (market.get('schema_version') == 1 and market.get('source') == 'tencent_fqkline'
                   and market.get('adjustment') == 'qfq' and market.get('calendar_code') == '510300')
    fetched = datetime.fromisoformat(market.get('fetched_at', '1970-01-01T00:00:00+08:00'))
    bars = {}
    for code, node in market.get('instruments', {}).items():
        if not node.get('rows_hash') or node['rows_hash'] != digest(node.get('rows', [])):
            raise ValueError(f'{code} 行情摘要校验失败')
        bars[code] = {r['date']: r for r in completed_rows(node.get('rows', []), fetched.astimezone(SHANGHAI))}
    benchmark_code = market.get('calendar_code', '510300')
    calendar = sorted(bars.get(benchmark_code, {}))
    for record in sorted(records, key=lambda r: r.get('timestamp', r.get('date', ''))):
        reconstructed = (allow_reconstructed and record.get('source') == 'reconstructed'
                         and record.get('audit', {}).get('original_run_verified') is True)
        if not verified_record(record) and not reconstructed:
            skipped['unverified_record'] += 1
            continue
        try:
            timestamp = datetime.fromisoformat(record['provenance']['finished_at'])
            if timestamp.tzinfo is None:
                raise ValueError('信号时间缺时区')
            timestamp = timestamp.astimezone(SHANGHAI)
            date = timestamp.date().isoformat()
            if date != record['date']:
                raise ValueError('日期与时间不一致')
        except (KeyError, ValueError, TypeError):
            skipped['unknown_signal_time'] += 1
            continue
        for sector, data in record.get('sectors', {}).items():
            if data.get('quality', {}).get('status') != 'ok' or data.get('index') is None:
                skipped['bad_quality'] += 1
                continue
            instrument = record_instrument(record, sector)
            if not instrument:
                skipped['instrument_mismatch'] += 1
                continue
            code, definition = instrument['etf'], data.get('definition_id')
            if not definition:
                skipped['unknown_definition'] += 1
                continue
            key = (sector, definition, code, date)
            if key in seen:
                skipped['duplicate_signal'] += 1
                continue
            seen.add(key)
            if not metadata_ok or not calendar or code not in bars:
                skipped['missing_market'] += 1
                continue
            if date < calendar[0]:
                skipped['calendar_before_coverage'] += 1
                continue
            future = [d for d in calendar if d > date]
            for horizon in horizons:
                if len(future) < horizon:
                    skipped['incomplete_future'] += 1
                    continue
                window = future[:horizon]
                if any(day not in bars[code] for day in window):
                    skipped['missing_bar'] += 1
                    continue
                entry, exit = window[0], window[-1]
                etf_return = bars[code][exit]['close'] / bars[code][entry]['open'] - 1
                benchmark = bars[benchmark_code][exit]['close'] / bars[benchmark_code][entry]['open'] - 1
                # 当前日收盘未完成时，不使用其收盘价来计算动量。
                past = [d for d in calendar if d < date or (d == date and (timestamp.hour, timestamp.minute) >= (15, 15))]
                momentum = None
                if len(past) >= 6 and all(d in bars[code] for d in past[-6:]):
                    momentum = 1 if bars[code][past[-1]]['close'] > bars[code][past[-6]]['close'] else 0
                # 只比较多头/现金暴露；高温或中性不持仓，低温持有ETF。不模拟不可执行的空头。
                exposure = 1 if data['index'] < 20 else 0
                samples.append({'sector': sector, 'definition_id': definition, 'etf': code,
                                'signal_date': date, 'signal_at': timestamp.isoformat(),
                                'index': data['index'], 'horizon': horizon,
                                'entry_date': entry, 'exit_date': exit,
                                'etf_return': etf_return, 'benchmark_return': benchmark,
                                'sentiment_exposure': exposure, 'sentiment_return': exposure * etf_return,
                                'momentum_return': momentum * etf_return if momentum is not None else None})
    grouped = defaultdict(list)
    for sample in samples:
        grouped[(sample['sector'], sample['definition_id'], sample['etf'], sample['horizon'])].append(sample)
    groups = []
    for key, rows in sorted(grouped.items()):
        sector, definition, code, horizon = key
        last_exit, nonoverlapping = '', 0
        for row in sorted(rows, key=lambda r: r['entry_date']):
            if row['entry_date'] > last_exit:
                nonoverlapping += 1
                last_exit = row['exit_date']
        momentum_rows = [r for r in rows if r['momentum_return'] is not None]
        groups.append({'sector': sector, 'definition_id': definition, 'etf': code, 'horizon': horizon,
                       'n': len(rows), 'nonoverlapping_n': nonoverlapping,
                       'etf_mean': mean(r['etf_return'] for r in rows),
                       'benchmark_mean': mean(r['benchmark_return'] for r in rows),
                       'sentiment_mean': mean(r['sentiment_return'] for r in rows),
                       'momentum_n': len(momentum_rows),
                       'momentum_mean': mean(r['momentum_return'] for r in momentum_rows) if momentum_rows else None,
                       'sentiment_minus_momentum': mean(r['sentiment_return'] - r['momentum_return'] for r in momentum_rows) if momentum_rows else None})
    return {'schema_version': 1, 'method': 'next_session_open_to_nth_session_close',
            'market_dataset_id': market.get('dataset_id'), 'horizons': list(horizons),
            'samples': samples, 'groups': groups, 'skipped': dict(skipped)}


def render_report(report):
    lines = ['# 宝妈指数交易日回测', '',
             '入场：信号完成后的下一个已观察交易日开盘；退出：第 N 个交易日收盘。',
             '情绪基准：指数 <20 持有ETF，其余持有现金；价格动量基准：此前5个交易日上涨持有，否则现金。',
             '比较毛收益，不含费用、滑点、成交约束或现金利息；不是实盘业绩。',
             '按板块、规则口径与ETF分别统计；重叠窗口不是独立样本，不合并宣称显著性。',
             '交易日日历取沪深300ETF已观察日线，不能证明供应商未遗漏交易日。', '',
             f'行情批次：{report.get("market_dataset_id") or "无"}',
             f'可计算窗口：{len(report["samples"])}；跳过原因：{json_text(report["skipped"])}', '']
    if not report['groups']:
        lines.append('**样本不足：尚无满足来源、质量、标的与完整未来交易日要求的样本，不能判断指标有效性。**')
    else:
        lines += ['| 板块 / ETF / 口径 | 周期 | 窗口 / 不重叠 | 情绪持仓 | ETF持有 | 沪深300 | 动量（可用数） | 情绪−动量（同窗） |',
                  '|---|---:|---:|---:|---:|---:|---:|---:|']
        for g in report['groups']:
            fmt = lambda x: '—' if x is None else f'{x:+.2%}'
            lines.append(f'| {g["sector"]} / {g["etf"]} / {g["definition_id"][:12]} | {g["horizon"]} | {g["n"]} / {g["nonoverlapping_n"]} | {fmt(g["sentiment_mean"])} | {fmt(g["etf_mean"])} | {fmt(g["benchmark_mean"])} | {fmt(g["momentum_mean"])} ({g["momentum_n"]}) | {fmt(g["sentiment_minus_momentum"])} |')
        lines += ['', '以上为描述统计；样本内阈值不作有效性证明，少量或重叠样本不能推出稳定预测能力。']
    return '\n'.join(lines) + '\n'


def json_text(value):
    import json
    return json.dumps(value, ensure_ascii=False, sort_keys=True)
