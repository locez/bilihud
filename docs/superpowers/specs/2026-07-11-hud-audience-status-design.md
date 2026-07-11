# BiliHUD HUD Audience Status Design

## Purpose

Add a compact audience status strip to the top of the normal BiliHUD window. The strip shows Bilibili's public room metrics without presenting popularity as a verified concurrent viewer count, and lets the user inspect the contribution-ranked audience identities that Bilibili exposes.

The feature is informational. It does not change danmaku reception, room connection semantics, live control, or mirror output.

## Scope

In scope:

- show room popularity, current-live-session watched count, and online-rank count;
- make the online-rank text clickable;
- show visible ranked users and each user's contribution value in a compact anchored popup;
- refresh the snapshot immediately after connection and every 30 seconds;
- reuse the authenticated `aiohttp` session already owned by `DanmakuClient`;
- stop and clear the feature when the room disconnects, changes, or enters gaming/pass-through mode.

Out of scope:

- claiming that popularity is a real concurrent viewer count;
- reconstructing identities that Bilibili does not return;
- tracking historical audience data;
- adding audience metrics to BiliHUD Mirror;
- adding sorting, filtering, search, export, or manual refresh controls;
- relying on deprecated WebSocket heartbeat popularity values.

## Confirmed Interface

The existing header remains unchanged. A separate status strip appears directly below it after the first successful audience snapshot:

```text
21 人气 · 9 人看过 · 在线榜 3
```

The strip is approximately 22 pixels high and uses the existing dark translucent utility styling. Popularity and watched count use restrained neutral text. Only `在线榜 3` uses the blue interactive treatment and pointing-hand cursor.

Clicking `在线榜 3` opens a frameless popup anchored below the clickable text:

```text
在线榜                         可见 1 / 共 3
用户名                                贡献值
缘梦星声                                   1
还有 2 位用户未公开
```

The popup has these behaviors:

- user names and contribution values are displayed in two aligned columns;
- contribution value comes from the ranked user's `score` field;
- a long visible list scrolls internally and never resizes the HUD;
- the popup reports visible and total counts separately;
- when the total exceeds the returned user list length, the footer reports the unexposed count;
- an empty visible list shows a concise empty state while preserving the total count;
- clicking outside, pressing Escape, disconnecting, switching rooms, or entering gaming mode closes it.

The status strip follows the existing header visibility contract. Gaming/pass-through mode hides the strip completely. Disconnecting hides the strip, clears its snapshot, and closes the popup.

## Data Semantics

The UI must preserve Bilibili's distinct metric meanings:

- `popularity`: Bilibili's room popularity value, displayed as `N 人气`;
- `watched_show.num`: the current live session's cumulative watched count, displayed as `N 人看过`;
- contribution-rank `count`: the online-rank total exposed by the contribution-rank service, displayed as `在线榜 N`;
- contribution-rank `item`: the identities Bilibili exposes for the selected rank;
- item `score`: that user's contribution value.

The application must not label any of these fields as a verified concurrent viewer count. The contribution-rank total may exceed the returned item count. Missing identities are summarized, not synthesized.

## API Contract

`DanmakuClient` uses its existing logged-in or anonymous `aiohttp.ClientSession` for both requests.

Room metrics:

```text
GET https://api.live.bilibili.com/xlive/web-room/v1/index/getInfoByRoom
room_id=<room id>
```

Relevant response paths:

```text
data.popularity.popularity
data.room_info.online                  # fallback popularity only
data.watched_show.num
```

Contribution-ranked audience:

```text
GET https://api.live.bilibili.com/xlive/general-interface/v1/rank/queryContributionRank
ruid=<anchor uid>
room_id=<room id>
page=1
page_size=100
type=online_rank
switch=contribution_rank
platform=web
```

Relevant response paths:

```text
data.count
data.count_text
data.item[].uid
data.item[].name
data.item[].score
data.item[].rank
data.item[].is_mystery
```

The anchor UID is read from the room-info response. The implementation must use the current `queryContributionRank` contract rather than the obsolete `getOnlineRank` request.

Requests include a Bilibili live-room Referer. No cookie, CSRF token, or other credential value is logged or added to the UI.

## Data Model

Introduce two immutable values in a focused audience module, following the existing `live_emoticons.py` parser pattern:

```python
@dataclass(frozen=True)
class AudienceUser:
    uid: int
    name: str
    contribution: int
    rank: int
    is_mystery: bool = False


@dataclass(frozen=True)
class AudienceSnapshot:
    room_id: int
    popularity: int
    watched_count: int
    online_rank_count: int
    users: tuple[AudienceUser, ...]

    @property
    def hidden_user_count(self) -> int:
        return max(0, self.online_rank_count - len(self.users))
```

Parsing functions own integer normalization, missing-field defaults, list validation, and conversion from API dictionaries. UI code consumes typed values and does not traverse raw Bilibili JSON.

## Component Boundaries

### Audience Parser Module

A new focused module owns the audience data classes and pure parsing helpers. It has no Qt or network dependencies.

### DanmakuClient

`DanmakuClient` owns `fetch_audience_snapshot()` because it already owns the authenticated Bilibili session and room ID. The method:

1. requires an initialized session;
2. fetches room info;
3. extracts the anchor UID;
4. fetches the contribution-ranked audience;
5. returns a typed `AudienceSnapshot`.

The request sequence is intentionally ordered because the second endpoint requires the anchor UID returned by the first.

### Audience Status Strip

A small Qt widget owns the visible status text and clickable online-rank control. It accepts `AudienceSnapshot | None` and contains no networking or timers.

### Audience Popup

A small frameless popup owns the two-column user list, visible/total summary, empty state, hidden-user footer, scrolling, and dismissal behavior. It renders cached snapshots only and performs no API requests.

### DanmakuWidget

`DanmakuWidget` owns feature lifecycle coordination:

- create the strip and popup during UI initialization;
- start the refresh task only after the danmaku client connects;
- apply snapshots only when the room ID and refresh generation still match;
- close and clear the feature before replacing or stopping a client;
- hide the strip and close the popup in gaming mode;
- restore normal visibility only after a new successful snapshot.

## Refresh Lifecycle

The refresh loop follows this sequence:

1. room connection succeeds;
2. any previous audience refresh task is cancelled and awaited;
3. the status strip remains hidden while the first request is pending;
4. fetch and apply one audience snapshot immediately;
5. wait 30 seconds;
6. repeat while the same client, room ID, and generation remain current.

Only one audience refresh task may exist per `DanmakuWidget`. Room changes increment or replace a generation token so a late response from an old room cannot update the current UI.

The popup uses the latest cached snapshot. Opening it does not create an additional API request.

## Error Handling

- If the initial snapshot fails, leave the strip hidden and log the failure at informational or warning level.
- If a later refresh fails, keep the last successful snapshot visible and log the failure.
- Do not append recurring audience refresh errors to the danmaku list and do not open modal error dialogs.
- Invalid or missing response fields normalize to safe non-negative values where possible.
- A non-zero Bilibili API code raises a descriptive client-side exception and does not partially replace the displayed snapshot.
- Cancelling the refresh task during disconnect is expected control flow and must not be logged as an error.

## Layout And Accessibility

- The status strip has stable height and spacing so data changes do not resize the header controls.
- Numeric labels use compact, non-wrapping text and elide only if the full strip cannot fit.
- The online-rank control has a pointing-hand cursor and a tooltip naming the action.
- The popup constrains its width to the HUD and its height to the available content area.
- Long user names elide while their full names remain available through tooltips.
- Contribution values are right-aligned and use tabular numeric alignment where supported.
- Keyboard Escape closes the popup.
- The popup is unavailable in gaming/pass-through mode because the entire status strip is hidden.

## Testing

### Pure Parser Tests

- parse popularity, watched count, rank count, user identity, and contribution score;
- fall back from `data.popularity.popularity` to `data.room_info.online`;
- reject or safely normalize malformed list and numeric fields;
- calculate hidden-user count when total exceeds visible users;
- clamp hidden-user count to zero when responses are inconsistent.

### Request Contract Tests

- request `getInfoByRoom` with the current room ID and live-room Referer;
- use the returned anchor UID for `queryContributionRank`;
- send `room_id`, `page_size=100`, `type=online_rank`, `switch=contribution_rank`, and `platform=web`;
- convert successful responses into one typed snapshot;
- reject non-zero API responses without exposing credentials.

### Widget Tests

- format the strip as `N 人气 · N 人看过 · 在线榜 N`;
- make only the online-rank element actionable;
- render each user and contribution in the same popup row;
- show visible and total counts plus the hidden-user footer;
- render the empty visible-list state;
- constrain long lists to an internal scroll area;
- close on outside click, Escape, disconnect, room switch, and gaming mode;
- hide and clear on disconnect;
- retain the last snapshot after a later refresh failure.

### Lifecycle Tests

- fetch immediately after a successful connection;
- wait 30 seconds between successful refresh attempts;
- cancel and await the old task when disconnecting or replacing the room;
- ignore a late result from an old client or generation;
- keep the strip hidden when the first refresh fails.

### Visual Verification

Run the Qt UI in offscreen mode at the default 300-pixel HUD width. Capture the normal-mode header, status strip, and open audience popup. Verify that controls and labels do not overlap, the popup remains within HUD bounds, long names elide, contribution values align, and entering gaming mode hides both status strip and popup.

## Acceptance Criteria

- A successful room connection produces a status strip without user action.
- The strip updates no more frequently than every 30 seconds.
- Popularity is labeled `人气`, not viewer count.
- Clicking `在线榜 N` opens the anchored popup.
- Every visible popup row maps one returned user to that user's contribution score.
- Unexposed online-rank identities are represented only by an aggregate footer.
- The popup does not resize the HUD or obscure the header controls.
- Disconnecting, changing rooms, or enabling gaming mode hides and clears the feature.
- Transient refresh failures do not erase the last valid snapshot or spam the UI.
- Automated parser, request, widget, and lifecycle tests pass.
