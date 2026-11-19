"""Versioned daily-auction research rules, not a tick matching engine."""
import math
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

RULE_VERSION = 'ashare-daily-2026-07-06-v1'
SOURCES = [
    'https://www.szse.cn/aboutus/trends/news/t20200821_580924.html',
    'https://www.szse.cn/www/marketServices/technicalservice/doc/P020230724535729507237.pdf',
    'https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml',
    'https://www.szse.cn/lawrules/service/member/t20260630_621403.html',
    'https://www.sse.com.cn/disclosure/diclosure/upper/',
]

def price_tick(value):
    return float(Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))

def board_for(code):
    if not isinstance(code, str) or len(code) != 6 or not code.isdigit():
        raise ValueError('需要六位沪深 A 股代码')
    if code.startswith('688'): return 'star'
    if code.startswith(('300', '301')): return 'chinext'
    if code.startswith(('600','601','603','605','000','001','002','003')): return 'main'
    raise ValueError('严格日线研究暂仅支持沪深普通 A 股')

def daily_rule(code, day, status, reference, listing_ordinal=None, listed_on=None):
    date.fromisoformat(day); board = board_for(code)
    if type(status.get('is_st')) is not bool or type(status.get('suspended')) is not bool:
        raise ValueError(code+' 缺少当日 ST / 停牌状态，不能用今天的简称回填历史')
    minimum, step, maximum = (200, 1, 100000) if board == 'star' else (100, 100, 1000000)
    # Explicit exchange price bands take priority, including unusual sessions.
    no_limit = status.get('no_price_limit')
    if no_limit is not None and type(no_limit) is not bool: raise ValueError('no_price_limit 必须是布尔值')
    upper, lower = status.get('limit_up'), status.get('limit_down')
    if no_limit is True:
        if upper is not None or lower is not None: raise ValueError('无涨跌幅限制不能同时设置涨跌停价')
        ratio, origin = None, 'explicit_no_limit'
    elif upper is not None or lower is not None:
        if not all(type(v) in (int,float) and math.isfinite(v) and v>0 for v in (upper,lower)) or lower>upper:
            raise ValueError('涨跌停价格须为正有限数且下限不大于上限')
        if any(abs(v-price_tick(v))>1e-8 for v in (upper,lower)):raise ValueError('涨跌停价格须符合 0.01 元价位')
        ratio, origin = None, 'explicit_exchange_bands'
    else:
        if status.get('special_session') not in (None,'regular'):
            raise ValueError('重新上市/退市整理首日等特殊交易日需提供明确涨跌停价或无涨跌幅标识')
        modern_ipo = (board=='star' or (board=='chinext' and listed_on and listed_on>='2020-08-24')
                      or (board=='main' and listed_on and listed_on>='2023-04-10'))
        if listing_ordinal is not None and listing_ordinal<=5:
            if modern_ipo:
                upper=lower=None;ratio=None;origin='registration_ipo_first_five'
            else:raise ValueError('旧制 IPO 初期需提供明确涨跌停价，不能套用普通交易日规则')
        else:
            ratio = .2 if board=='star' or (board=='chinext' and day>='2020-08-24') else .1
            if status['is_st'] and board=='main' and day<'2026-07-06':ratio=.05
            if type(reference) not in (int,float) or not math.isfinite(reference) or reference<=0:
                raise ValueError('缺少有效涨跌停参考价')
            upper,lower=price_tick(reference*(1+ratio)),price_tick(reference*(1-ratio));origin='dated_rule'
    if board=='main' and status['is_st']:maximum=min(maximum,500000)
    return {'version':RULE_VERSION,'board':board,'upper':upper,'lower':lower,'ratio':ratio,
            'minimum_buy':minimum,'quantity_step':step,'maximum_order':maximum,'origin':origin,
            'suspended':status['suspended'],'is_st':status['is_st']}

def execution_quote(code, day, bar, rule, side, quantity, available, slippage, participation):
    """No use of total daily volume as an opening-auction liquidity budget."""
    if side not in ('buy','sell'):raise ValueError('交易方向无效')
    if not 0<=slippage<=.03 or not 0<participation<=.1:raise ValueError('滑点或开盘集合竞价参与率无效')
    if type(quantity) is not int or quantity<=0:raise ValueError('委托数量须为正整数')
    if rule['suspended']:return {'filled':0,'reason':'停牌'}
    if bar.get('volume_shares',0)<=0:return {'filled':0,'reason':'零成交量'}
    if side=='sell' and available<=0:return {'filled':0,'reason':'T+1 可卖数量不足'}
    opening=bar['raw_open'];up,down=rule['upper'],rule['lower']
    if side=='buy' and up is not None and opening>=up-.005:return {'filled':0,'reason':'开盘涨停，保守拒绝'}
    if side=='sell' and down is not None and opening<=down+.005:return {'filled':0,'reason':'开盘跌停，保守拒绝'}
    # Capacity is supplied opening auction shares, not final daily volume.
    auction=bar.get('auction_volume_shares')
    if type(auction) not in (int,float) or not math.isfinite(auction) or auction<0:
        return {'filled':0,'reason':'缺少开盘集合竞价成交量，不能推算开盘容量'}
    capacity=math.floor(auction*participation)
    n=min(quantity,capacity,rule['maximum_order'],available if side=='sell' else quantity)
    if side=='buy':
        n=n//rule['quantity_step']*rule['quantity_step']
        if n<rule['minimum_buy']:return {'filled':0,'reason':'资金或开盘容量不足最小申报数量'}
    elif n<available:
        n=n//rule['quantity_step']*rule['quantity_step']
        if n<rule['minimum_buy']:return {'filled':0,'reason':'容量不足，零股需一次性卖出'}
    if n<=0:return {'filled':0,'reason':'开盘容量不足'}
    proposed=price_tick(opening*(1+slippage if side=='buy' else 1-slippage))
    # Slippage cannot invent a fill outside the observed day's price range.
    lo=max(bar['raw_low'],down if down is not None else bar['raw_low'])
    hi=min(bar['raw_high'],up if up is not None else bar['raw_high'])
    if lo>hi or not lo-.005<=opening<=hi+.005:raise ValueError(code+' OHLC 与涨跌停价格冲突')
    lo=math.ceil((lo-1e-8)*100)/100;hi=math.floor((hi+1e-8)*100)/100
    if lo>hi:raise ValueError('观察价格范围内没有有效的 0.01 元成交价位')
    price=min(hi,max(lo,proposed))
    return {'filled':int(n),'price':price,'reason':'全部成交' if n==quantity else '部分成交，余单当日撤销',
            'auction_capacity':capacity}
