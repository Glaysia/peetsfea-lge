---
title: Code Commandments
created: 2026-04-17 @ 09:09
updated: 2026-04-17 @ 09:09
tags:
  - governance
---

# Code Commandments

`CODE_COMMANDMENTS.md` is the canonical registry for repository-wide coding commandments.

- Commandment numbers are stable once published.
- New commandments may be added later without renumbering older ones.
- This revision intentionally documents Commandments 1 through 5.
- Undocumented commandment numbers are out of scope until they are explicitly ratified.

## Commandment 1: Raise on Every Failure

This commandment applies to all source code in this repository, including future code.

- Failures must raise exceptions instead of being downgraded to `False`, `None`, logging-only behavior, or silent continuation.
- Execution must stop on the first failure by default.
- Best-effort continuation is forbidden unless a user requirement explicitly asks for it and the relevant code path documents that exception.
- If an external boundary reports failure without raising on its own, repository code must convert that failure into a raised exception immediately.
- The raised exception must name the failed operation and include enough local context to make the failure actionable.

This is a normative rule, not a suggestion. Do not treat failure as normal control flow.

## Commandment 2: PyAEDT `False` Must Raise Immediately

This commandment applies to every PyAEDT call in this repository, including future code.

- If a PyAEDT call returns the boolean value `False`, raise immediately at the call site or through a thin helper that raises on behalf of the call site.
- Do not ignore the return value of a PyAEDT call that can signal failure with `False`.
- Do not translate a PyAEDT `False` result into logging, warnings, retries, branching, or best-effort continuation unless the user explicitly asked for that behavior and the code still raises for the failed operation.
- The exception must name the PyAEDT operation and include useful local context such as object name, design ID, path, dimensions, or relevant parameters.

This commandment specializes Commandment 1 for the PyAEDT boundary.

## Commandment 3: `src/` Must Not Use Nullable Runtime State

This commandment applies to repository-owned Python code under `src/`.

- Do not use `Optional[...]`, `| None`, or `NotRequired[...]` to model repository runtime state.
- Do not use `if value is None` or `if value is not None` as ordinary control flow inside `src/`.
- This commandment applies to all `src/` code, including parser, boundary, and adapter code. No parser/spec-boundary exception is permitted.
- Absence is not a valid steady-state value in repository runtime code. Model it as a different phase/type, or as a required registry key that must exist before read.
- If later logic requires a value, the value must be created and stored canonically at the owning step. Downstream code must read that canonical value, not reconstruct or guess it.
- If a value is required but missing, assert or raise immediately at the first read site with actionable context.

This commandment does not permit sentinel `None` state to leak across internal boundaries.

## Commandment 4: Bind Only After Asserted Validation

This commandment applies to repository-owned Python code under `src/`.

- Raw external values may exist only briefly in `raw_*` variables before validation.
- Before storing or re-binding an external value as a repository variable, assert the required shape explicitly.
- When reading attributes from dynamic objects, first `assert hasattr(...)`, then read the attribute, then `assert isinstance(...)` or assert an equivalent invariant before reuse.
- When reading registry or mapping state that is required for correct execution, first `assert key in registry`, then use direct indexing. Do not treat missing keys as a normal branch.
- Bare `assert` is the standard enforcement mechanism for these invariants in `src/`.

This repository does not support `python -O`. Optimized mode strips required fail-fast assertions and is therefore invalid for development, tests, and normal execution.

## Commandment 5: Attribute and Mapping Fallbacks Are Forbidden

This commandment applies to repository-owned Python code under `src/`.

- Do not use `getattr(obj, "attr", default)` to continue with a fallback value.
- Do not use `hasattr(...)` as a conditional capability probe that silently chooses fallback behavior. Use it only as a precondition assertion before required access.
- Do not use `mapping.get(key)` or similar default-return APIs for required repository state.
- This commandment applies to all `src/` code, including parser and boundary code. Do not reclassify missing required state as optional by introducing a boundary exception.
- Do not return empty strings, empty lists, zero-valued geometry, `False`, or `None` as degraded substitutes for missing required runtime data.
- If an external boundary does not provide a required attribute, module, material, session, name, edge, bbox, or coordinate, raise immediately with context.

This commandment specializes Commands 1, 3, and 4 for dynamic attribute access and mapping access.

## Allowed

- Check any failure indicator and raise immediately.
- Check a PyAEDT result and raise immediately when the result is `False`.
- Wrap repeated PyAEDT calls in a thin helper whose only job is to convert `False` into a raised exception with context.
- Add context such as object name, operation name, path, design ID, or relevant parameters before re-raising.
- Use phase-specific types or registry membership assertions instead of nullable runtime state.
- Read required attributes with `assert hasattr(...)`, then `getattr(...)`, then explicit invariant checks.
- Read required mapping entries with `assert key in mapping` followed by `mapping[key]`.

## Disallowed

- Downgrading a real failure into ordinary control flow.
- Ignoring the return value of a PyAEDT call that can return `False`.
- Printing a warning or logging the failure and continuing execution.
- Returning `False` or `None` to the caller instead of raising.
- Converting a PyAEDT `False` result into ordinary branching as though it were an expected non-exceptional outcome.
- Using `Optional[...]`, `| None`, `NotRequired[...]`, `is None`, or `is not None` as repository runtime-state control flow inside `src/`.
- Using `getattr(..., default)` or `mapping.get(...)` to hide missing required state.
- Running repository code with `python -O`.
