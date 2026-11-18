"""Descriptive cross-sectional factor diagnostics, never a trading backtest."""
import math
import statistics as st
from datetime import date

FACTORS = {'momentum20': '20 日动量', 'reversal5': '5 日反转', 'lowvol20': '20 日低波'}
HORIZONS = (1, 5, 20)


def mean(values):
    values = [v for v in values if v is not None]
    return st.mean(values) if values else None


def ranks(values):
    """Average ranks for ties; original ordering never resolves ties."""
    ordered = sorted(range(len(values)), key=values.__getitem__)
    result = [0.] * len(values)
    i = 0
    while i < len(values):
        j = i + 1
        while j < len(values) and values[ordered[j]] == values[ordered[i]]:
            j += 1
        for k in ordered[i:j]:
            result[k] = (i + j - 1) / 2
        i = j
    return result


def correlation(x, y, ranked=False):
    if len(x) != len(y) or len(x) < 3:
        return None
    if ranked:
        x, y = ranks(x), ranks(y)
    a, b = st.mean(x), st.mean(y)
    dx, dy = [v-a for v in x], [v-b for v in y]
    denominator = math.sqrt(sum(v*v for v in dx)*sum(v*v for v in dy))
    return sum(u*v for u, v in zip(dx, dy))/denominator if denominator > 1e-14 else None


def groups(x, y):
    """Equal-count three buckets. Boundary ties make groups undefined."""
    order = sorted(range(len(x)), key=x.__getitem__)
    cuts = (len(x)//3, 2*len(x)//3)
    if any(x[order[k-1]] == x[order[k]] for k in cuts):
        return None
    edges = (0, *cuts, len(x))
    return [st.mean(y[k] for k in order[edges[j]:edges[j+1]]) for j in range(3)]


def summarize(rows):
    ic = [r['ic'] for r in rows if r['ic'] is not None]
    ric = [r['rank_ic'] for r in rows if r['rank_ic'] is not None]
    sd = st.stdev(ric) if len(ric) > 1 else 0
    return {'dates': len(rows), 'valid_ic': len(ic), 'valid_rank_ic': len(ric),
            'mean_ic': mean(ic), 'mean_rank_ic': mean(ric),
            'rank_ic_ir': st.mean(ric)/sd if sd > 1e-12 else None,
            'positive_rank_ic_ratio': mean([int(v > 0) for v in ric]),
            'group_returns': [mean([r['groups'][j] for r in rows if r['groups'] is not None]) for j in range(3)],
            'valid_groups': sum(r['groups'] is not None for r in rows),
            'mean_spread': mean([r['groups'][2]-r['groups'][0] for r in rows if r['groups'] is not None])}


def factor_validation(series, end, factor='momentum20', horizon=5):
    date.fromisoformat(end)
    if factor not in FACTORS or type(horizon) is not int or horizon not in HORIZONS:
        raise ValueError('因子或持有期无效；持有期仅支持 1、5、20 日')
    if not isinstance(series, dict) or not 5 <= len(series) <= 8:
        raise ValueError('因子验证需 5–8 只不重复股票，建议扩大有效样本后再作判断')
    codes = sorted(series)
    histories = {}
    for code in codes:
        rows = [b for b in series[code] if b['date'] <= end]
        dates = [b['date'] for b in rows]
        if dates != sorted(set(dates)):
            raise ValueError(code+' 日线日期须递增且不重复')
        for b in rows:
            date.fromisoformat(b['date'])
            if not isinstance(b['close'], (int, float)) or not math.isfinite(b['close']) or b['close'] <= 0:
                raise ValueError(code+' 收盘价须为正有限数')
        histories[code] = {b['date']: b['close'] for b in rows}
    common = sorted(set.intersection(*(set(h) for h in histories.values())))
    if len(common) < 240:
        raise ValueError('至少需要 240 个共同交易日；请缩短股票池上市时间差或调整查看日期')
    # All horizons and candidates share exactly the same signal dates for decay comparison.
    # Keep at most 504 complete signal dates; 20 preceding returns define each feature.
    positions = range(max(20, len(common)-20-504), len(common)-20)
    prices = {c: [histories[c][d] for d in common] for c in codes}
    records = {f: {h: [] for h in HORIZONS} for f in FACTORS}
    for i in positions:
        values = {f: [] for f in FACTORS}
        for code in codes:
            p = prices[code]
            values['momentum20'].append(p[i]/p[i-20]-1)
            values['reversal5'].append(-(p[i]/p[i-5]-1))
            values['lowvol20'].append(-st.stdev([p[j]/p[j-1]-1 for j in range(i-19, i+1)]))
        for h in HORIZONS:
            y = [prices[c][i+h]/prices[c][i]-1 for c in codes]
            for f, x in values.items():
                records[f][h].append({'date': common[i], 'label_end': common[i+h],
                    'ic': correlation(x, y), 'rank_ic': correlation(x, y, True), 'groups': groups(x, y)})
    rows = records[factor][horizon]
    rolling = [{'date': r['date'], 'ic': mean([p['ic'] for p in rows[max(0,i-19):i+1]]),
                'rank_ic': mean([p['rank_ic'] for p in rows[max(0,i-19):i+1]])} for i, r in enumerate(rows) if i >= 19]
    # Forward walk: select factor AND direction exclusively in the training window.
    # Test folds have 42 signal dates, do not overlap, and use one cohort per horizon.
    # Training labels ending on the first test signal date are purged conservatively.
    folds = []
    for start in range(126+horizon, len(rows)-41, 42):
        test = rows[start:start+42]
        test_start = test[0]['date']
        train_indexes = [j for j in range(start) if rows[j]['label_end'] < test_start][-126:]
        candidates = []
        for f in FACTORS:
            s = summarize([records[f][horizon][j] for j in train_indexes])
            if s['mean_rank_ic'] is not None and s['valid_rank_ic'] >= 60:
                candidates.append((abs(s['mean_rank_ic']), f, s))
        if not candidates:
            continue
        _, chosen, training = max(candidates, key=lambda v: (v[0], v[1]))
        direction = 1 if training['mean_rank_ic'] >= 0 else -1
        test_rows = [r for j,r in enumerate(records[chosen][horizon][start:start+42], start)
                     if (j-(126+horizon)) % horizon == 0]
        # Orient groups and IC with the training-only direction; do not refit on test returns.
        oriented = [{**r, 'ic': None if r['ic'] is None else r['ic']*direction,
                     'rank_ic': None if r['rank_ic'] is None else r['rank_ic']*direction,
                     'groups': None if r['groups'] is None else r['groups'][::direction]} for r in test_rows]
        folds.append({'fold': len(folds)+1, 'train_start': rows[train_indexes[0]]['date'],
            'train_end': rows[train_indexes[-1]]['date'],
            'train_label_end': max(rows[j]['label_end'] for j in train_indexes),
            'test_start': test_start, 'test_end': test[-1]['date'], 'test_label_end': max(r['label_end'] for r in test_rows),
            'factor': chosen, 'factor_name': FACTORS[chosen], 'direction': direction,
            'train_mean_rank_ic': training['mean_rank_ic']*direction, 'test': summarize(oriented), 'observations': oriented})
    notes = [
        '仅验证当前手动候选池；5–8 只股票的横截面很小，有幸存者偏差，不等同全市场因子研究。',
        '仅检验价格因子，不把当前财报评分回填到历史。财务因子需完整历史披露数据后另行验证。',
        '按共同日期交集计算，缺失日期会改变观测间隔；1/5/20 日指共同观测步数，并非保证连续市场交易日。',
        '因子在当日收盘形成，标签为该收盘至未来收盘的复权收益；分组是描述性远期收益，不是可执行交易净值，不计费用、涨跌停和卖空约束。',
        '衰减图采用相同信号日期，最长 20 日标签未完成的日期一律排除。每日标签可能重叠；ICIR 为均值/样本标准差，不年化、不报告独立样本显著性。',
        '三组按因子值从低到高分桶；边界并列时分组无定义，不按股票代码强拆。常数截面 IC 与 Rank IC 无定义，保留为空。',
        '滚动训练最多 126 个信号日，测试窗 42 个信号日，训练标签必须严格早于测试起点；训练选因子及正反方向，测试期内不再选择。测试按全局统一的持有期间隔抽样，避免折内及跨折的收益区间重叠，不合成收益曲线。',
        '历史价格是上游当前修订版本；日期截断只能阻止读取后续行，不能提供完整历史 PIT 数据。']
    return {'asof': end, 'factor': factor, 'factor_name': FACTORS[factor], 'horizon': horizon, 'codes': codes,
        'common_start': common[0], 'common_end': common[-1], 'common_rows': len(common),
        'signal_start': rows[0]['date'], 'signal_end': rows[-1]['date'], 'label_end': rows[-1]['label_end'],
        'summary': summarize(rows), 'observations': rows, 'rolling': rolling,
        'decay': [{'horizon': h, **summarize(records[factor][h])} for h in HORIZONS],
        'folds': folds, 'notes': notes}
