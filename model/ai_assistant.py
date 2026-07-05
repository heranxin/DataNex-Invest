"""
AI 股票助手：RAG 知识检索 + 实时行情/新闻 + 大模型 API。
API Key 通过环境变量配置，切勿写入前端代码。
"""
import json
import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import requests
from requests.adapters import HTTPAdapter
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
KNOWLEDGE_FILE = ROOT / 'knowledge' / 'stock_knowledge.json'
INDEX_FILE = ROOT / 'knowledge' / 'rag_index.joblib'

_rag_cache = None
_session_local = threading.local()
_KB_CHUNK_MAX = 420
_LIVE_NEWS_MAX = 3


def _reset_rag_cache():
    global _rag_cache
    _rag_cache = None

SYSTEM_PROMPT = """你是「数境智投」AI 股票助手，面向 A 股投资者提供客观、专业的知识解答。

回答要求：
1. 优先依据【知识库参考】和【实时数据】作答，不要编造不存在的政策、数据、股价或时间。
2. 若【实时数据】中有具体股票行情与公告，必须结合这些数据作答；已有收盘价时不得写「暂无可靠信息」。
3. 引用权威来源时注明出处（如证监会、交易所规则、知识库条目来源）。
4. 涉及具体投资建议时，必须提醒「仅供参考，不构成投资建议」。
5. 不确定的内容明确说「暂无可靠信息」，不要猜测。
6. 回答结构清晰，使用简洁中文，**分 3～5 点完整阐述**，一般 400～800 字，每点写完整句子，**禁止半途截断**。
7. **禁止使用 Markdown 标题符号**（不要用 #、##、###），用「1. 2. 3.」或「一、二、三」分点即可。
8. 禁止自行编写「截至 XX:XX」之类的时间戳；系统会在文末补充数据更新时间。
9. 分析个股投资价值时，必须覆盖：估值（PE/PB，引用系统数据）、盈利能力（ROE/现金流）、分红、行业地位、**主要风险**、**简要结论**。
10. A 股代码必须为 6 位数字（如贵州茅台是 **600519**、中国平安是 **601318**），不得写错或截断。
11. 用户指定分析某只股票时，全文只能讨论该股票代码，禁止出现其他股票代码或张冠李戴。
12. 涉及分红、股息再投资等问题时，需解释概念、适用场景、风险与示例，不要只列一条就结束。
13. **术语必须准确**：市盈率=PE，市净率=PB，市现率=PCF；**禁止把 PE 写成 PF**；不得混淆指标含义。
14. 系统已注入【基本面指标】时，**必须引用具体数字**进行分析对比；**禁止**写「需用户补充最新财报」「需用户验证」等推责表述。
15. 个股分析最后必须有「风险与结论」小结，明确说明数据局限，但不推卸数据责任。
16. 涉及国内公募 REITs：负债率监管上限约 28.6%（总资产≤净资产140%），禁止套用海外「负债率50%」标准；封闭式基金不能向基金公司赎回，场内 T+1 交易。
17. 涉及黄金投资：首饰金无投资价值；黄金 ETF 场内可正常卖出，勿夸大「无法赎回」；实物金条仅适合少量长期兜底配置。"""


def _load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / '.env')
    except ImportError:
        pass


def _get_api_config():
    _load_env()
    max_tokens = int(os.getenv('AI_MAX_TOKENS', '1800'))
    api_key = (os.getenv('SILICONFLOW_API_KEY') or os.getenv('AI_API_KEY', '')).strip().strip('"').strip("'")
    return {
        'api_key': api_key,
        'api_base': os.getenv('AI_API_BASE', 'https://api.siliconflow.cn/v1/chat/completions'),
        'model': os.getenv('AI_MODEL', 'Qwen/Qwen2.5-7B-Instruct'),
        'max_tokens': max(512, min(max_tokens, 2048)),
    }


def _new_http_session():
    """创建独立 HTTP 会话，避免多用户并发时共享会话互相影响。"""
    session = requests.Session()
    # 避免服务器上残留的 HTTP(S)_PROXY 环境变量干扰 LLM 调用并触发编码异常
    session.trust_env = False
    session.proxies = {}
    adapter = HTTPAdapter(pool_connections=32, pool_maxsize=32)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session


def _get_http_session():
    """每个线程一个会话，提升并发稳定性。"""
    session = getattr(_session_local, 'session', None)
    if session is None:
        session = _new_http_session()
        _session_local.session = session
    return session


class StockRAG:
    def __init__(self):
        with open(KNOWLEDGE_FILE, encoding='utf-8') as f:
            self.entries = json.load(f)
        self.texts = [
            f"{e['title']} {e['category']} {e['content']}" for e in self.entries
        ]
        # 字符 n-gram 更适合中文短问句检索
        self.vectorizer = TfidfVectorizer(
            analyzer='char_wb', ngram_range=(2, 4), max_features=10000,
        )
        self.matrix = self.vectorizer.fit_transform(self.texts)

    def retrieve(self, query, top_k=5):
        if not query.strip():
            return []
        q_vec = self.vectorizer.transform([query])
        scores = cosine_similarity(q_vec, self.matrix)[0]
        indices = np.argsort(scores)[::-1][:top_k]
        results = []
        for idx in indices:
            if scores[idx] <= 0:
                continue
            entry = self.entries[int(idx)].copy()
            entry['score'] = round(float(scores[idx]), 4)
            results.append(entry)
        return results


def get_rag():
    global _rag_cache
    if _rag_cache is not None:
        return _rag_cache
    if INDEX_FILE.exists() and KNOWLEDGE_FILE.exists():
        if KNOWLEDGE_FILE.stat().st_mtime > INDEX_FILE.stat().st_mtime:
            try:
                INDEX_FILE.unlink()
            except OSError:
                pass
    if INDEX_FILE.exists():
        try:
            data = joblib.load(INDEX_FILE)
            rag = StockRAG.__new__(StockRAG)
            rag.entries = data['entries']
            rag.texts = data.get('texts') or [
                f"{e['title']} {e['category']} {e['content']}" for e in rag.entries
            ]
            rag.vectorizer = data['vectorizer']
            rag.matrix = data['matrix']
            _rag_cache = rag
            return _rag_cache
        except Exception as e:
            logger.warning('RAG 索引加载失败，将重新构建: %s', e)
    _rag_cache = StockRAG()
    try:
        INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            'vectorizer': _rag_cache.vectorizer,
            'matrix': _rag_cache.matrix,
            'entries': _rag_cache.entries,
            'texts': _rag_cache.texts,
        }, INDEX_FILE)
    except Exception as e:
        logger.warning('RAG 索引保存失败: %s', e)
    return _rag_cache


A_SHARE_CODE_RE = re.compile(
    r'(?<!\d)((?:600|601|603|605|688|000|001|002|003|300)\d{3})(?!\d)'
)

# 常见 A 股简称 → 代码（按名称长度降序匹配，避免「茅台」误伤）
STOCK_ALIASES = {
    '贵州茅台': '600519', '五粮液': '000858', '泸州老窖': '000568',
    '宁德时代': '300750', '比亚迪': '002594', '中国平安': '601318',
    '招商银行': '600036', '平安银行': '000001', '工商银行': '601398',
    '兴业银行': '601166', '中信证券': '600030', '华泰证券': '601688',
    '隆基绿能': '601012', '紫金矿业': '601899', '山东黄金': '600547',
    '长江电力': '600900', '万科': '000002', '恒瑞医药': '600276',
    '长春高新': '000661', '茅台': '600519',
}

STOCK_CODE_TO_NAME = {
    '600001': '邯郸钢铁', '600519': '贵州茅台', '000858': '五粮液', '000568': '泸州老窖',
    '300750': '宁德时代', '002594': '比亚迪', '601318': '中国平安',
    '600036': '招商银行', '000001': '平安银行', '601398': '工商银行',
    '601166': '兴业银行', '600030': '中信证券', '601688': '华泰证券',
    '601012': '隆基绿能', '601899': '紫金矿业', '600547': '山东黄金',
    '600900': '长江电力', '000002': '万科A', '600276': '恒瑞医药',
    '000661': '长春高新',
}


def extract_stock_codes(text):
    return list(dict.fromkeys(A_SHARE_CODE_RE.findall(text)))[:3]


def resolve_stock_codes(text):
    """从 6 位代码或股票简称中解析标的。"""
    codes = extract_stock_codes(text)
    for alias, code in sorted(STOCK_ALIASES.items(), key=lambda x: -len(x[0])):
        if alias in text and code not in codes:
            codes.append(code)
    return codes[:3]


def sanitize_answer(text):
    """清理模型偶发的错误时间戳、裸露 Markdown 与重复免责。"""
    if not text:
        return text
    text = re.sub(
        r'[（(]?注[：:]\s*上述分析基于截至[^）)\n]*[）)]?',
        '',
        text,
    )
    text = re.sub(
        r'截至\s*\d{1,2}\s*:\s*\d{1,2}(?!\d)',
        '',
        text,
    )
    # 去掉孤立 # 行、行首多余 #
    text = re.sub(r'(?m)^#{1,6}\s*$', '', text)
    text = re.sub(r'(?m)^#{1,6}\s+', '', text)
    text = fix_alias_stock_codes(text)
    text = fix_financial_terminology(text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def fix_financial_terminology(text):
    """纠正模型偶发的财务术语笔误。"""
    if not text:
        return text
    text = re.sub(r'PF\s*[（(]\s*市盈率\s*[）)]', 'PE（市盈率）', text, flags=re.I)
    text = re.sub(r'[（(]\s*PF\s*[）)]', '（PE）', text, flags=re.I)
    text = re.sub(r'(?<![A-Za-z])PF(?=\s*[（(])', 'PE', text)
    text = re.sub(r'当前\s*PF\b', '当前 PE', text, flags=re.I)
    text = re.sub(r'\bPF\s*[=＝]', 'PE=', text)
    return text


def remove_shirking_phrases(answer, live_facts):
    """有注入数据时去掉「需用户补充财报」类推责表述。"""
    if not answer or not live_facts:
        return answer
    has_metrics = any(
        f.get('pe_ttm') is not None or f.get('pb') is not None or f.get('last_price') is not None
        for f in live_facts
    )
    if not has_metrics:
        return answer
    answer = re.sub(r'[（(]?需用户补充[^）)\n]*[）)]?', '', answer)
    answer = re.sub(r'需用户补充[^。\n]*', '', answer)
    answer = re.sub(r'需补充最新财报[^。\n]*。?', '', answer)
    answer = re.sub(r'\(需.*?验证\)', '', answer)
    return answer


def looks_truncated(text, is_stock_analysis=False):
    """检测回答是否疑似被截断。"""
    if not text:
        return False
    stripped = text.strip()
    if is_stock_analysis and len(stripped) < 280:
        return True
    if stripped.endswith(('需警惕', '需关注', '需注意', '若高于', '若低于', '但由于', '然而', '同时')):
        return True
    if is_stock_analysis and not re.search(r'(风险|结论|小结|综上|总结)', stripped[-120:]):
        if len(stripped) > 180:
            return True
    tail = stripped[-1]
    if len(stripped) > 220 and tail not in '。！？.!?）)」"':
        return True
    return False


def complete_truncated_answer(messages, partial, config, temperature):
    """对截断回答做一次续写补全。"""
    cont_messages = list(messages) + [
        {'role': 'assistant', 'content': partial},
        {
            'role': 'user',
            'content': (
                '上一段分析未完成，请从断点续写并补全剩余要点：'
                '行业估值对比、主要风险、结论小结。'
                '不要重复已有内容；术语市盈率必须写 PE，禁止写 PF；'
                '必须写完整句并以句号结束。'
            ),
        },
    ]
    cont_config = {**config, 'max_tokens': min(1024, config.get('max_tokens', 1800))}
    more, _ = call_llm(cont_messages, config=cont_config, temperature=temperature)
    if more:
        return partial.rstrip() + '\n' + more.strip()
    return partial


# 模型常写错的知名股票代码 → 正确代码
_ALIAS_CODE_FIXES = [
    ('贵州茅台', '600519', ('60551', '651511', '600551', '605519')),
    ('茅台', '600519', ('60551', '651511', '600551')),
    ('中国平安', '601318', ('60022', '600022', '60122', '60318')),
    ('平安', '601318', ('60022', '600022')),
    ('宁德时代', '300750', ('30075', '30750')),
    ('比亚迪', '002594', ('2594', '00259')),
    ('五粮液', '000858', ('858', '00858')),
]


def fix_alias_stock_codes(text):
    if not text:
        return text
    for name, correct, wrong_list in _ALIAS_CODE_FIXES:
        if name not in text:
            continue
        for wrong in wrong_list:
            text = re.sub(
                rf'(?<![0-9]){re.escape(wrong)}(?![0-9])',
                correct,
                text,
            )
    return text


def enforce_live_facts(answer, facts):
    """校正模型偶发截断或编造的股票代码与价格。"""
    if not answer or not facts:
        return answer

    target_codes = [str(f.get('code', '')).zfill(6) for f in facts if f.get('code')]

    for f in facts:
        code = str(f.get('code', '')).zfill(6)
        name = f.get('name') or STOCK_CODE_TO_NAME.get(code, code)
        price = f.get('last_price')

        if len(code) == 6:
            answer = re.sub(
                rf'股票代码[：:]\s*(?!{re.escape(code)})\d{{4,6}}\b',
                f'股票代码：{code}',
                answer,
            )
            answer = re.sub(
                rf'代码[：:]\s*(?!{re.escape(code)})\d{{4,6}}\b',
                f'代码：{code}',
                answer,
            )
            answer = re.sub(
                rf'[（(]\s*代码[：:]?\s*(?!{re.escape(code)})\d{{4,6}}\s*[）)]',
                f'（代码 {code}）',
                answer,
            )
            if name and not str(name).isdigit() and name in answer:
                answer = re.sub(
                    rf'({re.escape(name)}[（(]\s*代码[：:]?\s*)(?!{re.escape(code)})\d{{4,6}}(\s*[）)]?)',
                    rf'\1{code}\2',
                    answer,
                )

        if price is not None:
            correct = float(price)
            price_fmt = f'{correct:.2f}'

            def _replace_bad_price(match):
                found = float(match.group(1))
                if abs(found - correct) < 0.02:
                    return match.group(0)
                if correct >= 100 and found < correct * 0.35:
                    return f'{price_fmt}{match.group(2)}'
                if abs(found * 10 - correct) < 2 or abs(found * 100 - correct) < 20:
                    return f'{price_fmt}{match.group(2)}'
                return match.group(0)

            answer = re.sub(
                r'(\d+(?:\.\d+)?)(\s*元)',
                _replace_bad_price,
                answer,
            )

    if len(target_codes) == 1:
        answer = lock_single_stock_codes(answer, target_codes[0])

    return answer


def lock_single_stock_codes(answer, code):
    """单股分析：将正文中其他股票代码统一为目标代码，杜绝张冠李戴。"""
    code = str(code).zfill(6)
    if not answer or not code:
        return answer

    # 「651511是邯郸钢铁」类表述
    answer = re.sub(
        rf'(?<!\d)\d{{6}}(?=\s*是)',
        code,
        answer,
    )
    # 标准 A 股代码格式
    answer = A_SHARE_CODE_RE.sub(
        lambda m: m.group(1) if m.group(1) == code else code,
        answer,
    )
    return answer


def remove_false_unknowns(answer, facts):
    """有行情时去掉模型误报的「暂无可靠信息」。"""
    has_price = any(f.get('last_price') is not None for f in facts)
    if not has_price:
        return answer
    lines = []
    for line in answer.splitlines():
        if re.search(r'暂无.*可靠信息|无可靠信息|暂无具体', line, re.I):
            if re.search(r'股价|收盘|价格|市盈|PE|PB|估值|盈利|分红', line, re.I):
                continue
        lines.append(line)
    return '\n'.join(lines)


def build_facts_preamble(facts):
    """在回答开头插入系统确认的准确行情，避免模型写错代码/价格。"""
    if not facts:
        return ''
    parts = ['【实时行情 · 系统数据】', '']
    for f in facts:
        code = str(f.get('code', '')).zfill(6)
        name = f.get('name') or STOCK_CODE_TO_NAME.get(code, code)
        if str(name).isdigit() or name == code:
            parts.append(f'股票 {code}')
        else:
            parts.append(f'{name}（股票代码 {code}）')
        if f.get('industry'):
            parts.append(f'- 所属行业：{f["industry"]}')
        if f.get('last_price') is not None:
            parts.append(f'- 最新收盘价：{float(f["last_price"]):.2f} 元')
        if f.get('return_5d') is not None:
            parts.append(f'- 近5日涨跌幅：{f["return_5d"]:+.2f}%')
        if f.get('return_20d') is not None:
            parts.append(f'- 近20日涨跌幅：{f["return_20d"]:+.2f}%')
        if f.get('pe_ttm') is not None:
            parts.append(f'- 市盈率 PE（动态）：{float(f["pe_ttm"]):.2f} 倍')
        if f.get('pb') is not None:
            parts.append(f'- 市净率 PB：{float(f["pb"]):.2f} 倍')
        if f.get('dividend_yield') is not None:
            parts.append(f'- 股息率：{float(f["dividend_yield"]):.2f}%')
        if f.get('roe') is not None:
            parts.append(f'- 净资产收益率 ROE：{float(f["roe"]):.2f}%')
        if f.get('eps') is not None:
            parts.append(f'- 每股收益 EPS：{float(f["eps"]):.4f} 元')
        if f.get('industry_pe_hint'):
            parts.append(f'- 行业估值参考：{f["industry_pe_hint"]}')
        if f.get('data_warning'):
            parts.append(f'- 提示：{f["data_warning"]}')
        parts.append('')
    parts.append('—' * 20)
    parts.append('')
    return '\n'.join(parts)


def _fetch_one_stock(code):
    """拉取单只股票行情与资讯（供并行调用）。"""
    blocks = []
    sources = []
    facts = []

    try:
        from model.news_analysis import (
            get_industry_valuation_hint,
            get_recent_price_context,
            get_stock_fundamentals,
            get_stock_industry,
            get_stock_name,
        )
        import utils
    except ImportError:
        return blocks, sources, facts

    try:
        code = str(code).zfill(6)
        name = get_stock_name(code)
        display_name = STOCK_CODE_TO_NAME.get(code, name)
        if str(name).isdigit():
            name = display_name
        industry = get_stock_industry(code)
        price_ctx = get_recent_price_context(code)
        fundamentals = get_stock_fundamentals(code)
        news = utils.fund_Stock_Info(code)[:_LIVE_NEWS_MAX]

        lines = [
            '【行情与基本面 — 以下数字须原样引用，代码必须为6位】',
            f'股票简称：{display_name}',
            f'股票代码：{code}',
            f'行业：{industry}',
        ]
        fact = {
            'code': code,
            'name': display_name,
            'industry': industry,
            'industry_pe_hint': get_industry_valuation_hint(industry),
        }
        fact.update({k: v for k, v in fundamentals.items() if k != 'code'})

        if price_ctx:
            last_price = float(price_ctx['last_price'])
            fact.update({
                'last_price': last_price,
                'return_5d': price_ctx['return_5d'],
                'return_20d': price_ctx['return_20d'],
            })
            lines.append(f"最新收盘价：{last_price:.2f} 元")
            lines.append(
                f"近5个交易日涨跌幅：{price_ctx['return_5d']:+.2f}%；"
                f"近20个交易日涨跌幅：{price_ctx['return_20d']:+.2f}%"
            )
            lines.append(f"行情数据来源：{price_ctx['source']}")
            sources.append({'title': f'{display_name} 行情数据', 'source': price_ctx['source']})
        else:
            warn = '未能获取有效行情，该代码可能已退市、停牌或不存在，请勿编造其他股票代码'
            fact['data_warning'] = warn
            lines.append(f'行情状态：{warn}')

        if fact.get('pe_ttm') is not None:
            lines.append(f"市盈率 PE（动态）：{float(fact['pe_ttm']):.2f} 倍")
        if fact.get('pb') is not None:
            lines.append(f"市净率 PB：{float(fact['pb']):.2f} 倍")
        if fact.get('dividend_yield') is not None:
            lines.append(f"股息率：{float(fact['dividend_yield']):.2f}%")
        if fact.get('roe') is not None:
            lines.append(f"净资产收益率 ROE：{float(fact['roe']):.2f}%")
        if fact.get('eps') is not None:
            lines.append(f"每股收益 EPS：{float(fact['eps']):.4f} 元")
        if fact.get('industry_pe_hint'):
            lines.append(f"行业估值参考：{fact['industry_pe_hint']}")
        if fundamentals:
            sources.append({'title': f'{display_name} 基本面指标', 'source': '东方财富'})

        if news:
            lines.append('近期公告/资讯：')
            for i, n in enumerate(news, 1):
                lines.append(f"  {i}. {n.text}")
                if n.link:
                    sources.append({
                        'title': n.text[:40],
                        'source': getattr(n, 'source', '东方财富'),
                        'link': n.link,
                    })

        facts.append(fact)
        blocks.append('\n'.join(lines))
    except Exception as e:
        logger.warning('获取 %s 实时数据失败: %s', code, e)

    return blocks, sources, facts


def fetch_live_context(stock_codes):
    """拉取个股实时行情与近期新闻作为 RAG 补充。"""
    if not stock_codes:
        return '', [], []

    blocks = []
    sources = []
    facts = []
    workers = min(len(stock_codes), 3)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(_fetch_one_stock, stock_codes))

    for b, s, f in results:
        blocks.extend(b)
        sources.extend(s)
        facts.extend(f)

    return '\n\n'.join(blocks), sources, facts


def _build_kb_context(query, rag):
    chunks = rag.retrieve(query, top_k=5)
    stock_codes = resolve_stock_codes(query)

    topic_keywords = []
    if stock_codes or '分析' in query or '投资价值' in query or '估值' in query:
        topic_keywords.extend(['白酒行业', '市盈率', '市净率', 'ROE', '分红', '风险'])
    if len(chunks) < 2:
        if '茅台' in query or '白酒' in query:
            topic_keywords.extend(['白酒行业', '股息率', '市盈率'])
        if '投资价值' in query or '估值' in query:
            topic_keywords.extend(['市盈率', '市净率', 'ROE', '分红'])
    if '分红' in query or '股息' in query or '再投资' in query:
        topic_keywords.extend(['分红与股息率', '价值投资', '银行'])
    if '黄金' in query or '金条' in query or 'gold' in query.lower():
        topic_keywords.extend(['黄金投资科普', '资产配置', '分散投资'])
    if 'reit' in query.lower() or 'REIT' in query or '不动产' in query or '基础设施' in query:
        topic_keywords.extend(['公募REITs投资科普', '资产配置', '分散投资'])
    if any(k in query for k in ('基金', 'ETF', 'etf', 'LOF', '定投', '指数基', '债基', '可转债')):
        topic_keywords.extend(['公募基金基础', '指数基金与主动', '债券基金', 'ETF与LOF'])
    if any(k in query for k in ('止盈', '止损', '加仓', '仓位', '筛选')):
        topic_keywords.extend(['基金定投', '分散投资', '仓位管理'])
        topic_keywords.extend(['市盈率', '分红', '风险'])
    for kw in dict.fromkeys(topic_keywords):
        chunks.extend(rag.retrieve(kw, top_k=1))

    seen = set()
    chunks = [c for c in chunks if c['id'] not in seen and not seen.add(c['id'])][:5]

    kb_text = '\n\n'.join(
        f"【{c['title']}】（来源：{c['source']}）\n{c['content'][:_KB_CHUNK_MAX]}"
        for c in chunks
    )
    sources = [{'title': c['title'], 'source': c['source'], 'category': c['category']} for c in chunks]
    return kb_text, sources


def build_context(query):
    rag = get_rag()
    stock_codes = resolve_stock_codes(query)
    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_kb = pool.submit(_build_kb_context, query, rag)
        fut_live = pool.submit(fetch_live_context, stock_codes)
        kb_text, sources = fut_kb.result()
        live_text, live_sources, live_facts = fut_live.result()
    sources.extend(live_sources)
    return kb_text, live_text, sources, live_facts


def _prepare_chat(user_message, history=None):
    history = history or []
    kb_text, live_text, sources, live_facts = build_context(user_message)

    context_block = ''
    if kb_text:
        context_block += f'\n\n【知识库参考】\n{kb_text}'
    if live_text:
        context_block += f'\n\n【实时数据】\n{live_text}'

    user_content = user_message
    if live_facts:
        hints = []
        for f in live_facts:
            hint = f"{f['name']} 股票代码 {f['code']}"
            if f.get('last_price') is not None:
                hint += f"，最新收盘价 {float(f['last_price']):.2f} 元"
            if f.get('pe_ttm') is not None:
                hint += f"，PE {float(f['pe_ttm']):.2f} 倍"
            if f.get('pb') is not None:
                hint += f"，PB {float(f['pb']):.2f} 倍"
            hints.append(hint)
        user_content += (
            f"\n\n（系统已注入行情与基本面：{'；'.join(hints)}。"
            f"全文仅可分析上述股票，股票代码必须写为完整6位数字 {live_facts[0]['code']}。"
            f"必须引用系统给出的 PE/PB 数据，术语用 PE 不用 PF，"
            f"需写完整 3～5 点并包含风险与结论，禁止半途截断。）"
        )

    messages = [{'role': 'system', 'content': SYSTEM_PROMPT + context_block}]
    for h in history[-4:]:
        if h.get('role') in ('user', 'assistant') and h.get('content'):
            messages.append({'role': h['role'], 'content': h['content']})
    messages.append({'role': 'user', 'content': user_content})

    base_config = _get_api_config()
    llm_config = dict(base_config)
    if live_facts:
        llm_config['max_tokens'] = max(llm_config['max_tokens'], 2048)

    return {
        'messages': messages,
        'kb_text': kb_text,
        'live_text': live_text,
        'sources': sources,
        'live_facts': live_facts,
        'llm_temp': 0.15 if live_text else 0.5,
        'llm_config': llm_config,
        'is_stock_analysis': bool(live_facts),
        'user_message': user_message,
    }


def _finalize_answer(raw_answer, used_llm, live_text, live_facts, user_message, kb_text, prep=None):
    answer = raw_answer
    if not answer:
        answer = fallback_answer(user_message, kb_text, live_text, [])
    elif used_llm:
        answer = raw_answer
        is_stock = bool(live_facts)
        if prep and looks_truncated(answer, is_stock_analysis=is_stock):
            answer = complete_truncated_answer(
                prep['messages'],
                answer,
                prep.get('llm_config') or _get_api_config(),
                prep.get('llm_temp', 0.5),
            )
        answer = sanitize_answer(answer)
        answer = remove_shirking_phrases(answer, live_facts)
        answer = remove_false_unknowns(answer, live_facts)
        answer = enforce_live_facts(answer, live_facts)
        answer = fix_alias_stock_codes(answer)
        if live_facts:
            answer = build_facts_preamble(live_facts) + answer
            answer = enforce_live_facts(answer, live_facts)

    if used_llm and answer and '不构成投资建议' not in answer and '仅供参考' not in answer:
        answer += '\n\n---\n以上内容仅供参考，不构成投资建议。股市有风险，投资需谨慎。'

    if live_text:
        ts = datetime.now().strftime('%Y-%m-%d %H:%M')
        answer += f'\n\n（行情与公告数据更新时间：{ts}）'

    return answer


def _llm_payload(messages, config, temperature):
    return {
        'model': config['model'],
        'messages': messages,
        'temperature': temperature,
        'max_tokens': config['max_tokens'],
        'stream': False,
    }
def call_llm(messages, config=None, temperature=0.5):
    config = config or _get_api_config()
    api_key = config['api_key']
    if not api_key:
        return None, '未配置 AI API Key，请在 .env 中设置 SILICONFLOW_API_KEY'

    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }
    payload = _llm_payload(messages, config, temperature)

    try:
        resp = _get_http_session().post(
            config['api_base'], headers=headers, json=payload, timeout=(8, 55),
        )
        resp.raise_for_status()
        data = resp.json()
        content = data['choices'][0]['message']['content']
        return content.strip(), None
    except requests.Timeout:
        return None, 'AI 服务响应超时，请稍后重试'
    except Exception as e:
        logger.error('LLM 调用失败: %s', e)
        return None, f'AI 服务暂时不可用: {e}'


def call_llm_stream(messages, config=None, temperature=0.5):
    """流式调用 LLM，逐段 yield 文本。"""
    config = config or _get_api_config()
    api_key = config['api_key']
    if not api_key:
        return

    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }
    payload = _llm_payload(messages, config, temperature)
    payload['stream'] = True

    session = _new_http_session()
    try:
        resp = session.post(
            config['api_base'],
            headers=headers,
            json=payload,
            stream=True,
            timeout=(8, 90),
        )
        resp.raise_for_status()
        # SSE 默认 encoding 可能是 ISO-8859-1，会导致中文乱码
        for raw_line in resp.iter_lines(decode_unicode=False):
            if not raw_line:
                continue
            try:
                line = raw_line.decode('utf-8')
            except UnicodeDecodeError:
                line = raw_line.decode('utf-8', errors='replace')
            if not line.startswith('data:'):
                continue
            data_str = line[5:].strip()
            if data_str == '[DONE]':
                break
            try:
                chunk = json.loads(data_str)
                delta = chunk['choices'][0].get('delta') or {}
                content = delta.get('content')
                if content:
                    yield content
            except (json.JSONDecodeError, KeyError, IndexError):
                continue
    except Exception as e:
        logger.error('LLM 流式调用失败: %s', e)
        raise
    finally:
        session.close()


def fallback_answer(query, kb_text, live_text, sources):
    """无 API Key 时基于知识库拼接回答。"""
    parts = ['根据知识库检索，为您整理如下参考信息：\n']
    if live_text:
        parts.append('【实时数据】\n' + live_text + '\n')
    if kb_text:
        parts.append('【知识库】\n' + kb_text[:1500])
    else:
        parts.append('暂未检索到高度相关的知识条目，建议换个问法或提及具体股票代码（如 600519）。')
    parts.append('\n\n⚠️ 以上内容仅供参考，不构成投资建议。如需更智能的解读，请配置 SILICONFLOW_API_KEY。')
    return '\n'.join(parts)


def chat(user_message, history=None):
    """
    主入口：RAG + 实时数据 + LLM。
    返回 dict: answer, sources, has_live_data, used_llm
    """
    prep = _prepare_chat(user_message, history)
    answer, err = call_llm(
        prep['messages'],
        config=prep['llm_config'],
        temperature=prep['llm_temp'],
    )
    used_llm = answer is not None

    if not answer:
        answer = fallback_answer(user_message, prep['kb_text'], prep['live_text'], prep['sources'])
        if err and '未配置' not in err:
            answer += f'\n\n（提示：{err}）'
    else:
        answer = _finalize_answer(
            answer, used_llm, prep['live_text'], prep['live_facts'],
            user_message, prep['kb_text'], prep=prep,
        )

    return {
        'answer': answer,
        'sources': prep['sources'][:8],
        'has_live_data': bool(prep['live_text']),
        'has_knowledge': bool(prep['kb_text']),
        'used_llm': used_llm,
        'model': _get_api_config()['model'] if used_llm else 'knowledge-base',
    }


def chat_stream(user_message, history=None):
    """流式对话：先 meta，再 token，最后 done（含完整后处理回答）。"""
    prep = _prepare_chat(user_message, history)
    config = _get_api_config()
    meta = {
        'success': True,
        'sources': prep['sources'][:8],
        'has_live_data': bool(prep['live_text']),
        'has_knowledge': bool(prep['kb_text']),
        'model': config['model'],
    }
    yield {'event': 'meta', 'data': meta}

    if not config['api_key']:
        answer = fallback_answer(
            user_message, prep['kb_text'], prep['live_text'], prep['sources'],
        )
        answer += '\n\n（提示：未配置 AI API Key）'
        yield {'event': 'done', 'data': {
            **meta,
            'answer': answer,
            'used_llm': False,
        }}
        return

    parts = []
    try:
        for token in call_llm_stream(
            prep['messages'], config=prep['llm_config'], temperature=prep['llm_temp'],
        ):
            parts.append(token)
            yield {'event': 'token', 'data': token}
    except Exception as e:
        yield {'event': 'error', 'data': {'error': f'AI 服务暂时不可用: {e}'}}
        return

    raw = ''.join(parts).strip()
    if not raw:
        answer = fallback_answer(
            user_message, prep['kb_text'], prep['live_text'], prep['sources'],
        )
        answer += '\n\n（提示：AI 服务响应超时，请稍后重试）'
        yield {'event': 'done', 'data': {**meta, 'answer': answer, 'used_llm': False}}
        return

    answer = _finalize_answer(
        raw, True, prep['live_text'], prep['live_facts'], user_message, prep['kb_text'], prep=prep,
    )
    yield {'event': 'done', 'data': {**meta, 'answer': answer, 'used_llm': True}}


def build_index():
    """预构建并缓存 RAG 索引（可选）。"""
    rag = StockRAG()
    joblib.dump({'vectorizer': rag.vectorizer, 'matrix': rag.matrix, 'entries': rag.entries}, INDEX_FILE)
    return len(rag.entries)
