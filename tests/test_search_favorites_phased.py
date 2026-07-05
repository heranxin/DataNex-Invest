"""
自选股盯盘 + 名称搜索 — 分阶段验收测试

用法:
    python tests/test_search_favorites_phased.py
    python tests/test_search_favorites_phased.py --phase 1
    python tests/test_search_favorites_phased.py --phase 1,2,3
"""
import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


class CheckResult:
    def __init__(self, name, passed, detail='', dimension='功能'):
        self.name = name
        self.passed = passed
        self.detail = detail
        self.dimension = dimension

    def __str__(self):
        icon = '✅' if self.passed else '❌'
        return f'  {icon} [{self.dimension}] {self.name}' + (f' — {self.detail}' if self.detail else '')


class PhaseResult:
    def __init__(self, phase_id, title):
        self.phase_id = phase_id
        self.title = title
        self.checks = []
        self.start = time.time()

    def add(self, name, passed, detail='', dimension='功能'):
        self.checks.append(CheckResult(name, passed, detail, dimension))

    @property
    def passed(self):
        return all(c.passed for c in self.checks)

    @property
    def elapsed(self):
        return time.time() - self.start

    def summary(self):
        ok = sum(1 for c in self.checks if c.passed)
        total = len(self.checks)
        status = '通过' if self.passed else '未通过'
        lines = [
            f'\n{"=" * 60}',
            f'阶段 {self.phase_id}: {self.title}  [{status}]  ({ok}/{total})  {self.elapsed:.1f}s',
            f'{"=" * 60}',
        ]
        for c in self.checks:
            lines.append(str(c))
        return '\n'.join(lines)


ALL_PHASES = []


def run_phase(phase_id, title):
    def decorator(fn):
        def wrapper(*args, **kwargs):
            pr = PhaseResult(phase_id, title)
            try:
                fn(pr)
            except Exception as e:
                pr.add('阶段执行异常', False, f'{e}\n{traceback.format_exc()[:300]}', '稳定性')
            ALL_PHASES.append(pr)
            print(pr.summary())
            return pr.passed
        wrapper._phase_id = phase_id
        return wrapper
    return decorator


@run_phase(1, '股票搜索索引与解析（模块级）')
def phase1_stock_search(pr: PhaseResult):
    from model.stock_search import (
        is_valid_a_share_code,
        search_stocks,
        resolve_stock_query,
        build_stock_index,
    )

    valid_cases = ['600519', '000001', '300750', '688981']
    for code in valid_cases:
        pr.add(f'合法代码 {code}', is_valid_a_share_code(code), '', '准确性')

    invalid_cases = ['12345', '999999', 'ABCDEF', '']
    for code in invalid_cases:
        pr.add(f'非法代码 {code or "空"}', not is_valid_a_share_code(code), '', '准确性')

    index = build_stock_index()
    pr.add('搜索索引非空', len(index) >= len(valid_cases), f'{len(index)} 条', '完整性')

    code_hits = search_stocks('600519', limit=5)
    pr.add('精确代码 600519', any(h['code'] == '600519' for h in code_hits), str(code_hits[:2]), '准确性')

    name_hits = search_stocks('贵州茅台', limit=5)
    pr.add('名称「贵州茅台」', any(h['code'] == '600519' for h in name_hits), str(name_hits[:2]), '准确性')

    partial_hits = search_stocks('茅台', limit=5)
    pr.add('简称「茅台」', any('茅台' in h['name'] for h in partial_hits), str(partial_hits[:2]), '准确性')

    alias_hits = search_stocks('BYD', limit=5)
    pr.add('拼音别名 BYD', any(h['code'] == '002594' for h in alias_hits), str(alias_hits[:2]), '准确性')

    empty_hits = search_stocks('', limit=5)
    pr.add('空查询返回空', len(empty_hits) == 0, '', '边界')

    code, err = resolve_stock_query('600519')
    pr.add('解析纯代码', code == '600519' and err is None, f'{code}', '功能')

    code2, err2 = resolve_stock_query('宁德时代')
    pr.add('解析名称', code2 == '300750' and err2 is None, f'{code2}', '功能')

    code3, err3 = resolve_stock_query('不存在的股票xyz')
    pr.add('解析失败有错误', code3 is None and err3, err3 or '', '边界')


@run_phase(2, '搜索 HTTP API')
def phase2_search_api(pr: PhaseResult):
    from app import app

    with app.test_client() as client:
        r = client.get('/api/stock-search?q=茅台&limit=5')
        pr.add('HTTP 200', r.status_code == 200, str(r.status_code), '功能')
        data = r.get_json()
        items = data.get('items', [])
        pr.add('返回 items 结构', isinstance(items, list) and len(items) > 0, f'count={data.get("count")}', '数据')
        pr.add('含 code/name/match_type', all(
            'code' in i and 'name' in i and 'match_type' in i for i in items
        ), str(items[0]) if items else '', '数据质量')

        r2 = client.get('/api/stock-search?q=')
        pr2 = r2.get_json()
        pr.add('空查询', pr2.get('count', -1) == 0, str(pr2), '边界')

        r3 = client.get('/api/resolve-stock?q=比亚迪')
        d3 = r3.get_json()
        pr.add('resolve 比亚迪', d3.get('success') and d3.get('code') == '002594', str(d3), '准确性')

        r4 = client.get('/api/resolve-stock?q=INVALID_XYZ')
        pr.add('resolve 失败 400', r4.status_code == 400, r4.get_json().get('error', '')[:40], '边界')

        r5 = client.get('/search')
        pr.add('搜索页可访问', r5.status_code == 200, '', '功能')
        pr.add('搜索页含联想容器', b'stockSuggest' in r5.data, '', '前端')


@run_phase(3, '自选行情服务（模块级）')
def phase3_favorite_quotes(pr: PhaseResult):
    from model.favorite_quotes import fetch_favorite_quotes, _parse_change_pct, _parse_price

    pr.add('涨跌幅解析 +2.5%', _parse_change_pct('2.5%') == 2.5, '', '准确性')
    pr.add('涨跌幅解析 -1%', _parse_change_pct('-1%') == -1.0, '', '准确性')
    pr.add('价格解析', _parse_price('123.45') == 123.45, '', '准确性')

    empty = fetch_favorite_quotes([])
    pr.add('空列表', empty == [], '', '边界')

    try:
        quotes = fetch_favorite_quotes(['600519', '000001'], sort_by='change_pct')
        pr.add('批量行情 ≥1', len(quotes) >= 1, f'{len(quotes)} 条', '数据')
        if quotes:
            q = quotes[0]
            pr.add('行情字段完整', all(k in q for k in ('code', 'name', 'price', 'change_pct', 'status')),
                   str({k: q[k] for k in ('code', 'name', 'price', 'change_display', 'status')}), '数据质量')
            pr.add('600519 在结果中', any(x['code'] == '600519' for x in quotes), '', '准确性')

        by_name = fetch_favorite_quotes(['600519', '000001'], sort_by='name')
        pr.add('按名称排序', by_name == sorted(by_name, key=lambda x: x.get('name') or x['code']), '', '功能')
    except Exception as e:
        pr.add('批量行情（网络）', False, str(e)[:120], '数据')


@run_phase(4, '自选 API 与收藏逻辑')
def phase4_favorite_api(pr: PhaseResult):
    from app import app, db, User, FavoriteStock

    test_user = 'test_sf_user'
    test_pass = 'test_sf_pass'

    with app.app_context():
        u = User.query.filter_by(username=test_user).first()
        if u:
            FavoriteStock.query.filter_by(user_id=u.id).delete()
            db.session.delete(u)
            db.session.commit()

        u = User(username=test_user)
        u.set_password(test_pass)
        db.session.add(u)
        db.session.commit()
        uid = u.id

    with app.test_client() as client:
        pr.add('未登录 favorite-quotes 401',
               client.get('/api/favorite-quotes').status_code == 401, '', '安全')

        with client.session_transaction() as sess:
            sess['user_id'] = uid
            sess['username'] = test_user

        r_add_name = client.post('/api/add-favorite-stock?code=贵州茅台')
        d_add = r_add_name.get_json()
        pr.add('名称添加自选', r_add_name.status_code == 200 and d_add.get('code') == '600519',
               str(d_add), '功能')

        r_dup = client.post('/api/add-favorite-stock?code=600519')
        dup_json = r_dup.get_json()
        pr.add('重复添加友好返回', r_dup.status_code == 200 and dup_json.get('duplicate'), dup_json, '边界')

        r_add2 = client.post('/api/add-favorite-stock?code=000001')
        pr.add('第二只自选', r_add2.status_code == 200, '', '功能')

        r_list = client.get('/api/favorite-stocks')
        codes = r_list.get_json()
        pr.add('自选列表 ≥2', len(codes) >= 2, str(codes), '功能')

        r_quotes = client.get('/api/favorite-quotes?sort=change_pct')
        qd = r_quotes.get_json()
        items = qd.get('items', [])
        pr.add('盯盘 API 200', r_quotes.status_code == 200, f'count={qd.get("count")}', '功能')
        pr.add('盯盘含涨跌幅', all('change_pct' in i for i in items), str(items[0] if items else ''), '数据')

        r_rm = client.post('/api/remove-favorite-stock?code=平安银行')
        pr.add('名称移除自选', r_rm.status_code == 200 and r_rm.get_json().get('success'), '', '功能')

        r_fav_page = client.get('/favorite-stocks')
        pr.add('自选页可访问', r_fav_page.status_code == 200, '', '功能')
        pr.add('自选页含盯盘板', b'favoriteBoard' in r_fav_page.data, '', '前端')

    with app.app_context():
        u = User.query.filter_by(username=test_user).first()
        if u:
            FavoriteStock.query.filter_by(user_id=u.id).delete()
            db.session.delete(u)
            db.session.commit()


@run_phase(5, '前端静态资源与模板')
def phase5_frontend(pr: PhaseResult):
    files = [
        ROOT / 'static' / 'js' / 'stock-search.js',
        ROOT / 'static' / 'js' / 'favorite-board.js',
        ROOT / 'templates' / 'search.html',
        ROOT / 'templates' / 'favorite_stocks.html',
        ROOT / 'templates' / 'dashboard.html',
    ]
    for f in files:
        pr.add(f'文件存在 {f.name}', f.exists(), str(f), '完整性')

    search_js = (ROOT / 'static' / 'js' / 'stock-search.js').read_text(encoding='utf-8')
    pr.add('StockSearch.init', 'StockSearch' in search_js and 'initStockSearch' in search_js, '', '功能')
    pr.add('搜索 API 路径', '/api/stock-search' in search_js, '', '功能')

    fav_js = (ROOT / 'static' / 'js' / 'favorite-board.js').read_text(encoding='utf-8')
    pr.add('FavoriteBoard.load', 'FavoriteBoard' in fav_js and 'favorite-quotes' in fav_js, '', '功能')

    css = (ROOT / 'static' / 'css' / 'app.css').read_text(encoding='utf-8')
    pr.add('CSS 联想样式', '.stock-suggest-dropdown' in css, '', 'UI')
    pr.add('CSS 盯盘样式', '.fav-quote-row' in css, '', 'UI')

    dash = (ROOT / 'templates' / 'dashboard.html').read_text(encoding='utf-8')
    pr.add('工作台盯盘区', 'dashFavoriteBoard' in dash, '', 'UI')


@run_phase(6, '整体联调与放行门禁')
def phase6_integration(pr: PhaseResult):
    from app import app, db, User, FavoriteStock
    from model.stock_search import resolve_stock_query, search_stocks

    flow_user = 'test_sf_flow'
    with app.app_context():
        u = User.query.filter_by(username=flow_user).first()
        if u:
            FavoriteStock.query.filter_by(user_id=u.id).delete()
            db.session.delete(u)
            db.session.commit()
        u = User(username=flow_user)
        u.set_password('x')
        db.session.add(u)
        db.session.commit()
        uid = u.id

    # 用户旅程：搜索 → 添加自选 → 盯盘
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = uid
            sess['username'] = flow_user

        hits = search_stocks('GZMT', limit=3)
        pr.add('旅程-拼音搜茅台', any(h['code'] == '600519' for h in hits), str(hits), 'E2E')

        code, _ = resolve_stock_query('GZMT')
        r1 = client.post(f'/api/add-favorite-stock?code={code}')
        pr.add('旅程-添加自选', r1.get_json().get('success'), str(r1.get_json()), 'E2E')

        r2 = client.get('/api/favorite-quotes')
        items = r2.get_json().get('items', [])
        pr.add('旅程-盯盘有数据', len(items) >= 1 and items[0].get('code') == '600519', str(items[0] if items else ''), 'E2E')

        r3 = client.get('/api/stock-search?q=600519')
        pr.add('旅程-搜索 API 一致', r3.get_json().get('items', [{}])[0].get('code') == '600519', '', '一致性')

        r4 = client.get('/dashboard')
        pr.add('旅程-工作台 200', r4.status_code == 200 and b'dashFavoriteBoard' in r4.data, '', 'E2E')

    with app.app_context():
        u = User.query.filter_by(username=flow_user).first()
        if u:
            FavoriteStock.query.filter_by(user_id=u.id).delete()
            db.session.delete(u)
            db.session.commit()

    # 性能：搜索应 < 3s（有缓存时更快）
    t0 = time.time()
    search_stocks('银行', limit=10)
    elapsed = time.time() - t0
    pr.add('搜索响应 < 3s', elapsed < 3.0, f'{elapsed:.2f}s', '性能')


PHASE_FUNCS = {
    1: phase1_stock_search,
    2: phase2_search_api,
    3: phase3_favorite_quotes,
    4: phase4_favorite_api,
    5: phase5_frontend,
    6: phase6_integration,
}


def main():
    parser = argparse.ArgumentParser(description='自选股盯盘+名称搜索 分阶段验收')
    parser.add_argument('--phase', type=str, default='all', help='1 或 1,2,3 或 all')
    args = parser.parse_args()

    if args.phase == 'all':
        phases = sorted(PHASE_FUNCS.keys())
    else:
        phases = [int(p.strip()) for p in args.phase.split(',')]

    print('\n' + '█' * 60)
    print('  数境智投 · 自选股盯盘 + 名称搜索 分阶段验收')
    print('█' * 60)

    gate_open = True
    for p in phases:
        fn = PHASE_FUNCS.get(p)
        if not fn:
            print(f'未知阶段: {p}')
            continue
        passed = fn()
        if not passed:
            gate_open = False
            print(f'\n⛔ 阶段 {p} 未通过，停止后续阶段（可用 --phase 单独调试）')
            if args.phase == 'all':
                break

    print('\n' + '█' * 60)
    print('  验收总结')
    print('█' * 60)
    for pr in ALL_PHASES:
        ok = sum(1 for c in pr.checks if c.passed)
        status = '✅ 通过' if pr.passed else '❌ 未通过'
        print(f'  阶段 {pr.phase_id} {pr.title}: {status} ({ok}/{len(pr.checks)})')

    total_ok = sum(1 for pr in ALL_PHASES for c in pr.checks if c.passed)
    total = sum(len(pr.checks) for pr in ALL_PHASES)

    if gate_open and args.phase == 'all' and len(ALL_PHASES) == 6:
        print(f'\n🟢 放行结论: 全部 6 阶段通过 ({total_ok}/{total} 项)，可以上线')
        return 0
    elif gate_open:
        print(f'\n🟡 部分阶段通过 ({total_ok}/{total} 项)')
        return 0
    else:
        print(f'\n🔴 放行结论: 未通过 ({total_ok}/{total} 项)，请修复后重测')
        return 1


if __name__ == '__main__':
    sys.exit(main())
