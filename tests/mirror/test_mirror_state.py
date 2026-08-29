import pytest

from bilihud.danmaku.messages import (
    DanmakuMessage,
    GiftCurrency,
    GiftEffectFrame,
    GiftEffectLayout,
    GiftMessage,
    ImageSegment,
    InteractionKind,
    InteractMessage,
    MessageAuthor,
    MessageBadge,
    MessageBadgeKind,
    ReplySegment,
    SuperChatMessage,
    SystemMessageLevel,
    TextSegment,
    make_system_message,
)
from bilihud.mirror.state import MirrorDisplaySettings, MirrorState, message_to_mirror_entry, mirror_settings_payload


def _author(name="Locez", color="#66CCFF", badges=()):
    return MessageAuthor(uid=1, name=name, color=color, badges=badges)


def test_mirror_settings_payload_includes_the_shared_hud_font() -> None:
    assert mirror_settings_payload(
        MirrorDisplaySettings(
            gift_effects_enabled=True,
            font_family="Noto Sans CJK SC",
            danmaku_x=12,
            danmaku_y=34,
        )
    ) == {
        "giftEffects": True,
        "fontFamily": "Noto Sans CJK SC",
        "danmakuX": 12,
        "danmakuY": 34,
    }


def test_message_to_mirror_entry_converts_text_danmaku():
    message = DanmakuMessage(author=_author(), segments=(TextSegment("<hello>"),))

    entry = message_to_mirror_entry(1, message)

    assert entry == {
        "seq": 1,
        "kind": "danmaku",
        "user": "Locez",
        "userColor": "#66CCFF",
        "segments": [{"type": "text", "text": "<hello>"}],
    }


def test_message_to_mirror_entry_converts_pure_emoticon_danmaku():
    message = DanmakuMessage(
        author=_author(),
        segments=(ImageSegment("[妙啊]", "https://i0.hdslb.com/bfs/live/emote.png", 183, 60),),
    )

    entry = message_to_mirror_entry(2, message)

    assert entry["segments"] == [
        {
            "type": "image",
            "text": "[妙啊]",
            "url": "https://i0.hdslb.com/bfs/live/emote.png",
            "width": 104,
            "height": 34,
        }
    ]


def test_message_to_mirror_entry_converts_inline_emoticons():
    message = DanmakuMessage(
        author=_author(),
        segments=(
            ImageSegment("[汤圆]", "https://i0.hdslb.com/bfs/live/tangyuan.png", 60, 60),
            TextSegment(" ok "),
            ImageSegment("[汤圆]", "https://i0.hdslb.com/bfs/live/tangyuan.png", 60, 60),
        ),
    )

    entry = message_to_mirror_entry(3, message)

    assert entry["segments"] == [
        {
            "type": "image",
            "text": "[汤圆]",
            "url": "https://i0.hdslb.com/bfs/live/tangyuan.png",
            "width": 34,
            "height": 34,
        },
        {"type": "text", "text": " ok "},
        {
            "type": "image",
            "text": "[汤圆]",
            "url": "https://i0.hdslb.com/bfs/live/tangyuan.png",
            "width": 34,
            "height": 34,
        },
    ]


def test_message_to_mirror_entry_preserves_reply_target_prefix():
    message = DanmakuMessage(
        author=_author(),
        segments=(ReplySegment("@绚下的小恐龙 "), TextSegment("test")),
    )

    entry = message_to_mirror_entry(4, message)

    assert entry["segments"] == [
        {"type": "reply", "text": "@绚下的小恐龙 "},
        {"type": "text", "text": "test"},
    ]


def test_message_to_mirror_entry_includes_compact_author_badges():
    badges = (
        MessageBadge(MessageBadgeKind.MEDAL, "小狐 26", "粉丝牌", "#FF79C6"),
        MessageBadge(MessageBadgeKind.WEALTH, "✦ 8", "财富等级", "#C9B6FF"),
        MessageBadge(MessageBadgeKind.PRIVILEGE, "⚓︎", "大航海", "#86C8FF"),
    )
    message = DanmakuMessage(author=_author(badges=badges), segments=(TextSegment("测试"),))

    entry = message_to_mirror_entry(4, message)

    assert entry["badges"] == [
        {
            "type": "medal",
            "text": "小狐 26",
            "title": "粉丝牌",
            "color": "#FF79C6",
        },
        {
            "type": "wealth",
            "text": "✦ 8",
            "title": "财富等级",
            "color": "#C9B6FF",
        },
        {
            "type": "privilege",
            "text": "⚓︎",
            "title": "大航海",
            "color": "#86C8FF",
        },
    ]


def test_message_to_mirror_entry_maps_guard_levels_to_blue_purple_gold_badges():
    governor = message_to_mirror_entry(
        1,
        DanmakuMessage(
            author=_author(badges=(MessageBadge(MessageBadgeKind.PRIVILEGE, "🛳︎", "大航海", "#FFD700"),)),
            segments=(TextSegment("1"),),
        ),
    )
    admiral = message_to_mirror_entry(
        2,
        DanmakuMessage(
            author=_author(badges=(MessageBadge(MessageBadgeKind.PRIVILEGE, "⛴︎", "大航海", "#C9B6FF"),)),
            segments=(TextSegment("2"),),
        ),
    )
    captain = message_to_mirror_entry(
        3,
        DanmakuMessage(
            author=_author(badges=(MessageBadge(MessageBadgeKind.PRIVILEGE, "⚓︎", "大航海", "#86C8FF"),)),
            segments=(TextSegment("3"),),
        ),
    )

    assert governor["badges"] == [{"type": "privilege", "text": "🛳︎", "title": "大航海", "color": "#FFD700"}]
    assert admiral["badges"] == [{"type": "privilege", "text": "⛴︎", "title": "大航海", "color": "#C9B6FF"}]
    assert captain["badges"] == [{"type": "privilege", "text": "⚓︎", "title": "大航海", "color": "#86C8FF"}]


def test_message_to_mirror_entry_converts_gift_message():
    message = GiftMessage(
        author=_author(color="#FFD700"),
        segments=(TextSegment("赠送 辣条 x3"),),
        action="赠送",
        gift_name="辣条",
        quantity=3,
    )

    entry = message_to_mirror_entry(4, message)

    assert entry == {
        "seq": 4,
        "kind": "gift",
        "user": "Locez",
        "userColor": "#FFD700",
        "segments": [{"type": "text", "text": "赠送 辣条 x3"}],
        "giftId": 0,
        "giftAction": "赠送",
        "giftValue": "",
        "giftName": "辣条",
        "giftQuantity": 3,
        "giftImageUrl": "",
        "giftEffectUrl": "",
        "giftAnimationUrl": "",
    }


def test_message_to_mirror_entry_preserves_packed_gift_effect_layout():
    message = GiftMessage(
        author=_author(color="#FFD700"),
        segments=(TextSegment("送出 浪漫城堡 x1"),),
        action="送出",
        gift_name="浪漫城堡",
        quantity=1,
        gift_effect_url="https://i0.hdslb.com/bfs/live/castle.mp4",
        gift_effect_layout=GiftEffectLayout(
            rgb_frame=GiftEffectFrame(0, 0, 720, 1280),
            alpha_frame=GiftEffectFrame(724, 0, 360, 640),
        ),
    )

    entry = message_to_mirror_entry(5, message)

    assert entry["giftEffectLayout"] == {
        "rgbFrame": {"x": 0, "y": 0, "width": 720, "height": 1280},
        "alphaFrame": {"x": 724, "y": 0, "width": 360, "height": 640},
    }


def test_message_to_mirror_entry_preserves_gift_animation_url():
    message = GiftMessage(
        author=_author(color="#FFD700"),
        segments=(TextSegment("赠送 小花花 x1"),),
        action="赠送",
        gift_name="小花花",
        quantity=1,
        gift_animation_url="https://i0.hdslb.com/bfs/live/flower.gif",
    )

    entry = message_to_mirror_entry(6, message)

    assert entry["giftAction"] == "赠送"
    assert entry["giftAnimationUrl"] == "https://i0.hdslb.com/bfs/live/flower.gif"


def test_message_to_mirror_entry_serializes_total_gift_value_in_yuan():
    message = GiftMessage(
        author=_author(color="#FFD700"),
        segments=(TextSegment("赠送 辣条 x2"),),
        action="赠送",
        gift_name="辣条",
        quantity=2,
        unit_price=1000,
        currency=GiftCurrency.GOLD,
    )

    entry = message_to_mirror_entry(7, message)

    assert entry["giftValue"] == "¥2"


def test_message_to_mirror_entry_converts_interact_message():
    message = InteractMessage(
        author=_author(name="观众", color="#AAAAAA"),
        segments=(TextSegment("关注了主播"),),
        interaction=InteractionKind.FOLLOW,
    )

    entry = message_to_mirror_entry(5, message)

    assert entry == {
        "seq": 5,
        "kind": "interact",
        "user": "观众",
        "userColor": "#AAAAAA",
        "segments": [{"type": "text", "text": "关注了主播"}],
    }


def test_message_to_mirror_entry_includes_like_count():
    message = InteractMessage(
        author=_author(name="点赞用户", color="#AAAAAA"),
        segments=(TextSegment("为主播点赞了"),),
        interaction=InteractionKind.LIKE,
        count=3,
    )

    entry = message_to_mirror_entry(5, message)

    assert entry["segments"] == [{"type": "text", "text": "为主播点赞了 x3"}]


def test_message_to_mirror_entry_converts_system_message():
    entry = message_to_mirror_entry(6, make_system_message("连接失败", SystemMessageLevel.ERROR))

    assert entry == {
        "seq": 6,
        "kind": "system",
        "user": " [系统]",
        "userColor": "#FF5555",
        "segments": [{"type": "text", "text": "连接失败"}],
    }


def test_message_to_mirror_entry_converts_super_chat_theme_metadata():
    message = SuperChatMessage(
        author=_author(name="SC用户", color="#FFE08A"),
        segments=(TextSegment("支持主播"),),
        message_id=12,
        price=30,
        message="支持主播",
        background_color="#223344",
        background_bottom_color="#112233",
        background_price_color="#FFE08A",
    )

    entry = message_to_mirror_entry(7, message)

    assert entry == {
        "seq": 7,
        "kind": "super_chat",
        "user": "SC用户",
        "userColor": "#FFE08A",
        "segments": [{"type": "text", "text": "支持主播"}],
        "scId": 12,
        "scPrice": 30,
        "scBackgroundColor": "#223344",
        "scBackgroundBottomColor": "#112233",
        "scBackgroundPriceColor": "#FFE08A",
    }


def test_mirror_state_caps_messages_and_assigns_sequences():
    state = MirrorState(max_messages=2)

    first = state.add_message(DanmakuMessage(author=_author(name="A"), segments=(TextSegment("1"),)))
    second = state.add_message(DanmakuMessage(author=_author(name="B"), segments=(TextSegment("2"),)))
    third = state.add_message(DanmakuMessage(author=_author(name="C"), segments=(TextSegment("3"),)))

    assert first["seq"] == 1
    assert second["seq"] == 2
    assert third["seq"] == 3
    assert [entry["user"] for entry in state.snapshot()] == ["B", "C"]


def test_mirror_state_rejects_nonpositive_history_limit():
    with pytest.raises(ValueError, match="message limit must be positive"):
        MirrorState(max_messages=0)
