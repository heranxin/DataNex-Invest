import json
import logging
import os
import sys
import warnings
from pathlib import Path

import joblib
import numpy as np

warnings.filterwarnings('ignore', category=FutureWarning, module='transformers')
warnings.filterwarnings('ignore', category=FutureWarning, module='torch')
warnings.filterwarnings('ignore', category=FutureWarning, module='huggingface_hub')
try:
    from sklearn.exceptions import InconsistentVersionWarning
    warnings.filterwarnings('ignore', category=InconsistentVersionWarning)
except ImportError:
    pass

ROOT_DIR = Path(__file__).parent.parent
sys.path.append(str(ROOT_DIR))

import utils
from model.news_analysis import (
    DISCLAIMER,
    METHODOLOGY,
    blend_price_changes,
    blend_sentiment,
    build_market_note,
    classify_announcement,
    compute_confidence,
    get_recent_price_context,
    get_stock_industry,
    get_stock_name,
    model_reliability_hint,
    refine_trend_label,
    synthesize_prediction,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

_MODEL_CACHE = {}
_META_CACHE = {}
DEFAULT_MODEL_DIR = os.path.join(os.path.dirname(__file__), '..', 'models')


def _joblib_load_sklearn_model(path):
    import sklearn.tree._tree as sktree

    original_check = sktree._check_node_ndarray

    def _compat_check(node_ndarray, expected_dtype=None):
        if expected_dtype is None:
            expected_dtype = sktree.NODE_DTYPE
        if node_ndarray.dtype == expected_dtype:
            return node_ndarray
        old_names = set(node_ndarray.dtype.names or [])
        new_names = set(expected_dtype.names or [])
        if 'missing_go_to_left' in new_names and 'missing_go_to_left' not in old_names:
            upgraded = np.zeros(node_ndarray.shape[0], dtype=expected_dtype)
            for name in old_names:
                upgraded[name] = node_ndarray[name]
            upgraded['missing_go_to_left'] = 0
            return upgraded
        return original_check(node_ndarray, expected_dtype)

    sktree._check_node_ndarray = _compat_check
    try:
        model = joblib.load(path)
    finally:
        sktree._check_node_ndarray = original_check
    return _upgrade_sklearn_estimator(model)


def _upgrade_sklearn_estimator(estimator):
    from sklearn.tree import DecisionTreeRegressor, DecisionTreeClassifier

    if hasattr(estimator, 'estimators_'):
        for est in estimator.estimators_:
            _upgrade_sklearn_estimator(est)

    if isinstance(estimator, (DecisionTreeRegressor, DecisionTreeClassifier)):
        if not hasattr(estimator, 'monotonic_cst'):
            estimator.monotonic_cst = None

    if not hasattr(estimator, 'monotonic_cst'):
        try:
            estimator.monotonic_cst = None
        except (AttributeError, TypeError):
            pass
    return estimator


def _load_json(model_dir, filename):
    path = os.path.join(model_dir, filename)
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def _get_feature_config(model_dir):
    return _load_json(model_dir, 'feature_config.json')


def _align_features(features, n_expected):
    n_actual = features.shape[1]
    if n_actual == n_expected:
        return features
    if n_actual > n_expected:
        return features[:, :n_expected]
    pad = np.zeros((features.shape[0], n_expected - n_actual))
    return np.hstack([features, pad])


def load_models(model_dir=None, use_cache=True):
    model_dir = model_dir or DEFAULT_MODEL_DIR
    cache_key = os.path.abspath(model_dir)
    if use_cache and cache_key in _MODEL_CACHE:
        return _MODEL_CACHE[cache_key]

    sentiment_model_path = os.path.join(model_dir, 'sentiment_model.pkl')
    vectorizer_path = os.path.join(model_dir, 'vectorizer.joblib')
    price_model_path = os.path.join(model_dir, 'price_model.pkl')

    for p in (sentiment_model_path, vectorizer_path, price_model_path):
        if not os.path.exists(p):
            raise FileNotFoundError(f'模型文件不存在: {p}')

    sentiment_model = _joblib_load_sklearn_model(sentiment_model_path)
    vectorizer = joblib.load(vectorizer_path)
    price_model = _joblib_load_sklearn_model(price_model_path)

    logger.info('模型加载成功')
    models = (sentiment_model, vectorizer, price_model)
    if use_cache:
        _MODEL_CACHE[cache_key] = models
        _META_CACHE[cache_key] = {
            'config': _get_feature_config(model_dir),
            'metrics': _load_json(model_dir, 'model_metrics.json'),
            'calibration': _load_json(model_dir, 'industry_calibration.json'),
        }
    return models


def _get_meta(model_dir=None):
    model_dir = model_dir or DEFAULT_MODEL_DIR
    cache_key = os.path.abspath(model_dir)
    if cache_key not in _META_CACHE:
        _META_CACHE[cache_key] = {
            'config': _get_feature_config(model_dir),
            'metrics': _load_json(model_dir, 'model_metrics.json'),
            'calibration': _load_json(model_dir, 'industry_calibration.json'),
        }
    return _META_CACHE[cache_key]


def extract_features(news_text, vectorizer, model_dir=None, n_features_expected=None):
    model_dir = model_dir or DEFAULT_MODEL_DIR
    config = _get_feature_config(model_dir)
    mode = config.get('mode', 'hybrid_tfidf_finbert')

    rule_info = classify_announcement(news_text)
    tfidf_vector = vectorizer.transform([news_text]).toarray()

    if mode == 'tfidf_only':
        combined = tfidf_vector
    elif mode in ('hybrid', 'hybrid_tfidf_finbert'):
        from model.train import FINBERT_WEIGHT, RULE_WEIGHT, get_finbert_embeddings
        finbert_features = get_finbert_embeddings([news_text])
        rule_col = np.array([[rule_info['rule_sentiment']]])
        combined = np.hstack([
            tfidf_vector,
            FINBERT_WEIGHT * finbert_features,
            RULE_WEIGHT * rule_col,
        ])
    else:
        from model.train import get_finbert_embeddings
        finbert_features = get_finbert_embeddings([news_text])
        combined = np.hstack([tfidf_vector, 0.8 * finbert_features])

    if n_features_expected is not None:
        combined = _align_features(combined, n_features_expected)

    return combined, rule_info


def predict_sentiment_and_price_change(news_text, models=None, model_dir=None):
    try:
        model_dir = model_dir or DEFAULT_MODEL_DIR
        if models is None:
            models = load_models(model_dir)
        sentiment_model, vectorizer, price_model = models
        n_features = getattr(sentiment_model, 'n_features_in_', None)

        combined_features, rule_info = extract_features(
            news_text, vectorizer, model_dir=model_dir, n_features_expected=n_features,
        )
        ml_sentiment = float(sentiment_model.predict(combined_features)[0])
        ml_price = price_model.predict(combined_features)[0]

        sentiment = blend_sentiment(ml_sentiment, rule_info['rule_sentiment'])
        price_change = blend_price_changes(ml_price, rule_info['rule_sentiment'])

        return sentiment, price_change, rule_info
    except Exception as e:
        logger.error(f'单条新闻预测错误: {e}', exc_info=True)
        return None, None, None


def _apply_industry_calibration(avg_price_change, industry, model_dir=None):
    meta = _get_meta(model_dir)
    cal = meta.get('calibration', {})
    industries = cal.get('industries', {})
    if industry not in industries:
        return avg_price_change

    ind = industries[industry]
    global_mean = cal.get('global_mean_1d', 0.0)
    scale = max(ind.get('std_1d', 0.01), 0.01)
    adjusted = np.array(avg_price_change, dtype=float).copy()
    adjusted[0] += (ind['mean_1d'] - global_mean) * 0.2
    adjusted[1] += (ind.get('mean_2d', 0) - global_mean) * 0.15
    adjusted[2] += (ind.get('mean_3d', 0) - global_mean) * 0.1
    adjusted = adjusted * (1 + (scale - 1) * 0.05)
    return adjusted


def _direction_label(day1):
    if day1 > 0.08:
        return '看多', 'up'
    if day1 < -0.08:
        return '看空', 'down'
    return '中性', 'flat'


def predict_stock_movement(stock_id):
    try:
        news_info = utils.fund_Stock_Info(stock_id)
        logger.info(f'获取到新闻条数: {len(news_info)}')
        if not news_info:
            return None

        model_dir = DEFAULT_MODEL_DIR
        try:
            models = load_models(model_dir)
        except Exception as e:
            logger.error(f'模型加载失败: {e}')
            return None

        meta = _get_meta(model_dir)
        industry = get_stock_industry(stock_id)
        stock_name = get_stock_name(stock_id)
        price_context = get_recent_price_context(stock_id)
        news_source = news_info[0].source if news_info else '东方财富'

        sentiments = []
        price_changes_list = []
        rule_types = []
        news_evidence = []

        for item in news_info:
            news = item.text
            sentiment, price_changes, rule_info = predict_sentiment_and_price_change(
                news, models=models, model_dir=model_dir,
            )
            if sentiment is None or price_changes is None:
                continue

            sentiments.append(sentiment)
            price_changes_list.append(price_changes)
            rule_types.append(rule_info['type'])

            d1 = float(np.asarray(price_changes)[0])
            dir_label, dir_key = _direction_label(d1)
            news_evidence.append({
                'title': news,
                'link': item.link or '',
                'source': getattr(item, 'source', news_source),
                'rule_label': rule_info['label'],
                'rule_type': rule_info['type'],
                'sentiment': round(float(sentiment), 4),
                'price_day1_pct': round(d1, 2),
                'direction': dir_key,
                'direction_label': dir_label,
            })

        if not sentiments:
            return None

        synthesis = synthesize_prediction(sentiments, price_changes_list, rule_types)
        avg_price_change = np.mean(price_changes_list, axis=0)
        avg_price_change = _apply_industry_calibration(avg_price_change, industry, model_dir)
        price_changes_rounded = [round(float(x), 2) for x in avg_price_change]

        display_trend, trend_key, trend_hint = refine_trend_label(
            synthesis['trend'],
            synthesis['trend_key'],
            price_changes_rounded,
        )

        confidence, warnings, stats = compute_confidence(
            sentiments, price_changes_list, meta.get('metrics'), rule_types,
        )

        model_r2 = meta.get('metrics', {}).get('sentiment_r2')
        model_weak, usage_hint = model_reliability_hint(model_r2)

        market_note = ''
        if price_context:
            market_note = build_market_note(synthesis['trend_key'], price_context.get('return_5d'))

        return {
            'stock_code': str(stock_id).zfill(6),
            'stock_name': stock_name,
            'avg_sentiment': f"{synthesis['avg_sentiment']:.4f}",
            'composite_score': synthesis['composite_score'],
            'trend': display_trend,
            'trend_key': trend_key,
            'trend_hint': trend_hint,
            'news_analysis': synthesis['summary'],
            'market_note': market_note,
            'price_changes': price_changes_rounded,
            'news_count': len(sentiments),
            'industry': industry,
            'confidence_level': confidence,
            'warnings': warnings,
            'confidence_stats': stats,
            'disclaimer': DISCLAIMER,
            'methodology': METHODOLOGY,
            'news_source': news_source,
            'news_evidence': news_evidence[:12],
            'price_context': price_context,
            'announcement_stats': {
                'bullish': synthesis['bullish_count'],
                'bearish': synthesis['bearish_count'],
                'routine': synthesis['routine_count'],
                'weighted_up': synthesis['weighted_up'],
                'weighted_down': synthesis['weighted_down'],
            },
            'model_r2': model_r2,
            'model_weak': model_weak,
            'usage_hint': usage_hint,
            'train_samples': meta.get('metrics', {}).get('train_samples'),
            'data_source': meta.get('metrics', {}).get('data_source', 'unknown'),
        }
    except Exception as e:
        logger.error(f'预测股票 {stock_id} 失败: {e}', exc_info=True)
        return None


if __name__ == '__main__':
    import pprint
    pprint.pp(predict_stock_movement('600519'))
