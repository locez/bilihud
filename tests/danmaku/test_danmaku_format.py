from bilihud.danmaku.format import (
    danmaku_author_badges_html,
    danmaku_emoticon_scaled_size,
    danmaku_emoticon_url,
    danmaku_message_content_html,
    danmaku_message_emoticon_urls,
    gift_value_text,
)
from bilihud.danmaku.messages import (
    DanmakuMessage,
    GiftCurrency,
    GiftMessage,
    ImageSegment,
    MessageAuthor,
    MessageBadge,
    MessageBadgeKind,
    ReplySegment,
    TextSegment,
)


def _message(*segments, badges=()):
    return DanmakuMessage(
        author=MessageAuthor(uid=1, name="Locez", color="#66CCFF", badges=badges),
        segments=tuple(segments),
    )


def _gift(*, quantity: int, unit_price: int, currency: GiftCurrency) -> GiftMessage:
    return GiftMessage(
        author=MessageAuthor(uid=2, name="送礼用户", color="#FFD700"),
        segments=(TextSegment("赠送 礼物"),),
        action="赠送",
        gift_name="礼物",
        quantity=quantity,
        unit_price=unit_price,
        currency=currency,
    )


def test_gift_value_text_formats_total_gold_coins_as_yuan():
    assert gift_value_text(_gift(quantity=2, unit_price=750, currency=GiftCurrency.GOLD)) == "¥1.5"
    assert gift_value_text(_gift(quantity=3, unit_price=1000, currency=GiftCurrency.GOLD)) == "¥3"


def test_gift_value_text_omits_non_gold_currency():
    assert gift_value_text(_gift(quantity=1, unit_price=1000, currency=GiftCurrency.SILVER)) == ""
    assert gift_value_text(_gift(quantity=1, unit_price=1000, currency=GiftCurrency.UNKNOWN)) == ""


def test_danmaku_emoticon_url_only_uses_pure_emoticon_messages():
    emoticon = _message(ImageSegment("[妙啊]", "https://i0.hdslb.com/bfs/live/emote.png", 183, 60))
    text = _message(TextSegment("[妙啊]"))

    assert danmaku_emoticon_url(emoticon) == "https://i0.hdslb.com/bfs/live/emote.png"
    assert danmaku_emoticon_url(text) == ""


def test_danmaku_emoticon_scaled_size_preserves_aspect_ratio():
    segment = ImageSegment("[妙啊]", "https://i0.hdslb.com/bfs/live/emote.png", 183, 60)

    assert danmaku_emoticon_scaled_size(segment) == (104, 34)


def test_danmaku_message_content_html_renders_emoticon_image_and_escapes_text():
    emoticon = _message(
        ImageSegment(
            '[<妙啊>"]',
            "https://i0.hdslb.com/bfs/live/emote.png?x=1&y=2",
            60,
            60,
        )
    )
    text = _message(TextSegment("<b>普通弹幕</b>"))

    assert danmaku_message_content_html(emoticon) == (
        '<img class="emoticon" src="https://i0.hdslb.com/bfs/live/emote.png?x=1&amp;y=2" '
        'width="34" height="34" alt="[&lt;妙啊&gt;&quot;]" />'
    )
    assert danmaku_message_content_html(text) == "&lt;b&gt;普通弹幕&lt;/b&gt;"


def test_danmaku_message_content_html_renders_inline_emoticons_from_segments():
    message = _message(
        ImageSegment("[汤圆]", "https://i0.hdslb.com/bfs/live/tangyuan.png?x=1&y=2", 60, 60),
        ImageSegment("[汤圆]", "https://i0.hdslb.com/bfs/live/tangyuan.png?x=1&y=2", 60, 60),
        TextSegment(" <ok>"),
    )

    assert danmaku_message_content_html(message) == (
        '<img class="emoticon" src="https://i0.hdslb.com/bfs/live/tangyuan.png?x=1&amp;y=2" '
        'width="34" height="34" alt="[汤圆]" />'
        '<img class="emoticon" src="https://i0.hdslb.com/bfs/live/tangyuan.png?x=1&amp;y=2" '
        'width="34" height="34" alt="[汤圆]" />'
        " &lt;ok&gt;"
    )


def test_danmaku_message_content_html_prepends_reply_target_prefix():
    message = _message(ReplySegment("@绚下的小恐龙 "), TextSegment("test"))

    assert danmaku_message_content_html(message) == (
        '<span class="reply">@绚下的小恐龙&nbsp;</span>test'
    )


def test_danmaku_message_emoticon_urls_include_inline_emots_once():
    message = _message(
        ImageSegment("[汤圆]", "https://i0.hdslb.com/bfs/live/tangyuan.png", 60, 60),
        ImageSegment("[汤圆]", "https://i0.hdslb.com/bfs/live/tangyuan.png", 60, 60),
        TextSegment(" [无图]"),
    )

    assert danmaku_message_emoticon_urls(message) == [
        "https://i0.hdslb.com/bfs/live/tangyuan.png"
    ]


def test_danmaku_author_badges_html_renders_compact_metadata_badges():
    badges = (
        MessageBadge(MessageBadgeKind.MEDAL, "<狐> 26", "粉丝牌", "#FF79C6"),
        MessageBadge(MessageBadgeKind.WEALTH, "✦ 8", "财富等级", "#C9B6FF"),
        MessageBadge(MessageBadgeKind.PRIVILEGE, "⚓︎", "大航海", "#86C8FF"),
    )
    message = _message(TextSegment("测试"), badges=badges)

    rendered = danmaku_author_badges_html(message)

    assert "meta-badge medal-badge" in rendered
    assert "&lt;狐&gt; 26</span>&nbsp;<span" in rendered
    assert "meta-badge wealth-badge" in rendered
    assert "✦ 8</span>&nbsp;<span" in rendered
    assert "meta-badge privilege-badge" in rendered
    assert "⚓︎" in rendered


def test_danmaku_author_badges_html_omits_empty_metadata():
    message = _message(TextSegment("测试"))

    assert danmaku_author_badges_html(message) == ""
