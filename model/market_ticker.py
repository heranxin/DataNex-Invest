"""工作台热股滚动条：按天快照，页面只读本地 JSON，不阻塞拉行情。"""
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from model.favorite_quotes import _parse_change_pct, _parse_price, _quote_fallback
from model.news_analysis import STOCK_DISPLAY_NAMES

TICKER_POOL = [
    '600519', '300750', '002594', '601398', '600036',
    '000001', '601318', '688981', '600276', '601899',
    '000858', '601012', '600900', '300308', '002415',
]

_ROOT = os.path.dirname(os.path.dirname(__file__))
_CACHE_DIR = os.path.join(_ROOT, 'static', 'cache')
_DAILY_FILE = os.path.join(_CACHE_DIR, 'market_ticker_daily.json')
_STOCK_CACHE_DIR = os.path.join(_ROOT, 'static', 'new_cache')

_FETCH_TIMEOUT = 15
_MAX_WORKERS = 4
_REFRESH_LOCK = threading.Lock()
_BG_STARTED = False


def _today_str():
    return datetime.now().strftime('%Y-%m-%d')


def _ensure_cache_dir():
    os.makedirs(_CACHE_DIR, exist_ok=True)


def _tick_class(change_pct):
    if change_pct > 0:
        return 'up'
    if change_pct < 0:
        return 'down'
    return 'flat'


def _quote_from_local_stock_cache(code: str):
    """读取单股本地缓存（stock_data 写入），不发起网络请求。"""
    path = os.path.join(_STOCK_CACHE_DIR, f'{code}_data.json')
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        rt = data.get('realtime') or {}
        price = _parse_price(rt.get('最新价'))
        change_pct = _parse_change_pct(rt.get('涨跌幅'))
        name = str(rt.get('名称') or STOCK_DISPLAY_NAMES.get(code, code))
        if price is None:
            return None
        return {
            'code': code,
            'name': name,
            'price': price,
            'change_pct': change_pct,
            'change_display': f'{change_pct:+.2f}%',
            'status': 'cached',
        }
    except Exception:
        return None


def _build_daily_payload(items, trade_date=None, source='本地快照'):
    trade_date = trade_date or _today_str()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return {
        'trade_date': trade_date,
        'items': items,
        'mode': 'daily',
        'mode_label': '每日热股 · 按涨跌幅',
        'source': source,
        'updated_at': now,
        'updated_hint': f'数据日期 {trade_date} · 每个交易日更新一次',
        'count': len(items),
    }


def _load_daily_file():
    if not os.path.isfile(_DAILY_FILE):
        return None
    try:
        with open(_DAILY_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if data.get('items'):
            return data
    except Exception as e:
        print(f'读取每日热股失败: {e}')
    return None


def _save_daily_file(payload):
    _ensure_cache_dir()
    try:
        with open(_DAILY_FILE, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f'写入每日热股失败: {e}')


def _collect_items_for_snapshot(limit=12):
    """优先本地单股缓存，缺失项在后台刷新时再补网络。"""
    items = []
    for code in TICKER_POOL:
        q = _quote_from_local_stock_cache(code)
        if q:
            items.append(q)
    items.sort(key=lambda x: abs(x.get('change_pct') or 0), reverse=True)
    if len(items) >= 4:
        return items[:limit]

    for code in TICKER_POOL:
        if any(x['code'] == code for x in items):
            continue
        items.append({
            'code': code,
            'name': STOCK_DISPLAY_NAMES.get(code, code),
            'price': None,
            'change_pct': 0.0,
            'change_display': '--',
            'status': 'pending',
        })
    return items[:limit]


def _fetch_one_network(code: str):
    from model.network_utils import direct_connection
    with direct_connection():
        return _quote_fallback(code)


def refresh_daily_ticker(limit=12):
    """手动/后台：拉取并写入当日快照（不在页面请求里调用）。"""
    limit = max(4, min(int(limit or 12), 20))
    quotes = []
    try:
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            futures = {pool.submit(_fetch_one_network, c): c for c in TICKER_POOL}
            for fut in as_completed(futures, timeout=_FETCH_TIMEOUT):
                try:
                    q = fut.result()
                    if q and q.get('price') is not None:
                        quotes.append(q)
                except Exception as e:
                    print(f'热股更新失败 {futures.get(fut)}: {e}')
    except Exception as e:
        print(f'热股并行更新超时: {e}')

    if len(quotes) < 4:
        for code in TICKER_POOL:
            if any(x['code'] == code for x in quotes):
                continue
            q = _quote_from_local_stock_cache(code)
            if q:
                quotes.append(q)

    if len(quotes) < 4:
        old = _load_daily_file()
        if old and old.get('items'):
            return old

    quotes.sort(key=lambda x: abs(x.get('change_pct') or 0), reverse=True)
    payload = _build_daily_payload(quotes[:limit], trade_date=_today_str(), source='akshare/新浪')
    _save_daily_file(payload)
    print(f'每日热股已更新: {payload["trade_date"]} · {len(payload["items"])} 只')
    return payload


def _ensure_daily_file_exists():
    data = _load_daily_file()
    if data:
        return data
    payload = _build_daily_payload(
        _collect_items_for_snapshot(12),
        trade_date=_today_str(),
        source='本地缓存/待更新',
    )
    _save_daily_file(payload)
    return payload


def get_daily_ticker_for_page(limit=12):
    """供 dashboard 模板使用：只读文件，毫秒级返回。"""
    limit = max(4, min(int(limit or 12), 20))
    data = _ensure_daily_file_exists()
    items = (data.get('items') or [])[:limit]
    for q in items:
        q['cls'] = _tick_class(q.get('change_pct') or 0)
    return {
        'stocks': items,
        'meta': data.get('updated_hint') or f'数据日期 {data.get("trade_date", "")}',
        'trade_date': data.get('trade_date'),
    }


def market_ticker_payload(limit=12, force=False):
    """API：只读每日快照；force=1 时同步刷新（管理用，页面不调用）。"""
    if force:
        return refresh_daily_ticker(limit)
    data = _ensure_daily_file_exists()
    items = (data.get('items') or [])[: max(4, min(int(limit or 12), 20))]
    out = data.copy()
    out['items'] = items
    out['count'] = len(items)
    return out


def schedule_daily_refresh_if_stale():
    """若快照不是今天的，后台静默更新（不阻塞用户）。"""
    global _BG_STARTED
    if _BG_STARTED:
        return
    _BG_STARTED = True

    data = _load_daily_file()
    if data and data.get('trade_date') == _today_str():
        return

    def job():
        if not _REFRESH_LOCK.acquire(blocking=False):
            return
        try:
            refresh_daily_ticker(12)
        except Exception as e:
            print(f'后台更新每日热股失败: {e}')
        finally:
            _REFRESH_LOCK.release()

    threading.Thread(target=job, daemon=True).start()
