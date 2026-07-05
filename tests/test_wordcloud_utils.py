"""词云预处理单元测试。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model.wordcloud_utils import build_word_frequencies, STOPWORDS


SAMPLE_GUARANTEE = """
隆基绿能科技股份有限公司关于为全资子公司提供担保的公告
本公司及董事会全体成员保证公告内容真实、准确、完整，不存在虚假记载、
误导性陈述或重大遗漏，并对其内容的真实性、准确性和完整性承担个别及连带法律责任。
为满足子公司经营资金需求，公司拟为全资子公司隆基乐叶光伏科技有限公司
向银行申请综合授信提供连带责任保证担保，担保金额不超过人民币50,000万元，
担保期限自董事会审议通过之日起12个月。被担保人隆基乐叶为公司合并报表范围内子公司，
本次担保有利于支持子公司业务发展，不存在损害公司及中小股东利益的情形。
"""


def test_filters_boilerplate():
    freqs = build_word_frequencies(SAMPLE_GUARANTEE, top_k=20)
    assert freqs, '应提取到关键词'
    top_words = list(freqs.keys())[:10]
    assert '董事会' not in top_words
    assert '虚假记载' not in top_words
    assert '法律责任' not in top_words
    assert '担保' in top_words
    assert '子公司' in top_words
    assert any(w in freqs for w in ('隆基绿能', '隆基乐叶', '授信', '被担保人', '连带责任'))


def test_stopwords_cover_common_particles():
    assert '的' in STOPWORDS
    assert '万元' in STOPWORDS


if __name__ == '__main__':
    test_filters_boilerplate()
    test_stopwords_cover_common_particles()
    freqs = build_word_frequencies(SAMPLE_GUARANTEE, top_k=15)
    print('Top keywords:', list(freqs.keys()))
    print('OK')
