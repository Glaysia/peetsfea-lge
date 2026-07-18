from __future__ import annotations

from dataclasses import dataclass
from math import gcd
from typing import Literal, TypedDict, cast


SswConstraintComparisonOperator = Literal["<", "<=", ">", ">=", "=="]


class SswConstraintPathRef(TypedDict):
    path: str


class SswConstraintValueRef(TypedDict):
    value: str | float


class SswConstraintFuncRef(TypedDict):
    func: str


SswConstraintComparableRef = SswConstraintPathRef | SswConstraintFuncRef
SswConstraintOperandRef = SswConstraintPathRef | SswConstraintValueRef | SswConstraintFuncRef
SswConstraintOperandValue = int | float | str


@dataclass(frozen=True)
class SswConstraintRule:
    id: str
    message: str
    enabled: bool
    lhs: SswConstraintComparableRef
    op: SswConstraintComparisonOperator
    rhs: SswConstraintOperandRef


@dataclass(frozen=True)
class SswConstraintCoil:
    object_id: str
    is_ssw_enabled: bool
    turn_n_int: int
    twist_factor: int


@dataclass(frozen=True)
class _ConstraintFunctionCall:
    name: str
    args: tuple[str, ...]


def _require_table(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"{context} must be a table")
    return value


def _require_key(table: dict[str, object], key: str, context: str) -> object:
    if key not in table:
        raise ValueError(f"{context} is missing required key {key!r}")
    return table[key]


def _require_non_empty_str(table: dict[str, object], key: str, context: str) -> str:
    raw_value = _require_key(table, key, context)
    if not isinstance(raw_value, str):
        raise TypeError(f"{context}.{key} must be str")
    if raw_value == "":
        raise ValueError(f"{context}.{key} must be non-empty")
    return raw_value


def _require_bool(table: dict[str, object], key: str, context: str) -> bool:
    raw_value = _require_key(table, key, context)
    if not isinstance(raw_value, bool):
        raise TypeError(f"{context}.{key} must be bool")
    return raw_value


def _require_constraint_path(value: object, *, context: str) -> str:
    table = _require_table(value, context)
    if set(table.keys()) != {"path"}:
        raise ValueError(f"{context} must contain only ['path']")
    return _require_non_empty_str(table, "path", context)


def _require_constraint_value(value: object, *, context: str) -> str | float:
    table = _require_table(value, context)
    if set(table.keys()) != {"value"}:
        raise ValueError(f"{context} must contain only ['value']")
    raw_value = _require_key(table, "value", context)
    if isinstance(raw_value, bool):
        raise TypeError(f"{context}.value must be number|string")
    if isinstance(raw_value, (int, float)):
        return float(raw_value)
    if isinstance(raw_value, str):
        if raw_value == "":
            raise ValueError(f"{context}.value must be non-empty")
        return raw_value
    raise TypeError(f"{context}.value must be number|string")


def _split_constraint_func_args(text: str, *, context: str) -> tuple[str, ...]:
    parts: list[str] = []
    token: list[str] = []
    depth = 0
    for char in text:
        if char == "(":
            depth += 1
            token.append(char)
            continue
        if char == ")":
            depth -= 1
            if depth < 0:
                raise ValueError(f"{context} has unmatched ')'")
            token.append(char)
            continue
        if char == "," and depth == 0:
            piece = "".join(token).strip()
            if piece == "":
                raise ValueError(f"{context} contains an empty argument")
            parts.append(piece)
            token = []
            continue
        token.append(char)
    if depth != 0:
        raise ValueError(f"{context} has unmatched '('")
    tail = "".join(token).strip()
    if tail != "":
        parts.append(tail)
    return tuple(parts)


def _parse_constraint_func_call(raw_func: str, *, context: str) -> _ConstraintFunctionCall:
    text = raw_func.strip()
    if not text.endswith(")") or "(" not in text:
        raise ValueError(f"{context}.func must be a call expression")
    open_index = text.find("(")
    name = text[:open_index].strip()
    if name != "ssw_conductor_component_count":
        raise ValueError(
            f"{context}.func must be one of ['ssw_conductor_component_count(...)'] (actual={name!r})"
        )
    body = text[open_index + 1 : -1].strip()
    if body == "":
        raise ValueError(f"{context}.func must contain one argument")
    args = _split_constraint_func_args(body, context=f"{context}.func")
    if len(args) != 1:
        raise ValueError(f"{context}.func ssw_conductor_component_count() must contain exactly one argument")
    return _ConstraintFunctionCall(name=name, args=args)


def _parse_constraint_func(value: object, *, context: str) -> str:
    table = _require_table(value, context)
    if set(table.keys()) != {"func"}:
        raise ValueError(f"{context} must contain only ['func']")
    raw_func = _require_non_empty_str(table, "func", context)
    _parse_constraint_func_call(raw_func, context=context)
    return raw_func


def _parse_comparable_ref(value: object, *, context: str) -> SswConstraintComparableRef:
    if not isinstance(value, dict):
        raise TypeError(f"{context} must be a table")
    if set(value.keys()) == {"path"}:
        return SswConstraintPathRef(path=_require_constraint_path(value, context=context))
    if set(value.keys()) == {"func"}:
        return SswConstraintFuncRef(func=_parse_constraint_func(value, context=context))
    raise ValueError(f"{context} must contain exactly one of ['path'], ['func']")


def _parse_operand_ref(value: object, *, context: str) -> SswConstraintOperandRef:
    if not isinstance(value, dict):
        raise TypeError(f"{context} must be a table")
    if set(value.keys()) == {"path"}:
        return SswConstraintPathRef(path=_require_constraint_path(value, context=context))
    if set(value.keys()) == {"value"}:
        return SswConstraintValueRef(value=_require_constraint_value(value, context=context))
    if set(value.keys()) == {"func"}:
        return SswConstraintFuncRef(func=_parse_constraint_func(value, context=context))
    raise ValueError(f"{context} must contain exactly one of ['path'], ['value'], ['func']")


def _parse_constraint_rule(raw_rule: object, *, index: int, context: str) -> SswConstraintRule:
    dotted = f"{context}.constraints.rules[{index}]"
    table = _require_table(raw_rule, dotted)
    required_keys = {"id", "kind", "message", "enabled", "lhs", "op", "rhs"}
    if set(table.keys()) != required_keys:
        raise ValueError(f"{dotted} must contain exactly keys {sorted(required_keys)}")
    raw_kind = _require_non_empty_str(table, "kind", dotted)
    if raw_kind != "comparison":
        raise ValueError(f"{dotted}.kind must be 'comparison' (actual={raw_kind!r})")
    raw_op = _require_non_empty_str(table, "op", dotted)
    if raw_op not in ("<", "<=", ">", ">=", "=="):
        raise ValueError(f"{dotted}.op must be one of ['<', '<=', '>', '>=', '==']")
    return SswConstraintRule(
        id=_require_non_empty_str(table, "id", dotted),
        message=_require_non_empty_str(table, "message", dotted),
        enabled=_require_bool(table, "enabled", dotted),
        lhs=_parse_comparable_ref(_require_key(table, "lhs", dotted), context=f"{dotted}.lhs"),
        op=cast(SswConstraintComparisonOperator, raw_op),
        rhs=_parse_operand_ref(_require_key(table, "rhs", dotted), context=f"{dotted}.rhs"),
    )


def parse_ssw_constraint_rules(root: dict[str, object], *, context: str) -> tuple[SswConstraintRule, ...]:
    constraints = _require_table(_require_key(root, "constraints", context), f"{context}.constraints")
    raw_rules = _require_key(constraints, "rules", f"{context}.constraints")
    if isinstance(raw_rules, (str, bytes)) or not isinstance(raw_rules, list):
        raise TypeError(f"{context}.constraints.rules must be a list")
    if len(raw_rules) == 0:
        raise ValueError(f"{context}.constraints.rules must be non-empty")
    seen_ids: set[str] = set()
    parsed_rules: list[SswConstraintRule] = []
    for index, raw_rule in enumerate(raw_rules):
        parsed = _parse_constraint_rule(raw_rule, index=index, context=context)
        if parsed.id in seen_ids:
            raise ValueError(f"{context}.constraints.rules contains duplicate id {parsed.id!r}")
        seen_ids.add(parsed.id)
        parsed_rules.append(parsed)
    return tuple(parsed_rules)


def _coil_by_object_id(coils: tuple[SswConstraintCoil, ...], object_id: str, *, context: str) -> SswConstraintCoil:
    matches = tuple(coil for coil in coils if coil.object_id == object_id)
    if len(matches) != 1:
        raise ValueError(f"{context} references unknown SSW coil object_id {object_id!r}")
    return matches[0]


def _path_value(coils: tuple[SswConstraintCoil, ...], path: str, *, context: str) -> SswConstraintOperandValue:
    parts = tuple(path.split("."))
    if len(parts) != 3 or parts[0] != "modeled_objects":
        raise ValueError(f"{context} references unsupported path {path!r}")
    coil = _coil_by_object_id(coils, parts[1], context=context)
    field = parts[2]
    if field == "is_ssw_enabled":
        return 1 if coil.is_ssw_enabled else 0
    if field == "turn_n_int":
        return coil.turn_n_int
    if field == "twist_factor":
        return coil.twist_factor
    raise ValueError(f"{context} references unsupported SSW coil field {field!r}")


def _ssw_component_count(coil: SswConstraintCoil, *, context: str) -> int:
    if coil.turn_n_int <= 0:
        raise ValueError(f"{context} requires positive turn_n_int (object_id={coil.object_id!r})")
    if coil.twist_factor < 0:
        raise ValueError(f"{context} requires non-negative twist_factor (object_id={coil.object_id!r})")
    if not coil.is_ssw_enabled:
        return 1
    return gcd(coil.turn_n_int, coil.twist_factor)


def _func_value(coils: tuple[SswConstraintCoil, ...], raw_func: str, *, context: str) -> SswConstraintOperandValue:
    call = _parse_constraint_func_call(raw_func, context=context)
    if call.name == "ssw_conductor_component_count":
        coil = _coil_by_object_id(coils, call.args[0], context=context)
        return _ssw_component_count(coil, context=context)
    raise ValueError(f"{context}.func unsupported function {call.name!r}")


def _operand_value(
    coils: tuple[SswConstraintCoil, ...],
    operand: SswConstraintOperandRef,
    *,
    context: str,
) -> SswConstraintOperandValue:
    if "path" in operand:
        return _path_value(coils, operand["path"], context=context)
    if "value" in operand:
        return operand["value"]
    return _func_value(coils, operand["func"], context=context)


def _evaluate_comparison(
    lhs: SswConstraintOperandValue,
    op: SswConstraintComparisonOperator,
    rhs: SswConstraintOperandValue,
) -> bool:
    if op in ("<", "<=", ">", ">="):
        if isinstance(lhs, str) or isinstance(rhs, str):
            raise TypeError(f"comparison operator {op!r} is not supported for string operands")
        numeric_lhs = lhs
        numeric_rhs = rhs
        if op == "<":
            return numeric_lhs < numeric_rhs
        if op == "<=":
            return numeric_lhs <= numeric_rhs
        if op == ">":
            return numeric_lhs > numeric_rhs
        if op == ">=":
            return numeric_lhs >= numeric_rhs
    if op == "<":
        raise AssertionError("ordered comparison branch must return before this point")
    if op == "<=":
        raise AssertionError("ordered comparison branch must return before this point")
    if op == ">":
        raise AssertionError("ordered comparison branch must return before this point")
    if op == ">=":
        raise AssertionError("ordered comparison branch must return before this point")
    if op == "==":
        return lhs == rhs
    raise ValueError(f"unsupported comparison operator {op!r}")


def require_ssw_constraints_satisfied(
    *,
    rules: tuple[SswConstraintRule, ...],
    coils: tuple[SswConstraintCoil, ...],
) -> None:
    for rule in rules:
        if not rule.enabled:
            continue
        context = f"constraints.rules[{rule.id}]"
        lhs_value = _operand_value(coils, rule.lhs, context=f"{context}.lhs")
        rhs_value = _operand_value(coils, rule.rhs, context=f"{context}.rhs")
        if not _evaluate_comparison(lhs_value, rule.op, rhs_value):
            raise ValueError(
                f"constraint {rule.id!r} failed: {rule.message} "
                f"(lhs={lhs_value!r}, op={rule.op!r}, rhs={rhs_value!r})"
            )


__all__ = [
    "SswConstraintCoil",
    "SswConstraintComparisonOperator",
    "SswConstraintComparableRef",
    "SswConstraintFuncRef",
    "SswConstraintOperandRef",
    "SswConstraintPathRef",
    "SswConstraintRule",
    "SswConstraintValueRef",
    "parse_ssw_constraint_rules",
    "require_ssw_constraints_satisfied",
]
