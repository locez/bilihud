import importlib

import pytest

from bilihud.danmaku.blivedm_adapter import (
    MessageConversionError,
    parse_guard_purchase,
    to_hud_gift_message,
    to_hud_guard_message,
    to_hud_message,
    to_hud_message_or_system,
)
from bilihud.danmaku.messages import (
    DanmakuMessage,
    GiftCurrency,
    GiftMessage,
    ImageSegment,
    InteractionKind,
    InteractMessage,
    MessageBadgeKind,
    ReplySegment,
    SystemMessage,
    SystemMessageLevel,
    TextSegment,
)

web_models = importlib.import_module("blivedm.models.web")


def test_to_hud_message_converts_danmaku_into_typed_fragments_and_badges():
    raw_message = web_models.DanmakuMessage(
        uid=7,
        uname="Locez",
        msg="[汤圆] ok",
        mode_info={
            "extra": {
                "show_reply": True,
                "reply_uname": "主播",
                "emots": {
                    "[汤圆]": {
                        "url": "https://i0.hdslb.com/bfs/live/tangyuan.png",
                        "width": 60,
                        "height": 60,
                    }
                },
            }
        },
        medal_name="小狐",
        medal_level=26,
        wealth_level=8,
        privilege_type=3,
    )

    message = to_hud_message(raw_message)

    assert isinstance(message, DanmakuMessage)
    assert message.author.uid == 7
    assert message.author.name == "Locez"
    assert message.author.color == "#FFD700"
    assert [badge.kind for badge in message.author.badges] == [
        MessageBadgeKind.MEDAL,
        MessageBadgeKind.WEALTH,
        MessageBadgeKind.PRIVILEGE,
    ]
    assert message.segments == (
        ReplySegment("@主播 "),
        ImageSegment("[汤圆]", "https://i0.hdslb.com/bfs/live/tangyuan.png", 60, 60),
        TextSegment(" ok"),
    )


def test_to_hud_message_converts_gift_and_interaction_variants():
    gift = to_hud_message(
        web_models.GiftMessage(
            uid=3,
            uname="观众",
            action="赠送",
            gift_name="辣条",
            num=2,
            price=1000,
            coin_type="gold",
            gift_id=123,
            gift_img_basic="https://i0.hdslb.com/bfs/live/laitiao.png",
        )
    )
    interact = to_hud_message(web_models.InteractWordV2Message(uid=4, username="新观众", msg_type=2))

    assert isinstance(gift, GiftMessage)
    assert gift.author.name == "观众"
    assert gift.quantity == 2
    assert gift.unit_price == 1000
    assert gift.currency is GiftCurrency.GOLD
    assert gift.total_price == 2000
    assert gift.gift_id == 123
    assert gift.gift_image_url == "https://i0.hdslb.com/bfs/live/laitiao.png"
    assert gift.segments == (TextSegment("赠送 辣条 x2"),)
    assert isinstance(interact, InteractMessage)
    assert interact.author.name == "新观众"
    assert interact.interaction is InteractionKind.FOLLOW
    assert interact.segments == (TextSegment("关注了主播"),)


def test_to_hud_gift_message_keeps_normalized_official_effect_urls():
    raw_message = web_models.GiftMessage(gift_id=32132, gift_name="浪漫城堡", num=1)

    gift = to_hud_gift_message(
        raw_message,
        gift_effect_url="https://i0.hdslb.com/bfs/live/castle.mp4",
        gift_animation_url="https://i0.hdslb.com/bfs/live/castle.gif",
    )

    assert gift.gift_effect_url == "https://i0.hdslb.com/bfs/live/castle.mp4"
    assert gift.gift_animation_url == "https://i0.hdslb.com/bfs/live/castle.gif"


def test_guard_purchase_uses_the_anchor_effect_instead_of_the_buyer_effect():
    purchase = parse_guard_purchase(
        {
            "uid": 7,
            "username": "舰长用户",
            "guard_level": 3,
            "num": 1,
            "price": 198000,
            "gift_id": 10003,
            "gift_name": "舰长",
            "start_time": 123,
            "effect_id": 397,
        }
    )

    assert purchase is not None
    assert purchase.effect_id == 590
    gift = to_hud_guard_message(
        purchase,
        gift_effect_url="https://i0.hdslb.com/bfs/live/captain.mp4",
    )

    assert gift.action == "开通"
    assert gift.gift_name == "舰长"
    assert gift.gift_id == 10003
    assert gift.gift_effect_url.endswith("captain.mp4")
    assert gift.author.badges[0].kind is MessageBadgeKind.PRIVILEGE


def test_guard_toast_parser_uses_room_effect_and_filters_gifted_duplicate():
    raw_toast = {
        "sender_uinfo": {"uid": 8, "base": {"name": "提督用户"}},
        "guard_info": {"guard_level": 2, "start_time": 456},
        "pay_info": {"num": 1, "price": 1998000},
        "gift_info": {"gift_id": 10002, "gift_name": "提督"},
        "option": {"source": 0, "is_group": False},
        "effect_info": {"room_effect_id": 591, "room_group_effect_id": 1337},
    }

    purchase = parse_guard_purchase(raw_toast)
    duplicate = parse_guard_purchase(
        {
            **raw_toast,
            "option": {"source": 2, "is_group": False},
        }
    )

    assert purchase is not None
    assert purchase.effect_id == 591
    assert purchase.event_id == "456"
    assert duplicate is None


@pytest.mark.parametrize(
    ("msg_type", "interaction"),
    [
        (1, InteractionKind.ENTER),
        (2, InteractionKind.FOLLOW),
        (3, InteractionKind.SHARE),
        (4, InteractionKind.SPECIAL_FOLLOW),
        (5, InteractionKind.MUTUAL_FOLLOW),
        (6, InteractionKind.LIKE),
    ],
)
def test_to_hud_message_maps_all_interaction_codes(msg_type: int, interaction: InteractionKind) -> None:
    message = to_hud_message(web_models.InteractWordV2Message(username="观众", msg_type=msg_type))

    assert isinstance(message, InteractMessage)
    assert message.interaction is interaction
    assert message.segments == (TextSegment(interaction.text),)


def test_to_hud_message_degrades_malformed_optional_emoticon_metadata_to_text():
    raw_message = web_models.DanmakuMessage(dm_type=1, msg="[坏表情]", emoticon_options="not-json")

    message = to_hud_message(raw_message)

    assert isinstance(message, DanmakuMessage)
    assert message.segments == (TextSegment("[坏表情]"),)


def test_to_hud_message_rejects_unsupported_third_party_models():
    with pytest.raises(MessageConversionError, match="unsupported blivedm message type"):
        to_hud_message(web_models.SuperChatMessage(message="不支持"))


def test_to_hud_message_or_system_exposes_conversion_failure_as_domain_message():
    message = to_hud_message_or_system(object())

    assert isinstance(message, SystemMessage)
    assert message.level is SystemMessageLevel.ERROR
    assert message.text == "收到无法解析的直播消息"
