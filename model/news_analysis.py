"""公告类型规则、行业映射、综合研判与置信度评估。"""
import re

import numpy as np

NEUTRAL_PATTERNS = [
    r'董事会决议', r'股东会', r'股东大会', r'监事会', r'会议通知', r'召开.*通知',
    r'法律意见书', r'核查意见', r'保荐意见', r'独立意见', r'述职报告',
    r'内部控制', r'内控', r'审计报告', r'年报', r'半年报', r'季报', r'一季度报告',
    r'半年度报告', r'年度报告', r'提示性公告', r'补充公告', r'更正公告',
    r'投资者关系', r'调研活动', r'接待调研', r'路演', r'业绩说明会',
    r'章程', r'制度', r'管理办法', r'议事规则', r'选举', r'提名',
]

BULLISH_PATTERNS = [
    r'业绩预增', r'净利润增长', r'扭亏', r'中标', r'重大合同', r'战略合作',
    r'回购', r'增持', r'分红', r'派息', r'权益分派', r'分派实施', r'高送转', r'超预期',
    r'获批', r'通过审核', r'并购重组', r'资产注入', r'订单', r'产能扩张',
    r'涨停', r'利好', r'上调评级', r'推荐',
]

BEARISH_PATTERNS = [
    r'业绩预减', r'业绩下滑', r'亏损', r'减持', r'质押', r'违约', r'诉讼',
    r'立案', r'调查', r'处罚', r'警示', r'退市风险', r'停牌', r'债务',
    r'下调评级', r'利空', r'暴跌', r'商誉减值', r'计提',
]

INDUSTRY_MAP = {
    '600519': '白酒', '000858': '白酒', '000568': '白酒',
    '000001': '银行', '600036': '银行', '601166': '银行', '601398': '银行',
    '601318': '保险', '601601': '保险',
    '300750': '新能源', '002594': '新能源', '601012': '新能源',
    '600276': '医药', '000661': '医药',
    '601899': '有色', '600547': '有色',
    '600900': '电力', '000002': '地产',
    '600030': '券商', '601688': '券商',
}

STOCK_DISPLAY_NAMES = {
    '600519': '贵州茅台', '000858': '五粮液', '000568': '泸州老窖',
    '600001': '邯郸钢铁', '300750': '宁德时代', '002594': '比亚迪', '601318': '中国平安',
    '600036': '招商银行', '000001': '平安银行', '601398': '工商银行',
    '601166': '兴业银行', '600030': '中信证券', '601688': '华泰证券',
    '601012': '隆基绿能', '601899': '紫金矿业', '600547': '山东黄金',
    '600900': '长江电力', '000002': '万科A', '600276': '恒瑞医药',
    '688981': '中芯国际', '002415': '海康威视', '300308': '中际旭创',
    '000661': '长春高新',
}

DISCLAIMER = '本预测结果由机器学习模型自动生成，仅供参考，不构成投资建议。股市有风险，投资需谨慎。'

METHODOLOGY = [
    '新闻来源：东方财富公告 API / 新浪财经（自动获取最近 20 条）',
    '情感分析：TF-IDF + FinBERT 嵌入 + 公告类型规则融合',
    '价格预测：基于 2466 条真实 A 股公告-收益率样本训练',
    '行业校准：按所属行业历史波动对预测做轻量修正',
]


def _match_any(text, patterns):
    for p in patterns:
        if re.search(p, text, re.I):
            return True
    return False


def classify_announcement(text):
    text = (text or '').strip()
    if not text:
        return {'type': 'unknown', 'rule_sentiment': 0.0, 'label': '未知'}

    if _match_any(text, BEARISH_PATTERNS):
        return {'type': 'bearish', 'rule_sentiment': -0.6, 'label': '偏利空'}
    if _match_any(text, BULLISH_PATTERNS):
        return {'type': 'bullish', 'rule_sentiment': 0.6, 'label': '偏利好'}
    if _match_any(text, NEUTRAL_PATTERNS):
        return {'type': 'routine', 'rule_sentiment': 0.0, 'label': '例行中性'}

    return {'type': 'general', 'rule_sentiment': 0.0, 'label': '一般资讯'}


def get_stock_industry(stock_code):
    code = str(stock_code).strip().zfill(6)
    if code in INDUSTRY_MAP:
        return INDUSTRY_MAP[code]
    try:
        import akshare as ak
        info = ak.stock_individual_info_em(symbol=code)
        row = info[info['item'] == '行业']
        if not row.empty:
            industry = str(row.iloc[0]['value']).strip()
            if industry and industry != '--':
                INDUSTRY_MAP[code] = industry
                return industry
    except Exception:
        pass
    return '综合'


def get_stock_name(stock_code):
    code = str(stock_code).strip().zfill(6)
    if code in STOCK_DISPLAY_NAMES:
        return STOCK_DISPLAY_NAMES[code]
    try:
        from stock_data import fetch_stock_data
        data = fetch_stock_data(code, days=30)
        if data and data.get('realtime'):
            name = data['realtime'].get('名称') or data['realtime'].get('name')
            if name and str(name) not in ('--', code) and not str(name).isdigit():
                return str(name).strip()
    except Exception:
        pass
    try:
        import akshare as ak
        info = ak.stock_individual_info_em(symbol=code)
        row = info[info['item'] == '股票简称']
        if not row.empty:
            name = str(row.iloc[0]['value']).strip()
            if name and name != '--':
                return name
    except Exception:
        pass
    return STOCK_DISPLAY_NAMES.get(code, code)


_INFO_FIELD_MAP = {
    '市盈率-动态': 'pe_ttm',
    '市盈率(动态)': 'pe_ttm',
    '市盈率': 'pe',
    '市净率': 'pb',
    '股息率': 'dividend_yield',
    '股息率(%)': 'dividend_yield',
    '净资产收益率': 'roe',
    '每股收益': 'eps',
    '每股净资产': 'bps',
    '总股本': 'total_shares',
    '流通股': 'float_shares',
}

INDUSTRY_VALUATION_HINT = {
    '白酒': '白酒龙头 PE 常见约 15～35 倍，需结合增速、批价与分红综合看',
    '银行': '银行板块 PE 常见约 4～8 倍，关注不良率与息差',
    '保险': '保险板块 PE 波动较大，需结合内含价值与新业务价值',
    '新能源': '成长行业 PE 弹性大，需匹配业绩兑现度',
    '医药': '医药 PE 分化明显，创新药与仿制药逻辑不同',
    '券商': '券商 PE 与行情景气度高度相关',
}


def _parse_info_number(val):
    if val is None:
        return None
    s = str(val).strip().replace(',', '').replace('%', '')
    if not s or s in ('--', '-', 'nan', 'None'):
        return None
    try:
        return round(float(s), 4)
    except (TypeError, ValueError):
        return None


def get_stock_fundamentals(stock_code):
    """拉取个股 PE/PB/股息率等公开基本面指标（东方财富）。"""
    code = str(stock_code).strip().zfill(6)
    out = {'code': code}
    try:
        import akshare as ak
        from model.network_utils import direct_connection
        with direct_connection():
            info = ak.stock_individual_info_em(symbol=code)
        for _, row in info.iterrows():
            item = str(row.get('item', '')).strip()
            if item not in _INFO_FIELD_MAP:
                continue
            field = _INFO_FIELD_MAP[item]
            parsed = _parse_info_number(row.get('value'))
            if parsed is not None:
                out[field] = parsed
            elif field not in out:
                raw = str(row.get('value', '')).strip()
                if raw and raw not in ('--', '-'):
                    out[field] = raw
        if out.get('pe') and not out.get('pe_ttm'):
            out['pe_ttm'] = out['pe']
    except Exception:
        pass
    return out if len(out) > 1 else {}


def get_industry_valuation_hint(industry):
    industry = (industry or '').strip()
    for key, hint in INDUSTRY_VALUATION_HINT.items():
        if key in industry:
            return hint
    return '请结合所属行业平均估值与个股历史分位综合判断，不宜单看绝对值'


def get_recent_price_context(stock_code):
    """获取近期行情作为预测支撑依据。"""
    try:
        from stock_data import fetch_stock_data
        data = fetch_stock_data(stock_code, days=30)
        if not data or data.get('history') is None:
            return None
        hist = data['history']
        if len(hist) < 5:
            return None
        closes = hist['收盘'].astype(float)
        last = float(closes.iloc[-1])
        d5 = float(closes.iloc[-5]) if len(closes) >= 5 else float(closes.iloc[0])
        d20 = float(closes.iloc[-20]) if len(closes) >= 20 else float(closes.iloc[0])
        ret_5d = (last - d5) / d5 * 100 if d5 else 0
        ret_20d = (last - d20) / d20 * 100 if d20 else 0

        if ret_5d > 2:
            short_trend = '近5日走强'
        elif ret_5d < -2:
            short_trend = '近5日走弱'
        else:
            short_trend = '近5日横盘'

        return {
            'last_price': round(last, 2),
            'return_5d': round(ret_5d, 2),
            'return_20d': round(ret_20d, 2),
            'short_trend': short_trend,
            'source': 'akshare 前复权日线',
        }
    except Exception:
        return None


def blend_sentiment(ml_sentiment, rule_sentiment, rule_weight=0.45):
    ml = float(ml_sentiment) if ml_sentiment is not None else 0.0
    rule = float(rule_sentiment) if rule_sentiment is not None else 0.0
    return (1 - rule_weight) * ml + rule_weight * rule


def blend_price_changes(ml_changes, rule_sentiment, industry_scale=1.0):
    changes = np.asarray(ml_changes, dtype=float).copy()
    rule_adj = rule_sentiment * 0.15 * industry_scale
    return changes + rule_adj


def synthesize_prediction(sentiments, price_changes_list, rule_types):
    """
    统一情感与价格信号，生成一致的趋势判断与可读摘要。
    例行公告在价格投票中权重降低。
    """
    sentiments = [float(s) for s in sentiments]
    weights = [0.25 if t == 'routine' else 1.0 for t in rule_types]
    w_sum = sum(weights) or 1.0

    weighted_day1 = sum(
        float(np.asarray(pc)[0]) * w for pc, w in zip(price_changes_list, weights)
    ) / w_sum

    avg_sent = float(np.mean(sentiments))
    # 综合分：情感 50% + 加权首日涨跌信号 50%（涨跌% 缩放到约 [-1,1]）
    price_signal = float(np.clip(weighted_day1 / 3.0, -1.0, 1.0))
    composite = avg_sent * 0.5 + price_signal * 0.5

    if composite > 0.06:
        trend, trend_key = '上涨趋势', 'up'
    elif composite < -0.06:
        trend, trend_key = '下跌趋势', 'down'
    else:
        trend, trend_key = '震荡趋势', 'flat'

    bullish_n = sum(1 for t in rule_types if t == 'bullish')
    bearish_n = sum(1 for t in rule_types if t == 'bearish')
    routine_n = sum(1 for t in rule_types if t == 'routine')
    general_n = len(rule_types) - bullish_n - bearish_n - routine_n

    # 加权方向票（例行公告降权）
    up_w = down_w = 0.0
    for pc, t, w in zip(price_changes_list, rule_types, weights):
        d1 = float(np.asarray(pc)[0])
        if d1 > 0.05:
            up_w += w
        elif d1 < -0.05:
            down_w += w

    parts = []
    if avg_sent > 0.05:
        parts.append('新闻综合情感偏积极')
    elif avg_sent < -0.05:
        parts.append('新闻综合情感偏消极')
    else:
        parts.append('新闻综合情感偏中性')

    type_desc = []
    if routine_n:
        type_desc.append(f'例行公告 {routine_n} 条（已降权）')
    if bullish_n:
        type_desc.append(f'偏利好 {bullish_n} 条')
    if bearish_n:
        type_desc.append(f'偏利空 {bearish_n} 条')
    if general_n:
        type_desc.append(f'一般资讯 {general_n} 条')
    if type_desc:
        parts.append('公告构成：' + '、'.join(type_desc))

    if weighted_day1 > 0.1:
        parts.append('加权价格信号略偏多')
    elif weighted_day1 < -0.1:
        parts.append('加权价格信号略偏空')
    else:
        parts.append('加权价格信号中性')

    if up_w > down_w * 1.2:
        parts.append(f'方向统计偏多（加权看多 {up_w:.1f} vs 看空 {down_w:.1f}）')
    elif down_w > up_w * 1.2:
        parts.append(f'方向统计偏空（加权看多 {up_w:.1f} vs 看空 {down_w:.1f}）')
    else:
        parts.append('方向统计分化，短期或震荡')

    return {
        'trend': trend,
        'trend_key': trend_key,
        'composite_score': round(composite, 4),
        'avg_sentiment': round(avg_sent, 4),
        'weighted_day1': round(weighted_day1, 4),
        'summary': '；'.join(parts) + '。',
        'bullish_count': bullish_n,
        'bearish_count': bearish_n,
        'routine_count': routine_n,
        'weighted_up': round(up_w, 2),
        'weighted_down': round(down_w, 2),
    }


def refine_trend_label(trend, trend_key, price_changes_3d):
    """
    震荡趋势下，结合 3 日预测涨跌幅给出更易读的子标签与说明。
    返回 (display_trend, trend_key, trend_hint)
    """
    if trend_key != 'flat' or not price_changes_3d:
        return trend, trend_key, None

    changes = [float(x) for x in price_changes_3d[:3]]
    if not changes:
        return trend, trend_key, None

    threshold = 0.02
    all_pos = len(changes) >= 2 and all(c > threshold for c in changes)
    all_neg = len(changes) >= 2 and all(c < -threshold for c in changes)
    avg_chg = sum(changes) / len(changes)

    if all_pos:
        return (
            '震荡偏强',
            trend_key,
            '综合方向中性偏弱，但模型测算未来 3 个交易日小幅上行',
        )
    if all_neg:
        return (
            '震荡偏弱',
            trend_key,
            '综合方向中性偏弱，但模型测算未来 3 个交易日小幅下行',
        )
    if avg_chg > 0.08:
        return (
            '震荡略偏多',
            trend_key,
            '大方向震荡，短期涨跌信号略偏多',
        )
    if avg_chg < -0.08:
        return (
            '震荡略偏空',
            trend_key,
            '大方向震荡，短期涨跌信号略偏空',
        )
    return trend, trend_key, '大方向震荡，3 日涨跌幅度有限'


def build_market_note(trend_key, return_5d):
    """行情与情感结论交叉说明。"""
    if return_5d is None:
        return ''
    r5 = float(return_5d)
    if trend_key == 'down' and r5 < -2:
        return f'与近5日行情（{r5:+.2f}%）走势一致'
    if trend_key == 'up' and r5 > 2:
        return f'与近5日行情（{r5:+.2f}%）走势一致'
    if trend_key == 'flat':
        if abs(r5) >= 8:
            return (
                f'近5日行情 {r5:+.2f}% 波动较大，但公告情感偏中性；'
                f'股价波动与新闻面未形成一致信号，宜结合行情与公告分别判断'
            )
        return f'近5日涨跌幅 {r5:+.2f}%，整体偏震荡'
    return f'与近5日行情（{r5:+.2f}%）存在分化，宜谨慎看待'


def model_reliability_hint(model_r2):
    """R² 过低时的使用建议。"""
    if model_r2 is None:
        return False, None
    try:
        r2 = float(model_r2)
    except (TypeError, ValueError):
        return False, None
    if r2 >= 0.1:
        return False, None
    return True, (
        '当前新闻对股价的解释力较弱（R²={:.2f}），建议以「公告情感速览」为主，'
        '本页 3 日涨跌预测仅作辅助参考，不宜作为交易依据。'
    ).format(r2)


def compute_confidence(sentiments, price_changes_list, model_metrics=None, rule_types=None):
    warnings = []
    sentiments = [float(s) for s in sentiments if s is not None]
    price_changes_list = [np.asarray(p, dtype=float) for p in price_changes_list if p is not None]

    if not sentiments:
        return '低', ['无有效预测结果'], {}

    sent_arr = np.array(sentiments)
    sent_std = float(np.std(sent_arr))
    unique_sent = len({round(s, 4) for s in sentiments})
    unique_ratio = unique_sent / len(sentiments)

    if sent_std < 0.02:
        warnings.append('多条新闻情感预测高度相同，模型对当前文本区分度不足')
    if unique_ratio <= 0.15 and len(sentiments) >= 5:
        warnings.append('多数新闻得到相同预测值，请勿将结果视为逐条分析结论')

    if price_changes_list:
        pc = np.array(price_changes_list)
        if np.std(pc[:, 0]) < 0.02:
            warnings.append('各条新闻的价格变动预测几乎一致，置信度偏低')

    if model_metrics:
        r2 = model_metrics.get('sentiment_r2')
        if r2 is not None and r2 < 0.1:
            warnings.insert(0, f'模型训练拟合度有限（R²={r2:.2f}），新闻对股价解释力弱')
            warnings.insert(1, '建议优先查看公告情感标注；下方 3 日涨跌预测仅供辅助参考')

    if len(sentiments) < 5:
        warnings.append('有效新闻条数较少，统计稳定性不足')

    if rule_types and sum(1 for t in rule_types if t == 'routine') >= len(rule_types) * 0.7:
        warnings.append('公告以例行披露为主，对短期走势指引有限')

    if len(warnings) >= 2:
        level = '低'
    elif len(warnings) == 1:
        level = '中'
    else:
        level = '高' if sent_std >= 0.15 else '中'

    stats = {
        'sentiment_std': round(sent_std, 4),
        'unique_sentiment_count': unique_sent,
        'news_analyzed': len(sentiments),
    }
    return level, warnings, stats
