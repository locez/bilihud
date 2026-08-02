import importlib

import pytest

from bilihud.domain.messages import (
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
from bilihud.infrastructure.blivedm_adapter import (
    MessageConversionError,
    to_hud_message,
    to_hud_message_or_system,
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
        )
    )
    interact = to_hud_message(web_models.InteractWordV2Message(uid=4, username="新观众", msg_type=2))

    assert isinstance(gift, GiftMessage)
    assert gift.author.name == "观众"
    assert gift.quantity == 2
    assert gift.unit_price == 1000
    assert gift.currency is GiftCurrency.GOLD
    assert gift.total_price == 2000
    assert gift.segments == (TextSegment("赠送 辣条 x2"),)
    assert isinstance(interact, InteractMessage)
    assert interact.author.name == "新观众"
    assert interact.interaction is InteractionKind.FOLLOW
    assert interact.segments == (TextSegment("关注了主播"),)


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
