"""网络请求：绕过失效的系统代理，避免 akshare 访问东方财富失败。"""
import os
from contextlib import contextmanager

_PROXY_KEYS = (
    'HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy',
    'ALL_PROXY', 'all_proxy',
)


@contextmanager
def direct_connection():
    """临时清除代理环境变量，直连行情源。"""
    saved = {}
    for k in _PROXY_KEYS:
        if k in os.environ:
            saved[k] = os.environ.pop(k)
    prev_no = os.environ.get('NO_PROXY')
    os.environ['NO_PROXY'] = '*'
    os.environ['no_proxy'] = '*'
    try:
        yield
    finally:
        if prev_no is None:
            os.environ.pop('NO_PROXY', None)
            os.environ.pop('no_proxy', None)
        else:
            os.environ['NO_PROXY'] = prev_no
            os.environ['no_proxy'] = prev_no
        for k, v in saved.items():
            os.environ[k] = v
