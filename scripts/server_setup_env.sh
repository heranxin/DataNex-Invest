#!/usr/bin/env bash
# 数境智投 - Ubuntu 服务器基础环境配置
set -eu

APP_DIR="${APP_DIR:-/home/ubuntu/stock-sentiment-app}"
PY="${PY:-python3}"

echo "==> 更新系统包..."
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -y
sudo apt-get upgrade -y

echo "==> 安装系统依赖..."
sudo apt-get install -y \
  python3 python3-venv python3-pip python3-dev \
  build-essential git curl wget unzip \
  sqlite3 \
  fonts-noto-cjk fonts-wqy-microhei fonts-wqy-zenhei \
  libfreetype6-dev libpng-dev pkg-config \
  chromium-browser || sudo apt-get install -y chromium

echo "==> 创建项目目录: ${APP_DIR}"
mkdir -p "${APP_DIR}"
cd "${APP_DIR}"

if [ ! -d venv ]; then
  echo "==> 创建 Python 虚拟环境..."
  ${PY} -m venv venv
fi

source venv/bin/activate
python -m pip install --upgrade pip setuptools wheel

echo "==> 安装 PyTorch (CPU)..."
pip install torch --index-url https://download.pytorch.org/whl/cpu

if [ -f requirements.txt ]; then
  echo "==> 安装 Python 依赖 (requirements.txt)..."
  pip install -r requirements.txt
else
  echo "WARN: requirements.txt 不存在，跳过 pip 安装"
fi

echo "==> 验证关键包..."
python - <<'PY'
import importlib
mods = [
    'flask', 'flask_sqlalchemy', 'pandas', 'numpy', 'akshare',
    'sklearn', 'torch', 'transformers', 'jieba', 'wordcloud',
    'DrissionPage', 'bs4', 'mplfinance', 'joblib',
]
failed = []
for m in mods:
    try:
        importlib.import_module(m)
        print('OK', m)
    except Exception as e:
        failed.append((m, str(e)))
        print('FAIL', m, e)
if failed:
    raise SystemExit('部分依赖未安装成功: ' + str(failed))
print('ALL_DEPENDENCIES_OK')
PY

mkdir -p instance static/new_cache static/cache static/charts logs

cat > "${APP_DIR}/env.example" <<'EOF'
# 复制为 .env 后填写
FLASK_ENV=production
SECRET_KEY=change-me-to-random-string
SILICONFLOW_API_KEY=
HTTP_PROXY=
HTTPS_PROXY=
NO_PROXY=127.0.0.1,localhost
EOF

echo "==> 环境配置完成"
echo "项目目录: ${APP_DIR}"
echo "激活虚拟环境: source ${APP_DIR}/venv/bin/activate"
echo "下一步: 上传代码到 ${APP_DIR}，复制 env.example 为 .env 并启动应用"
