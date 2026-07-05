import pandas as pd
import jieba  # 中文分词库
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.model_selection import train_test_split

# 加载中文停用词
def load_stopwords(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        stopwords = [line.strip() for line in f.readlines()]
    return set(stopwords)

# 中文分词函数
def chinese_tokenizer(text):
    return jieba.lcut(text)

def load_and_preprocess_data(file_path, stopwords_path=None):
    # 读取数据
    df = pd.read_csv(file_path)
    texts = df['news_text'].tolist()
    # 假设 CSV 文件中有 'sentiment_score' 和 'price_change_1', 'price_change_2', 'price_change_3'
    sentiment_scores = df['sentiment_score'].tolist()
    price_changes = df[['price_change_1', 'price_change_2', 'price_change_3']].values.tolist()

    # 加载停用词（如果提供了路径）
    if stopwords_path:
        stopwords = load_stopwords(stopwords_path)
    else:
        # 使用默认的简单中文停用词
        stopwords = set(['的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一', '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好', '自己', '这'])

    # 使用 jieba 分词和中文停用词的 TF-IDF 向量化器
    vectorizer = TfidfVectorizer(
        tokenizer=chinese_tokenizer,  # 使用 jieba 分词
        stop_words=list(stopwords),   # 设置中文停用词
        max_features=5000,            # 限制特征数量，可根据需要调整
        ngram_range=(1, 2)            # 同时考虑单字和双字词
    )

    # 特征提取
    features = vectorizer.fit_transform(texts)

    # 划分训练集和验证集
    X_train, X_val, y_train_sentiment, y_val_sentiment, y_train_price, y_val_price = train_test_split(
        features, sentiment_scores, price_changes, test_size=0.2, random_state=42
    )

    return X_train, X_val, y_train_sentiment, y_val_sentiment, y_train_price, y_val_price, vectorizer