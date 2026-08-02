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
