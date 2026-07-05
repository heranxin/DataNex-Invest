"""
快速训练预测模型（仅 TF-IDF），与当前 scikit-learn 版本兼容。
无需 FinBERT、Ollama、GPU。运行后可直接使用股票预测功能。

用法:
    python model/train_quick.py
"""
import json
import os

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, r2_score

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = os.path.join(os.path.dirname(__file__), 'data', 'stock_news.csv')
MODEL_DIR = os.path.join(ROOT, 'models')
MAX_FEATURES = 5000


def main():
    print(f'读取训练数据: {DATA_FILE}')
    df = pd.read_csv(DATA_FILE, engine='python')
    texts = df['news_text'].astype(str).tolist()
    sentiment_scores = df['sentiment_score'].tolist()
    price_changes = df[['price_change_1', 'price_change_2', 'price_change_3']].values

    print('提取 TF-IDF 特征...')
    vectorizer = TfidfVectorizer(max_features=MAX_FEATURES)
    X = vectorizer.fit_transform(texts).toarray()
    print(f'特征维度: {X.shape[1]}')

    X_train, X_test, y_train_s, y_test_s, y_train_p, y_test_p = train_test_split(
        X, sentiment_scores, price_changes, test_size=0.2, random_state=42
    )

    print('训练情感模型...')
    sentiment_model = RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)
    sentiment_model.fit(X_train, y_train_s)

    print('训练价格变动模型...')
    price_model = RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)
    price_model.fit(X_train, y_train_p)

    y_pred_s = sentiment_model.predict(X_test)
    y_pred_p = price_model.predict(X_test)
    print(f'情感模型 MSE: {mean_squared_error(y_test_s, y_pred_s):.4f}, R2: {r2_score(y_test_s, y_pred_s):.4f}')
    print(f'价格模型 MSE: {mean_squared_error(y_test_p, y_pred_p, multioutput="raw_values")}')

    os.makedirs(MODEL_DIR, exist_ok=True)
    joblib.dump(sentiment_model, os.path.join(MODEL_DIR, 'sentiment_model.pkl'))
    joblib.dump(vectorizer, os.path.join(MODEL_DIR, 'vectorizer.joblib'))
    joblib.dump(price_model, os.path.join(MODEL_DIR, 'price_model.pkl'))

    with open(os.path.join(MODEL_DIR, 'feature_config.json'), 'w', encoding='utf-8') as f:
        json.dump({'mode': 'tfidf_only', 'max_features': MAX_FEATURES}, f, ensure_ascii=False)

    print(f'模型已保存到: {MODEL_DIR}')
    print('请重启 Flask 服务后使用股票预测功能。')


if __name__ == '__main__':
    main()
