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
_LAST_GOOD_FILE = os.path.join(_CACHE_DIR, 'market_ticker_last_good.json')
_STOCK_CACHE_DIR = os.path.join(_ROOT, 'static', 'new_cache')

_FETCH_TIMEOUT = 35
_MAX_WORKERS = 4
_REFRESH_LOCK = threading.Lock()


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
    return _load_payload_file(_DAILY_FILE)


def _load_payload_file(path):
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if data.get('items'):
            return data
    except Exception as e:
        print(f'读取每日热股失败: {e}')
    return None


def _save_daily_file(payload):
    _save_payload_file(_DAILY_FILE, payload)


def _save_payload_file(path, payload):
    _ensure_cache_dir()
    try:
        with open(path, 'w', encoding='utf-8') as f:
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


def _priced_count(items):
    return sum(1 for q in (items or []) if q.get('price') is not None)


def _merge_with_previous(quotes, previous_items, limit):
    """用旧快照补齐缺失 code，避免整排都是 --。"""
    merged = list(quotes or [])
    by_code = {q.get('code'): q for q in merged if q.get('code')}
    for old in previous_items or []:
        code = old.get('code')
        if not code or code in by_code:
            continue
        if old.get('price') is None:
            continue
        stale = old.copy()
        stale['status'] = 'stale'
        merged.append(stale)
        by_code[code] = stale
        if len(merged) >= limit:
            break
    merged.sort(key=lambda x: abs(x.get('change_pct') or 0), reverse=True)
    return merged[:limit]


def _needs_refresh(data):
    """判定是否需要后台刷新：日期过期或内容仍是占位。"""
    if not data:
        return True
    items = data.get('items') or []
    if not items:
        return True
    if data.get('trade_date') != _today_str():
        return True
    if _priced_count(items) < 4:
        return True
    source = str(data.get('source') or '')
    if '待更新' in source:
        return True
    return any((q.get('status') == 'pending') for q in items)


def _hydrate_with_local_cache(data, limit=12):
    """用本地单股缓存补齐 pending，避免页面长期显示 --。"""
    limit = max(4, min(int(limit or 12), 20))
    items = list((data or {}).get('items') or [])[:limit]
    by_code = {str(x.get('code')): x for x in items if x.get('code')}
    changed = False

    for code in TICKER_POOL:
        if len(items) >= limit and code in by_code:
            continue
        cached = _quote_from_local_stock_cache(code)
        if not cached:
            continue
        old = by_code.get(code)
        if old:
            if old.get('price') is None or old.get('status') == 'pending':
                by_code[code] = cached
                changed = True
        elif len(items) < limit:
            by_code[code] = cached
            changed = True

    if not changed:
        return data, False

    merged = list(by_code.values())
    merged.sort(key=lambda x: abs(x.get('change_pct') or 0), reverse=True)
    merged = merged[:limit]

    out = (data or {}).copy()
    out['items'] = merged
    out['count'] = len(merged)
    out['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if _priced_count(merged) >= 4:
        out['source'] = '本地缓存'
    return out, True


def _fetch_one_network(code: str):
    from model.network_utils import direct_connection
    with direct_connection():
        return _quote_fallback(code)


def _fetch_batch_sina_quotes(codes):
    """优先走新浪批量行情：一次请求，稳定性高于逐只拉取。"""
    out = {}
    if not codes:
        return out
    try:
        import akshare as ak
        from model.network_utils import direct_connection
        with direct_connection():
            spot = ak.stock_zh_a_spot()
        code_set = set(codes)
        for _, row in spot.iterrows():
            raw_code = str(row.get('代码', '')).strip()
            if not raw_code:
                continue
            code = raw_code[-6:].zfill(6)
            if code not in code_set:
                continue
            price = _parse_price(row.get('最新价'))
            if price is None:
                continue
            change_pct = _parse_change_pct(row.get('涨跌幅'))
            name = str(row.get('名称') or STOCK_DISPLAY_NAMES.get(code, code)).strip()
            out[code] = {
                'code': code,
                'name': name or STOCK_DISPLAY_NAMES.get(code, code),
                'price': price,
                'change_pct': change_pct,
                'change_display': f'{change_pct:+.2f}%',
                'status': 'ok',
            }
    except Exception as e:
        print(f'新浪批量行情失败: {e}')
    return out


def refresh_daily_ticker(limit=12):
    """手动/后台：拉取并写入当日快照（不在页面请求里调用）。"""
    limit = max(4, min(int(limit or 12), 20))
    quotes = []
    batch = _fetch_batch_sina_quotes(TICKER_POOL)
    for code in TICKER_POOL:
        q = batch.get(code)
        if q:
            quotes.append(q)

    existing_codes = {q.get('code') for q in quotes}
    missing_codes = [c for c in TICKER_POOL if c not in existing_codes]

    try:
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            futures = {pool.submit(_fetch_one_network, c): c for c in missing_codes}
            for fut in as_completed(futures, timeout=_FETCH_TIMEOUT):
                try:
                    q = fut.result()
                    if q and q.get('price') is not None:
                        quotes.append(q)
                except Exception as e:
                    print(f'热股更新失败 {futures.get(fut)}: {e}')
    except Exception as e:
        print(f'热股并行更新超时: {e}')

    existing_codes = {q.get('code') for q in quotes}
    unresolved_codes = [c for c in missing_codes if c not in existing_codes]
    if unresolved_codes and len(quotes) < limit:
        # 并发超时或上游抖动后，顺序补拉一轮，避免整条行情都为 "--"
        for code in unresolved_codes:
            try:
                q = _fetch_one_network(code)
                if q and q.get('price') is not None:
                    quotes.append(q)
            except Exception as e:
                print(f'热股顺序补拉失败 {code}: {e}')

    if len(quotes) < 4:
        for code in TICKER_POOL:
            if any(x['code'] == code for x in quotes):
                continue
            q = _quote_from_local_stock_cache(code)
            if q:
                quotes.append(q)

    old = _load_daily_file()
    last_good = _load_payload_file(_LAST_GOOD_FILE)
    if old and old.get('items'):
        quotes = _merge_with_previous(quotes, old.get('items'), limit)
    if _priced_count(quotes) < 4 and last_good and last_good.get('items'):
        quotes = _merge_with_previous(quotes, last_good.get('items'), limit)
    if _priced_count(quotes) < 4 and old and old.get('items'):
        return old

    quotes.sort(key=lambda x: abs(x.get('change_pct') or 0), reverse=True)
    payload = _build_daily_payload(quotes[:limit], trade_date=_today_str(), source='akshare/新浪')
    if _priced_count(payload.get('items')) >= 4:
        _save_payload_file(_LAST_GOOD_FILE, payload)
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
    data, changed = _hydrate_with_local_cache(data, limit)
    if changed:
        _save_daily_file(data)
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
    data, changed = _hydrate_with_local_cache(data, limit)
    if changed:
        _save_daily_file(data)
    items = (data.get('items') or [])[: max(4, min(int(limit or 12), 20))]
    out = data.copy()
    out['items'] = items
    out['count'] = len(items)
    return out


def schedule_daily_refresh_if_stale():
    """若快照不是今天的，后台静默更新（不阻塞用户）。"""
    data = _load_daily_file()
    if not _needs_refresh(data):
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
