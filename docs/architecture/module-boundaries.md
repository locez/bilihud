# Module Boundaries

This document defines the dependency direction for production code. It is a
stable design rule, not a list of current migration tasks.

## Layers

| Layer | Owns | May depend on | Must not depend on |
| --- | --- | --- | --- |
| Presentation | Widgets, dialogs, input binding, rendering | Application contracts, domain values, Qt | Concrete network clients, persistence, platform implementation details |
| Application | Use cases, workflow coordination, lifecycle ownership | Domain values and ports | Presentation code, concrete infrastructure implementations |
| Domain | Business rules, value objects, states, stable contracts | Python standard library | Qt, network libraries, persistence, platform APIs, third-party raw models |
| Infrastructure | Network, persistence, platform and third-party adapters | Application ports, domain contracts, external libraries | Presentation decisions and UI state |

## Rules

- Dependencies should point toward stable contracts and business meaning.
- External data is parsed and validated before entering the domain or application layer.
- Third-party raw objects do not cross an infrastructure boundary without an explicit adapter contract.
- `bilihud.domain.messages` owns HUD message variants, author metadata, badges,
  and content segments; `bilihud.infrastructure.blivedm_adapter` is the only
  boundary that converts `blivedm` web models into those contracts.
- `bilihud.mock_messages` creates deterministic domain messages for the tray's
  developer regression action and must not instantiate raw third-party models.
- `danmaku_format`, `mirror_state`, and Qt message rendering consume domain
  messages and must not import `blivedm` models directly.
- `hud_controller` owns room connection transitions, audience refresh tasks,
  normalized send commands, and typed HUD events; `hud_ports` defines the
  client capability and factory ports used to inject infrastructure.
- `danmaku_widget` binds `HudState` and `HudEvent` values to Qt controls and
  does not own a concrete `DanmakuClient` or its connection tasks.
- `mirror_coordinator` owns Mirror configuration, message history, server
  lifecycle, and typed operation results; `mirror_ports` injects the HTTP
  capability without importing the concrete server into application code.
- `mirror_server` only serves coordinator-owned state and applies the image
  proxy allowlist, DNS address checks, redirect policy, and response limits.
- `overlay_ports` owns toolkit-neutral window geometry, capability, result, and
  drag-strategy contracts; it must not import Qt, ctypes, or desktop APIs.
- `qt_window_host` is the presentation-side Qt binding for those contracts;
  `infrastructure.window_platform` owns capability-provider selection,
  `infrastructure.qt_window_platform` owns the portable Qt window baseline,
  and `infrastructure.layer_shell` and `infrastructure.x11` isolate optional
  native enhancements.
- Layer Shell drag behavior is selected through an infrastructure strategy
  registry: the existing KDE-compatible local-anchor strategy remains the
  default, while niri uses global pointer deltas and output-bound clamping for
  asynchronous compositor configure feedback.
- `danmaku_widget` binds the `OverlayPlatform` capability snapshot and forwards
  window gestures; desktop names and native handles do not appear in its
  workflow logic. A new desktop-specific drag behavior, such as a Layer Shell
  compositor-specific strategy, is added as a provider or strategy, not as a
  desktop-name branch in the widget.
- Presentation code binds state and commands; it does not own business workflows.
- Application code owns use-case lifecycles and coordinates infrastructure through ports.
- Domain code remains deterministic and independently testable whenever practical.
- New code must not introduce a circular dependency or a dependency in the forbidden direction.
- A temporary boundary exception must be narrow, documented, and covered by a removal condition.

## Verification

The executable import rules live in `tests/test_architecture.py` and run as part
of the normal test suite and CI. Architecture tests may inspect the import AST
by design; this is different from testing business behavior by matching source
strings or implementation fragments.
