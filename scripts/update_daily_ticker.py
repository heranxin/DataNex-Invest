#!/usr/bin/env python
"""手动更新工作台「每日热股」快照。建议每个交易日收盘后或开盘前执行一次。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from model.market_ticker import refresh_daily_ticker


def main():
    payload = refresh_daily_ticker(12)
    print(f"已更新 {payload.get('trade_date')} · {payload.get('count', len(payload.get('items', [])))} 只")
    for q in payload.get('items', []):
        print(f"  {q.get('name')} {q.get('code')} {q.get('price')} {q.get('change_display')}")


if __name__ == '__main__':
    main()
