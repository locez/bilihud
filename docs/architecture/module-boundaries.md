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
