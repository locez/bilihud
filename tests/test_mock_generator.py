# -*- coding: utf-8 -*-
from bilihud.mock_generator import MockMessageGenerator


def test_mock_message_generator():
    danmaku = MockMessageGenerator.create_mock_danmaku(user="小明", msg="测试单条弹幕")
    assert danmaku.uname == "小明"
    assert danmaku.msg == "测试单条弹幕"

    gift = MockMessageGenerator.create_mock_gift(user="小红", gift_name="辣条", num=10)
    assert gift.uname == "小红"
    assert gift.gift_name == "辣条"
    assert gift.num == 10

    interact = MockMessageGenerator.create_mock_interact(user="老王", msg_type=1)
    assert interact.username == "老王"
    assert interact.msg_type == 1
