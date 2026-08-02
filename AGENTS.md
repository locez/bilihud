# AGENTS.md

## Scope

This file applies to the repository root and all subdirectories.

- This file contains only long-lived, repeatable engineering rules.
- Do not store issue lists, milestones, temporary migrations, or current technical-debt inventories here.
- Specific work is tracked in issues, pull requests, and design documents.
- A nested `AGENTS.md` may add stricter local rules, but must not weaken this file.
- System, developer, and user instructions take precedence over this file.

## General Principles

- Understand the existing code, tests, build configuration, and runtime before changing them.
- Prefer small, verifiable, reversible changes.
- Never overwrite, revert, or clean up changes that belong to the user.
- Avoid unrelated refactors, formatting changes, and dependency upgrades.
- Do not turn a temporary workaround into a permanent design.
- Add an abstraction only when it reduces coupling, clarifies ownership, or improves testability.
- Update tests and documentation when behavior or public contracts change.

## Change Workflow

For every task:

1. Confirm the scope, constraints, and acceptance criteria.
2. Check the current branch and working-tree status.
3. Read the relevant implementation, tests, and configuration.
4. Define the behavior boundary before implementing it.
5. Decide what evidence is needed for the change. Add or update tests only when
   they verify a meaningful behavior, contract, invariant, or failure path.
   Do not add tests merely because a file, setting, or code path changed.
6. Keep the change focused and complete.
7. Run the checks relevant to the change.
8. Review the final diff for unrelated files and temporary artifacts.
9. Record the change, tests, risks, and remaining work in the commit or pull request.

Do not develop directly on the default branch.

## Architecture

Business logic, external systems, and presentation code must have clear boundaries.

- Presentation code handles display, input, and state binding.
- Application code coordinates use cases and workflow lifecycles.
- Domain code owns business rules, value objects, state, and stable contracts.
- Infrastructure code adapts networks, files, databases, platform APIs, and third-party libraries.
- Business logic must not depend directly on a concrete UI, network client, or platform implementation.
- External data must be parsed, validated, and normalized at the boundary.
- Raw third-party objects must not propagate through business code without an explicit contract.
- Prefer interfaces, protocols, or capability models over concrete implementations.
- Avoid circular dependencies, implicit global state, and owner objects that absorb unrelated responsibilities.
- Transitional compatibility code must have a clearly limited scope and a documented removal condition.

## Strong Typing

Strong typing is a continuous requirement for all new and modified code.

- Public functions, methods, attributes, and cross-module interfaces must have complete annotations.
- Do not introduce unexplained `Any` into application or domain contracts.
- Do not use unbounded dictionaries to represent business state.
- Parse external JSON, configuration, and third-party objects into typed structures.
- Use `dataclass`, `Enum`, `Protocol`, `TypedDict`, and type aliases when they express the real contract.
- Give states, commands, events, errors, and configuration explicit structures.
- Use the type checker configured by the repository; do not hide errors by expanding exclusions.
- Every type suppression must document its reason, impact, and follow-up path.

## Documentation and Comments

- Public modules, classes, protocols, functions, and methods must have concise docstrings that explain their responsibility and relevant input, output, side effect, ownership, or failure contract.
- Key class fields must have a nearby comment or class-level field documentation when their role, default, sensitivity, lifecycle, or ownership is not obvious from the type alone.
- Document configuration fields, injected services, sessions, tasks, credentials, and other state that crosses a layer or has a non-trivial lifecycle.
- Private helpers need documentation when they enforce an invariant, normalize external data, handle security-sensitive values, or coordinate cancellation and resource cleanup.
- Comments should explain intent and constraints rather than repeat the code. Keep them short and update them with the behavior they describe.

## Python Quality

- Use explicit resource ownership and context management.
- Avoid mutable default arguments, implicit global state, and duplicated business logic.
- Catch only exceptions that can be handled; avoid blanket `except Exception` blocks.
- Use the repository's logging mechanism instead of `print()` for production diagnostics.
- Represent failures with explicit error types or result values.
- Keep functions focused and avoid unnecessary complexity.
- Prefer the standard library and existing project tools before adding dependencies.
- Do not modify third-party vendored code unless the task explicitly requires it.

## Async and Lifecycle

- Every asynchronous task must have a clear creator and owner.
- Keep task handles and cancel, await, and inspect them at the appropriate lifecycle boundary.
- Do not create unowned fire-and-forget tasks.
- Start, stop, retry, and shutdown operations should be predictable and as idempotent as practical.
- Network sessions, files, servers, threads, and subprocesses must have explicit cleanup paths.
- Do not rely on object destruction or process exit to release critical resources.
- Test cancellation, timeouts, repeated calls, and exceptional shutdown paths.

## Security

- Never expose passwords, tokens, sessions, private keys, or other secrets in logs, tests, issues, pull requests, or commits.
- Do not store sensitive data in ordinary configuration files, temporary files, or build artifacts.
- Do not bypass authentication, TLS, validation, or permission checks for convenience.
- Validate every external input.
- Treat external URLs, file paths, redirects, and subprocess arguments as security boundaries.
- Apply reasonable timeouts and response-size limits to network requests.
- Security behavior must be covered by automated tests rather than relying on callers to use an API correctly.

## Testing

Tests are executable evidence for behavior and contracts, not a way to count
changed lines or restate the implementation.

- Before writing a test, name the observable behavior or contract it protects
  and the regression that would make it fail. If that cannot be stated clearly,
  do not add the test.
- Prefer behavior, interface, integration, and failure-path tests that survive
  internal refactoring and fail when an externally observable contract breaks.
- Do not add tests only to increase coverage, mirror every branch mechanically,
  or confirm that a recently edited file contains an expected line.
- Do not use raw source reads, substring checks, import order, call ordering, or
  private implementation details as primary assertions. In particular, avoid
  tests shaped like `assert "..." in Path(...).read_text()` for source or
  configuration files.
- Structural rules can be tested when the structure is itself a stable contract,
  such as module dependency boundaries or a generated artifact. Test them at the
  right level with an AST/import-graph check, a format-aware parser, an actual
  build/package installation, or CI validation. Do not replace those checks with
  hand-written literal searches through files.
- For metadata-only, lockfile-only, formatting-only, or workflow-only changes,
  prefer the real tool that consumes the artifact (`uv lock --check`, a build,
  package validation, or CI) over a unit test that repeats its text.
- Exact literals are appropriate when they are part of a stable external
  contract, such as user-visible output, a protocol field, or serialized data.
  They are not evidence that an implementation detail exists in a particular
  file.
- Use fakes, stubs, or adapters for external services.
- Cover normal, failure, cancellation, timeout, and repeated-call paths.
- Run the full test suite when changing public behavior, lifecycle management, or cross-module contracts.
- Run the relevant build, packaging, or CI checks when changing dependencies or build configuration.
- Never solve a failing test by deleting coverage, weakening assertions, or expanding exclusions without documenting the reason.
- Record environment limitations and remaining risk when a check cannot run.

## Verification

- Treat `pyproject.toml`, CI workflows, and project documentation as the source of truth for supported runtimes and commands.
- Run the smallest relevant check set during development and the required full checks before submission.
- Typical local commands are:

  ```bash
  uv sync --extra test
  xvfb-run -a uv run pytest -q
  uv run ruff check --select=E9,F63,F7,F82 src/
  uv run ruff check src tests
  uv run ty check src
  uv build
  ```

- Update this section when the canonical project commands change.
- Run `git diff --check` before committing.
- Never claim that a check passed unless it was actually run.
- Distinguish pre-existing failures from regressions introduced by the current change.

## Git Workflow

Use branch names in this form:

```text
<type>/issue-<number>-<short-description>
```

Examples:

```text
feat/issue-123-add-login-flow
fix/issue-124-handle-timeout
refactor/issue-125-split-service
chore/issue-126-update-tooling
```

- One branch should normally contain one logical task.
- Do not develop directly on the default branch.
- Do not use destructive Git commands to overwrite user changes.
- Do not force-push over shared history.
- Do not commit caches, credentials, build artifacts, or temporary files.
- Review the staged diff before committing.

## Conventional Commits

Commit messages must follow:

```text
<type>(<scope>): <summary>

<body>

<footer>
```

Allowed types:

```text
feat fix refactor test docs build ci chore perf revert
```

Rules:

- Use a lowercase type.
- Prefer a scope describing the affected responsibility or module.
- Keep the summary concise, imperative, and without a trailing period.
- One commit should express one logical change.
- Do not use `WIP`, `update`, or otherwise meaningless commit messages.
- Use the body to explain why the change is needed, how behavior changed, and how it was verified.
- Use `Refs: #<number>` for ongoing work.
- Use `Closes #<number>` only when the commit or pull request actually completes the issue.
- Use a `BREAKING CHANGE:` footer for breaking changes.

Example:

```text
refactor(auth): isolate credential storage

Move credential persistence behind a typed storage interface and
keep presentation code independent from the concrete backend.

Refs: #123
```

## Completion Checklist

Before committing or opening a pull request, confirm:

- [ ] The change matches the current task scope.
- [ ] Existing user changes were preserved.
- [ ] New interfaces have explicit types.
- [ ] No unnecessary cross-layer dependency was introduced.
- [ ] Asynchronous tasks and resources have clear lifecycles.
- [ ] Relevant tests passed.
- [ ] Static-check results were verified.
- [ ] `git diff --check` passed.
- [ ] No secrets or temporary files are included.
- [ ] The commit follows Conventional Commits.
- [ ] The pull request includes a summary, verification results, risks, and references.
