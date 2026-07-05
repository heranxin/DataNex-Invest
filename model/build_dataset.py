"""
从东方财富公告 + akshare 行情构建真实 A 股训练集。
每条样本：公告标题、公告日、随后 3 个交易日收益率、规则情感分。

用法:
    python model/build_dataset.py
"""
import os
import sys
import time
from datetime import datetime, timedelta

import akshare as ak
import pandas as pd
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from model.news_analysis import classify_announcement, get_stock_industry
OUTPUT = os.path.join(os.path.dirname(__file__), 'data', 'stock_news_real.csv')

# 覆盖多行业代表性 A 股
STOCK_CODES = [
    '600519', '000858', '000001', '600036', '601318',
    '300750', '002594', '600276', '601899', '600030',
    '000002', '601012', '600900', '000661',
]

EASTMONEY_URL = 'https://np-anotice-stock.eastmoney.com/api/security/ann'


def fetch_announcements(stock_code, pages=5, page_size=50):
    """拉取带日期的公告列表。"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://data.eastmoney.com/',
    }
    rows = []
    for page in range(1, pages + 1):
        params = {
            'page_size': page_size,
            'page_index': page,
            'ann_type': 'A',
            'client_source': 'web',
            'stock_list': stock_code,
        }
        try:
            resp = requests.get(EASTMONEY_URL, params=params, headers=headers, timeout=20)
            resp.raise_for_status()
            payload = resp.json()
            items = payload.get('data', {}).get('list', []) if payload.get('success') else []
            if not items:
                break
            for item in items:
                title = (item.get('title_ch') or item.get('title') or '').strip()
                notice_date = (item.get('notice_date') or item.get('display_time') or '')[:10]
                if not title or not notice_date:
                    continue
                columns = item.get('columns') or []
                if columns and columns[0].get('column_name'):
                    title = f"{title}（{columns[0]['column_name']}）"
                rows.append({
                    'stock_code': stock_code,
                    'notice_date': notice_date,
                    'news_text': title,
                })
            time.sleep(0.3)
        except Exception as e:
            print(f'  公告第{page}页失败: {e}')
            break
    return rows


def fetch_price_history(stock_code, years=3):
    """获取前复权日线。"""
    end = datetime.now().strftime('%Y%m%d')
    start = (datetime.now() - timedelta(days=365 * years)).strftime('%Y%m%d')
    try:
        df = ak.stock_zh_a_hist(
            symbol=stock_code, period='daily',
            start_date=start, end_date=end, adjust='qfq',
        )
        df = df[['日期', '收盘']].copy()
        df['日期'] = pd.to_datetime(df['日期'])
        df['收盘'] = pd.to_numeric(df['收盘'], errors='coerce')
        return df.dropna().sort_values('日期').reset_index(drop=True)
    except Exception as e:
        print(f'  行情获取失败 {stock_code}: {e}')
        return pd.DataFrame(columns=['日期', '收盘'])


def forward_returns(price_df, notice_date):
    """计算公告日后第 1/2/3 个交易日收益率（%）。"""
    if price_df.empty:
        return None
    dt = pd.to_datetime(notice_date)
    future = price_df[price_df['日期'] > dt].head(3)
    if len(future) < 3:
        return None
    base_row = price_df[price_df['日期'] <= dt]
    if base_row.empty:
        return None
    base = float(base_row.iloc[-1]['收盘'])
    if base <= 0:
        return None
    rets = []
    for _, row in future.iterrows():
        rets.append((float(row['收盘']) - base) / base * 100)
    return rets[0], rets[1], rets[2]


def build():
    all_rows = []
    for code in STOCK_CODES:
        industry = get_stock_industry(code)
        print(f'处理 {code} ({industry})...')
        announcements = fetch_announcements(code)
        prices = fetch_price_history(code)
        if prices.empty:
            print(f'  跳过：无行情')
            continue
        added = 0
        for ann in announcements:
            rets = forward_returns(prices, ann['notice_date'])
            if rets is None:
                continue
            rule = classify_announcement(ann['news_text'])
            avg_ret = sum(rets) / 3
            # 标签：真实收益为主，规则情感为辅
            sentiment_score = max(-1.0, min(1.0, avg_ret / 5.0 * 0.7 + rule['rule_sentiment'] * 0.3))
            all_rows.append({
                'stock_code': code,
                'industry': industry,
                'notice_date': ann['notice_date'],
                'news_text': ann['news_text'],
                'rule_sentiment': rule['rule_sentiment'],
                'announcement_type': rule['type'],
                'sentiment_score': round(sentiment_score, 4),
                'price_change_1': round(rets[0], 4),
                'price_change_2': round(rets[1], 4),
                'price_change_3': round(rets[2], 4),
            })
            added += 1
        print(f'  有效样本: {added}')

    if not all_rows:
        raise RuntimeError('未生成任何训练样本，请检查网络与 akshare')

    df = pd.DataFrame(all_rows)
    df = df.drop_duplicates(subset=['stock_code', 'notice_date', 'news_text'])
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    df.to_csv(OUTPUT, index=False, encoding='utf-8-sig')
    print(f'\n已保存 {len(df)} 条样本 -> {OUTPUT}')
    print(df.groupby('industry').size().to_string())
    return OUTPUT


if __name__ == '__main__':
    build()
