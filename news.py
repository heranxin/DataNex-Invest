"""东方财富热点资讯抓取（网友点击排行榜）+ 本地缓存"""
import json
import os
import re
import threading
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup
from DrissionPage import Chromium, ChromiumOptions

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, 'static', 'new_cache')
HOT_NEWS_CACHE_FILE = os.path.join(CACHE_DIR, 'hot_news_cache.json')
# 每 30 分钟刷新一次；页面/API 优先读缓存，后台静默更新
CACHE_TTL_SECONDS = 1800

_REFRESH_LOCK = threading.Lock()

_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ),
    'Referer': 'https://data.eastmoney.com/',
}

_EASTMONEY_NOTICE_URL_RE = re.compile(
    r'https?://data\.eastmoney\.com/notices/detail/(?P<stock>\d+)/(?P<art>[A-Za-z0-9]+)\.html',
    re.I,
)


def _ensure_cache_dir():
    os.makedirs(CACHE_DIR, exist_ok=True)


def _read_hot_news_cache(allow_stale=False):
    _ensure_cache_dir()
    if not os.path.exists(HOT_NEWS_CACHE_FILE):
        return None
    try:
        with open(HOT_NEWS_CACHE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        updated = datetime.fromisoformat(data['updated_at'])
        if not allow_stale and datetime.now() - updated > timedelta(seconds=CACHE_TTL_SECONDS):
            return None
        return data
    except Exception:
        return None


def _write_hot_news_cache(items):
    _ensure_cache_dir()
    data = {
        'updated_at': datetime.now().isoformat(),
        'source': '东方财富 · 网友点击排行榜',
        'items': items,
    }
    with open(HOT_NEWS_CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def _scrape_hot_news_requests():
    """HTTP 抓取网友点击排行榜，无需启动浏览器。"""
    try:
        from model.network_utils import direct_connection
        with direct_connection():
            resp = requests.get(
                'https://finance.eastmoney.com/a/czqyw.html',
                headers=_HEADERS,
                timeout=15,
            )
        resp.encoding = resp.apparent_encoding or 'utf-8'
        soup = BeautifulSoup(resp.text, 'html.parser')
        for tag in soup.find_all(string=lambda t: t and '网友点击' in str(t)):
            parent = tag.parent
            for _ in range(8):
                if parent is None:
                    break
                ul = parent.find_next('ul')
                if ul:
                    items = []
                    for a in ul.find_all('a'):
                        text = (a.get_text() or '').strip()
                        link = (a.get('href') or '').strip()
                        if text and link.startswith('http'):
                            items.append({'title': text, 'link': link})
                    if items:
                        return items
                parent = parent.parent
    except Exception as e:
        print(f'HTTP 抓取热点新闻失败: {e}')
    return []


def _scrape_hot_news_drission():
    co = ChromiumOptions()
    co.headless()
    browser = Chromium(co)
    tab = browser.latest_tab
    tab.get('https://finance.eastmoney.com/a/czqyw.html')
    location = tab.ele('text:网友点击排行榜')
    location = location.parent(1).next()
    title_els = location.eles('css:ul li a')
    items = []
    for el in title_els:
        text = (el.text or '').strip()
        link = el.link
        if text and link:
            items.append({'title': text, 'link': link})
    try:
        browser.quit()
    except Exception:
        pass
    return items


def _fetch_hot_news_network():
    """网络拉取：优先 HTTP，失败再尝试无头浏览器。"""
    items = _scrape_hot_news_requests()
    if items:
        return items
    try:
        return _scrape_hot_news_drission()
    except Exception as e:
        print(f'浏览器抓取热点新闻失败: {e}')
    return []


def _schedule_hot_news_refresh():
    """缓存过期时在后台更新，不阻塞 API 响应。"""

    def job():
        if not _REFRESH_LOCK.acquire(blocking=False):
            return
        try:
            items = _fetch_hot_news_network()
            if items:
                _write_hot_news_cache(items)
                print(f'热点新闻后台已更新: {len(items)} 条')
        except Exception as e:
            print(f'热点新闻后台更新失败: {e}')
        finally:
            _REFRESH_LOCK.release()

    threading.Thread(target=job, daemon=True).start()


def get_hot_news(force_refresh=False):
    """
    返回 (items, updated_at_iso, source_label)
    items: [{'title', 'link'}, ...]
    数据来自东方财富「网友点击排行榜」，按用户点击量排序，非毫秒级实时。
    """
    cached = _read_hot_news_cache(allow_stale=True)

    if force_refresh:
        items = _fetch_hot_news_network()
        if items:
            data = _write_hot_news_cache(items)
            return data['items'], data['updated_at'], data['source']
        if cached:
            return cached.get('items', []), cached.get('updated_at'), cached.get('source', '东方财富')
        return [], None, '东方财富'

    fresh = _read_hot_news_cache(allow_stale=False)
    if fresh:
        return fresh['items'], fresh['updated_at'], fresh.get('source', '东方财富')

    if cached:
        _schedule_hot_news_refresh()
        source = cached.get('source', '东方财富')
        return cached.get('items', []), cached.get('updated_at'), source + ' · 缓存'

    items = _fetch_hot_news_network()
    if items:
        data = _write_hot_news_cache(items)
        return data['items'], data['updated_at'], data['source']
    return [], None, '东方财富'


def getNews():
    """兼容旧接口：返回标题列表与链接列表"""
    items, _, _ = get_hot_news()
    return [i['title'] for i in items], [i['link'] for i in items]


def _clean_paragraphs(paragraphs, title=''):
    cleaned = []
    for p in paragraphs:
        p = (p or '').strip()
        if not p or len(p) < 4:
            continue
        if title and p == title:
            continue
        if p.startswith('责任编辑') or p.startswith('风险提示'):
            continue
        if re.match(r'^[^\u4e00-\u9fff]{0,6}APP', p):
            continue
        cleaned.append(p)
    return cleaned


def _scrape_eastmoney_notice_api(link):
    """东方财富个股公告详情页：正文在 notice API，页面多为 PDF 链接。"""
    m = _EASTMONEY_NOTICE_URL_RE.search(link or '')
    if not m:
        return None

    art_code = m.group('art')
    resp = requests.get(
        'https://np-cnotice-stock.eastmoney.com/api/content/ann',
        params={'art_code': art_code, 'client_source': 'web'},
        headers=_HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json().get('data') or {}
    content = (data.get('notice_content') or '').strip()
    title = (data.get('notice_title') or '').strip()
    if not content:
        return None

    raw_lines = [ln.strip() for ln in re.split(r'\n+', content) if ln.strip()]
    paragraphs = _clean_paragraphs(raw_lines, title)
    if not paragraphs:
        paragraphs = [re.sub(r'\s+', ' ', content)]

    published_at = (data.get('notice_date') or data.get('eitime') or '')[:10]

    return {
        'title': title,
        'source': '东方财富网',
        'published_at': published_at,
        'paragraphs': paragraphs,
        'link': link,
    }


def _scrape_article_requests(link):
    resp = requests.get(link, headers=_HEADERS, timeout=15)
    resp.encoding = resp.apparent_encoding or 'utf-8'
    soup = BeautifulSoup(resp.text, 'html.parser')

    title_el = soup.select_one('h1') or soup.select_one('.title')
    title = title_el.get_text(strip=True) if title_el else ''

    time_el = (
        soup.select_one('.time')
        or soup.select_one('.infos')
        or soup.select_one('[class*="time"]')
    )
    published_at = time_el.get_text(strip=True) if time_el else ''
    published_at = re.sub(r'\s+', ' ', published_at).strip()

    txtinfos = soup.select_one('.txtinfos') or soup.select_one('#ContentBody')
    if not txtinfos:
        return None

    paragraphs = [p.get_text(strip=True) for p in txtinfos.find_all('p')]
    paragraphs = _clean_paragraphs(paragraphs, title)
    if not paragraphs:
        return None

    return {
        'title': title,
        'source': '东方财富网',
        'published_at': published_at,
        'paragraphs': paragraphs,
        'link': link,
    }


def _scrape_article_drission(link):
    co = ChromiumOptions()
    co.headless()
    browser = Chromium(co)
    tab = browser.latest_tab
    tab.get(link)
    title = ''
    try:
        h1 = tab.ele('css:h1', timeout=3)
        if h1:
            title = h1.text.strip()
    except Exception:
        pass

    location = tab.ele('@class=txtinfos')
    news_articles = []
    articles = location.eles('css:p')
    if len(articles) > 2:
        articles = articles[1:-2]
    for article in articles:
        news_articles.append(article.text.strip())
    try:
        browser.quit()
    except Exception:
        pass

    paragraphs = _clean_paragraphs(news_articles, title)
    return {
        'title': title,
        'source': '东方财富网',
        'published_at': '',
        'paragraphs': paragraphs,
        'link': link,
    }


def getNewsArticles(link, title_hint=''):
    """
    获取新闻正文，返回结构化 dict。
    兼容：若调用方期望 list，请使用 get_news_article_dict。
    """
    article = get_news_article_dict(link, title_hint=title_hint)
    return article.get('paragraphs', [])


def get_news_article_dict(link, title_hint=''):
    if not link:
        return {'title': title_hint or '财经资讯', 'paragraphs': [], 'source': '东方财富网', 'published_at': '', 'link': link}

    if _EASTMONEY_NOTICE_URL_RE.search(link):
        try:
            article = _scrape_eastmoney_notice_api(link)
            if article and article.get('paragraphs'):
                if not article.get('title') and title_hint:
                    article['title'] = title_hint
                return article
        except Exception as e:
            print(f'公告 API 抓取失败: {e}')

    try:
        article = _scrape_article_requests(link)
        if article and article.get('paragraphs'):
            if not article.get('title') and title_hint:
                article['title'] = title_hint
            return article
    except Exception as e:
        print(f'HTTP 抓取正文失败: {e}')

    try:
        article = _scrape_article_drission(link)
        if article.get('paragraphs'):
            if not article.get('title') and title_hint:
                article['title'] = title_hint
            return article
    except Exception as e:
        print(f'浏览器抓取正文失败: {e}')

    return {
        'title': title_hint or '财经资讯',
        'source': '东方财富网',
        'published_at': '',
        'paragraphs': [],
        'link': link,
    }
