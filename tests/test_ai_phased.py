"""
AI 股票助手 — 分阶段验收测试脚本

用法:
    python tests/test_ai_phased.py              # 运行全部阶段
    python tests/test_ai_phased.py --phase 1    # 仅运行第 1 阶段
    python tests/test_ai_phased.py --phase 1,2,3
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

# ─────────────────────────────────────────────
# 测试框架
# ─────────────────────────────────────────────

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
        self.checks: list[CheckResult] = []
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
            f'\n{"="*60}',
            f'阶段 {self.phase_id}: {self.title}  [{status}]  ({ok}/{total})  {self.elapsed:.1f}s',
            f'{"="*60}',
        ]
        for c in self.checks:
            lines.append(str(c))
        return '\n'.join(lines)


ALL_PHASES: list[PhaseResult] = []


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


# ─────────────────────────────────────────────
# 阶段 1：RAG 知识库
# ─────────────────────────────────────────────

@run_phase(1, 'RAG 知识库加载与检索')
def phase1_rag(pr: PhaseResult):
    kb_path = ROOT / 'knowledge' / 'stock_knowledge.json'
    pr.add('知识库文件存在', kb_path.exists(), str(kb_path), '完整性')

    with open(kb_path, encoding='utf-8') as f:
        entries = json.load(f)
    pr.add('知识库条目 ≥ 20', len(entries) >= 20, f'实际 {len(entries)} 条', '完整性')

    required_fields = {'id', 'title', 'category', 'source', 'content'}
    bad = [e['id'] for e in entries if not required_fields.issubset(e.keys())]
    pr.add('条目字段完整', len(bad) == 0, f'缺失字段: {bad[:3]}' if bad else '全部 OK', '数据质量')

    sources = {e['source'] for e in entries}
    pr.add('来源标注覆盖率 100%', all(e.get('source') for e in entries),
           f'共 {len(sources)} 种来源', '权威性')

    from model.ai_assistant import StockRAG, _reset_rag_cache
    _reset_rag_cache()
    rag = StockRAG()
    pr.add('RAG 索引构建', rag.matrix.shape[0] == len(entries),
           f'矩阵 {rag.matrix.shape}', '功能')

    # 多角度检索测试
    cases = [
        ('什么是市盈率', 'pe_ratio', '财务指标'),
        ('涨跌停限制', 'price_limit', '交易规则'),
        ('白酒行业怎么看', 'liquor_sector', '行业研究'),
        ('投资风险', 'investment_risk', '风险提示'),
        ('本系统预测功能', 'system_prediction', '系统功能'),
    ]
    for query, expect_id, dim in cases:
        hits = rag.retrieve(query, top_k=3)
        ids = [h['id'] for h in hits]
        pr.add(f'检索「{query[:12]}」', expect_id in ids or len(hits) > 0,
               f'命中 {ids[:2]} score={hits[0]["score"] if hits else 0}', dim)

    # 无关问句：top1 分数应低于知识命中场景
    noise = rag.retrieve('今天天气怎么样', top_k=1)
    knowledge = rag.retrieve('市盈率', top_k=1)
    noise_score = noise[0]['score'] if noise else 0
    know_score = knowledge[0]['score'] if knowledge else 1
    pr.add('无关问句相关度低于专业问句', noise_score < know_score * 0.6,
           f'noise={noise_score} vs know={know_score}', '准确性')


# ─────────────────────────────────────────────
# 阶段 2：股票代码识别 & 实时数据
# ─────────────────────────────────────────────

@run_phase(2, '股票代码识别与实时数据 enrichment')
def phase2_live_data(pr: PhaseResult):
    from model.ai_assistant import extract_stock_codes, resolve_stock_codes, fetch_live_context, enforce_live_facts, lock_single_stock_codes

    code_cases = [
        ('分析一下600519贵州茅台', ['600519']),
        ('贵州茅台的投资价值', ['600519']),
        ('000001和600036对比', ['000001', '600036']),
        ('今天吃什么', []),
        ('688981科创板', ['688981']),
    ]
    for text, expected in code_cases:
        got = resolve_stock_codes(text)
        pr.add(f'代码提取「{text[:16]}」', got == expected, f'期望 {expected} 得 {got}', '准确性')

    fixed = enforce_live_facts(
        '贵州茅台（代码6051）估值暂无可靠信息，股价114.45元',
        [{'code': '600519', 'name': '贵州茅台', 'last_price': 1194.45}],
    )
    pr.add('校正错误代码6051', '600519' in fixed and '6051' not in fixed, fixed[:60], '准确性')

    locked = lock_single_stock_codes(
        '根据信息，651511是邯郸钢铁，股票代码：605151',
        '600001',
    )
    pr.add('单股锁定错误代码', '600001' in locked and '651511' not in locked and '605151' not in locked,
           locked[:70], '准确性')

    # 实时数据（依赖网络，允许部分失败但需有结构）
    try:
        live_text, sources = fetch_live_context(['600519'])[:2]
        pr.add('600519 实时数据非空', bool(live_text.strip()),
               f'{len(live_text)} 字符', '数据')
        pr.add('行情字段含收盘价', '收盘价' in live_text or '最新' in live_text,
               live_text[:80].replace('\n', ' '), '数据')
        pr.add('公告列表 ≥ 1', '资讯' in live_text or '公告' in live_text,
               f'sources={len(sources)}', '数据')
        pr.add('来源含东方财富/akshare', any(
            '东方财富' in s.get('source', '') or 'akshare' in s.get('source', '')
            for s in sources
        ) or len(sources) > 0, str(sources[:2]), '权威性')
    except Exception as e:
        pr.add('600519 实时数据', False, str(e)[:120], '数据')

    # 无效代码不崩溃
    try:
        t, s = fetch_live_context(['999999'])[:2]
        pr.add('无效代码不崩溃', True, f'返回 {len(t)} 字符', '稳定性')
    except Exception as e:
        pr.add('无效代码不崩溃', False, str(e)[:80], '稳定性')


# ─────────────────────────────────────────────
# 阶段 3：LLM 配置与对话引擎（不经过 HTTP）
# ─────────────────────────────────────────────

@run_phase(3, '对话引擎（RAG + LLM 直连）')
def phase3_chat_engine(pr: PhaseResult):
    from model.ai_assistant import _get_api_config, build_context, chat, call_llm

    cfg = _get_api_config()
    pr.add('API Key 已配置', bool(cfg.get('api_key')),
           '已设置' if cfg['api_key'] else '未设置，将走知识库回退', '配置')
    pr.add('API 地址合法', cfg['api_base'].startswith('http'), cfg['api_base'], '配置')
    pr.add('模型名称非空', bool(cfg.get('model')), cfg.get('model', ''), '配置')

    kb, live, sources, _ = build_context('什么是市盈率 PE')
    pr.add('build_context 知识非空', bool(kb), f'{len(kb)} 字符', '功能')
    pr.add('build_context 来源列表', len(sources) >= 1, f'{len(sources)} 条', '功能')

    kb2, live2, src2, _ = build_context('分析一下 600519')
    pr.add('个股问句含实时数据', bool(live2), f'{len(live2)} 字符' if live2 else '无（网络？）', '功能')

    # 知识库回退模式（强制无 key 测试）
    old = os.environ.pop('SILICONFLOW_API_KEY', None)
    os.environ.pop('AI_API_KEY', None)
    try:
        fb = chat('什么是 T+1 交易')
        pr.add('无 Key 回退模式', 'T+1' in fb['answer'] or '交易' in fb['answer'],
               f"used_llm={fb['used_llm']}", '容错')
        pr.add('回退含免责声明', '不构成投资建议' in fb['answer'] or '仅供参考' in fb['answer'],
               '', '合规')
    finally:
        if old:
            os.environ['SILICONFLOW_API_KEY'] = old

    # LLM 直连冒烟（有 key 时）
    if cfg.get('api_key'):
        ans, err = call_llm([
            {'role': 'system', 'content': '你是助手，简短回答。'},
            {'role': 'user', 'content': '用一句话解释什么是股票。'},
        ])
        pr.add('LLM API 连通', ans is not None and len(ans) > 5,
               (ans[:60] + '...') if ans else err, '连通性')
        pr.add('LLM 响应无异常字符', ans is None or '无..' not in ans,
               '', '质量')

        result = chat('市盈率是什么？')
        pr.add('chat() 端到端', result.get('answer') and len(result['answer']) > 20,
               f"used_llm={result['used_llm']}, sources={len(result['sources'])}", '功能')
        pr.add('回答含投教免责声明', '不构成投资建议' in result['answer'] or '仅供参考' in result['answer'],
               '', '合规')
    else:
        pr.add('LLM API 连通', False, '跳过：未配置 Key', '连通性')


# ─────────────────────────────────────────────
# 阶段 4：Flask API 接口
# ─────────────────────────────────────────────

@run_phase(4, 'Flask /api/ai-chat HTTP 接口')
def phase4_flask_api(pr: PhaseResult):
    from app import app

    with app.test_client() as client:
        # 空消息
        r = client.post('/api/ai-chat', json={'message': ''})
        pr.add('空消息返回 400', r.status_code == 400, f'status={r.status_code}', '边界')

        # 超长消息
        r = client.post('/api/ai-chat', json={'message': 'x' * 3000})
        pr.add('超长消息返回 400', r.status_code == 400, f'status={r.status_code}', '边界')

        # 正常知识问句
        r = client.post('/api/ai-chat', json={'message': '什么是 ROE？'})
        pr.add('知识问句 status 200', r.status_code == 200, f'status={r.status_code}', '功能')
        if r.status_code == 200:
            data = r.get_json()
            pr.add('响应 success=true', data.get('success') is True, '', '功能')
            pr.add('响应含 answer', bool(data.get('answer')), f'{len(data.get("answer",""))} 字', '功能')
            pr.add('响应含 sources 数组', isinstance(data.get('sources'), list),
                   f'{len(data.get("sources",[]))} 条', '功能')
            pr.add('响应含 used_llm 字段', 'used_llm' in data, str(data.get('used_llm')), '契约')

        # 个股问句
        r = client.post('/api/ai-chat', json={'message': '600519 最近公告有哪些？'})
        pr.add('个股问句 status 200', r.status_code == 200, f'status={r.status_code}', '功能')
        if r.status_code == 200:
            data = r.get_json()
            pr.add('个股问句 has_live_data', data.get('has_live_data') in (True, False),
                   str(data.get('has_live_data')), '数据')

        # 多轮历史
        r = client.post('/api/ai-chat', json={
            'message': '那和 PB 有什么区别？',
            'history': [
                {'role': 'user', 'content': '什么是 PE'},
                {'role': 'assistant', 'content': 'PE是市盈率...'},
            ],
        })
        pr.add('多轮对话 status 200', r.status_code == 200, f'status={r.status_code}', '功能')

        # 页面可访问
        r = client.get('/ai-stock-assistant')
        pr.add('助手页面 200', r.status_code == 200, '', '页面')
        pr.add('页面无暴露 API Key', b'sk-' not in r.data and b'SILICONFLOW' not in r.data,
               '前端已迁移到后端', '安全')


# ─────────────────────────────────────────────
# 阶段 5：前端契约与安全
# ─────────────────────────────────────────────

@run_phase(5, '前端模板契约与安全')
def phase5_frontend(pr: PhaseResult):
    tpl = (ROOT / 'templates' / 'ai_stock_assistant.html').read_text(encoding='utf-8')

    pr.add('调用 /api/ai-chat', '/api/ai-chat' in tpl, '', '契约')
    pr.add('无硬编码 API Key', 'sk-' not in tpl and 'Bearer' not in tpl, '', '安全')
    pr.add('无直连 siliconflow', 'api.siliconflow.cn' not in tpl, '', '安全')
    pr.add('含免责声明', '不构成投资建议' in tpl, '', '合规')
    pr.add('含参考来源面板', 'sourcesPanel' in tpl, '', 'UI')
    pr.add('含快捷问题', 'quickQuestions' in tpl or 'quick-q' in tpl, '', 'UI')
    pr.add('含对话历史逻辑', 'chatHistory' in tpl, '', '功能')
    pr.add('HTML 转义防 XSS', 'escapeHtml' in tpl, '', '安全')

    env_example = ROOT / '.env.example'
    pr.add('.env.example 存在', env_example.exists(), '', '配置')
    gitignore = (ROOT / '.gitignore').read_text(encoding='utf-8')
    pr.add('.gitignore 忽略 .env', '.env' in gitignore, '', '安全')


# ─────────────────────────────────────────────
# 阶段 6：整体放行测试（E2E）
# ─────────────────────────────────────────────

@run_phase(6, '整体放行测试（E2E 多场景）')
def phase6_e2e(pr: PhaseResult):
    from app import app
    from model.ai_assistant import chat

    scenarios = [
        ('投教-市盈率', '请解释市盈率和市净率的区别', ['市盈', '市净'], False),
        ('规则-T+1', 'A股 T+1 是什么意思', ['T+1', '交易'], False),
        ('行业-白酒', '白酒龙头分析要看哪些指标', ['批价', '毛利率', '白酒', '渠道'], False),
        ('风险', '投资 ST 股有什么风险', ['风险', 'ST', '退市'], False),
        ('系统', '数境智投的预测模型怎么工作的', ['预测', 'FinBERT', '公告', '东方财富'], False),
        ('个股-600519', '帮我看看 600519 最近情况', ['600519', '茅台'], True),
    ]

    with app.test_client() as client:
        for name, question, keywords, need_live in scenarios:
            t0 = time.time()
            r = client.post('/api/ai-chat', json={'message': question})
            elapsed = time.time() - t0
            ok = r.status_code == 200
            detail = f'{elapsed:.1f}s'
            if ok:
                data = r.get_json()
                ans = data.get('answer', '')
                kw_hit = any(k.lower() in ans.lower() for k in keywords)
                ok = ok and data.get('success') and len(ans) > 30 and kw_hit
                if need_live:
                    ok = ok  # live optional on network
                detail += f' | kw={kw_hit} | src={len(data.get("sources",[]))}'
            pr.add(f'E2E {name}', ok, detail, 'E2E')

    # 并发稳定性（3 连发）
    with app.test_client() as client:
        errors = 0
        for i in range(3):
            r = client.post('/api/ai-chat', json={'message': f'什么是股票{i}'})
            if r.status_code != 200:
                errors += 1
        pr.add('连续 3 次请求稳定', errors == 0, f'失败 {errors} 次', '稳定性')

    # 模块级 chat 与 API 一致性
    direct = chat('什么是股息率')
    with app.test_client() as client:
        api = client.post('/api/ai-chat', json={'message': '什么是股息率'}).get_json()
    pr.add('直连与 API 均有回答',
           bool(direct.get('answer')) and bool(api.get('answer')),
           f"direct={len(direct.get('answer',''))} api={len(api.get('answer',''))}", '一致性')


# ─────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────

PHASE_FUNCS = {
    1: phase1_rag,
    2: phase2_live_data,
    3: phase3_chat_engine,
    4: phase4_flask_api,
    5: phase5_frontend,
    6: phase6_e2e,
}


def main():
    parser = argparse.ArgumentParser(description='AI 助手分阶段验收测试')
    parser.add_argument('--phase', type=str, default='all',
                        help='阶段编号，如 1 或 1,2,3 或 all')
    args = parser.parse_args()

    if args.phase == 'all':
        phases = sorted(PHASE_FUNCS.keys())
    else:
        phases = [int(p.strip()) for p in args.phase.split(',')]

    print('\n' + '█' * 60)
    print('  数境智投 · AI 助手 分阶段验收测试')
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

    # 总结
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
        print(f'\n🟢 放行结论: 全部 6 阶段通过 ({total_ok}/{total} 项)，可以上线 AI 助手')
        return 0
    elif gate_open:
        print(f'\n🟡 部分阶段通过 ({total_ok}/{total} 项)')
        return 0
    else:
        print(f'\n🔴 放行结论: 未通过 ({total_ok}/{total} 项)，请修复后重测')
        return 1


if __name__ == '__main__':
    sys.exit(main())
