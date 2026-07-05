import os
import json
import time
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
import akshare as ak
from datetime import datetime, timedelta

# 配置中文字体
plt.rcParams["font.family"] = ["SimHei", "WenQuanYi Micro Hei", "Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False  # 解决负号显示问题

# 创建保存图片和缓存的目录
CHARTS_DIR = "static/charts"
# 换一个新的缓存目录，防止数据冲突
NEW_CACHE_DIR = "static/new_cache"
os.makedirs(CHARTS_DIR, exist_ok=True)
os.makedirs(NEW_CACHE_DIR, exist_ok=True)

def fetch_stock_data(stock_code="600519", days=30, cache_timeout=300):
    """
    获取股票数据，包括实时行情和历史K线数据
    
    参数:
        stock_code: 股票代码，默认为"600519"（贵州茅台）
        days: 获取的历史交易日天数，默认为30天
        cache_timeout: 缓存超时时间（秒），默认为300秒（5分钟）
    
    返回:
        dict: 包含股票数据的字典
    """
    # 构建缓存文件路径
    cache_file = os.path.join(NEW_CACHE_DIR, f"{stock_code}_data.json")
    cache_meta_file = os.path.join(NEW_CACHE_DIR, f"{stock_code}_meta.json")
    
    # 检查缓存是否存在且未过期
    if os.path.exists(cache_file) and os.path.exists(cache_meta_file):
        try:
            with open(cache_meta_file, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            
            # 检查缓存时间
            cache_time = datetime.fromisoformat(meta['timestamp'])
            if datetime.now() - cache_time < timedelta(seconds=cache_timeout):
                print(f"使用缓存数据: {cache_file}")
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cached_data = json.load(f)
                
                # 恢复DataFrame格式
                if 'history' in cached_data:
                    cached_data['history'] = pd.DataFrame(cached_data['history'])
                    cached_data['history']['日期'] = pd.to_datetime(cached_data['history']['日期'])
                
                return cached_data
        except Exception as e:
            print(f"读取缓存失败: {e}")
    
    # 如果缓存不存在或已过期，重新获取数据
    print(f"获取最新数据: {stock_code}")
    result = {}
    
    try:
        from test import get_stock_data as load_stock_data
        base_data = load_stock_data(stock_code, days=days)
        if base_data is None:
            raise ValueError("数据获取失败")

        hist_df = base_data["history"].copy()
        if '成交量' not in hist_df.columns and 'volume' in hist_df.columns:
            hist_df['成交量'] = hist_df['volume']

        result["realtime"] = {
            "名称": stock_code,
            **base_data["realtime"],
        }
        result["history"] = hist_df[['日期', '开盘', '收盘', '最高', '最低', '成交量']].copy()
        if "history" in result and not result["history"].empty:
            # 计算每日回报率
            hist_df = result["history"]
            hist_df['日回报率'] = hist_df['收盘'].pct_change() * 100
            
            # 计算累积回报率
            hist_df['累积回报率'] = (1 + hist_df['日回报率']/100).cumprod() - 1
            hist_df['累积回报率'] = hist_df['累积回报率'] * 100  # 转换为百分比
            
            result["history"] = hist_df
        
        # 保存到缓存
        try:
            cache_data = result.copy()
            if 'history' in cache_data:
                cache_data['history'] = cache_data['history'].to_dict('records')
            
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2, default=str)
            
            # 保存元数据
            meta = {
                'timestamp': datetime.now().isoformat(),
                'stock_code': stock_code,
                'days': days
            }
            with open(cache_meta_file, 'w', encoding='utf-8') as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            
            print(f"数据已缓存到: {cache_file}")
        except Exception as e:
            print(f"保存缓存失败: {e}")
        
        return result
    
    except Exception as e:
        print(f"获取股票数据失败: {e}")
        return None

def compute_return_rate_series(stock_code, decision_point, days=60):
    """
    计算决策点起的持有回报率序列（供 ECharts 使用）。
    公式：回报率(%) = (当日收盘 - 决策日收盘) / 决策日收盘 × 100
    """
    from model.news_analysis import get_stock_name

    data = fetch_stock_data(stock_code, days=max(days, 30) * 2)
    if data is None or "history" not in data or data["history"].empty:
        return None

    hist_data = data["history"].copy()
    if not pd.api.types.is_datetime64_any_dtype(hist_data['日期']):
        hist_data['日期'] = pd.to_datetime(hist_data['日期'])

    decision_date = pd.to_datetime(decision_point)
    filtered = hist_data[hist_data['日期'] >= decision_date].copy()
    if filtered.empty:
        return None

    initial_price = float(filtered.iloc[0]['收盘'])
    if initial_price <= 0:
        return None

    points = []
    for _, row in filtered.iterrows():
        close = float(row['收盘'])
        ret = (close - initial_price) / initial_price * 100
        dt = row['日期']
        date_str = dt.strftime('%Y-%m-%d') if hasattr(dt, 'strftime') else str(dt)[:10]
        points.append({
            'date': date_str,
            'close': round(close, 2),
            'return_pct': round(ret, 2),
        })

    last = points[-1]
    rt = data.get('realtime') or {}
    name = str(rt.get('名称') or rt.get('name') or '').strip()
    if not name or name == stock_code or name.isdigit():
        name = get_stock_name(stock_code)

    returns = [p['return_pct'] for p in points]
    peak = returns[0]
    max_drawdown = 0.0
    for r in returns:
        peak = max(peak, r)
        max_drawdown = min(max_drawdown, r - peak)

    return {
        'code': stock_code,
        'name': name,
        'decision_point': decision_point,
        'initial_price': round(initial_price, 2),
        'current_price': last['close'],
        'total_return_pct': last['return_pct'],
        'trading_days': len(points),
        'max_drawdown_pct': round(max_drawdown, 2),
        'points': points,
    }


def calculate_return_rate_chart(stock_code, decision_point, days=30):
    """
    计算并绘制从决策点开始的回报率图表
    
    参数:
        stock_code: 股票代码
        decision_point: 决策点日期 (格式: 'YYYY-MM-DD')
        days: 显示的天数
    
    返回:
        str: 图表保存路径
    """
    # 获取股票数据
    data = fetch_stock_data(stock_code, days=days*2)  # 获取更多数据以确保包含决策点
    if data is None or "history" not in data or data["history"].empty:
        return None
    
    hist_data = data["history"].copy()
    
    try:
        # 将决策点转换为datetime对象
        decision_date = pd.to_datetime(decision_point)
        
        # 筛选决策点之后的数据
        filtered_data = hist_data[hist_data['日期'] >= decision_date]
        
        if filtered_data.empty:
            print(f"没有找到决策点 {decision_point} 之后的数据")
            return None
        
        # 计算回报率
        initial_price = filtered_data.iloc[0]['收盘']
        filtered_data['回报率'] = (filtered_data['收盘'] - initial_price) / initial_price * 100
        
        # 设置图片清晰度
        plt.rcParams['figure.dpi'] = 300
        
        # 创建图表
        plt.figure(figsize=(12, 6))
        plt.plot(filtered_data['日期'], filtered_data['回报率'], marker='o', linestyle='-', color='g', linewidth=2, markersize=4)
        
        # 添加标题和标签
        stock_name = data["realtime"].get("名称", stock_code)
        plt.title(f"{stock_name}({stock_code}) 自 {decision_point} 以来的投资回报率", fontsize=16)
        plt.xlabel("日期", fontsize=12)
        plt.ylabel("回报率 (%)", fontsize=12)
        
        # 设置x轴日期格式
        plt.xticks(rotation=45)
        plt.gca().xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter('%Y-%m-%d'))
        
        # 添加网格线
        plt.grid(True, linestyle='--', alpha=0.7)
        
        # 添加水平线表示0%回报率
        plt.axhline(y=0, color='r', linestyle='-', alpha=0.3)
        
        # 标记初始点和当前点
        plt.scatter([filtered_data.iloc[0]['日期']], [filtered_data.iloc[0]['回报率']], color='red', s=100, zorder=5)
        plt.scatter([filtered_data.iloc[-1]['日期']], [filtered_data.iloc[-1]['回报率']], color='blue', s=100, zorder=5)
        
        # 添加初始点和当前点的标签
        plt.annotate(f"初始: {filtered_data.iloc[0]['回报率']:.2f}%", 
                    (filtered_data.iloc[0]['日期'], filtered_data.iloc[0]['回报率']),
                    textcoords="offset points", 
                    xytext=(0,10), 
                    ha='center')
        
        plt.annotate(f"当前: {filtered_data.iloc[-1]['回报率']:.2f}%", 
                    (filtered_data.iloc[-1]['日期'], filtered_data.iloc[-1]['回报率']),
                    textcoords="offset points", 
                    xytext=(0,10), 
                    ha='center')
        
        # 自动调整布局
        plt.tight_layout()
        
        # 保存图表
        chart_path = os.path.join(CHARTS_DIR, f"{stock_code}_{decision_point}_return_rate.png")
        plt.savefig(chart_path)
        plt.close()
        
        return chart_path
    except Exception as e:
        print(f"计算回报率图表失败: {e}")
        return None

# 测试函数
if __name__ == "__main__":
    # 获取股票数据
    stock_data = fetch_stock_data("600519", days=60)
    
    if stock_data:
        # 打印实时行情
        print("实时行情:")
        for key, value in stock_data["realtime"].items():
            print(f"{key}: {value}")
        
        # 计算并绘制回报率图表
        latest_date = stock_data["history"].iloc[-30]['日期'].strftime('%Y-%m-%d')
        return_chart = calculate_return_rate_chart("600519", latest_date, days=30)
        print(f"回报率图表已保存至: {return_chart}")