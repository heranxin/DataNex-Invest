"""
训练混合特征模型：TF-IDF + FinBERT + 规则情感。
优先使用 build_dataset.py 生成的真实 A 股数据。

用法:
    python model/build_dataset.py   # 首次或定期更新数据
    python model/train.py
"""
import json
import os
import warnings

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.model_selection import train_test_split

warnings.filterwarnings('ignore', category=FutureWarning, module='transformers')
warnings.filterwarnings('ignore', category=FutureWarning, module='torch')
warnings.filterwarnings('ignore', category=FutureWarning, module='huggingface_hub')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_DATA = os.path.join(os.path.dirname(__file__), 'data', 'stock_news_real.csv')
FALLBACK_DATA = os.path.join(os.path.dirname(__file__), 'data', 'stock_news.csv')
MODEL_DIR = os.path.join(ROOT, 'models')

TFIDF_MAX_FEATURES = 3000
FINBERT_WEIGHT = 0.8
RULE_WEIGHT = 1.0

# FinBERT
import torch
from transformers import BertModel, BertTokenizer

local_model_path = os.path.join(ROOT, 'finbert')
tokenizer = None
finbert_model = None

try:
    print('正在加载本地 FinBERT 模型...')
    tokenizer = BertTokenizer.from_pretrained(local_model_path)
    finbert_model = BertModel.from_pretrained(local_model_path)
    print('本地 FinBERT 加载成功')
except Exception as e:
    print(f'本地 FinBERT 失败: {e}，尝试在线模型...')
    try:
        tokenizer = BertTokenizer.from_pretrained('ProsusAI/finbert')
        finbert_model = BertModel.from_pretrained('ProsusAI/finbert')
        print('在线 FinBERT 加载成功')
    except Exception as e2:
        print(f'FinBERT 不可用: {e2}')

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
if finbert_model is not None:
    finbert_model.to(device)
    finbert_model.eval()


def load_data(file_path):
    print(f'读取训练数据: {file_path}')
    df = pd.read_csv(file_path, engine='python')
    print(f'样本数: {len(df)}, 列: {df.columns.tolist()}')

    texts = df['news_text'].astype(str).tolist()
    sentiment_scores = df['sentiment_score'].tolist()
    price_changes = df[['price_change_1', 'price_change_2', 'price_change_3']].values.tolist()

    rule_sentiments = None
    if 'rule_sentiment' in df.columns:
        rule_sentiments = df['rule_sentiment'].fillna(0).tolist()
    else:
        from model.news_analysis import classify_announcement
        rule_sentiments = [classify_announcement(t)['rule_sentiment'] for t in texts]

    industries = df['industry'].tolist() if 'industry' in df.columns else ['综合'] * len(texts)
    stock_codes = df['stock_code'].astype(str).tolist() if 'stock_code' in df.columns else [''] * len(texts)
    return texts, sentiment_scores, price_changes, rule_sentiments, industries, stock_codes


def get_finbert_embeddings(texts, batch_size=16):
    if tokenizer is None or finbert_model is None:
        print('FinBERT 不可用，使用零向量')
        return np.zeros((len(texts), 768))

    embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        inputs = tokenizer(
            batch, return_tensors='pt', truncation=True,
            padding=True, max_length=128,
        ).to(device)
        with torch.no_grad():
            outputs = finbert_model(**inputs)
        cls_emb = outputs.last_hidden_state[:, 0, :].cpu().numpy()
        embeddings.append(cls_emb)
    return np.vstack(embeddings)


def build_features(texts, rule_sentiments, vectorizer=None, fit=False):
    if fit:
        vectorizer = TfidfVectorizer(max_features=TFIDF_MAX_FEATURES, ngram_range=(1, 2))
        tfidf = vectorizer.fit_transform(texts).toarray()
    else:
        tfidf = vectorizer.transform(texts).toarray()

    finbert = get_finbert_embeddings(texts)
    rule_col = np.array(rule_sentiments, dtype=float).reshape(-1, 1)

    combined = np.hstack([
        tfidf,
        FINBERT_WEIGHT * finbert,
        RULE_WEIGHT * rule_col,
    ])
    return combined, vectorizer


def build_industry_calibration(industries, price_changes):
    """按行业统计收益率，用于预测阶段校准。"""
    from collections import defaultdict
    buckets = defaultdict(list)
    for ind, pc in zip(industries, price_changes):
        buckets[str(ind)].append(pc)

    global_mean = float(np.mean([p[0] for p in price_changes]))
    cal = {'global_mean_1d': global_mean, 'industries': {}}
    for ind, rows in buckets.items():
        arr = np.array(rows)
        cal['industries'][ind] = {
            'count': len(rows),
            'mean_1d': float(np.mean(arr[:, 0])),
            'mean_2d': float(np.mean(arr[:, 1])),
            'mean_3d': float(np.mean(arr[:, 2])),
            'std_1d': float(np.std(arr[:, 0]) or 0.01),
        }
    return cal


def train_hybrid_model(data_file=None, model_dir=None):
    data_file = data_file or (REAL_DATA if os.path.exists(REAL_DATA) else FALLBACK_DATA)
    model_dir = model_dir or MODEL_DIR

    texts, sentiment_scores, price_changes, rule_sentiments, industries, stock_codes = load_data(data_file)

    X, vectorizer = build_features(texts, rule_sentiments, fit=True)
    y_sent = np.array(sentiment_scores, dtype=float)
    y_price = np.array(price_changes, dtype=float)

    X_train, X_test, y_tr_s, y_te_s, y_tr_p, y_te_p = train_test_split(
        X, y_sent, y_price, test_size=0.2, random_state=42,
    )

    print('训练情感模型...')
    sentiment_model = RandomForestRegressor(n_estimators=120, random_state=42, n_jobs=-1)
    sentiment_model.fit(X_train, y_tr_s)

    print('训练价格变动模型...')
    price_model = RandomForestRegressor(n_estimators=120, random_state=42, n_jobs=-1)
    price_model.fit(X_train, y_tr_p)

    pred_s = sentiment_model.predict(X_test)
    pred_p = price_model.predict(X_test)
    mse_s = mean_squared_error(y_te_s, pred_s)
    r2_s = r2_score(y_te_s, pred_s)
    mse_p = mean_squared_error(y_te_p, pred_p, multioutput='raw_values')
    r2_p = r2_score(y_te_p, pred_p, multioutput='raw_values')

    print(f'情感 MSE={mse_s:.4f}, R²={r2_s:.4f}')
    print(f'价格 MSE={mse_p}, R²={r2_p}')

    os.makedirs(model_dir, exist_ok=True)
    joblib.dump(sentiment_model, os.path.join(model_dir, 'sentiment_model.pkl'))
    joblib.dump(vectorizer, os.path.join(model_dir, 'vectorizer.joblib'))
    joblib.dump(price_model, os.path.join(model_dir, 'price_model.pkl'))

    industry_cal = build_industry_calibration(industries, price_changes)
    metrics = {
        'sentiment_mse': float(mse_s),
        'sentiment_r2': float(r2_s),
        'price_mse': [float(x) for x in mse_p],
        'price_r2': [float(x) for x in r2_p],
        'train_samples': len(texts),
        'data_source': os.path.basename(data_file),
        'feature_dim': int(X.shape[1]),
    }

    with open(os.path.join(model_dir, 'feature_config.json'), 'w', encoding='utf-8') as f:
        json.dump({
            'mode': 'hybrid_tfidf_finbert',
            'tfidf_max_features': TFIDF_MAX_FEATURES,
            'finbert_weight': FINBERT_WEIGHT,
            'rule_feature': True,
        }, f, ensure_ascii=False, indent=2)

    with open(os.path.join(model_dir, 'model_metrics.json'), 'w', encoding='utf-8') as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

    with open(os.path.join(model_dir, 'industry_calibration.json'), 'w', encoding='utf-8') as f:
        json.dump(industry_cal, f, ensure_ascii=False, indent=2)

    print(f'模型已保存至 {model_dir}')
    return metrics


if __name__ == '__main__':
    if not os.path.exists(REAL_DATA):
        print('未找到真实数据集，请先运行: python model/build_dataset.py')
        print('将暂时使用示例数据训练...')
    train_hybrid_model()
