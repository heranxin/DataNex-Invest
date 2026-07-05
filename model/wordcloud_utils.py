"""公告词云文本预处理：jieba 分词 + 停用词过滤。"""
from __future__ import annotations

import re
from collections import Counter

import jieba
import jieba.analyse

# 公告常见复合词，避免被错误切开
for word in (
    '全资子公司', '被担保人', '连带责任', '隆基绿能', '隆基乐叶',
    '光伏科技', '综合授信', '合并报表', '董事会', '监事会',
):
    jieba.add_word(word, freq=10000)

# 通用中文虚词
_BASE_STOPWORDS = {
    '的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一', '一个',
    '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好',
    '自己', '这', '那', '他', '她', '它', '我们', '你们', '他们', '其', '及', '与',
    '或', '而', '但', '因', '为', '以', '于', '对', '从', '向', '由', '被', '把',
    '将', '让', '给', '等', '之', '所', '可', '能', '已', '未', '并', '且', '若',
    '如', '则', '即', '又', '再', '还', '更', '最', '非常', '十分', '进行', '通过',
    '根据', '按照', '有关', '相关', '其中', '以及', '同时', '此外', '因此', '由于',
    '如果', '虽然', '但是', '然而', '其中', '上述', '如下', '如下所示', '如下表',
    '如下所述', '如下列', '如下文',
    '年', '月', '日', '时', '分', '秒', '万元', '亿元', '元', '人民币',
    '第', '个', '条', '项', '款', '号', '次', '本', '该', '此', '各', '每',
}

# 公告套话、合规表述（过滤后保留业务关键词如「担保」「子公司」）
_ANNOUNCEMENT_STOPWORDS = {
    '公司', '本公司', '公告', '特此公告', '董事会', '监事会', '股东大会',
    '证券', '证券交易所', '交易所', '中国证监会', '证监会', '披露', '信息披露',
    '投资者', '广大投资者', '敬请', '注意', '风险', '投资风险', '法律责任',
    '虚假记载', '误导性陈述', '重大遗漏', '保证', '真实', '准确', '完整',
    '承担', '个别', '连带', '责任', '董事', '监事', '高级管理人员', '高管',
    '全体董事', '全体监事', '全体高管', '全体成员', '保证公告', '内容真实', '内容准确',
    '内容完整', '不存在', '记载', '陈述', '遗漏', '情况', '事项', '如下',
    '如下表', '如下所示', '详见', '附件', '备查', '文件', '目录', '网站',
    '巨潮资讯', '资讯网', 'http', 'https', 'www', 'com', 'cn',
    '股票', '代码', '简称', '名称', '股份', '有限', '有限公司', '集团',
    '控股', '股东', '实际控制人', '关联', '关系', '独立', '第三方',
    '符合', '规定', '要求', '适用', '法律', '法规', '规章', '规则',
    '办法', '指引', '通知', '意见', '决定', '决议', '审议', '批准',
    '同意', '通过', '召开', '会议', '出席', '表决', '弃权', '回避',
    '生效', '实施', '执行', '履行', '完成', '截止', '截至', '期间',
    '年度', '季度', '报告期', '财务', '数据', '指标', '变动', '变化',
    '增加', '减少', '上升', '下降', '同比', '环比', '比例', '百分比',
    '约为', '大约', '左右', '以上', '以下', '之间', '包括', '不含',
    '除', '外', '其他', '其余', '合计', '总计', '共计', '分别',
    '具体', '详细', '简要', '概述', '说明', '解释', '原因', '影响',
    '可能', '存在', '发生', '导致', '造成', '产生', '带来', '涉及',
    '关于', '有关', '针对', '就', '就本', '现就', '现对', '现将',
    '特此', '敬告', '提示', '告知', '通知', '函', '告', '书',
    '之日起', '之日起至', '之日起为', '内容', '完整性', '准确性', '真实性',
    '误导性', '虚假', '个别及', '叶为', '隆基乐',
}

STOPWORDS = _BASE_STOPWORDS | _ANNOUNCEMENT_STOPWORDS

_DATE_PATTERN = re.compile(
    r'\d{4}年\d{1,2}月\d{1,2}日|\d{4}-\d{2}-\d{2}|\d{4}/\d{2}/\d{2}'
)
_PURE_NUM = re.compile(r'^\d+(\.\d+)?$')
_PURE_PUNCT = re.compile(r'^[\W_]+$')


def _normalize_text(text: str) -> str:
    cleaned = _DATE_PATTERN.sub(' ', text)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


def _is_valid_token(token: str) -> bool:
    token = token.strip()
    if len(token) < 2:
        return False
    if token in STOPWORDS:
        return False
    if _PURE_NUM.match(token):
        return False
    if _PURE_PUNCT.match(token):
        return False
    if all(ch in '年月日时分秒' for ch in token):
        return False
    return True


def build_word_frequencies(text: str, top_k: int = 90) -> dict[str, float]:
    """
    对公告正文分词、去停用词，返回词频字典（供 WordCloud.generate_from_frequencies）。
    结合 jieba TF-IDF 关键词与词频统计，突出业务词汇。
    """
    cleaned = _normalize_text(text)
    if not cleaned:
        return {}

    tfidf_tags = jieba.analyse.extract_tags(cleaned, topK=top_k * 3, withWeight=True)
    freqs: dict[str, float] = {}
    for word, weight in tfidf_tags:
        if _is_valid_token(word):
            freqs[word] = float(weight)

    tokens = jieba.lcut(cleaned)
    counts = Counter(t for t in tokens if _is_valid_token(t))
    for word, count in counts.most_common(top_k * 3):
        if word not in freqs:
            freqs[word] = float(count)
        else:
            freqs[word] = freqs[word] * (1.0 + 0.15 * count)

    ranked = sorted(freqs.items(), key=lambda item: item[1], reverse=True)[:top_k]
    return dict(ranked)
