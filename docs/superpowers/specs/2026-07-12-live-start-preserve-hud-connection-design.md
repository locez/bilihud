# Preserve HUD Connection During Live Start

## Context

Opening the live control dialog resolves the authenticated anchor room and connects the HUD to that room. The later `cbf2891` change also wired `LiveControlDialog.handle_start_live()` back to `DanmakuWidget._connect_to_room_id()` through an ensure callback.

That second path is incorrect. Starting a Bilibili live session does not require reconnecting the danmaku WebSocket. If the connection helper decides the existing client is not active, it may stop or replace the HUD client while the user is starting live. This can reset the HUD button to "连接", break incoming danmaku, and make the original connection unavailable for an explicit disconnect.

This also conflicts with the existing qasync danmaku shutdown design, which requires incoming danmaku to continue during live start without a forced reconnect.

## Goal

- Starting live must not inspect, stop, reconnect, replace, or otherwise mutate the HUD danmaku connection.
- The HUD client object and its callbacks must remain unchanged throughout `handle_start_live()`.
- Opening live control should continue to resolve the anchor room and automatically connect the HUD.

## Non-Goals

- Do not change manual HUD connect or disconnect behavior.
- Do not change how the anchor room is resolved when live control opens.
- Do not add automatic danmaku reconnection.
- Do not change Bilibili live API or OBS sequencing.

## Design

Remove the start-live-to-HUD connection contract entirely:

- Delete the ensure-HUD callback field and setter from `LiveControlDialog`.
- Delete `_ensure_hud_room()` and its call from `handle_start_live()`.
- Stop wiring `DanmakuWidget._connect_to_room_id()` into the dialog.
- Keep `_ensure_live_control_room()` unchanged so opening live control still connects the HUD to the authenticated anchor room.

After this change, the live control dialog owns only live API and OBS state. `DanmakuWidget` remains the sole owner of the HUD connection lifecycle.

## Data Flow

### Open Live Control

1. Resolve the authenticated anchor room ID.
2. Connect or reuse the HUD connection for that room.
3. Open `LiveControlDialog` with the resolved room ID.

### Start Live

1. Validate the live control form and OBS state.
2. Save and synchronize live room metadata.
3. Call the Bilibili start-live API.
4. Handle credentials and OBS startup.
5. Leave the HUD connection and button state untouched.

## Error Handling

Live API and OBS errors continue to use the dialog's existing status handling. Because start-live no longer calls HUD connection code, a HUD connection error cannot be misreported as a live-start failure and cannot reset the HUD connection UI.

## Testing

- Replace the existing source-level assertion that requires `handle_start_live()` to ensure the HUD room.
- Assert that `LiveControlDialog` exposes no ensure-HUD callback contract and that `handle_start_live()` contains no HUD connection call.
- Keep coverage proving that opening live control resolves the anchor room and calls `_connect_to_room_id()` once.
- Run the focused live control and danmaku widget tests, followed by the full test suite.

## Success Criteria

- Clicking "开始直播" never calls `DanmakuWidget._connect_to_room_id()`.
- A HUD showing "断开" before live start keeps the same client object and button state during live start.
- Incoming danmaku and manual disconnect continue to use the original HUD client.
- Opening live control still automatically connects the authenticated anchor room.
