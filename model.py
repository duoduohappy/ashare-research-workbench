"""Observable Markov regime model. All frames use expanding past-only counts."""
import math

NAMES = ['熊市', '震荡', '牛市']

def analyze(bars, window=20, threshold=.05):
    if not 5 <= window <= 120 or not .001 <= threshold <= .5:
        raise ValueError('回看周期应为 5–120，阈值应为 0.1%–50%')
    counts = [[0.0]*3 for _ in range(3)]
    frames = []
    previous = None
    pi = [1/3]*3
    for i, bar in enumerate(bars):
        state = None
        ret = None
        if i >= window:
            ret = bar['close']/bars[i-window]['close']-1
            state = 2 if ret > threshold else 0 if ret < -threshold else 1
            if previous is not None:
                counts[previous][state] += 1
            previous = state
        # Dirichlet smoothing keeps unobserved rows stochastic.
        matrix = [[(v+.5)/(sum(row)+1.5) for v in row] for row in counts]
        # Warm start; smoothing ensures a unique stationary distribution.
        for _ in range(2000):
            nxt = [sum(pi[k]*matrix[k][j] for k in range(3)) for j in range(3)]
            diff = max(abs(nxt[j]-pi[j]) for j in range(3))
            pi = nxt
            if diff < 1e-10:
                break
        probs = matrix[state] if state is not None else None
        frames.append({'date':bar['date'], 'close':bar['close'], 'state':state,
                       'return':ret, 'matrix':matrix, 'stationary':pi[:],
                       'probs':probs, 'signal':probs[2]-probs[0] if probs else None,
                       'samples': int(sum(map(sum, counts)))})
    return frames

def validate_bars(rows):
    from datetime import date
    seen = {}
    for row in rows:
        day = str(row['date'])[:10]
        date.fromisoformat(day)
        close = float(row['close'])
        if not math.isfinite(close) or close <= 0:
            raise ValueError('价格必须为正的有限数值')
        clean = {'date':day, 'close':close}
        for key in ('raw_open','raw_close','raw_high','raw_low','volume'):
            if key in row:
                value=float(row[key])
                if not math.isfinite(value) or value<0 or (key!='volume' and value==0):
                    raise ValueError('原始价格与成交量字段无效')
                clean[key]=value
        seen[day] = clean
    result = [seen[k] for k in sorted(seen)]
    if len(result) < 30:
        raise ValueError('可用历史不足 30 个交易日')
    return result
