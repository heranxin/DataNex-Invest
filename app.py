from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file, Response
import json
from wordcloud import WordCloud
import requests
import io
from bs4 import BeautifulSoup
import re
import urllib.parse
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import webbrowser  # 导入webbrowser模块
import os  # 导入os模块用于处理文件路径
import sys  # 导入sys模块用于添加模块搜索路径
import warnings  # 导入warnings模块用于过滤警告
import traceback  # 放在文件开头

# 过滤警告
warnings.filterwarnings("ignore", category=FutureWarning, module="transformers")
warnings.filterwarnings("ignore", category=FutureWarning, module="torch")
warnings.filterwarnings("ignore", category=FutureWarning, module="huggingface_hub")
warnings.filterwarnings("ignore", category=UserWarning, module="werkzeug")

from test import get_stock_data, plot_line_chart, plot_candlestick_chart, plot_stock_line_chart
plot_candlestick_chart
from stock_data import fetch_stock_data,calculate_return_rate_chart
from news import getNews, getNewsArticles, get_hot_news, get_news_article_dict  # 导入 news.py 中的函数
from model.stock_search import search_stocks, resolve_stock_query, is_valid_a_share_code, build_stock_index
from model.stock_browse import get_browse_payload
from model.favorite_quotes import fetch_favorite_quotes
ROOT_DIR = Path(__file__).parent
sys.path.append(str(ROOT_DIR))

app = Flask(__name__, template_folder='templates')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SECRET_KEY'] = 'this-is-DingZhens-key-here'
db = SQLAlchemy(app)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    nickname = db.Column(db.String(50), nullable=True)
    phone = db.Column(db.String(20), unique=True, nullable=True)
    email = db.Column(db.String(120), unique=True, nullable=True)
    guide_completed = db.Column(db.Boolean, default=False, nullable=False)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class FavoriteStock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    stock_code = db.Column(db.String(10), nullable=False)
    user = db.relationship('User', backref=db.backref('favorite_stocks', lazy=True))


def _normalize_favorite_code(code):
    return str(code or '').strip().zfill(6)


def _find_favorite(user_id, code):
    target = _normalize_favorite_code(code)
    for fav in FavoriteStock.query.filter_by(user_id=user_id).all():
        if _normalize_favorite_code(fav.stock_code) == target:
            return fav
    return None


@app.context_processor
def inject_user():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        show_onboarding = bool(user and not user.guide_completed)
        return dict(current_user=user, show_onboarding=show_onboarding)
    return dict(current_user=None, show_onboarding=False)


def _migrate_user_guide_column():
    """为旧库补充 guide_completed 字段；已有用户默认视为已看过指南。"""
    from sqlalchemy import inspect, text

    insp = inspect(db.engine)
    if 'user' not in insp.get_table_names():
        return
    cols = {c['name'] for c in insp.get_columns('user')}
    if 'guide_completed' in cols:
        return
    with db.engine.connect() as conn:
        conn.execute(text('ALTER TABLE user ADD COLUMN guide_completed BOOLEAN DEFAULT 0 NOT NULL'))
        conn.execute(text('UPDATE user SET guide_completed = 1'))
        conn.commit()


@app.route('/')
def index():
    return redirect(url_for('login'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        nickname = request.form.get('nickname')
        phone = request.form.get('phone')
        email = request.form.get('email')

        if User.query.filter_by(username=username).first():
            return render_template('register.html', error='用户名已存在')
        if phone and User.query.filter_by(phone=phone).first():
            return render_template('register.html', error='手机号已被注册')
        if email and User.query.filter_by(email=email).first():
            return render_template('register.html', error='邮箱已被注册')

        new_user = User(
            username=username,
            nickname=nickname,
            phone=phone,
            email=email
        )
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        session['user_id'] = new_user.id
        session['username'] = new_user.username
        return redirect(url_for('login'))  # 修改为定向到 login 页面

    return render_template('register.html')


@app.route('/profile')
def profile():
    print(session)  # 打印 session 内容

    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    print(f"Querying user with username: {username}")  # 打印查询条件

    user = User.query.filter_by(username=username).first()
    if not user:
        print("User not found in database")  # 用户未找到时打印日志
        return redirect(url_for('login'))

    return render_template('profile.html', user=user)

@app.route('/edit_profile', methods=['GET', 'POST'])
def edit_profile():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    user = User.query.filter_by(username=username).first()
    error = None
    success = None

    if request.method == 'POST':
        # 处理个人信息更新
        nickname = request.form.get('nickname')
        phone = request.form.get('phone')
        email = request.form.get('email')

        # 检查手机号和邮箱是否已被其他用户使用
        if phone and User.query.filter(User.phone == phone, User.id != user.id).first():
            error = '手机号已被注册'
        elif email and User.query.filter(User.email == email, User.id != user.id).first():
            error = '邮箱已被注册'
        else:
            # 更新个人信息
            user.nickname = nickname
            user.phone = phone
            user.email = email

            # 处理密码更新
            old_password = request.form.get('old_password')
            new_password = request.form.get('new_password')
            confirm_password = request.form.get('confirm_password')

            if old_password or new_password or confirm_password:
                # 验证旧密码
                if not user.check_password(old_password):
                    error = '当前密码不正确'
                elif new_password != confirm_password:
                    error = '新密码和确认密码不匹配'
                elif len(new_password) < 6:
                    error = '新密码长度至少需要6个字符'
                else:
                    # 更新密码
                    user.set_password(new_password)
                    success = '密码已成功更新'

            if not error:
                db.session.commit()
                success = success or '个人信息已成功更新'

    return render_template('edit_profile.html', user=user, error=error, success=success)


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    reset_success = None
    if request.args.get('reset') == '1':
        reset_success = '账户已清空，请注册新账号后登录，即可体验新手使用指南。'
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()

        if not user:
            error = '账号不存在'
        elif not user.check_password(password):
            error = '密码错误'
        else:
            session['username'] = user.username
            session['user_id'] = user.id
            session['fresh_login'] = True
            return redirect(url_for('dashboard'))

    return render_template('login.html', error=error, reset_success=reset_success)


@app.route('/api/dev/reset-users', methods=['POST'])
def dev_reset_users():
    """开发测试：清空所有用户与自选股数据，便于重新注册并体验新手引导。"""
    try:
        FavoriteStock.query.delete()
        User.query.delete()
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'初始化失败：{e}'}), 500

    session.clear()
    return jsonify({'success': True, 'message': '已清空全部账户，请重新注册后登录体验新手引导'})


@app.route('/dashboard')
def dashboard():
    if 'username' in session:
        username = session['username']
        user = User.query.filter_by(username=username).first()
        if not user:
            return redirect(url_for('login'))
        favorite_stocks = user.favorite_stocks
        fav_codes = [s.stock_code for s in favorite_stocks]
        from model.favorite_quotes import fetch_favorite_quotes
        from model.market_ticker import get_daily_ticker_for_page, schedule_daily_refresh_if_stale
        schedule_daily_refresh_if_stale()
        ticker = get_daily_ticker_for_page(12)
        favorite_quotes = fetch_favorite_quotes(fav_codes, sort_by='change_pct', cache_only=True)
        fav_cached = sum(1 for q in favorite_quotes if q.get('status') == 'cached')
        fav_hint = f'{len(favorite_quotes)} 只自选 · 本地缓存 {fav_cached} 只'
        if fav_cached < len(favorite_quotes):
            fav_hint += ' · 其余后台刷新中'
        else:
            fav_hint += ' · 后台静默更新'
        return render_template(
            'dashboard.html',
            user=user,
            favorite_stocks=favorite_stocks,
            favorite_quotes=favorite_quotes,
            fav_hint=fav_hint,
            ticker=ticker,
        )
    else:
        return redirect(url_for('index'))


@app.route('/logout')
def logout():
    session.pop('username', None)
    session.pop('user_id', None)
    session.pop('fresh_login', None)
    return redirect(url_for('index'))


@app.route('/api/complete-guide', methods=['POST'])
def complete_guide():
    if 'user_id' not in session:
        return jsonify({'error': '未登录'}), 401
    user = User.query.get(session['user_id'])
    if not user:
        return jsonify({'error': '用户不存在'}), 404
    user.guide_completed = True
    db.session.commit()
    session.pop('fresh_login', None)
    return jsonify({'success': True})


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    """忘记密码页面"""
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        
        if not username or not email:
            return jsonify({'error': '用户名和邮箱不能为空'})
        
        # 检查用户是否存在
        user = User.query.filter_by(username=username, email=email).first()
        if not user:
            return jsonify({'error': '用户名或邮箱不正确'})
        
        # 这里应该发送重置密码邮件
        # 为了演示，我们直接返回成功消息
        return jsonify({'success': '重置邮件已发送，请检查您的邮箱'})
    
    return render_template('forgot_password.html')


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    """重置密码页面"""
    # 这里应该验证token的有效性
    # 为了演示，我们直接显示重置页面
    
    if request.method == 'POST':
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if not new_password or not confirm_password:
            return jsonify({'error': '密码不能为空'})
        
        if new_password != confirm_password:
            return jsonify({'error': '两次输入的密码不一致'})
        
        # 这里应该更新用户密码
        # 为了演示，我们直接返回成功消息
        return jsonify({'success': '密码重置成功'})
    
    return render_template('reset_password.html', token=token)


@app.route('/stock')
def stock():
    return render_template('stock.html')

@app.route('/stock_info')
def stock_info():
    return render_template('stock_info.html')

@app.route('/stock-news')
def stock_news():
    return render_template('stock_news.html')


@app.route('/sentiment-analysis')
def sentiment_analysis():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('sentiment_analysis.html')

@app.route('/test-buttons')
def test_buttons():
    return render_template('test_buttons.html')

# 添加gupiaotiaozhuan模块的路径到系统路径
MODULE_PATH = os.path.dirname(os.path.abspath(__file__))  # 获取当前文件所在目录
sys.path.append(MODULE_PATH)  # 将当前目录添加到系统路径中

def validate_a_stock_code(code):
    """验证A股股票代码格式"""
    # 移除可能的市场前缀（如SH或SZ）
    if code.upper().startswith(('SH', 'SZ')):
        code = code[2:]
    
    # 验证剩余部分是否为6位数字
    if not code.isdigit() or len(code) != 6:
        return False, None, '股票代码应为6位数字'
    
    return True, code, ''


@app.route('/api/stock-detail')
def get_stock_detail():
    stock_code = request.args.get('code')
    if not stock_code:
        return jsonify({'error': '缺少股票代码'}), 400
    
    # 验证股票代码
    is_valid, clean_code, error_msg = validate_a_stock_code(stock_code)
    if not is_valid:
        return jsonify({'error': error_msg}), 400
    
    # TODO: 调用实际的股票数据获取功能
    # 这里使用示例数据代替
    stock_data = {
        'code': clean_code,
        'name': f'股票{clean_code}',
        'price': f'{float(clean_code) * 10 + 5:.2f}元',
        'changePercent': '+2.5%',
        'volume': '1,234,567',
        'marketCap': '123.45亿'
    }
    return jsonify(stock_data)


# 添加股市新闻接口
@app.route('/api/stock-news')
def get_stock_news():
    stock_code = request.args.get('code')
    if not stock_code:
        return jsonify([])
    
    # 模拟新闻数据
    news_list = [
        {
            'title': f'{stock_code} 股票最新动态分析',
            'url': f'https://finance.sina.com.cn/stock/s/{stock_code}.html',
            'source': '新浪财经'
        },
        {
            'title': f'{stock_code} 公司公告信息',
            'url': f'https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletin.php?stockid={stock_code}',
            'source': '东方财富网'
        },
        {
            'title': f'{stock_code} 行业研究报告',
            'url': f'https://research.stock.finance.sina.com.cn/stock/s/{stock_code}.html',
            'source': '新浪财经'
        }
    ]
    
    return jsonify(news_list)

@app.route('/api/stock-news-utils')
def get_stock_news_utils():
    stock_code = request.args.get('code')
    if not stock_code:
        return jsonify({'error': '股票代码不能为空'})
    
    try:
        # 导入utils模块
        import sys
        import os
        sys.path.append(os.path.dirname(os.path.abspath(__file__)))
        # 只导入A股相关的函数，注释掉其他市场
        from utils import classify_stock_code, fund_Stock_Info
        # 注释掉其他市场的函数导入
        # from utils import stock_Index_Info, stock_Fund_Info, fund_Fund_Info, hk_Stock_Info, hk_Warrant_Info, us_Stock_Info, cn_Bond_Info
        
        # 根据股票代码分类获取新闻
        stock_type = classify_stock_code(stock_code)
        news_titles = None
        
        # 只处理A股（沪深股市个股）
        if stock_type == '沪深股市(个股)':
            news_titles = fund_Stock_Info(stock_code)
        # 注释掉其他市场的处理
        # elif stock_type == '沪深股市(指数)':
        #     news_titles = stock_Index_Info(stock_code)
        # elif stock_type == '沪深股市(场内基金)':
        #     news_titles = stock_Fund_Info(stock_code)
        # elif stock_type == '基金市场':
        #     news_titles = fund_Fund_Info(stock_code)
        # elif stock_type == '香港股市(正股)':
        #     news_titles = hk_Stock_Info(stock_code)
        # elif stock_type == '香港股市(涡轮)':
        #     news_titles = hk_Warrant_Info(stock_code)
        # elif stock_type == '美国股市':
        #     news_titles = us_Stock_Info(stock_code)
        # elif stock_type == '债券':
        #     news_titles = cn_Bond_Info(stock_code)
        else:
            return jsonify({'error': '不支持的股票类型，目前只支持A股（沪深股市个股）'})
        
        # 转换新闻数据格式并做情感标注
        news_list = []
        if news_titles:
            raw = [{'title': title.text, 'link': title.link} for title in news_titles]
            from model.sentiment_display import enrich_news_list
            use_ml = request.args.get('ml', '0') == '1'
            enriched, summary = enrich_news_list(raw, use_ml=use_ml)
            for row in enriched:
                news_list.append({
                    'title': row['title'],
                    'link': row['link'],
                    'rule_type': row['rule_type'],
                    'rule_label': row['rule_label'],
                    'sentiment': row['sentiment'],
                    'meter': row['meter'],
                })
            return jsonify({
                'news': news_list,
                'stock_type': stock_type,
                'sentiment_summary': summary,
            })

        return jsonify({'news': news_list, 'stock_type': stock_type, 'sentiment_summary': None})
        
    except Exception as e:
        print(f"获取新闻失败: {str(e)}")
        return jsonify({'error': '获取新闻失败'})

@app.route('/search')
def search():
    return render_template('search.html')


@app.route('/stock-browse')
def stock_browse():
    return render_template('stock_browse.html')


@app.route('/api/stock-browse')
def api_stock_browse():
    """股票发现首屏：默认不拉全市场行情，避免长时间转圈。"""
    try:
        with_quotes = request.args.get('quotes', '0') == '1'
        payload = get_browse_payload(with_quotes=with_quotes)
        return jsonify(payload)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/stock-browse-quotes')
def api_stock_browse_quotes():
    """分类示例股行情（轻量，不拉全市场 spot）。"""
    try:
        from model.stock_browse import get_browse_quotes_payload
        return jsonify(get_browse_quotes_payload())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/stock-chart-series')
def api_stock_chart_series():
    """返回 ECharts 用的 OHLC 序列 JSON。"""
    stock_code = request.args.get('code', '600519')
    if not stock_code.isdigit() or len(stock_code) != 6:
        return jsonify({'error': '无效股票代码'}), 400

    data = get_stock_data(stock_code)
    if data is None:
        return jsonify({'error': '数据获取失败'}), 500

    import pandas as pd
    hist = data.get('history')
    if isinstance(hist, list):
        hist = pd.DataFrame(hist)
    if hist is None or hist.empty:
        return jsonify({'error': '无历史数据'}), 500

    series = []
    for _, row in hist.iterrows():
        dt = row['日期']
        if hasattr(dt, 'strftime'):
            dt = dt.strftime('%Y-%m-%d')
        else:
            dt = str(dt)[:10]
        series.append({
            'date': dt,
            'open': float(row.get('开盘', row.get('open', 0)) or 0),
            'high': float(row.get('最高', row.get('high', 0)) or 0),
            'low': float(row.get('最低', row.get('low', 0)) or 0),
            'close': float(row.get('收盘', row.get('close', 0)) or 0),
            'volume': float(row.get('成交量', row.get('volume', 0)) or 0),
        })

    rt = data.get('realtime') or {}
    name = rt.get('名称') or rt.get('name') or stock_code
    return jsonify({
        'code': stock_code,
        'name': name,
        'realtime': rt,
        'series': series,
    })


@app.route('/api/stock-search')
def api_stock_search():
    q = request.args.get('q', '').strip()
    limit = request.args.get('limit', 10, type=int)
    if not q:
        return jsonify({'items': [], 'count': 0})
    if len(q) < 1:
        return jsonify({'items': [], 'count': 0, 'error': '关键词过短'})
    items = search_stocks(q, limit=limit)
    return jsonify({'items': items, 'count': len(items), 'query': q})


@app.route('/api/resolve-stock')
def api_resolve_stock():
    q = request.args.get('q', '').strip()
    code, err = resolve_stock_query(q)
    if err:
        return jsonify({'success': False, 'error': err}), 400
    return jsonify({'success': True, 'code': code})

# 添加股票跳转查询接口

@app.route('/api/stock-data')
def api_stock_data():
    stock_code = request.args.get('code', '600519')  # 获取请求参数中的股票代码，默认为 '600519'

    # 删除旧缓存的图表文件
    charts_dir = "static/charts"
    line_chart_path = os.path.join(charts_dir, f"{stock_code}_line.png")
    candlestick_chart_path = os.path.join(charts_dir, f"{stock_code}_candlestick.png")

    # 如果存在旧图表文件，则删除
    if os.path.exists(line_chart_path):
        os.remove(line_chart_path)
    if os.path.exists(candlestick_chart_path):
        os.remove(candlestick_chart_path)

    # 获取股票数据
    data = get_stock_data(stock_code)
    if data is None:
        return jsonify({"error": "数据获取失败"}), 500

    # 确保 data["history"] 是 list of dict
    import pandas as pd
    if isinstance(data.get("history"), pd.DataFrame):
        data["history"] = data["history"].to_dict(orient="records")
    # 保存本地json数据
    cache_dir = "static/new_cache"
    os.makedirs(cache_dir, exist_ok=True)
    cache_json_path = os.path.join(cache_dir, f"{stock_code}_data.json")
    def clean_nan_values(obj):
        import pandas as pd
        if isinstance(obj, dict):
            return {k: clean_nan_values(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [clean_nan_values(item) for item in obj]
        elif isinstance(obj, float) and (obj != obj):  # NaN
            return None
        elif isinstance(obj, pd.Timestamp):
            return obj.strftime('%Y-%m-%d %H:%M:%S')
        else:
            return obj
    with open(cache_json_path, "w", encoding="utf-8") as f:
        import json
        json.dump(clean_nan_values(data), f, ensure_ascii=False, indent=2)

    # 生成折线图和 K 线图并获取路径
    if isinstance(data["history"], list):
        data["history"] = pd.DataFrame(data["history"])
    line_chart_path = plot_line_chart(data["history"], stock_code)
    candlestick_chart_path = plot_candlestick_chart(data["history"], stock_code)

    # 构建相对路径用于前端访问
    line_path = f"/static/charts/{stock_code}_line.png"
    candle_path = f"/static/charts/{stock_code}_candlestick.png"

    # 构建响应数据
    response_data = {
        "realtime": clean_nan_values(data["realtime"]),
        "chart_paths": {
            "line": line_path,
            "candle": candle_path
        }
    }

    return jsonify(response_data)


@app.route('/stock-chart')
def stock_chart():
    code = request.args.get('code')
    if not code or not code.isdigit() or len(code) != 6:
        return "无效的股票代码", 400

    return render_template('stock_chart.html', stock_code=code)

@app.route('/favorite-stocks')
def favorite_stocks():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    if not user:
        session.clear()
        return redirect(url_for('login'))
    fav_codes = [_normalize_favorite_code(s.stock_code) for s in user.favorite_stocks]
    favorite_quotes = fetch_favorite_quotes(fav_codes, sort_by='change_pct', cache_only=True)
    return render_template(
        'favorite_stocks.html',
        stocks=user.favorite_stocks,
        favorite_quotes=favorite_quotes,
    )

@app.route('/api/add-favorite-stock', methods=['POST'])
def add_favorite_stock():
    if 'user_id' not in session:
        return jsonify({'error': '用户未登录'}), 401
    raw = request.args.get('code')
    if not raw and request.is_json:
        raw = (request.json or {}).get('code')
    if not raw:
        return jsonify({'error': '缺少股票代码或名称'}), 400
    stock_code, err = resolve_stock_query(raw)
    if err:
        return jsonify({'error': err}), 400
    stock_code = _normalize_favorite_code(stock_code)
    exists = _find_favorite(session['user_id'], stock_code)
    if exists:
        from model.news_analysis import get_stock_name
        return jsonify({
            'success': True,
            'duplicate': True,
            'code': stock_code,
            'name': get_stock_name(stock_code),
            'message': '该股票已在自选列表中',
        })
    fav = FavoriteStock(user_id=session['user_id'], stock_code=stock_code)
    db.session.add(fav)
    db.session.commit()
    from model.news_analysis import get_stock_name
    return jsonify({'success': True, 'code': stock_code, 'name': get_stock_name(stock_code)})

@app.route('/api/favorite-stocks')
def get_favorite_stocks():
    if 'user_id' not in session:
        return jsonify([])
    stocks = FavoriteStock.query.filter_by(user_id=session['user_id']).all()
    return jsonify([s.stock_code for s in stocks])


@app.route('/api/favorite-quotes')
def api_favorite_quotes():
    if 'user_id' not in session:
        return jsonify({'error': '用户未登录'}), 401
    sort_by = request.args.get('sort', 'change_pct')
    if sort_by not in ('change_pct', 'code', 'name'):
        sort_by = 'change_pct'
    stocks = FavoriteStock.query.filter_by(user_id=session['user_id']).all()
    codes = []
    for s in stocks:
        code = _normalize_favorite_code(s.stock_code)
        if is_valid_a_share_code(code) and code not in codes:
            codes.append(code)
    quotes = fetch_favorite_quotes(codes, sort_by=sort_by)
    return jsonify({
        'items': quotes,
        'count': len(quotes),
        'sort': sort_by,
        'updated_hint': '行情约每 2 分钟刷新',
        'cached_count': sum(1 for q in quotes if q.get('status') == 'cached'),
    })


@app.route('/api/market-ticker')
def api_market_ticker():
    """工作台热股：只读每日快照；refresh=1 时手动触发更新。"""
    try:
        limit = request.args.get('limit', 12, type=int)
        force = request.args.get('refresh', '0') == '1'
        from model.market_ticker import market_ticker_payload
        return jsonify(market_ticker_payload(limit=limit, force=force))
    except Exception as e:
        print(f'热股读取失败: {e}')
        from model.market_ticker import get_daily_ticker_for_page
        t = get_daily_ticker_for_page(12)
        return jsonify({'items': t['stocks'], 'updated_hint': t['meta']})


@app.route('/api/remove-favorite-stock', methods=['POST'])
def remove_favorite_stock():
    if 'user_id' not in session:
        return jsonify({'error': '用户未登录'}), 401
    raw = request.args.get('code')
    stock_code, err = resolve_stock_query(raw) if raw else (None, '缺少股票代码')
    if err:
        return jsonify({'error': err}), 400
    stock_code = _normalize_favorite_code(stock_code)
    fav = _find_favorite(session['user_id'], stock_code)
    if not fav:
        return jsonify({'error': '未收藏'}), 400
    db.session.delete(fav)
    db.session.commit()
    return jsonify({'success': True})

def _resolve_wordcloud_font():
    """查找可用于中文词云的字体（项目内或系统字体）。"""
    candidates = [
        ROOT_DIR / 'static' / 'fonts' / 'msyh.ttc',
        ROOT_DIR / 'static' / 'fonts' / 'simhei.ttf',
        Path(r'C:\Windows\Fonts\msyh.ttc'),
        Path(r'C:\Windows\Fonts\msyhbd.ttc'),
        Path(r'C:\Windows\Fonts\simhei.ttf'),
        Path(r'C:\Windows\Fonts\simsun.ttc'),
        Path('/usr/share/fonts/truetype/wqy/wqy-microhei.ttc'),
        Path('/System/Library/Fonts/PingFang.ttc'),
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None


def fetch_news_content(url):
    """抓取新闻正文，复用 news 模块的多策略解析。"""
    from news import get_news_article_dict

    article = get_news_article_dict(url)
    paragraphs = article.get('paragraphs') or []
    text = '\n'.join(p.strip() for p in paragraphs if p and p.strip())
    return text


def _wordcloud_back_link(from_page='', stock_code=''):
    """词云页返回链接：新标签打开时 history.back() 无效，需显式回链。"""
    if from_page == 'stock-news' and stock_code:
        return url_for('stock_news') + f'?code={stock_code}', '返回公告情感'
    if from_page == 'hot-news':
        return url_for('hot_news_hub'), '返回热点资讯'
    if from_page == 'dashboard':
        return url_for('dashboard') + '#market-hot-news', '返回工作台'
    return url_for('sentiment_analysis'), '返回情感分析'


@app.route('/news-wordcloud')
def news_wordcloud():
    url = request.args.get("url")
    title = request.args.get("title", "新闻词云")
    if not url:
        return "缺少必要参数", 400
    from_page = request.args.get("from", "")
    stock_code = (request.args.get("code") or "").strip()
    back_url, back_label = _wordcloud_back_link(from_page, stock_code)
    return render_template(
        "news_wordcloud.html",
        title=title,
        article_url=url,
        back_url=back_url,
        back_label=back_label,
        stock_code=stock_code,
    )

@app.route('/news-wordcloud-image')
def news_wordcloud_image():
    url = request.args.get("url")
    print("[调试] 收到图片请求，url参数：", url)
    if not url:
        print("[调试] 缺少url参数，返回400")
        return "No url", 400
    text = fetch_news_content(url)
    print("[调试] 正文长度：", len(text))
    print("[调试] 正文前100字：", text[:100])
    if not text or len(text) < 10:
        print("[调试] 新闻正文提取失败，返回500")
        return "新闻正文提取失败，请稍后重试或换一条资讯", 500
    font_path = _resolve_wordcloud_font()
    if not font_path:
        print("[调试] 未找到中文字体")
        return "未找到中文字体，无法生成词云", 500
    try:
        from model.wordcloud_utils import build_word_frequencies

        word_freqs = build_word_frequencies(text, top_k=90)
        if not word_freqs:
            print("[调试] 分词后无有效关键词")
            return "正文关键词提取失败，请换一条资讯重试", 500

        teal_palette = ['#00B5AD', '#0D9488', '#14B8A6', '#2DD4BF', '#134E4A', '#5EEAD4', '#0F766E']

        def _teal_color(word, font_size, position, orientation, random_state=None, **kwargs):
            return random_state.choice(teal_palette)

        wc = WordCloud(
            font_path=font_path,
            width=920,
            height=480,
            background_color='#F0FAF9',
            max_words=90,
            color_func=_teal_color,
        ).generate_from_frequencies(word_freqs)
        img_io = io.BytesIO()
        wc.to_image().save(img_io, format='PNG')
        img_io.seek(0)
        print("[调试] 词云图片生成成功，返回图片")
        return send_file(img_io, mimetype='image/png')
    except Exception as e:
        print("[调试] 词云生成失败：", e)
        return "词云生成失败", 500

# 回报率页面路由
@app.route('/return-rate')
def return_rate_page():
    code = request.args.get('code')
    if not code or not code.isdigit() or len(code) != 6:
        return "无效的股票代码", 400

    return render_template('return_rate.html', stock_code=code)

# 获取决策点路由
@app.route('/api/decision-points')
def api_decision_points():
    stock_code = request.args.get('code', '600519')
    data = fetch_stock_data(stock_code)
    if data is None:
        return jsonify({"error": "数据获取失败"}), 500
    history_data = data["history"]
    decision_points = history_data['日期'].dt.strftime('%Y-%m-%d').tolist()
    return jsonify(decision_points)

# 获取回报率图表路由
@app.route('/api/return-rate-series')
def api_return_rate_series():
    stock_code = request.args.get('code', '600519')
    decision_point = request.args.get('decision_point')
    if not decision_point:
        return jsonify({'error': '缺少决策点日期'}), 400
    from stock_data import compute_return_rate_series
    payload = compute_return_rate_series(stock_code, decision_point)
    if payload is None:
        return jsonify({'error': '数据不足，无法计算回报率'}), 500
    return jsonify(payload)


@app.route('/api/return-rate-chart')
def api_return_rate_chart():
    stock_code = request.args.get('code', '600519')
    decision_point = request.args.get('decision_point')
    chart_path = calculate_return_rate_chart(stock_code, decision_point)
    if chart_path is None:
        return jsonify({"error": "图表生成失败"}), 500
    # 直接返回图片文件
    return send_file(chart_path, mimetype='image/png')

# 跳转到回报率页面
@app.route('/transition-return-rate')
def transition_return_rate():
    return render_template('transition_return_rate.html')

# 跳转到AI股票助手页面
@app.route('/ai-stock-assistant')
def ai_stock_assistant():
    return render_template('ai_stock_assistant.html')


@app.route('/api/ai-chat', methods=['POST'])
def api_ai_chat():
    """AI 助手对话接口：RAG 知识库 + 实时数据 + 大模型。"""
    data = request.get_json(silent=True) or {}
    message = (data.get('message') or '').strip()
    history = data.get('history') or []
    stream = bool(data.get('stream'))

    if not message:
        return jsonify({'success': False, 'error': '消息不能为空'}), 400
    if len(message) > 2000:
        return jsonify({'success': False, 'error': '消息过长，请控制在 2000 字以内'}), 400

    try:
        from model.ai_assistant import chat, chat_stream

        if stream:
            def generate():
                for evt in chat_stream(message, history=history):
                    yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"

            return Response(
                generate(),
                mimetype='text/event-stream',
                headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
            )

        result = chat(message, history=history)
        return jsonify({
            'success': True,
            'answer': result['answer'],
            'sources': result.get('sources', []),
            'has_live_data': result.get('has_live_data', False),
            'has_knowledge': result.get('has_knowledge', False),
            'used_llm': result.get('used_llm', False),
            'model': result.get('model', ''),
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'AI 服务异常: {e}'}), 500

# 跳转到股票预测页面
@app.route('/stock-prediction')
def stock_prediction():
    return render_template('stock_prediction.html')

# 股票预测API接口
@app.route('/api/stock-prediction')
def api_stock_prediction():
    print("进入预测接口")  # 新增调试
    stock_code = request.args.get('code')
    print(f"预测股票代码: {stock_code}")  # 调试输出
    if not stock_code:
        return jsonify({"error": "缺少股票代码"}), 400
    try:
        from model.predict import predict_stock_movement
        prediction_result = predict_stock_movement(stock_code)
        print(f"预测结果: {prediction_result}")  # 调试输出
        if prediction_result:
            print(f"最终预测结果: {prediction_result}")
            import numpy as np
            def to_builtin_type(obj):
                if isinstance(obj, dict):
                    return {k: to_builtin_type(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [to_builtin_type(item) for item in obj]
                elif isinstance(obj, np.ndarray):
                    return obj.tolist()
                elif isinstance(obj, np.generic):
                    return obj.item()
                else:
                    return obj
            prediction_result = to_builtin_type(prediction_result)
            return jsonify({
                "success": True,
                "stock_code": stock_code,
                "prediction": prediction_result
            })
        else:
            model_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'models')
            required = ['sentiment_model.pkl', 'vectorizer.joblib', 'price_model.pkl']
            missing = [f for f in required if not os.path.exists(os.path.join(model_dir, f))]
            if missing:
                err = '预测模型文件缺失（' + '、'.join(missing) + '），请先运行 model/train.py 训练模型'
            else:
                err = '无法获取预测数据，可能是模型版本不兼容或新闻预测失败，请重启服务后重试，或运行 python model/train_quick.py 重新训练模型'
            return jsonify({
                "success": False,
                "error": err
            }), 500
    except Exception as e:
        print(f"预测失败: {e}")
        traceback.print_exc()
        msg = str(e)
        if 'incompatible dtype' in msg:
            msg = '模型与当前 scikit-learn 版本不兼容，请在当前环境重新运行 model/train.py 训练模型'
        return jsonify({
            "success": False,
            "error": f"预测失败: {msg}"
        }), 500

@app.route('/api/hot-news')
def hot_news():
    limit = request.args.get('limit', type=int)
    force = request.args.get('refresh') == '1'
    items, updated_at, source = get_hot_news(force_refresh=force)
    if limit and limit > 0:
        items = items[:limit]
    return jsonify({
        'items': items,
        'updated_at': updated_at,
        'source': source,
        'count': len(items),
        'cache_minutes': 30,
    })


@app.route('/hot-news')
def hot_news_hub():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('hot_news_hub.html')


@app.route('/news-article')
def news_article():
    link = request.args.get('link')
    title_hint = request.args.get('title', '')
    if link:
        return render_template('news_article.html', link=link, title_hint=title_hint)
    return "Missing news link", 400


@app.route('/api/news-article')
def get_news_article():
    link = request.args.get('link')
    title_hint = request.args.get('title', '')
    if not link:
        return jsonify({'error': '新闻链接不能为空'})

    try:
        article = get_news_article_dict(link, title_hint=title_hint)
        if not article.get('paragraphs'):
            return jsonify({'error': '暂无正文内容，请稍后重试或返回列表选择其他资讯'})
        # 附带相关热点（排除当前篇）
        related_items, updated_at, _ = get_hot_news()
        related = [i for i in related_items if i.get('link') != link][:6]
        article['related'] = related
        article['hot_news_updated_at'] = updated_at
        return jsonify(article)
    except Exception as e:
        print(f"获取新闻正文失败: {str(e)}")
        return jsonify({'error': '获取新闻正文失败'})

# 生成预测图表API接口
@app.route('/api/prediction-chart', methods=['GET', 'POST'])
def api_prediction_chart():
    stock_code = request.args.get('code')
    if not stock_code:
        return jsonify({"error": "缺少股票代码"}), 400
    import os, json
    # from flask import Response, request  # 删除request，只保留Response
    from flask import Response
    # 1. 先调用一次/api/stock-data，确保折线图和数据缓存都已生成
    with app.test_request_context(f'/api/stock-data?code={stock_code}'):
        resp = api_stock_data()
        if isinstance(resp, Response):
            if resp.status_code != 200:
                return jsonify({"error": "股票信息获取失败"}), 500
        elif isinstance(resp, tuple):
            if len(resp) > 1 and resp[1] != 200:
                return jsonify({"error": "股票信息获取失败"}), 500
    # 2. 读取历史数据
    line_chart_path = os.path.join('static/charts', f'{stock_code}_line.png')
    cache_json_path = os.path.join('static/new_cache', f'{stock_code}_data.json')
    try:
        if os.path.exists(line_chart_path) and os.path.exists(cache_json_path):
            with open(cache_json_path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            import pandas as pd
            hist_data = cache_data['history']
            hist_df = pd.DataFrame(hist_data)
            hist_df['日期'] = pd.to_datetime(hist_df['日期'])
            # 优先使用POST body中的prediction
            if request.method == 'POST' and request.is_json and 'prediction' in request.json:
                prediction_result = request.json['prediction']
            else:
                from model.predict import predict_stock_movement
                prediction_result = predict_stock_movement(stock_code)
            chart_path = generate_prediction_chart(hist_df, stock_code, prediction_result)
            if chart_path:
                return send_file(chart_path, mimetype='image/png')
            else:
                return jsonify({"error": "图表生成失败"}), 500
        else:
            return jsonify({"error": "本地资源生成失败"}), 500
    except Exception as e:
        print(f"预测图表生成失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"预测图表生成失败: {str(e)}"}), 500

def generate_prediction_chart(hist_data, stock_code, prediction_result):
    """
    生成包含预测线的图表，风格与历史折线图完全一致
    """
    try:
        import numpy as np
        from datetime import timedelta
        import os
        import pandas as pd
        from test import plot_stock_line_chart
        # 过滤无效历史数据
        if isinstance(hist_data, pd.DataFrame):
            hist_data = hist_data.dropna(subset=['日期', '收盘'])
        # 预测线相关变量
        last_price = hist_data['收盘'].iloc[-1]
        last_date = pd.to_datetime(hist_data['日期'].iloc[-1])  # 保证类型
        future_dates = []
        current_date = last_date
        for i in range(1, 4):
            current_date += timedelta(days=1)
            while current_date.weekday() >= 5:
                current_date += timedelta(days=1)
            future_dates.append(pd.to_datetime(current_date))  # 保证类型
        # 直接用后三天的预测变化值
        price_changes = prediction_result.get('price_changes', [0, 0, 0])
        if isinstance(price_changes, np.ndarray):
            price_changes = price_changes.tolist()
        if not isinstance(price_changes, list) or len(price_changes) != 3:
            price_changes = [0, 0, 0]
        future_prices = [last_price * (1 + float(price_changes[i]) / 100.0) for i in range(3)]
        # 画图x轴和y轴
        x_pred = [last_date] + future_dates
        y_pred = [last_price] + future_prices
        # 路径
        chart_path = os.path.join('static/charts', f'{stock_code}_prediction.png')
        # 标题
        title = f'{stock_code} {prediction_result.get("stock_name", "")} 价格预测'.strip()
        # 调用统一画图函数
        plot_stock_line_chart(hist_data, chart_path, stock_code, title, x_pred, y_pred)
        return chart_path
    except Exception as e:
        print(f"生成预测图表失败: {e}")
        return None

@app.route('/prediction-chart')
def prediction_chart():
    code = request.args.get('code')
    if not code or not code.isdigit() or len(code) != 6:
        return "无效的股票代码", 400
    return render_template('prediction_chart.html', stock_code=code)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        _migrate_user_guide_column()
    app.run(debug=True)