"""情感分可视化与资讯列表情感标注（规则 + 可选 ML）。"""
from model.news_analysis import classify_announcement


def sentiment_meter(score):
    """将 [-1, 1] 情感分转为用户可读的仪表盘数据。"""
    try:
        s = float(score)
    except (TypeError, ValueError):
        s = 0.0
    s = max(-1.0, min(1.0, s))
    pct = int((s + 1) / 2 * 100)  # 0=极空, 50=中性, 100=极多

    if s >= 0.35:
        label, tone = '偏乐观', 'bullish'
    elif s >= 0.08:
        label, tone = '略偏乐观', 'bullish'
    elif s <= -0.35:
        label, tone = '偏悲观', 'bearish'
    elif s <= -0.08:
        label, tone = '略偏悲观', 'bearish'
    else:
        label, tone = '中性', 'neutral'

    stars = max(1, min(5, round((s + 1) / 2 * 4 + 1)))
    return {
        'score': round(s, 4),
        'label': label,
        'tone': tone,
        'pct': pct,
        'stars': stars,
    }


def analyze_news_title(title, models=None):
    """单条公告标题情感分析。"""
    text = (title or '').strip()
    rule_info = classify_announcement(text)
    sentiment = float(rule_info['rule_sentiment'])
    source = 'rule'

    if models is not None:
        try:
            from model.predict import predict_sentiment_and_price_change
            ml_sent, _, _ = predict_sentiment_and_price_change(text, models=models)
            if ml_sent is not None:
                sentiment = float(ml_sent)
                source = 'ml'
        except Exception:
            pass

    meter = sentiment_meter(sentiment)
    return {
        'title': text,
        'rule_type': rule_info['type'],
        'rule_label': rule_info['label'],
        'sentiment': round(sentiment, 4),
        'sentiment_source': source,
        'meter': meter,
    }


def enrich_news_list(news_items, use_ml=False, model_dir=None):
    """
    news_items: [{'title', 'link'}, ...]
    返回带情感字段的列表与汇总。
    """
    models = None
    if use_ml:
        try:
            from model.predict import load_models
            models = load_models(model_dir)
        except Exception:
            models = None

    enriched = []
    for item in news_items or []:
        title = item.get('title') or item.get('text') or ''
        link = item.get('link') or ''
        row = analyze_news_title(title, models=models)
        row['link'] = link
        enriched.append(row)

    return enriched, summarize_sentiment(enriched)


def summarize_sentiment(items):
    if not items:
        return None

    scores = [float(i.get('sentiment', 0)) for i in items]
    avg = sum(scores) / len(scores)
    bullish = sum(1 for i in items if i.get('rule_type') == 'bullish')
    bearish = sum(1 for i in items if i.get('rule_type') == 'bearish')
    routine = sum(1 for i in items if i.get('rule_type') in ('routine', 'general', 'unknown'))

    meter = sentiment_meter(avg)
    if avg >= 0.15:
        overall = '近期公告整体偏积极'
    elif avg <= -0.15:
        overall = '近期公告整体偏谨慎'
    else:
        overall = '近期公告整体偏中性'

    return {
        'avg_sentiment': round(avg, 4),
        'meter': meter,
        'bullish': bullish,
        'bearish': bearish,
        'routine': routine,
        'total': len(items),
        'overall_text': overall,
        'has_ml': any(i.get('sentiment_source') == 'ml' for i in items),
    }
