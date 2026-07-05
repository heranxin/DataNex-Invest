"""股票发现：分类推荐 + 市场概览，帮助新手知道有哪些股票可查。"""
import json
import os

from model.news_analysis import STOCK_DISPLAY_NAMES
from model.favorite_quotes import (
    _parse_change_pct,
    _parse_price,
    _quote_from_local_stock_cache,
    fetch_favorite_quotes,
)
from model.stock_search import INDEX_CACHE, is_valid_a_share_code

# 按行业/主题整理的常见 A 股（新手入门用，非投资建议）
STOCK_CATEGORIES = [
    {
        'id': 'liquor',
        'name': '白酒食品',
        'icon': 'fa-cutlery',
        'desc': '消费白马，业绩与旺季销量相关',
        'codes': ['600519', '000858', '000568', '600887', '603288'],
    },
    {
        'id': 'new_energy',
        'name': '新能源',
        'icon': 'fa-bolt',
        'desc': '电池、整车、光伏产业链',
        'codes': ['300750', '002594', '601012', '002460', '300014'],
    },
    {
        'id': 'bank',
        'name': '银行金融',
        'icon': 'fa-university',
        'desc': '大盘蓝筹，分红与利率敏感',
        'codes': ['601398', '600036', '000001', '601318', '600030'],
    },
    {
        'id': 'tech',
        'name': '科技半导体',
        'icon': 'fa-microchip',
        'desc': '电子、通信、算力相关',
        'codes': ['688981', '002415', '000725', '603501', '300308'],
    },
    {
        'id': 'medicine',
        'name': '医药健康',
        'icon': 'fa-medkit',
        'desc': '创新药、医疗器械',
        'codes': ['600276', '000661', '300760', '603259', '600436'],
    },
    {
        'id': 'resource',
        'name': '资源周期',
        'icon': 'fa-diamond',
        'desc': '有色、黄金、电力等',
        'codes': ['601899', '600547', '600900', '601088', '600028'],
    },
]

BOARD_HINTS = [
    {'board': '沪主板', 'prefix': '60', 'hint': '代码以 60 开头，如 600519'},
    {'board': '科创板', 'prefix': '68', 'hint': '代码以 688 开头'},
    {'board': '深市主板', 'prefix': '00', 'hint': '代码以 00 开头，如 000001'},
    {'board': '创业板', 'prefix': '30', 'hint': '代码以 30 开头，如 300750'},
]


def all_category_codes():
    codes = []
    for cat in STOCK_CATEGORIES:
        for c in cat['codes']:
            if is_valid_a_share_code(c) and c not in codes:
                codes.append(c)
    return codes


def _load_index_fast():
    """只读本地缓存索引，不在请求里同步拉 akshare（避免页面卡死）。"""
    if os.path.exists(INDEX_CACHE):
        try:
            with open(INDEX_CACHE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            items = data.get('items') or []
            if items:
                return items
        except Exception:
            pass

    items = []
    seen = set()
    for code, name in STOCK_DISPLAY_NAMES.items():
        code = str(code).zfill(6)
        if code not in seen:
            seen.add(code)
            items.append({'code': code, 'name': name})
    for cat in STOCK_CATEGORIES:
        for code in cat['codes']:
            if code not in seen:
                seen.add(code)
                items.append({'code': code, 'name': STOCK_DISPLAY_NAMES.get(code, code)})
    return items


def _board_stats(items):
    counts = {'沪主板': 0, '科创板': 0, '深市主板': 0, '创业板': 0, '其他': 0}
    for entry in items:
        code = entry.get('code', '')
        if code.startswith('688'):
            counts['科创板'] += 1
        elif code.startswith('60'):
            counts['沪主板'] += 1
        elif code.startswith('00'):
            counts['深市主板'] += 1
        elif code.startswith('30'):
            counts['创业板'] += 1
        else:
            counts['其他'] += 1
    return counts


def _build_categories(index_names, quotes_map=None):
    quotes_map = quotes_map or {}
    categories = []
    for cat in STOCK_CATEGORIES:
        stocks = []
        for code in cat['codes']:
            if not is_valid_a_share_code(code):
                continue
            q = quotes_map.get(code, {})
            stocks.append({
                'code': code,
                'name': q.get('name') or index_names.get(code, STOCK_DISPLAY_NAMES.get(code, code)),
                'price': q.get('price'),
                'change_pct': q.get('change_pct', 0),
                'change_display': q.get('change_display', '--'),
            })
        categories.append({
            'id': cat['id'],
            'name': cat['name'],
            'icon': cat['icon'],
            'desc': cat['desc'],
            'stocks': stocks,
        })
    return categories


def get_browse_payload(with_quotes=False):
    """页面首屏：默认不拉全市场行情，保证秒开。"""
    index = _load_index_fast()
    index_names = {e['code']: e['name'] for e in index}
    total = len(index) if len(index) > 100 else 5200

    quotes_map = {}
    if with_quotes:
        try:
            for q in fetch_favorite_quotes(all_category_codes(), sort_by='code', lightweight=True):
                quotes_map[q['code']] = q
        except Exception as e:
            print(f'分类行情 enrichment 失败: {e}')

    return {
        'total_stocks': total,
        'board_stats': _board_stats(index),
        'board_hints': BOARD_HINTS,
        'categories': _build_categories(index_names, quotes_map),
        'quotes_loaded': bool(with_quotes),
        'search_tip': '平台支持全部 A 股：输入代码、中文名或拼音首字母即可搜索（如 茅台、BYD、GZMT）',
    }


def get_browse_quotes_payload():
    """异步补行情：仅 30 只分类股，轻量模式。"""
    codes = all_category_codes()
    quotes_map = {}
    try:
        # 1) 先用新浪批量行情，一次请求覆盖全部分类股
        quotes_map.update(_fetch_batch_sina_quotes(codes))

        # 2) 缺失项走现有兜底逻辑（轻量并行）
        missing = [c for c in codes if c not in quotes_map or quotes_map[c].get('price') is None]
        if missing:
            for q in fetch_favorite_quotes(missing, sort_by='code', lightweight=True):
                if q.get('price') is not None:
                    quotes_map[q['code']] = q

        # 3) 再用本地单股缓存补齐
        missing = [c for c in codes if c not in quotes_map or quotes_map[c].get('price') is None]
        for code in missing:
            cached = _quote_from_local_stock_cache(code)
            if cached and cached.get('price') is not None:
                quotes_map[code] = cached

        # 4) 最后从热股快照补（防止云端上游抖动时整页都显示 "--"）
        missing = [c for c in codes if c not in quotes_map or quotes_map[c].get('price') is None]
        ticker_map = _load_ticker_snapshot_map()
        for code in missing:
            snap = ticker_map.get(code)
            if snap and snap.get('price') is not None:
                quotes_map[code] = {
                    'code': code,
                    'name': snap.get('name') or STOCK_DISPLAY_NAMES.get(code, code),
                    'price': snap.get('price'),
                    'change_pct': snap.get('change_pct', 0.0),
                    'change_display': snap.get('change_display', '--'),
                    'status': 'cached',
                }

    except Exception as e:
        return {'quotes': {}, 'error': str(e)}
    return {'quotes': quotes_map}


def _fetch_batch_sina_quotes(codes):
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
        print(f'股票发现-新浪批量行情失败: {e}')
    return out


def _load_ticker_snapshot_map():
    root = os.path.dirname(os.path.dirname(__file__))
    cache_dir = os.path.join(root, 'static', 'cache')
    files = [
        os.path.join(cache_dir, 'market_ticker_daily.json'),
        os.path.join(cache_dir, 'market_ticker_last_good.json'),
    ]
    out = {}
    for path in files:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for item in data.get('items') or []:
                code = str(item.get('code') or '').zfill(6)
                if not code or code == '000000':
                    continue
                if code not in out and item.get('price') is not None:
                    out[code] = item
        except Exception:
            continue
    return out
