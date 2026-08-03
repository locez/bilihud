# Module Boundaries

This document defines the dependency direction for production code and the
ownership represented by the Python package layout. It is a stable design rule,
not a list of current migration tasks.

## Package Layout

The repository uses feature-first packages. A feature owns its pure contracts,
parsers, and concrete external adapters; the application package coordinates
those features through typed capability contracts.

```text
bilihud/
  app/             application workflows, capability contracts, lifecycle, composition wiring
  auth/            authentication and secure session storage
  config/          typed settings, persistence, and legacy migration
  danmaku/         message contracts, formatting, blivedm adapter, client
  live/            live-room models, parsing, Bilibili/OBS adapters, validation
  mirror/          mirror state, serialization, and HTTP server
  platform/        overlay contracts and desktop/native window adapters
  *.py             Qt presentation and process entry points (T10 scope)
```

There is intentionally no generic `domain/`, `infrastructure/`, or `shared/`
package. `domain` was too broad to communicate ownership, while a single
`infrastructure` package made unrelated network, platform, and third-party
adapters accumulate in one namespace. The adapter now lives beside the feature
whose external contract it implements.

`app/services.py` is the composition root exception: it is allowed to import
concrete adapters so one object graph can be assembled. Application workflows
and capability contracts under `app/` must remain independent from those implementations.
The Qt presentation files remain at the package root until T10 decides whether
they need a dedicated `presentation/` package.

## Layers

| Layer | Owns | May depend on | Must not depend on |
| --- | --- | --- | --- |
| Presentation | Widgets, dialogs, input binding, rendering | Application contracts, feature values, Qt | Concrete network clients, persistence, platform implementation details |
| Application | Use cases, workflow coordination, lifecycle ownership, capability contracts | Feature contracts and standard library | Presentation code and concrete adapters |
| Feature contracts | Typed values, states, events, errors, pure parsing rules | Python standard library and other stable feature contracts | Qt, network libraries, persistence, platform APIs, raw third-party models |
| Feature adapters | Network, persistence, platform, and third-party integrations | Feature contracts, application capability contracts, external libraries | Presentation decisions and UI state |

Dependencies should point toward stable contracts and business meaning. The
package name must make the owner apparent; a new module must not be added to the
root merely because it is convenient.

## Ownership Rules

- `danmaku.messages` owns HUD message variants, author metadata, badges, and
  content segments. `danmaku.blivedm_adapter` is the boundary that converts
  `blivedm` web models into those contracts.
- `danmaku.mock` creates deterministic normalized messages for the tray
  regression action. It must not instantiate raw third-party models.
- `danmaku.format`, `mirror.state`, and Qt message rendering consume normalized
  messages and must not import `blivedm` models directly.
- `app.hud` owns HUD workflow state/events; `app.hud_controller` owns room
  transitions, audience refresh tasks, normalized send commands, and shutdown.
  `app.hud_client` defines the injected client capability.
- `app.live_control_service` owns live-control workflow state transitions and
  operation lifecycles. `app.live_control_api` defines the Bilibili capability;
  `app.obs_control` defines the OBS capability; `app.credential_store` owns the
  OBS password storage contract; and `app.verification` defines QR-image
  generation. `live.models` contains the live-control values and outcome types;
  `live.adapters` connects the API and OBS contracts to external services.
- `app.mirror_coordinator` owns Mirror configuration, history, server lifecycle,
  and typed operation results. `app.mirror_server` injects the HTTP capability;
  `mirror.server` only serves coordinator-owned state and applies the image
  proxy allowlist, DNS address checks, redirect policy, and response limits.
- `platform.overlay_contracts` owns toolkit-neutral window geometry, capability,
  result, and drag-strategy contracts. `platform.window_platform`,
  `platform.qt_window_platform`, `platform.layer_shell`, `platform.x11`, and
  `platform.native` isolate desktop integrations. `qt_window_host` is the Qt
  presentation binding for those contracts.
- `config.store` owns typed non-sensitive settings and `config.compat` owns
  legacy migration. `config.legacy` is a temporary caller facade; it must not
  become a second configuration model.
- `auth.service` owns authentication sessions and secure keyring access. UI
  code receives its protocol through application services rather than creating
  an authentication implementation.
- External data is parsed, validated, and normalized before entering feature
  contracts or application workflows. Raw third-party objects do not cross an
  adapter boundary.
- Every asynchronous task has a named owner and a cancellation/await path.
  Network sessions, servers, and native resources have explicit shutdown paths.

## Compatibility

`config/legacy.py` and `danmaku/compat.py` are transitional modules. The root
`helpers.py` and `utils.py` files are compatibility-only shims to those owning
packages. Their `TODO` comments state the removal condition; new code must use
typed config, application services, live validation, and normalized
`HudMessage` values instead. A temporary compatibility export must remain
narrow and must not recreate a generic common package.

## Verification

The executable import rules live in `tests/test_architecture.py`. Behavioral
tests are grouped under `tests/app`, `tests/auth`, `tests/config`,
`tests/danmaku`, `tests/live`, `tests/mirror`, and `tests/platform`; Qt
presentation and packaging tests remain at the test root. Architecture tests
may inspect the import AST because dependency direction is itself a stable
structural contract.
