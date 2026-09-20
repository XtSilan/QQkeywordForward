"""Replay tests for the order-fingerprint dedup service.

Cases are taken from real production logs (see the planning doc):
宁波翔起 spacing/phone variants, 环港物流 self-duplicated bodies,
港泽小高 multi-order messages across groups, recruitment ads, etc.

Runs under pytest or directly: ``python tests/test_order_dedup.py``.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import orders  # noqa: E402

LEXICON = [
    "宜兴", "安吉", "江西", "德清", "长兴", "常州", "新北", "宣城",
    "玉山", "南京", "太仓", "如皋", "江阴", "长兴",
]

NOW = datetime(2026, 9, 20, 9, 0).timestamp()


def make_conn() -> sqlite3.Connection:
    """In-memory DB migrated with the real 006 script (doubles as a
    migration smoke test)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE notification_jobs(
          id INTEGER PRIMARY KEY, hit_id INTEGER, destination_id INTEGER);
        CREATE TABLE keyword_message_cooldowns(message_fingerprint TEXT PRIMARY KEY);
        CREATE TABLE sender_message_cooldowns(sender_id TEXT PRIMARY KEY);
        CREATE TABLE app_meta(key TEXT PRIMARY KEY, value TEXT);
        """
    )
    migration = (
        Path(__file__).resolve().parent.parent
        / "migrations" / "006_order_dedup.sql"
    ).read_text(encoding="utf-8")
    conn.executescript(migration)
    return conn


def handle(conn, settings, text, now=NOW, destinations=(1,), mark=True):
    """Simulate the nonebot handler decision flow. Returns (pushed, fps)."""
    candidates = orders.parse(text, LEXICON, now, settings)
    push_fps = set()
    for cand in candidates:
        fp, action = orders.decide(conn, cand, now, settings)
        if action == "push":
            push_fps.add(fp)
    pushed = bool(push_fps) and bool(destinations)
    if pushed and mark:
        for fp in push_fps:
            orders.mark_sent(conn, fp, now)
    return pushed, push_fps


def test_xiangqi_spacing_and_phone_variants_push_once():
    conn = make_conn()
    settings = orders.load_settings(conn)
    variants = [
        "现在 宜兴万石镇 对柜38T 地中海提 进四期 高价现在能提的联系18253071958",
        "现在 宜兴万石镇 对柜38T 地中海提 进四期18253071958",
        "现在宜兴 对柜38T 地中海提 进四期182530719585",  # 12位错号
        "今天，现在宜兴 对柜38T 地中海提 进四期18253071958",
        "现在 宜兴 万石镇 对柜 38T 地中海提 进四期 18253071958",
    ]
    results = [handle(conn, settings, text)[0] for text in variants]
    assert results == [True, False, False, False, False], results


def test_huangang_self_duplicated_body_pushes_once():
    conn = make_conn()
    settings = orders.load_settings(conn)
    body = (
        "明天小柜 安吉*2 放后 15T/19T 建德钦堂*2 放后 21T "
        "奉化萧王庙 15T 进出随便 13095966035"
    )
    doubled = f"{body} {body}"
    assert handle(conn, settings, doubled)[0] is True
    assert handle(conn, settings, doubled)[0] is False
    # 单独重发其中一段也认得出是同单（安吉那段拆不出来时是整单指纹）
    assert handle(conn, settings, body)[0] is False


def test_gangze_multi_order_message_dedups_per_order():
    conn = make_conn()
    settings = orders.load_settings(conn)
    text = (
        "明天 德清 新市 小柜 13t 随意 "
        "明天 东阳千祥 高柜 大榭提进舟山 支持带货13586529848 "
        "明天 长兴林城高柜 大榭提进舟山 支持带货13586529848"
    )
    candidates = orders.parse(text, LEXICON, NOW, settings)
    dests = sorted(c.dest for c in candidates)
    assert dests == ["德清", "长兴"], dests  # 东阳千祥无关键词被跳过

    pushed, fps = handle(conn, settings, text)
    assert pushed and len(fps) == 2  # 德清单、长兴单是两笔独立订单
    # 同一消息转到另一个群: 两单都已送达 -> 不再推
    pushed_again, _ = handle(conn, settings, text)
    assert pushed_again is False


def test_recruitment_ad_with_keyword_is_dropped():
    conn = make_conn()
    settings = orders.load_settings(conn)
    ad = (
        "🔥🔥全国300家工厂 🔥🔥江浙沪、安徽、河南、广东、山东、天津、北京、"
        "湖南、湖北、江西、河北、全国各大厂区高工价招人！ 岗位：小时工、日结工、"
        "焊工、叉车、电工、大龄工、寒暑假学生工 时薪18-35元/时、日薪200-450元/天 "
        "咨询热线 18337213157 13193529186"
    )
    assert orders.parse(ad, LEXICON, NOW, settings) == []
    assert handle(conn, settings, ad)[0] is False


def test_new_phone_allows_one_supplementary_push():
    conn = make_conn()
    settings = orders.load_settings(conn)
    assert handle(conn, settings, "明天宜兴 对柜 38T 联系15618167185")[0] is True
    # 同单换新电话 -> 补推一次
    assert handle(conn, settings, "明天宜兴 对柜 38T 联系13900001111")[0] is True
    # 第三次又换电话 -> 已达每单上限, 不再推
    assert handle(conn, settings, "明天宜兴 对柜 38T 联系13800001111")[0] is False


def test_undelivered_order_repush_on_repost():
    conn = make_conn()
    settings = orders.load_settings(conn)
    text = "明天安吉 大柜 19T 长胜物流提进二期 现金 13095966035"
    # 没有可用目的地 -> 不标记送达
    assert handle(conn, settings, text, destinations=())[0] is False
    # 顶单: 仍未送达, 允许重入队
    pushed, fps = handle(conn, settings, text, mark=False)
    assert pushed is True
    pushed, _ = handle(conn, settings, text, mark=False)
    assert pushed is True
    # 送达后顶单 -> 抑制
    for fp in fps:
        orders.mark_sent(conn, fp, NOW)
    assert handle(conn, settings, text)[0] is False


def test_window_expiry_treats_order_as_new():
    conn = make_conn()
    settings = orders.load_settings(conn)
    text = "明天安吉 大柜 19T 长胜物流提进二期 现金 13095966035"
    assert handle(conn, settings, text)[0] is True
    later = NOW + settings.window_seconds + 1
    assert handle(conn, settings, text, now=later)[0] is True


def main() -> int:
    tests = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {name}: {exc}")
        else:
            print(f"PASS {name}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
