from asyncio import sleep
import logging
import re

import requests
from bs4 import BeautifulSoup
from DrissionPage import Chromium
from DrissionPage import ChromiumOptions

logger = logging.getLogger(__name__)


class NewsItem:
    """统一新闻条目，兼容原 DrissionPage 元素的 text / link 属性。"""

    def __init__(self, text, link='', source=''):
        self.text = text
        self.link = link
        self.source = source or '东方财富'


def _to_sina_symbol(stock_id):
    code = str(stock_id).strip()
    if code.startswith(('5', '6', '9')):
        return f'sh{code}'
    return f'sz{code}'


def _fetch_news_eastmoney(stock_id, limit=20):
    """通过东方财富公告接口获取个股资讯（稳定、无需浏览器）。"""
    url = 'https://np-anotice-stock.eastmoney.com/api/security/ann'
    params = {
        'page_size': limit,
        'page_index': 1,
        'ann_type': 'A',
        'client_source': 'web',
        'stock_list': stock_id,
    }
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://data.eastmoney.com/',
    }
    resp = requests.get(url, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    payload = resp.json()
    items = payload.get('data', {}).get('list', []) if payload.get('success') else []
    news_list = []
    for item in items:
        title = (item.get('title_ch') or item.get('title') or '').strip()
        if not title:
            continue
        columns = item.get('columns') or []
        if columns and columns[0].get('column_name'):
            title = f"{title}（{columns[0]['column_name']}）"
        art_code = item.get('art_code', '')
        link = f'https://data.eastmoney.com/notices/detail/{stock_id}/{art_code}.html' if art_code else ''
        news_list.append(NewsItem(title, link, source='东方财富'))
    return news_list


def _fetch_news_sina(stock_id, limit=20):
    """解析新浪财经个股资讯页面。"""
    symbol = _to_sina_symbol(stock_id)
    url = f'https://vip.stock.finance.sina.com.cn/corp/go.php/vCB_AllNewsStock/symbol/{symbol}.phtml'
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'html.parser')
    news_list = []
    datelist = soup.find('div', class_='datelist')
    anchors = datelist.find_all('a') if datelist else soup.select('.datelist a, .list_009 a')
    for a in anchors:
        title = a.get_text(strip=True)
        link = a.get('href', '')
        if title:
            news_list.append(NewsItem(title, link, source='新浪财经'))
        if len(news_list) >= limit:
            break
    return news_list


def _fetch_news_browser(stock_id, limit=20):
    """浏览器爬取（最后备选，页面结构变化时可能失败）。"""
    browser = None
    try:
        co = ChromiumOptions()
        co.headless()
        browser = Chromium(co)
        tab = browser.latest_tab
        tab.get('https://biz.finance.sina.com.cn/suggest/lookup_n.php?')
        search_input = tab.ele('@id=inputSuggest')
        search_input.input(stock_id)
        search_button = tab.ele('@@type=submit@@value=查询')
        search_button.click()
        sleep(1)
        select_tab = browser.latest_tab
        if not select_tab.url.endswith('nc.shtml'):
            category = select_tab.ele('@id=stock_stock').next().child()
            link = category.ele(f'@href:{stock_id}')
            link.click()
        info_tab = browser.latest_tab
        news_button = info_tab.ele('@text()=公司资讯', timeout=8)
        news_button.click()
        news_tab = browser.latest_tab
        news_list_el = news_tab.ele('@class=datelist', timeout=8)
        elements = news_list_el.eles('css:ul a')
        return elements[:limit]
    finally:
        if browser is not None:
            try:
                browser.quit()
            except Exception:
                pass

def classify_stock_code(code):
    """
    股票代码分类函数 - 只处理A股市场
    判断输入的股票代码是否为A股（沪深股市个股）
    """
    if not code:
        return None
    
    code = code.strip().upper()
    
    # 解析代码前缀和实际代码
    prefix = ""
    actual_code = code
    
    # 提取前缀
    if code.startswith('SH'):
        prefix = 'SH'
        actual_code = code[2:]
    elif code.startswith('SZ'):
        prefix = 'SZ'
        actual_code = code[2:]
    # 注释掉其他市场的前缀处理
    # elif code.startswith('HK'):
    #     prefix = 'HK'
    #     actual_code = code[2:]
    # elif code.startswith('US.'):
    #     prefix = 'US'
    #     actual_code = code[3:]
    # elif '.' in code and not code.endswith('.HK'):
    #     parts = code.split('.', 1)
    #     if parts[0].upper() == 'US':
    #         prefix = 'US'
    #         actual_code = parts[1]
    
    # 注释掉香港股票后缀处理
    # if actual_code.endswith('.HK'):
    #     actual_code = actual_code[:-3]
    
    # A股代码规则定义
    shanghai_stock = r'^(600|601|603|605|688)\d{3}$'  # 上海主板、科创板
    shenzhen_stock = r'^(000|001|002|003|300)\d{3}$'  # 深圳主板、创业板
    
    # 注释掉其他市场的代码规则
    # shanghai_index = r'^(000001|000002|000003|000008|000009|000010|000011|000012|000016|000017|000300|000852|000985)$'
    # shenzhen_index = r'^(399001|399002|399003|399004|399005|399006|399100|399101|399102|399106|399107|399108|399678)$'
    # etf_fund = r'^(159\d{3}|512\d{3}|513\d{3}|515\d{3}|516\d{3}|518\d{3}|560\d{3}|561\d{3}|562\d{3}|563\d{3}|588\d{3})$'
    # mutual_fund = r'^\d{6}$'
    # hk_stock_pattern = r'^0*[1-9]\d{0,4}$'
    # hk_warrant_pattern = r'^0*[1-9]\d{4}$'
    # us_stock = r'^[A-Z]{1,5}$'
    # bond = r'^(1[0-9]\d{4}|2[0-9]\d{4}|11\d{4}|12\d{4}|13\d{4}|14\d{4}|15\d{4}|16\d{4}|17\d{4}|18\d{4}|19\d{4})$'
    
    # 只处理A股（沪深股市个股）
    if prefix == 'SH':
        if re.match(shanghai_stock, actual_code):
            return "沪深股市(个股)"
        # 注释掉其他类型
        # elif re.match(shanghai_index, actual_code):
        #     return "沪深股市(指数)"
        # elif re.match(etf_fund, actual_code):
        #     return "沪深股市(场内基金)"
        # elif re.match(bond, actual_code):
        #     return "债券"
        # elif re.match(mutual_fund, actual_code):
        #     return "基金市场"
    
    elif prefix == 'SZ':
        if re.match(shenzhen_stock, actual_code):
            return "沪深股市(个股)"
        # 注释掉其他类型
        # elif re.match(shenzhen_index, actual_code):
        #     return "沪深股市(指数)"
        # elif re.match(etf_fund, actual_code):
        #     return "沪深股市(场内基金)"
        # elif re.match(bond, actual_code):
        #     return "债券"
        # elif re.match(mutual_fund, actual_code):
        #     return "基金市场"
    
    # 注释掉其他市场的处理
    # elif prefix == 'HK':
    #     if re.match(hk_warrant_pattern, actual_code) and int(actual_code) >= 10000:
    #         return "香港股市(涡轮)"
    #     elif re.match(hk_stock_pattern, actual_code) and 1 <= int(actual_code) <= 99999:
    #         return "香港股市(正股)"
    
    # elif prefix == 'US':
    #     if re.match(us_stock, actual_code):
    #         return "美国股市"
    
    else:
        # 无前缀的情况，只处理A股
        if re.match(shanghai_stock, actual_code) or re.match(shenzhen_stock, actual_code):
            return "沪深股市(个股)"
        
        # 注释掉其他类型的处理
        # if re.match(shanghai_index, actual_code) or re.match(shenzhen_index, actual_code):
        #     return "沪深股市(指数)"
        
        # if re.match(etf_fund, actual_code):
        #     return "沪深股市(场内基金)"
        
        # if re.match(hk_warrant_pattern, actual_code) and len(actual_code) == 5:
        #     return "香港股市(涡轮)"
        
        # if re.match(hk_stock_pattern, actual_code) and 1 <= int(actual_code) <= 99999:
        #     return "香港股市(正股)"
        
        # if re.match(us_stock, actual_code) and not actual_code.isdigit():
        #     return "美国股市"
        
        # if re.match(bond, actual_code):
        #     return "债券"
        
        # if (re.match(mutual_fund, actual_code) and 
        #     not re.match(shanghai_stock, actual_code) and 
        #     not re.match(shenzhen_stock, actual_code) and 
        #     not re.match(etf_fund, actual_code)):
        #     return "基金市场"
    
    return None
    

# A股个股信息爬取
def fund_Stock_Info(stock_id):
    """
    获取 A 股个股资讯/公告标题列表。
    优先使用东方财富 API，失败时依次尝试新浪页面解析与浏览器爬取。
    """
    stock_id = str(stock_id).strip()
    errors = []

    for fetcher_name, fetcher in (
        ('eastmoney', _fetch_news_eastmoney),
        ('sina', _fetch_news_sina),
    ):
        try:
            news_list = fetcher(stock_id)
            if news_list:
                logger.info('通过 %s 获取到 %d 条新闻: %s', fetcher_name, len(news_list), stock_id)
                return news_list[:20]
        except Exception as exc:
            errors.append(f'{fetcher_name}: {exc}')
            logger.warning('新闻获取失败(%s): %s', fetcher_name, exc)

    try:
        news_list = _fetch_news_browser(stock_id)
        if news_list:
            logger.info('通过浏览器获取到 %d 条新闻: %s', len(news_list), stock_id)
            return news_list
    except Exception as exc:
        errors.append(f'browser: {exc}')
        logger.warning('浏览器爬取失败: %s', exc)

    if errors:
        logger.error('无法获取股票 %s 新闻: %s', stock_id, '; '.join(errors))
    return []

# 注释掉其他市场的爬取函数
# #沪深股市（指数）
# def stock_Index_Info(socket_id):
#     co = ChromiumOptions()
#     co.headless()  # 无头模式
#     browser = Chromium(co)         
#     tab = browser.latest_tab       
#     tab.get("https://vip.stock.finance.sina.com.cn/mkt/")   
#     search_input = tab.ele('@id=inputSuggest')      
#     search_input.input(socket_id)
#     search_button = tab.ele('@@type=submit@@value=查询')
#     search_button.click()
#     select_tab = browser.latest_tab
#     link = select_tab.ele(f'@href:{socket_id}')
#     link.click()
#     info_tab = browser.latest_tab
#     news_button = info_tab.ele('@text()=证券要闻')
#     news_button.click()
#     news_tab = browser.latest_tab
#     news_list = news_tab.ele('@class=list_009')
#     news_titles = news_list.eles('css:ul a')  
#     if news_titles:
#         for title in news_titles:
#             print(title.text,title.link)
#     else:
#         print("未找到新闻标题，请检查页面结构")
#     return news_titles

# #沪深股市（场内基金）
# def stock_Fund_Info(stock_id):
#     co = ChromiumOptions()
#     co.headless()  # 无头模式
#     browser = Chromium(co)          
#     tab = browser.latest_tab       
#     tab.get("https://vip.stock.finance.sina.com.cn/mkt/")   
#     search_input = tab.ele('@id=inputSuggest')      
#     search_input.input(stock_id)
#     search_button = tab.ele('@@type=submit@@value=查询')
#     search_button.click()
#     select_tab = browser.latest_tab
#     category=select_tab.ele('@@class=market@@id=fund_fund').next().child()
#     link = category.ele(f'@href:{stock_id}')
#     link.click()
#     info_tab = browser.latest_tab
#     news_button = info_tab.ele('@text()=基金新闻')
#     news_button.click()
#     more_button = info_tab.ele('@!id=gg_viewmore@@text()=更多 >>')
#     more_button.click()
#     news_tab = browser.latest_tab
#     news_list = news_tab.ele('@class=list_009')
#     news_titles = news_list.eles('css:ul a')  
#     if news_titles:
#         for title in news_titles:
#             print(title.text,title.link)
#     else:
#         print("未找到新闻标题，请检查页面结构")
#     return news_titles

# #基金市场
# def fund_Fund_Info(socket_id):
#     co = ChromiumOptions()
#     co.headless()  # 无头模式
#     browser = Chromium(co)         
#     tab = browser.latest_tab       
#     tab.get("https://vip.stock.finance.sina.com.cn/mkt/")   
#     search_input = tab.ele('@id=inputSuggest')      
#     search_input.input(socket_id)
#     search_button = tab.ele('@@type=submit@@value=查询')
#     search_button.click()
#     select_tab = browser.latest_tab
#     category=select_tab.ele('@@class=market@@id=fund_fund').next().child()
#     link = category.ele(f'@href:{socket_id}')
#     link.click()
#     info_tab = browser.latest_tab
#     news_button = info_tab.ele('@text()=基金新闻')
#     news_button.click()
#     more_button = info_tab.ele('@!id=gg_viewmore@@text()=更多 >>')
#     more_button.click()
#     news_tab = browser.latest_tab
#     news_list = news_tab.ele('@class=list_009')
#     news_titles = news_list.eles('css:ul a')  
#     if news_titles:
#         for title in news_titles:
#             print(title.text,title.link)
#     else:
#         print("未找到新闻标题，请检查页面结构")
#     return news_titles

# #香港股市（正股）
# def hk_Stock_Info(stock_id):
#     co = ChromiumOptions()
#     co.headless()  # 无头模式
#     browser = Chromium(co)         
#     tab = browser.latest_tab       
#     tab.get("https://vip.stock.finance.sina.com.cn/mkt/")   
#     search_input = tab.ele('@id=inputSuggest')      
#     search_input.input(stock_id)
#     search_button = tab.ele('@@type=submit@@value=查询')
#     search_button.click()
#     select_tab = browser.latest_tab
#     category=select_tab.ele('@@class=market@@id=hk_stock').next().child()
#     link = category.ele(f'@href:{stock_id}')
#     link.click()
#     info_tab = browser.latest_tab
#     news_button = info_tab.ele('@text()=港股新闻')
#     news_button.click()
#     news_tab = browser.latest_tab
#     news_list = news_tab.ele('@class=list_009')
#     news_titles = news_list.eles('css:ul a')  
#     if news_titles:
#         for title in news_titles:
#             print(title.text,title.link)
#     else:
#         print("未找到新闻标题，请检查页面结构")
#     return news_titles

# #香港股市（涡轮）
# def hk_Warrant_Info(stock_id):
#     co = ChromiumOptions()
#     co.headless()  # 无头模式
#     browser = Chromium(co)         
#     tab = browser.latest_tab       
#     tab.get("https://vip.stock.finance.sina.com.cn/mkt/")   
#     search_input = tab.ele('@id=inputSuggest')      
#     search_input.input(stock_id)
#     search_button = tab.ele('@@type=submit@@value=查询')
#     search_button.click()
#     select_tab = browser.latest_tab
#     category=select_tab.ele('@@class=market@@id=hk_warrant').next().child()
#     link = category.ele(f'@href:{stock_id}')
#     link.click()
#     info_tab = browser.latest_tab
#     news_button = info_tab.ele('@text()=港股新闻')
#     news_button.click()
#     news_tab = browser.latest_tab
#     news_list = news_tab.ele('@class=list_009')
#     news_titles = news_list.eles('css:ul a')  
#     if news_titles:
#         for title in news_titles:
#             print(title.text,title.link)
#     else:
#         print("未找到新闻标题，请检查页面结构")
#     return news_titles

# #美国股市
# def us_Stock_Info(stock_id):
#     co = ChromiumOptions()
#     co.headless()  # 无头模式
#     browser = Chromium(co)         
#     tab = browser.latest_tab       
#     tab.get("https://vip.stock.finance.sina.com.cn/mkt/")   
#     search_input = tab.ele('@id=inputSuggest')      
#     search_input.input(stock_id)
#     search_button = tab.ele('@@type=submit@@value=查询')
#     search_button.click()
#     select_tab = browser.latest_tab
#     category=select_tab.ele('@@class=market@@id=us_stock').next().child()
#     link = category.ele(f'@href:{stock_id}')
#     link.click()
#     info_tab = browser.latest_tab
#     news_button = info_tab.ele('@text()=美股新闻')
#     news_button.click()
#     news_tab = browser.latest_tab
#     news_list = news_tab.ele('@class=list_009')
#     news_titles = news_list.eles('css:ul a')  
#     if news_titles:
#         for title in news_titles:
#             print(title.text,title.link)
#     else:
#         print("未找到新闻标题，请检查页面结构")
#     return news_titles

# #债券
# def cn_Bond_Info(stock_id):
#     co = ChromiumOptions()
#     co.headless()  # 无头模式
#     browser = Chromium(co)         
#     tab = browser.latest_tab       
#     tab.get("https://vip.stock.finance.sina.com.cn/mkt/")   
#     search_input = tab.ele('@id=inputSuggest')      
#     search_input.input(stock_id)
#     search_button = tab.ele('@@type=submit@@value=查询')
#     search_button.click()
#     select_tab = browser.latest_tab
#     category=select_tab.ele('@@class=market@@id=bond').next().child()
#     link = category.ele(f'@href:{stock_id}')
#     link.click()
#     info_tab = browser.latest_tab
#     news_button = info_tab.ele('@text()=债券新闻')
#     news_button.click()
#     news_tab = browser.latest_tab
#     news_list = news_tab.ele('@class=list_009')
#     news_titles = news_list.eles('css:ul a')  
#     if news_titles:
#         for title in news_titles:
#             print(title.text,title.link)
#     else:
#         print("未找到新闻标题，请检查页面结构")
#     return news_titles

# def visit(url):
#     """
#     通用网页访问函数
#     参数: url - 要访问的网址
#     返回: 浏览器标签页对象
#     """
#     co = ChromiumOptions()
#     co.headless()  # 无头模式
#     browser = Chromium(co)         
#     tab = browser.latest_tab       
#     tab.get(url)
#     return tab 