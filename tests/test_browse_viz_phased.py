"""
股票发现 + ECharts 可视化 — 分阶段验收测试

用法:
    python tests/test_browse_viz_phased.py
    python tests/test_browse_viz_phased.py --phase 1
    python tests/test_browse_viz_phased.py --phase 1,2,3
"""
import argparse
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


@run_phase(1, '股票发现数据层（模块级）')
def phase1_browse_module(pr: PhaseResult):
    from model.stock_browse import STOCK_CATEGORIES, get_browse_payload, BOARD_HINTS
    from model.stock_search import is_valid_a_share_code

    pr.add('分类数量 ≥ 4', len(STOCK_CATEGORIES) >= 4, f'{len(STOCK_CATEGORIES)} 个', '完整性')
    pr.add('板块说明非空', len(BOARD_HINTS) >= 4, str(len(BOARD_HINTS)), '完整性')

    for cat in STOCK_CATEGORIES:
        valid_codes = [c for c in cat['codes'] if is_valid_a_share_code(c)]
        pr.add(f'分类「{cat["name"]}」含合法代码', len(valid_codes) >= 3,
               f'{len(valid_codes)}/{len(cat["codes"])}', '数据质量')

    payload = get_browse_payload(with_quotes=False)
    pr.add('total_stocks > 100', payload.get('total_stocks', 0) > 100,
           str(payload.get('total_stocks')), '数据')
    pr.add('categories 与配置一致', len(payload.get('categories', [])) == len(STOCK_CATEGORIES), '', '一致性')
    pr.add('board_stats 有键', bool(payload.get('board_stats')), str(list(payload.get('board_stats', {}).keys())[:4]), '数据')
    pr.add('search_tip 非空', bool(payload.get('search_tip')), '', 'UX')

    cats = payload.get('categories', [])
    if cats:
        stocks = cats[0].get('stocks', [])
        pr.add('分类股票含 code/name', all('code' in s and 'name' in s for s in stocks),
               str(stocks[0]) if stocks else '', '数据质量')


@run_phase(2, '股票发现 HTTP API')
def phase2_browse_api(pr: PhaseResult):
    from app import app

    with app.test_client() as client:
        r = client.get('/api/stock-browse')
        pr.add('HTTP 200', r.status_code == 200, str(r.status_code), '功能')
        data = r.get_json() or {}
        pr.add('无 error 字段', 'error' not in data, data.get('error', ''), '稳定性')

        total = data.get('total_stocks', 0)
        pr.add('total_stocks 合理', total > 100, str(total), '数据')

        cats = data.get('categories', [])
        pr.add('categories 非空', len(cats) > 0, f'{len(cats)} 类', '数据')

        all_codes = []
        for cat in cats:
            for s in cat.get('stocks', []):
                all_codes.append(s.get('code'))
        pr.add('含 600519 茅台', '600519' in all_codes, '', '准确性')
        pr.add('含 002594 比亚迪', '002594' in all_codes, '', '准确性')

        if cats and cats[0].get('stocks'):
            st = cats[0]['stocks'][0]
            pr.add('股票卡片含 code/name', 'code' in st and 'name' in st,
                   str({k: st.get(k) for k in ('code', 'name')}), '数据质量')

        r3 = client.get('/api/stock-browse-quotes')
        pr.add('行情补全 API 可达', r3.status_code == 200, str(r3.status_code), '功能')

        r2 = client.get('/stock-browse')
        pr.add('发现页 200', r2.status_code == 200, '', '功能')
        pr.add('发现页含搜索框', b'browseSearchInput' in r2.data, '', '前端')
        pr.add('发现页调 browse API', b'/api/stock-browse' in r2.data, '', '前端')


@run_phase(3, 'ECharts 图表数据 API')
def phase3_chart_series_api(pr: PhaseResult):
    from app import app
    fast = getattr(phase3_chart_series_api, '_fast', False)

    with app.test_client() as client:
        r_bad = client.get('/api/stock-chart-series?code=abc')
        pr.add('非法代码 400', r_bad.status_code == 400, r_bad.get_json().get('error', ''), '边界')

        if fast:
            pr.add('快速模式跳过行情拉取', True, '使用 --fast', '性能')
            return

        r = client.get('/api/stock-chart-series?code=600519')
        if r.status_code != 200:
            pr.add('600519 图表数据（需网络）', False, r.get_json().get('error', r.status_code), '数据')
            return

        data = r.get_json()
        series = data.get('series', [])
        pr.add('返回 series 非空', len(series) > 5, f'{len(series)} 点', '数据')
        pr.add('含 code/name', data.get('code') == '600519' and bool(data.get('name')), data.get('name', ''), '准确性')

        if series:
            pt = series[0]
            pr.add('OHLC 字段完整', all(k in pt for k in ('date', 'open', 'high', 'low', 'close')),
                   str(pt), '数据质量')
            pr.add('收盘价 > 0', float(pt.get('close', 0)) > 0, str(pt.get('close')), '准确性')

        pr.add('含 realtime', bool(data.get('realtime')), '', '数据')


@run_phase(4, '页面路由与导航入口')
def phase4_routes_nav(pr: PhaseResult):
    from app import app

    with app.test_client() as client:
        pages = [
            ('/stock-browse', b'browseSearchInput', '股票发现页'),
            ('/search', b'browse-promo-banner', '查询页发现入口'),
            ('/stock-chart?code=600519', b'stockEchart', 'ECharts 行情页'),
        ]
        for path, marker, label in pages:
            r = client.get(path)
            pr.add(label, r.status_code == 200 and marker in r.data, str(r.status_code), '功能')

        base = (ROOT / 'templates' / 'base.html').read_text(encoding='utf-8')
        pr.add('侧栏「股票发现」', "url_for('stock_browse')" in base or 'stock-browse' in base, '', '导航')

        dash = (ROOT / 'templates' / 'dashboard.html').read_text(encoding='utf-8')
        pr.add('工作台发现入口', "stock_browse" in dash, '', '导航')

        search = (ROOT / 'templates' / 'search.html').read_text(encoding='utf-8')
        pr.add('查询页链到发现', 'stock_browse' in search, '', '导航')


@run_phase(5, '前端静态资源与样式')
def phase5_frontend_assets(pr: PhaseResult):
    files = {
        'stock-chart-echarts.js': ROOT / 'static' / 'js' / 'stock-chart-echarts.js',
        'stock_browse.html': ROOT / 'templates' / 'stock_browse.html',
        'stock_chart.html': ROOT / 'templates' / 'stock_chart.html',
    }
    for name, path in files.items():
        pr.add(f'文件存在 {name}', path.exists(), str(path), '完整性')

    echarts_js = files['stock-chart-echarts.js'].read_text(encoding='utf-8')
    pr.add('StockChartEcharts.init', 'StockChartEcharts' in echarts_js and 'init' in echarts_js, '', '功能')
    pr.add('支持 candle/line', 'candle' in echarts_js and 'line' in echarts_js, '', '功能')

    chart_html = files['stock_chart.html'].read_text(encoding='utf-8')
    pr.add('引用 echarts CDN', 'echarts' in chart_html, '', '前端')
    pr.add('调用 chart-series API', '/api/stock-chart-series' in chart_html, '', '前端')
    pr.add('折线/K线切换按钮', 'lineBtn' in chart_html and 'candleBtn' in chart_html, '', 'UX')

    browse_html = files['stock_browse.html'].read_text(encoding='utf-8')
    pr.add('分类卡片网格', 'browse-stock-grid' in browse_html, '', 'UI')
    pr.add('集成 StockSearch', 'StockSearch.init' in browse_html, '', '功能')

    css = (ROOT / 'static' / 'css' / 'app.css').read_text(encoding='utf-8')
    pr.add('CSS 发现页样式', '.browse-stock-card' in css, '', 'UI')
    pr.add('CSS ECharts 容器', '.chart-echarts-wrap' in css, '', 'UI')


@run_phase(6, '整体联调与放行门禁')
def phase6_integration(pr: PhaseResult):
    from app import app
    from model.stock_browse import get_browse_payload
    from model.stock_search import resolve_stock_query
    fast = getattr(phase6_integration, '_fast', False)

    payload = get_browse_payload(with_quotes=False)
    codes = []
    for cat in payload.get('categories', []):
        for s in cat.get('stocks', []):
            codes.append(s['code'])
    pr.add('旅程-发现池非空', len(codes) >= 10, f'{len(codes)} 只', 'E2E')

    code, err = resolve_stock_query('比亚迪')
    pr.add('旅程-名称解析比亚迪', code == '002594' and not err, code or err, 'E2E')

    with app.test_client() as client:
        r1 = client.get('/api/stock-browse')
        d1 = r1.get_json()
        pr.add('旅程-发现 API', r1.status_code == 200 and d1.get('total_stocks', 0) > 0,
               str(d1.get('total_stocks')), 'E2E')

        r2 = client.get('/api/stock-chart-series?code=' + (code or '002594'))
        if fast:
            pr.add('旅程-图表 API 路由可达', r2.status_code in (200, 500), str(r2.status_code), 'E2E')
        elif r2.status_code == 200:
            s2 = r2.get_json().get('series', [])
            pr.add('旅程-比亚迪图表', len(s2) > 0, f'{len(s2)} 点', 'E2E')
        else:
            pr.add('旅程-比亚迪图表（需网络）', False, r2.get_json().get('error', ''), 'E2E')

        r3 = client.get('/stock-chart?code=002594')
        pr.add('旅程-行情页 200', r3.status_code == 200 and b'stockEchart' in r3.data, '', 'E2E')

        r4 = client.get('/stock-browse')
        pr.add('旅程-发现页 200', r4.status_code == 200, '', 'E2E')

    t0 = time.time()
    get_browse_payload(with_quotes=False)
    elapsed = time.time() - t0
    pr.add('发现数据（无行情）< 5s', elapsed < 5.0, f'{elapsed:.2f}s', '性能')


PHASE_FUNCS = {
    1: phase1_browse_module,
    2: phase2_browse_api,
    3: phase3_chart_series_api,
    4: phase4_routes_nav,
    5: phase5_frontend_assets,
    6: phase6_integration,
}


def main():
    parser = argparse.ArgumentParser(description='股票发现 + ECharts 可视化 分阶段验收')
    parser.add_argument('--phase', type=str, default='all', help='1 或 1,2,3 或 all')
    parser.add_argument('--fast', action='store_true', help='跳过慢速网络联调（阶段 3/6 部分项）')
    args = parser.parse_args()

    if args.phase == 'all':
        phases = sorted(PHASE_FUNCS.keys())
    else:
        phases = [int(p.strip()) for p in args.phase.split(',')]

    if args.fast:
        phase3_chart_series_api._fast = True
        phase6_integration._fast = True

    print('\n' + '█' * 60)
    print('  数境智投 · 股票发现 + 可视化 分阶段验收')
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
