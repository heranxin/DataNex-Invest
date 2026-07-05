"""自选股批量行情（优先本地缓存，缺失项并行补拉）。"""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from model.news_analysis import STOCK_DISPLAY_NAMES, get_stock_name
from model.stock_search import is_valid_a_share_code

_ROOT = os.path.dirname(os.path.dirname(__file__))
_STOCK_CACHE_DIR = os.path.join(_ROOT, 'static', 'new_cache')

_SPOT_CACHE = {'ts': 0, 'data': None}
_SPOT_TTL = 120
_FETCH_TIMEOUT = 25
_MAX_WORKERS = 4


def _parse_change_pct(raw) -> float:
    if raw is None:
        return 0.0
    s = str(raw).replace('%', '').strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_price(raw):
    if raw is None or raw in ('--', ''):
        return None
    try:
        return round(float(raw), 2)
    except (TypeError, ValueError):
        return None


def _load_spot_table():
    import akshare as ak
    from model.network_utils import direct_connection

    now = time.time()
    if _SPOT_CACHE['data'] is not None and now - _SPOT_CACHE['ts'] < _SPOT_TTL:
        return _SPOT_CACHE['data']

    with direct_connection():
        spot = ak.stock_zh_a_spot_em()
    _SPOT_CACHE['data'] = spot
    _SPOT_CACHE['ts'] = now
    return spot


def clear_spot_cache():
    _SPOT_CACHE['data'] = None
    _SPOT_CACHE['ts'] = 0


def _display_name_fast(code: str) -> str:
    """本地解析股票名称，不发起网络请求（页面直出用）。"""
    code = str(code).strip().zfill(6)
    if code in STOCK_DISPLAY_NAMES:
        return STOCK_DISPLAY_NAMES[code]
    index_path = os.path.join(_STOCK_CACHE_DIR, 'stock_search_index.json')
    if os.path.isfile(index_path):
        try:
            with open(index_path, 'r', encoding='utf-8') as f:
                items = json.load(f)
            for item in items:
                if str(item.get('code', '')).zfill(6) == code:
                    name = str(item.get('name') or '').strip()
                    if name:
                        return name
        except Exception:
            pass
    return code


def _quote_from_local_stock_cache(code: str):
    """读取单股本地 JSON 缓存，不发起网络请求。"""
    path = os.path.join(_STOCK_CACHE_DIR, f'{code}_data.json')
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        rt = data.get('realtime') or {}
        price = _parse_price(rt.get('最新价'))
        change_pct = _parse_change_pct(rt.get('涨跌幅'))
        name = str(rt.get('名称') or '').strip()
        if not name or name == code or name.isdigit():
            name = _display_name_fast(code)
        if price is None:
            return None
        return {
            'code': code,
            'name': name,
            'price': price,
            'change_pct': change_pct,
            'change_display': f'{change_pct:+.2f}%',
            'amount_yi': None,
            'volume_wan': None,
            'status': 'cached',
        }
    except Exception:
        return None


def _sort_quotes(quotes, sort_by='change_pct'):
    if sort_by == 'name':
        quotes.sort(key=lambda x: x.get('name') or x['code'])
    elif sort_by == 'code':
        quotes.sort(key=lambda x: x['code'])
    else:
        quotes.sort(key=lambda x: x.get('change_pct') or 0.0, reverse=True)
    return quotes


def _fetch_missing_parallel(codes):
    """并行补拉缺失自选行情。"""
    out = {}
    if not codes:
        return out
    workers = min(_MAX_WORKERS, len(codes))
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_quote_fallback, c): c for c in codes}
            for fut in as_completed(futures, timeout=_FETCH_TIMEOUT):
                code = futures[fut]
                try:
                    out[code] = fut.result()
                except Exception as e:
                    print(f'自选行情并行拉取失败 {code}: {e}')
                    out[code] = {
                        'code': code,
                        'name': get_stock_name(code),
                        'price': None,
                        'change_pct': 0.0,
                        'change_display': '--',
                        'amount_yi': None,
                        'volume_wan': None,
                        'status': 'unavailable',
                    }
    except Exception as e:
        print(f'自选行情并行拉取超时: {e}')
        for code in codes:
            if code not in out:
                out[code] = _quote_fallback(code)
    return out


def _quote_from_spot_row(code: str, row) -> dict:
    price = _parse_price(row.get('最新价'))
    change_pct = _parse_change_pct(row.get('涨跌幅'))
    name = str(row.get('名称', '')).strip() or get_stock_name(code)
    amount_raw = row.get('成交额')
    volume_raw = row.get('成交量')
    amount = None
    volume = None
    try:
        if amount_raw is not None:
            amount = round(float(amount_raw) / 1e8, 2)
    except (TypeError, ValueError):
        pass
    try:
        if volume_raw is not None:
            volume = round(float(volume_raw) / 1e4, 2)
    except (TypeError, ValueError):
        pass
    return {
        'code': code,
        'name': name,
        'price': price,
        'change_pct': change_pct,
        'change_display': f'{change_pct:+.2f}%',
        'amount_yi': amount,
        'volume_wan': volume,
        'status': 'ok',
    }


def _quote_fallback(code: str) -> dict:
    name = get_stock_name(code)
    try:
        from model.network_utils import direct_connection
        from stock_data import fetch_stock_data
        with direct_connection():
            data = fetch_stock_data(code, days=5, cache_timeout=600)
        if data and data.get('realtime'):
            rt = data['realtime']
            price = _parse_price(rt.get('最新价'))
            change_pct = _parse_change_pct(rt.get('涨跌幅'))
            return {
                'code': code,
                'name': name,
                'price': price,
                'change_pct': change_pct,
                'change_display': f'{change_pct:+.2f}%' if change_pct else str(rt.get('涨跌幅', '--')),
                'amount_yi': None,
                'volume_wan': None,
                'status': 'cached',
            }
    except Exception as e:
        print(f'自选行情回退失败 {code}: {e}')
    return {
        'code': code,
        'name': name,
        'price': None,
        'change_pct': 0.0,
        'change_display': '--',
        'amount_yi': None,
        'volume_wan': None,
        'status': 'unavailable',
    }


def fetch_favorite_quotes(stock_codes, sort_by='change_pct', lightweight=None, cache_only=False):
    """批量获取自选股行情。

    cache_only: 仅读本地单股缓存（供 dashboard 服务端直出，毫秒级）。
    lightweight: 为 True 时不拉全市场 spot；为 None 时 code 数量 ≤40 自动轻量。
    """
    codes = []
    for c in stock_codes or []:
        code = str(c).strip().zfill(6)
        if is_valid_a_share_code(code) and code not in codes:
            codes.append(code)

    if not codes:
        return []

    quotes = []
    missing = []
    for code in codes:
        cached = _quote_from_local_stock_cache(code)
        if cached:
            quotes.append(cached)
        else:
            missing.append(code)

    if cache_only:
        for code in missing:
            quotes.append({
                'code': code,
                'name': _display_name_fast(code),
                'price': None,
                'change_pct': 0.0,
                'change_display': '--',
                'amount_yi': None,
                'volume_wan': None,
                'status': 'pending',
            })
        return _sort_quotes(quotes, sort_by)

    use_light = lightweight if lightweight is not None else len(codes) <= 40

    spot = None
    if not use_light:
        try:
            spot = _load_spot_table()
        except Exception as e:
            print(f'全市场行情拉取失败: {e}')
    elif _SPOT_CACHE['data'] is not None and time.time() - _SPOT_CACHE['ts'] < _SPOT_TTL:
        spot = _SPOT_CACHE['data']

    if spot is not None and missing:
        code_set = set(missing)
        spot_map = {}
        for _, row in spot.iterrows():
            c = str(row.get('代码', '')).zfill(6)
            if c in code_set:
                spot_map[c] = row
        still_missing = []
        for code in missing:
            if code in spot_map:
                quotes.append(_quote_from_spot_row(code, spot_map[code]))
            else:
                still_missing.append(code)
        missing = still_missing

    if missing:
        fetched = _fetch_missing_parallel(missing)
        for code in missing:
            quotes.append(fetched.get(code) or _quote_fallback(code))

    return _sort_quotes(quotes, sort_by)
