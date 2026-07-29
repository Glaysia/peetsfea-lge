from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict, cast

LgeEvddConstraintComparisonOperator = Literal["<", "<=", ">", ">=", "=="]
LgeEvddConstraintValue = int | float | str


class LgeEvddConstraintPathRef(TypedDict):
    path: str


class LgeEvddConstraintValueRef(TypedDict):
    value: str | float


class LgeEvddConstraintFuncRef(TypedDict):
    func: str


LgeEvddConstraintComparableRef = LgeEvddConstraintPathRef | LgeEvddConstraintFuncRef
LgeEvddConstraintOperandRef = (
    LgeEvddConstraintPathRef | LgeEvddConstraintValueRef | LgeEvddConstraintFuncRef
)


@dataclass(frozen=True)
class LgeEvddConstraintRule:
    id: str
    message: str
    enabled: bool
    lhs: LgeEvddConstraintComparableRef
    op: LgeEvddConstraintComparisonOperator
    rhs: LgeEvddConstraintOperandRef


@dataclass(frozen=True)
class LgeEvddConstraintContext:
    primary_object_id: str
    secondary_object_id: str
    path_values: dict[str, LgeEvddConstraintValue]


@dataclass(frozen=True)
class _ConstraintFunctionCall:
    name: str
    args: tuple[str, ...]


_SUPPORTED_FUNCTIONS = frozenset(
    {
        "primary_planar_radial_build_x",
        "primary_planar_radial_build_y",
        "secondary_planar_bbox_size_x",
        "secondary_planar_bbox_size_y",
        "secondary_planar_radial_build_x",
        "secondary_planar_radial_build_y",
    }
)


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
    if name not in _SUPPORTED_FUNCTIONS:
        raise ValueError(
            f"{context}.func must be one of {sorted(_SUPPORTED_FUNCTIONS)} "
            f"(actual={name!r})"
        )
    body = text[open_index + 1 : -1].strip()
    if body == "":
        raise ValueError(f"{context}.func must contain one argument")
    args = _split_constraint_func_args(body, context=f"{context}.func")
    if len(args) != 1:
        raise ValueError(f"{context}.func {name}() must contain exactly one argument")
    return _ConstraintFunctionCall(name=name, args=args)


def _parse_constraint_func(value: object, *, context: str) -> str:
    table = _require_table(value, context)
    if set(table.keys()) != {"func"}:
        raise ValueError(f"{context} must contain only ['func']")
    raw_func = _require_non_empty_str(table, "func", context)
    _parse_constraint_func_call(raw_func, context=context)
    return raw_func


def _parse_comparable_ref(value: object, *, context: str) -> LgeEvddConstraintComparableRef:
    if not isinstance(value, dict):
        raise TypeError(f"{context} must be a table")
    if set(value.keys()) == {"path"}:
        return LgeEvddConstraintPathRef(path=_require_constraint_path(value, context=context))
    if set(value.keys()) == {"func"}:
        return LgeEvddConstraintFuncRef(func=_parse_constraint_func(value, context=context))
    raise ValueError(f"{context} must contain exactly one of ['path'], ['func']")


def _parse_operand_ref(value: object, *, context: str) -> LgeEvddConstraintOperandRef:
    if not isinstance(value, dict):
        raise TypeError(f"{context} must be a table")
    if set(value.keys()) == {"path"}:
        return LgeEvddConstraintPathRef(path=_require_constraint_path(value, context=context))
    if set(value.keys()) == {"value"}:
        return LgeEvddConstraintValueRef(value=_require_constraint_value(value, context=context))
    if set(value.keys()) == {"func"}:
        return LgeEvddConstraintFuncRef(func=_parse_constraint_func(value, context=context))
    raise ValueError(f"{context} must contain exactly one of ['path'], ['value'], ['func']")


def _parse_constraint_rule(
    raw_rule: object,
    *,
    index: int,
    context: str,
) -> LgeEvddConstraintRule:
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
    return LgeEvddConstraintRule(
        id=_require_non_empty_str(table, "id", dotted),
        message=_require_non_empty_str(table, "message", dotted),
        enabled=_require_bool(table, "enabled", dotted),
        lhs=_parse_comparable_ref(_require_key(table, "lhs", dotted), context=f"{dotted}.lhs"),
        op=cast(LgeEvddConstraintComparisonOperator, raw_op),
        rhs=_parse_operand_ref(_require_key(table, "rhs", dotted), context=f"{dotted}.rhs"),
    )


def parse_lgevdd_constraint_rules(
    root: dict[str, object],
    *,
    context: str,
) -> tuple[LgeEvddConstraintRule, ...]:
    constraints = _require_table(_require_key(root, "constraints", context), f"{context}.constraints")
    raw_rules = _require_key(constraints, "rules", f"{context}.constraints")
    if isinstance(raw_rules, (str, bytes)) or not isinstance(raw_rules, list):
        raise TypeError(f"{context}.constraints.rules must be a list")
    if len(raw_rules) == 0:
        raise ValueError(f"{context}.constraints.rules must be non-empty")
    seen_ids: set[str] = set()
    parsed_rules: list[LgeEvddConstraintRule] = []
    for index, raw_rule in enumerate(raw_rules):
        parsed = _parse_constraint_rule(raw_rule, index=index, context=context)
        if parsed.id in seen_ids:
            raise ValueError(f"{context}.constraints.rules contains duplicate id {parsed.id!r}")
        seen_ids.add(parsed.id)
        parsed_rules.append(parsed)
    return tuple(parsed_rules)


def _path_value(
    constraint_context: LgeEvddConstraintContext,
    path: str,
    *,
    context: str,
) -> LgeEvddConstraintValue:
    if path not in constraint_context.path_values:
        raise ValueError(f"{context} references unsupported LGE_EVDD path {path!r}")
    return constraint_context.path_values[path]


def _numeric_path_value(
    constraint_context: LgeEvddConstraintContext,
    path: str,
    *,
    context: str,
) -> int | float:
    value = _path_value(constraint_context, path, context=context)
    if isinstance(value, str):
        raise TypeError(f"{context} requires numeric path {path!r}")
    return value


def _integer_path_value(
    constraint_context: LgeEvddConstraintContext,
    path: str,
    *,
    context: str,
) -> int:
    value = _path_value(constraint_context, path, context=context)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{context} requires integer path {path!r}")
    return value


def _planar_path(object_id: str, field: str) -> str:
    return f"modeled_objects.{object_id}.{field}"


def _planar_radial_build(
    constraint_context: LgeEvddConstraintContext,
    *,
    object_id: str,
    axis: Literal["x", "y"],
    context: str,
) -> float:
    turns = _integer_path_value(
        constraint_context,
        _planar_path(object_id, "turns"),
        context=context,
    )
    layer_count = _integer_path_value(
        constraint_context,
        _planar_path(object_id, "layer_count"),
        context=context,
    )
    if turns <= 0 or layer_count <= 0:
        raise ValueError(
            f"{context} requires positive turns and layer_count "
            f"(turns={turns}, layer_count={layer_count})"
        )
    loops_on_largest_layer = (turns + layer_count - 1) // layer_count
    clearance = float(
        _numeric_path_value(
            constraint_context,
            _planar_path(object_id, f"inner_clearance_{axis}_mm"),
            context=context,
        )
    )
    trace_width = float(
        _numeric_path_value(
            constraint_context,
            _planar_path(object_id, "trace_width_mm"),
            context=context,
        )
    )
    turn_gap = float(
        _numeric_path_value(
            constraint_context,
            _planar_path(object_id, f"turn_gap_{axis}_mm"),
            context=context,
        )
    )
    return (
        clearance
        + loops_on_largest_layer * trace_width
        + (loops_on_largest_layer - 1) * turn_gap
    )


def _secondary_planar_bbox_size(
    constraint_context: LgeEvddConstraintContext,
    *,
    axis: Literal["x", "y"],
    context: str,
) -> float:
    object_id = constraint_context.secondary_object_id
    radial_build = _planar_radial_build(
        constraint_context,
        object_id=object_id,
        axis=axis,
        context=context,
    )
    keepout_field = (
        "center_keepout_width_x_mm"
        if axis == "x"
        else "center_keepout_height_y_mm"
    )
    keepout_size = float(
        _numeric_path_value(
            constraint_context,
            _planar_path(constraint_context.primary_object_id, keepout_field),
            context=context,
        )
    )
    if axis == "y":
        return keepout_size + 2.0 * radial_build
    lead_extension = float(
        _numeric_path_value(
            constraint_context,
            _planar_path(object_id, "lead_extension_x_mm"),
            context=context,
        )
    )
    return keepout_size + lead_extension + radial_build


def _func_value(
    constraint_context: LgeEvddConstraintContext,
    raw_func: str,
    *,
    context: str,
) -> LgeEvddConstraintValue:
    call = _parse_constraint_func_call(raw_func, context=context)
    expected_object_id = (
        constraint_context.primary_object_id
        if call.name.startswith("primary_")
        else constraint_context.secondary_object_id
    )
    if call.args[0] != expected_object_id:
        raise ValueError(
            f"{context}.func references an unknown object {call.args[0]!r} "
            f"(expected={expected_object_id!r})"
        )
    if call.name == "primary_planar_radial_build_x":
        return _planar_radial_build(
            constraint_context,
            object_id=constraint_context.primary_object_id,
            axis="x",
            context=context,
        )
    if call.name == "primary_planar_radial_build_y":
        return _planar_radial_build(
            constraint_context,
            object_id=constraint_context.primary_object_id,
            axis="y",
            context=context,
        )
    if call.name == "secondary_planar_radial_build_x":
        return _planar_radial_build(
            constraint_context,
            object_id=constraint_context.secondary_object_id,
            axis="x",
            context=context,
        )
    if call.name == "secondary_planar_radial_build_y":
        return _planar_radial_build(
            constraint_context,
            object_id=constraint_context.secondary_object_id,
            axis="y",
            context=context,
        )
    if call.name == "secondary_planar_bbox_size_x":
        return _secondary_planar_bbox_size(
            constraint_context,
            axis="x",
            context=context,
        )
    if call.name == "secondary_planar_bbox_size_y":
        return _secondary_planar_bbox_size(
            constraint_context,
            axis="y",
            context=context,
        )
    raise ValueError(f"{context}.func unsupported function {call.name!r}")


def _operand_value(
    constraint_context: LgeEvddConstraintContext,
    operand: LgeEvddConstraintOperandRef,
    *,
    context: str,
) -> LgeEvddConstraintValue:
    if "path" in operand:
        return _path_value(constraint_context, operand["path"], context=context)
    if "value" in operand:
        return operand["value"]
    assert "func" in operand
    return _func_value(constraint_context, operand["func"], context=context)


def _evaluate_comparison(
    lhs: LgeEvddConstraintValue,
    op: LgeEvddConstraintComparisonOperator,
    rhs: LgeEvddConstraintValue,
) -> bool:
    if op in ("<", "<=", ">", ">="):
        if isinstance(lhs, str) or isinstance(rhs, str):
            raise TypeError(f"comparison operator {op!r} is not supported for string operands")
        if op == "<":
            return lhs < rhs
        if op == "<=":
            return lhs <= rhs
        if op == ">":
            return lhs > rhs
        if op == ">=":
            return lhs >= rhs
    if op in ("<", "<=", ">", ">="):
        raise AssertionError("ordered comparison branch must return before this point")
    if op == "==":
        return lhs == rhs
    raise ValueError(f"unsupported comparison operator {op!r}")


def require_lgevdd_constraints_satisfied(
    *,
    rules: tuple[LgeEvddConstraintRule, ...],
    constraint_context: LgeEvddConstraintContext,
) -> None:
    for rule in rules:
        if not rule.enabled:
            continue
        context = f"constraints.rules[{rule.id}]"
        lhs_value = _operand_value(
            constraint_context,
            rule.lhs,
            context=f"{context}.lhs",
        )
        rhs_value = _operand_value(
            constraint_context,
            rule.rhs,
            context=f"{context}.rhs",
        )
        if not _evaluate_comparison(lhs_value, rule.op, rhs_value):
            raise ValueError(
                f"constraint {rule.id!r} failed: {rule.message} "
                f"(lhs={lhs_value!r}, op={rule.op!r}, rhs={rhs_value!r})"
            )


__all__ = [
    "LgeEvddConstraintComparableRef",
    "LgeEvddConstraintComparisonOperator",
    "LgeEvddConstraintContext",
    "LgeEvddConstraintFuncRef",
    "LgeEvddConstraintOperandRef",
    "LgeEvddConstraintPathRef",
    "LgeEvddConstraintRule",
    "LgeEvddConstraintValueRef",
    "parse_lgevdd_constraint_rules",
    "require_lgevdd_constraints_satisfied",
]
