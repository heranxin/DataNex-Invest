"""A 股名称/代码/拼音搜索索引。"""
import json
import os
import re
from datetime import datetime, timedelta

from model.news_analysis import STOCK_DISPLAY_NAMES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_CACHE = os.path.join(ROOT, 'static', 'new_cache', 'stock_search_index.json')
INDEX_TTL_SECONDS = 86400  # 24 小时重建一次全市场索引

PINYIN_ALIASES = {
    '600519': ['GZMT', 'MT', 'MAOTAI'],
    '000858': ['WLY'],
    '300750': ['NDSD', 'CATL'],
    '002594': ['BYD'],
    '601318': ['PAYH', 'PINGAN'],
    '600036': ['ZSYH'],
    '000001': ['PAYH', 'PAB'],
    '601398': ['GSYH', 'ICBC'],
    '600030': ['ZXZQ'],
    '601012': ['LJGN', 'LONGI'],
}

_A_SHARE_CODE_RE = re.compile(r'^(?:00|30|60|68|83|87|43)\d{4}$')


def is_valid_a_share_code(code: str) -> bool:
    code = str(code or '').strip()
    if not code:
        return False
    code = code.zfill(6)
    if code == '000000':
        return False
    return bool(_A_SHARE_CODE_RE.match(code))


def _pinyin_initials(text: str) -> str:
    try:
        from pypinyin import lazy_pinyin, Style
        return ''.join(lazy_pinyin(text, style=Style.FIRST_LETTER)).upper()
    except ImportError:
        return ''


def _ensure_cache_dir():
    os.makedirs(os.path.dirname(INDEX_CACHE), exist_ok=True)


def _item_entry(code: str, name: str):
    code = str(code).strip().zfill(6)
    name = str(name).strip()
    if not code or not name or not is_valid_a_share_code(code):
        return None
    aliases = list(PINYIN_ALIASES.get(code, []))
    py = _pinyin_initials(name)
    if py and py not in aliases:
        aliases.append(py)
    return {
        'code': code,
        'name': name,
        'pinyin': py,
        'aliases': aliases,
    }


def _build_index_from_akshare():
    import akshare as ak
    df = ak.stock_info_a_code_name()
    items = []
    seen = set()
    for _, row in df.iterrows():
        entry = _item_entry(row['code'], row['name'])
        if entry and entry['code'] not in seen:
            seen.add(entry['code'])
            items.append(entry)
    return items


def build_stock_index(force: bool = False):
    """构建或读取缓存的全市场搜索索引。"""
    _ensure_cache_dir()
    if not force and os.path.exists(INDEX_CACHE):
        try:
            with open(INDEX_CACHE, 'r', encoding='utf-8') as f:
                cached = json.load(f)
            updated = datetime.fromisoformat(cached['updated_at'])
            if datetime.now() - updated < timedelta(seconds=INDEX_TTL_SECONDS):
                return cached['items']
        except Exception:
            pass

    items = []
    seen = set()
    for code, name in STOCK_DISPLAY_NAMES.items():
        entry = _item_entry(code, name)
        if entry and entry['code'] not in seen:
            seen.add(entry['code'])
            items.append(entry)

    try:
        ak_items = _build_index_from_akshare()
        for entry in ak_items:
            if entry['code'] not in seen:
                seen.add(entry['code'])
                items.append(entry)
    except Exception as e:
        print(f'构建 akshare 搜索索引失败，使用内置列表: {e}')

    payload = {'updated_at': datetime.now().isoformat(), 'items': items}
    with open(INDEX_CACHE, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False)
    return items


def _score_item(entry, q_raw: str, q_upper: str, q_digits: str):
    code = entry['code']
    name = entry['name']
    py = (entry.get('pinyin') or '').upper()
    aliases = [a.upper() for a in entry.get('aliases', [])]

    if q_digits and code == q_digits:
        return 100
    if q_digits and code.startswith(q_digits):
        return 90 - (len(code) - len(q_digits))
    if name == q_raw:
        return 85
    if name.startswith(q_raw):
        return 80
    if q_raw in name:
        return 70
    if py and (py.startswith(q_upper) or q_upper in py):
        return 65
    for alias in aliases:
        if alias.startswith(q_upper) or q_upper in alias:
            return 60
    return 0


def search_stocks(query: str, limit: int = 10):
    """按代码、简称、拼音首字母搜索 A 股。"""
    q_raw = (query or '').strip()
    if not q_raw:
        return []

    limit = max(1, min(int(limit or 10), 30))
    q_upper = q_raw.upper()
    q_digits = re.sub(r'\D', '', q_raw)
    if q_digits:
        q_digits = q_digits.zfill(6) if len(q_digits) <= 6 else q_digits[:6]

    index = build_stock_index()
    scored = []
    for entry in index:
        score = _score_item(entry, q_raw, q_upper, q_digits)
        if score > 0:
            match_type = '代码' if score >= 90 else ('简称' if score >= 65 else '拼音')
            scored.append((score, entry['code'], entry['name'], match_type))

    scored.sort(key=lambda x: (-x[0], x[1]))
    return [
        {'code': code, 'name': name, 'match_type': mt}
        for _, code, name, mt in scored[:limit]
    ]


def resolve_stock_query(query: str):
    """将用户输入解析为 6 位股票代码。"""
    q = (query or '').strip()
    if not q:
        return None, '请输入股票代码或名称'

    digits = re.sub(r'\D', '', q)
    if len(digits) == 6 and is_valid_a_share_code(digits):
        return digits.zfill(6), None

    results = search_stocks(q, limit=1)
    if results:
        return results[0]['code'], None
    return None, f'未找到与「{q}」匹配的股票'
