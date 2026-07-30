# -*- coding: utf-8 -*-
from __future__ import annotations

import random
from typing import Any

import blivedm.models.web as web_models


class MockMessageGenerator:
    """开播前测试与预览用的模拟消息生成器。"""

    MOCK_USERS = [
        "极客小明",
        "狂热粉小红",
        "舰长-老王",
        "提督-阿杰",
        "游戏高手路人甲",
        "B站吃瓜群众",
    ]

    MOCK_DANMAKU_TEXTS = [
        "主播今天玩什么游戏呀？",
        "这关卡很久了，求教过关秘籍！",
        "666666 太强了！",
        "主播画面质量很好，声音也清脆 [点赞]",
        "主播好久不见，今晚玩到几点？",
        "这个键盘手感看着不错 [吃瓜]",
    ]

    MOCK_GIFTS = [
        ("辣条", "送出", 66, 100),
        ("小心心", "投递", 520, 10),
        ("吃瓜", "赠送", 1, 1000),
        ("牛哇", "投递", 6, 2000),
        ("舰长", "开通", 1, 198000),
    ]

    @classmethod
    def create_mock_danmaku(
        self,
        user: str | None = None,
        msg: str | None = None,
        is_guard: bool = False,
        is_admin: bool = False,
    ) -> Any:
        """生成模拟弹幕对象。"""
        uname = user or random.choice(self.MOCK_USERS)
        content = msg or random.choice(self.MOCK_DANMAKU_TEXTS)

        class MockDanmaku:
            def __init__(self, name: str, text: str, guard: bool, admin: bool):
                self.uname = name
                self.msg = text
                self.privilege_type = 3 if guard else 0
                self.vip = False
                self.svip = guard
                self.admin = admin
                self.is_system_error = False
                self.is_system_info = False
                self.emoticon_options_dict = {}

        return MockDanmaku(uname, content, is_guard, is_admin)

    @classmethod
    def create_mock_gift(
        self,
        user: str | None = None,
        gift_name: str | None = None,
        num: int | None = None,
    ) -> web_models.GiftMessage:
        """生成模拟礼物消息对象。"""
        uname = user or random.choice(self.MOCK_USERS)
        gift_info = random.choice(self.MOCK_GIFTS)

        g_name = gift_name or gift_info[0]
        action = gift_info[1]
        g_num = num or gift_info[2]
        price = gift_info[3]

        return web_models.GiftMessage(
            uname=uname,
            face="",
            gift_name=g_name,
            gift_id=1,
            num=g_num,
            price=price,
            action=action,
            coin_type="gold" if price >= 1000 else "silver",
            timestamp=0,
        )

    @classmethod
    def create_mock_interact(
        self,
        user: str | None = None,
        msg_type: int = 1,
    ) -> web_models.InteractWordV2Message:
        """生成模拟互动/进房消息对象。"""
        uname = user or random.choice(self.MOCK_USERS)
        return web_models.InteractWordV2Message(
            username=uname,
            msg_type=msg_type,
            timestamp=0,
        )
