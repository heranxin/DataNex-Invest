# test.py
import matplotlib

matplotlib.use('Agg')  # 避免 GUI 环境下出错
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
import akshare as ak
import pandas as pd
import mplfinance as mpf
import os
import json
import time
from datetime import datetime, timedelta
from matplotlib import pyplot as plt
import matplotlib.dates as mdates

# 设置 Matplotlib 支持中文
def configure_chinese_support():
    plt.rcParams['font.sans-serif'] = ['SimHei']  # 指定默认字体为黑体
    plt.rcParams['axes.unicode_minus'] = False  # 解决负号 '-' 显示为方块的问题


# 新增一个保存图片的目录
CHARTS_DIR = "static/charts"
CACHE_DIR = "static/cache"  # 缓存目录
os.makedirs(CHARTS_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)


def _to_sina_symbol(stock_code):
    if stock_code.startswith(('5', '6', '9')):
        return f"sh{stock_code}"
    return f"sz{stock_code}"


def _safe_get_value(value, default="--"):
    if pd.isna(value) or (isinstance(value, float) and value != value):
        return default
    return value


def _fetch_hist_data(stock_code, days=30):
    end_date = pd.Timestamp.now().strftime("%Y%m%d")
    start_date = (pd.Timestamp.now() - pd.Timedelta(days=days * 2)).strftime("%Y%m%d")

    try:
        hist_data = ak.stock_zh_a_hist(
            symbol=stock_code,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="qfq"
        )
        # akshare 列：日期, 股票代码, 开盘, 收盘, 最高, 最低, 成交量, 成交额, ...
        if '成交量' in hist_data.columns:
            hist_data = hist_data[['日期', '开盘', '收盘', '最高', '最低', '成交量']].copy()
        else:
            hist_data = hist_data.iloc[:, [0, 2, 3, 4, 5, 6]].copy()
            hist_data.columns = ['日期', '开盘', '收盘', '最高', '最低', '成交量']
        hist_data['日期'] = pd.to_datetime(hist_data['日期'])
        hist_data['股票代码'] = stock_code
        print("历史数据: 东方财富")
    except Exception as e:
        print(f"东方财富历史数据失败，改用新浪: {e}")
        hist_data = ak.stock_zh_a_daily(
            symbol=_to_sina_symbol(stock_code),
            start_date=start_date,
            end_date=end_date,
            adjust="qfq"
        )
        hist_data = hist_data.rename(columns={
            'date': '日期', 'open': '开盘', 'close': '收盘', 'high': '最高', 'low': '最低',
            'volume': '成交量',
        })
        hist_data['日期'] = pd.to_datetime(hist_data['日期'])
        hist_data['股票代码'] = stock_code
        cols = ['日期', '股票代码', '开盘', '收盘', '最高', '最低']
        if '成交量' in hist_data.columns:
            cols.append('成交量')
        hist_data = hist_data[cols]
        print("历史数据: 新浪")

    for col in ['开盘', '收盘', '最高', '最低']:
        hist_data[col] = hist_data[col].fillna(0)
    if '成交量' in hist_data.columns:
        hist_data['成交量'] = pd.to_numeric(hist_data['成交量'], errors='coerce').fillna(0)
    else:
        hist_data['成交量'] = 0

    if len(hist_data) > days:
        hist_data = hist_data.iloc[-days:]
    return hist_data.reset_index(drop=True)


def _fetch_realtime(stock_code, hist_data):
    for source, fetch in (
        ("东方财富", lambda: ak.stock_zh_a_spot_em()),
        ("新浪", lambda: ak.stock_zh_a_spot()),
    ):
        try:
            spot_data = fetch()
            if source == "东方财富":
                row = spot_data[spot_data["代码"] == stock_code].iloc[0]
            else:
                row = spot_data[spot_data["代码"] == _to_sina_symbol(stock_code)].iloc[0]

            price = _safe_get_value(row.get("最新价"), 0)
            if price not in (0, "0", "--"):
                print(f"实时行情: {source}")
                return {
                    "最新价": price,
                    "涨跌幅": f"{_safe_get_value(row.get('涨跌幅', 0), 0)}%",
                    "成交量": f"{_safe_get_value(row.get('成交量', 0), 0) / 10000:.2f}万手",
                    "成交额": f"{_safe_get_value(row.get('成交额', 0), 0) / 100000000:.2f}亿元",
                }
        except Exception as e:
            print(f"{source}实时行情失败: {e}")

    if hist_data is None or hist_data.empty:
        raise ValueError("无法获取实时行情")

    last = hist_data.iloc[-1]
    prev = hist_data.iloc[-2] if len(hist_data) > 1 else last
    change_pct = (last['收盘'] - prev['收盘']) / prev['收盘'] * 100 if prev['收盘'] else 0
    print("实时行情: 历史收盘价")
    return {
        "最新价": last['收盘'],
        "涨跌幅": f"{change_pct:.2f}%",
        "成交量": "--",
        "成交额": "--",
    }


def get_stock_data(stock_code="600519", days=30):
    """
    获取股票的实时行情、历史数据和财务数据。
    参数:
        stock_code: 股票代码 (默认值为600519)
        days: 获取最近的历史交易日天数 (默认为30天)
    返回:
        dict: 包含各类数据的字典对象
    """
    try:
        hist_data = _fetch_hist_data(stock_code, days=days)
        result = {
            "realtime": _fetch_realtime(stock_code, hist_data),
            "history": hist_data,
        }
        print(f"✅ 数据获取成功，历史数据长度: {len(result['history'])}")
        return result
    except Exception as e:
        print(f"❌ 数据获取失败: {str(e)}")
        return None


def plot_stock_line_chart(
    hist_data, 
    save_path, 
    stock_code="600519", 
    title=None, 
    pred_dates=None, 
    pred_prices=None
):
    """
    画历史折线图，可选叠加预测线，风格完全统一
    """
    configure_chinese_support()
    plt.figure(figsize=(12, 6))
    # 历史线
    plt.plot(hist_data['日期'], hist_data['收盘'], marker='o', linestyle='-', color='blue', linewidth=2, markersize=4, label='历史价格')
    # 预测线
    if pred_dates is not None and pred_prices is not None:
        plt.plot(pred_dates, pred_prices, marker='s', linestyle='--', color='red', linewidth=2, markersize=6, label='预测价格')
    # 标题
    if title is None:
        title = f"{stock_code} 最近 {len(hist_data)} 天收盘价趋势 (单位: 元)"
    plt.title(title, fontsize=16)
    plt.xlabel("日期", fontsize=12)
    plt.ylabel("价格 (元)", fontsize=12)
    plt.legend()
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(save_path, dpi=300, bbox_inches='tight')
    plt.close()


def plot_line_chart(data, stock_code="600519"):
    """Plot closing price line chart and return file path"""
    path = os.path.join(CHARTS_DIR, f"{stock_code}_line.png")
    print(f"正在生成折线图: {path}")
    plot_stock_line_chart(data, path, stock_code)
    return path


def plot_candlestick_chart(data, stock_code="600519"):
    """Plot candlestick chart and return file path"""
    path = os.path.join(CHARTS_DIR, f"{stock_code}_candlestick.png")

    print(f"正在生成K线图: {path}")
    configure_chinese_support()

    df = data.copy()
    df = df.rename(columns={'开盘': 'Open', '最高': 'High', '最低': 'Low', '收盘': 'Close'})
    df.set_index('日期', inplace=True)
    df = df[['Open', 'High', 'Low', 'Close']]

    # 使用 make_mpf_style 显式指定样式并保留字体设置
    mc = mpf.make_marketcolors(up='r', down='g', inherit=True)
    s = mpf.make_mpf_style(marketcolors=mc, rc={'font.sans-serif': 'SimHei'})

    mpf.plot(
        df,
        type='candle',
        style=s,
        title=f'{stock_code} 最近 {len(data)} 天K线图 (单位: 元)',
        ylabel='价格 (元)',
        volume=False,
        show_nontrading=False,
        savefig=path
    )
    return path


def test_chart_generation():
    """测试图表生成功能"""
    print("开始测试图表生成...")

    # 测试数据获取
    data = get_stock_data("600519")
    if data is None:
        print("❌ 数据获取失败")
        return False

    print(f"✅ 数据获取成功，历史数据长度: {len(data['history'])}")

    # 测试折线图生成
    try:
        line_path = plot_line_chart(data["history"], "600519")
        print(f"✅ 折线图生成成功: {line_path}")
    except Exception as e:
        print(f"❌ 折线图生成失败: {e}")
        return False

    # 测试K线图生成
    try:
        candle_path = plot_candlestick_chart(data["history"], "600519")
        print(f"✅ K线图生成成功: {candle_path}")
    except Exception as e:
        print(f"❌ K线图生成失败: {e}")
        return False

    return True


if __name__ == "__main__":
    test_chart_generation()