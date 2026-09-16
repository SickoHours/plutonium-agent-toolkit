"""``parameters``: what a composition may configure on a member, and what it may not.

A service module's behaviour is often chosen by the pack that uses it: a rotation cadence, a
box-pool flag. Without a declared field that choice lives in GSC, where a composition cannot be
checked against it and a reviewer cannot see it. So a module declares its parameters in
``module.json`` (name, type, an optional ``values`` or ``range``, a default and a meaning), a
composition sets them per member, and the plan resolves the two into one effective map.

Three rules carry the whole contract: a declaration's own default satisfies its own constraint,
a composition may set only declared names, and every value it sets satisfies that name's type
and constraint. The first is a declaration error (``pat module inspect`` refuses it, like any
other declaration defect); the last two are plan refusals of kind ``parameters``.

Nothing here reaches the package. No consumer reads a parameter yet: the plan row and the build
receipt record which configuration a build is, and the bytes are unchanged. Format:
``docs/MODULES.md``.
"""
from __future__ import annotations

import re

from ..core.errors import INPUT_INVALID, Failure

NAME = re.compile(r"^[a-z0-9_]{1,32}\Z")
TYPES = ("bool", "int", "string")
ARTICLE = {"bool": "a bool", "int": "an int", "string": "a string"}
MAX_PARAMETERS = 32
MAX_VALUES = 32
MAX_MEANING = 400
# A parameter value travels into the plan row and the build receipt, so a string is bounded
# there rather than at the declaration's whole-file limit.
MAX_VALUE_TEXT = 120
FIELDS = ("name", "type", "default", "meaning", "values", "range")
REQUIRED = ("name", "type", "default", "meaning")


def is_typed(type_name: str, value) -> bool:
    """Whether ``value`` is of the declared type. ``True`` is not an int here and ``1`` is not a
    bool: JSON tells the two apart and so does this contract."""
    if type_name == "bool":
        return isinstance(value, bool)
    if type_name == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, str) and len(value) <= MAX_VALUE_TEXT


def violation(declared: dict, value) -> str | None:
    """Why ``value`` does not satisfy this declared parameter, worded to follow the name, or
    ``None`` when it does."""
    type_name = declared["type"]
    if not is_typed(type_name, value):
        if type_name == "string" and isinstance(value, str):
            return f"is a string longer than {MAX_VALUE_TEXT} characters"
        return f"is not {ARTICLE[type_name]}"
    if declared.get("values") is not None and value not in declared["values"]:
        return f"is not one of the declared values {declared['values']}"
    if declared.get("range") is not None and not declared["range"][0] <= value <= declared["range"][1]:
        return f"is outside the declared range [{declared['range'][0]}, {declared['range'][1]}]"
    return None


def validate_declared(value, mid: str, field: str = "/parameters") -> list[dict] | None:
    """The ``parameters`` field of ``module.json``: the parameters a composition may set on this
    module. Absent is not an error and adds nothing. Echoed normalized, with ``values`` and
    ``range`` ``null`` where the declaration names neither."""
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > MAX_PARAMETERS:
        raise Failure(INPUT_INVALID, f"{mid}: parameters is a list of at most {MAX_PARAMETERS} declared parameters", field=field)
    rows: list[dict] = []
    seen: set[str] = set()
    for index, row in enumerate(value):
        at = f"{field}/{index}"
        if not isinstance(row, dict):
            raise Failure(INPUT_INVALID, f"{mid}: parameters[{index}] is an object {{name, type, default, meaning}}", field=at)
        unknown = sorted(set(row) - set(FIELDS))
        if unknown:
            raise Failure(INPUT_INVALID, f"{mid}: parameters[{index}] has unknown fields {unknown}", field=f"{at}/{unknown[0]}")
        missing = [key for key in REQUIRED if key not in row]
        if missing:
            raise Failure(INPUT_INVALID, f"{mid}: parameters[{index}] is missing {missing}",
                          "A declared parameter names itself, its type, its default and what it means; values or range are optional.",
                          field=f"{at}/{missing[0]}")
        name = row["name"]
        if not isinstance(name, str) or not NAME.fullmatch(name):
            raise Failure(INPUT_INVALID, f"{mid}: parameters[{index}].name is lowercase letters, digits and underscore, at most 32", field=f"{at}/name")
        if name in seen:
            raise Failure(INPUT_INVALID, f"{mid}: parameters declares {name!r} twice; a parameter name is unique within the module",
                          "Two rows for one name leave the default and the meaning ambiguous; keep one row.", field=f"{at}/name")
        seen.add(name)
        type_name = row["type"]
        if type_name not in TYPES:
            raise Failure(INPUT_INVALID, f"{mid}: parameters[{index}].type is one of {list(TYPES)}", field=f"{at}/type")
        # A normalized echo carries both keys with one of them null, and must re-validate: the
        # rule is about two constraints, not two keys.
        if row.get("values") is not None and row.get("range") is not None:
            raise Failure(INPUT_INVALID, f"{mid}: parameters[{index}] names values or range, never both", field=f"{at}/range")
        values = row.get("values")
        if values is not None:
            if type_name == "bool":
                raise Failure(INPUT_INVALID, f"{mid}: parameters[{index}].values narrows an int or a string; a bool already has its two values",
                              "Drop values; true and false are the whole set.", field=f"{at}/values")
            if not isinstance(values, list) or not 1 <= len(values) <= MAX_VALUES:
                raise Failure(INPUT_INVALID, f"{mid}: parameters[{index}].values is a list of 1 to {MAX_VALUES} allowed values", field=f"{at}/values")
            for position, allowed in enumerate(values):
                if not is_typed(type_name, allowed):
                    raise Failure(INPUT_INVALID, f"{mid}: parameters[{index}].values[{position}] is not {ARTICLE[type_name]}", field=f"{at}/values/{position}")
            if len(values) != len(set(values)):
                raise Failure(INPUT_INVALID, f"{mid}: parameters[{index}].values repeats a value", field=f"{at}/values")
        bounds = row.get("range")
        if bounds is not None:
            if type_name != "int":
                raise Failure(INPUT_INVALID, f"{mid}: parameters[{index}].range belongs to an int parameter; a {type_name} narrows with values",
                              field=f"{at}/range")
            if not isinstance(bounds, list) or len(bounds) != 2 or not all(is_typed("int", b) for b in bounds):
                raise Failure(INPUT_INVALID, f"{mid}: parameters[{index}].range is [min, max], two integers", field=f"{at}/range")
            if bounds[0] > bounds[1]:
                raise Failure(INPUT_INVALID, f"{mid}: parameters[{index}].range is [min, max] with min at most max: {bounds}", field=f"{at}/range")
        meaning = row["meaning"]
        if not isinstance(meaning, str) or not meaning.strip() or len(meaning) > MAX_MEANING:
            raise Failure(INPUT_INVALID, f"{mid}: parameters[{index}].meaning says what the parameter does, in at most {MAX_MEANING} characters",
                          field=f"{at}/meaning")
        declared = {"name": name, "type": type_name, "default": row["default"], "meaning": meaning,
                    "values": list(values) if values is not None else None,
                    "range": [bounds[0], bounds[1]] if bounds is not None else None}
        bad = violation(declared, row["default"])
        if bad:
            raise Failure(INPUT_INVALID, f"{mid}: parameters[{index}] default {row['default']!r} {bad}",
                          "A declaration's own default is the value every composition that sets nothing gets; it satisfies the same constraint.",
                          field=f"{at}/default")
        rows.append(declared)
    return rows


def validate_setting(value, where: str, field: str) -> dict:
    """The optional ``parameters`` map on a composition member: ``{name: value}``. Lexical only.
    Whether a name is declared and a value fits its constraint needs the member's module, and is
    a plan refusal of kind ``parameters`` (``compositions.resolve``)."""
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > MAX_PARAMETERS:
        raise Failure(INPUT_INVALID, f"{where}: parameters maps at most {MAX_PARAMETERS} declared parameter names to values", field=field)
    out: dict = {}
    for name, setting in value.items():
        if not isinstance(name, str) or not NAME.fullmatch(name):
            raise Failure(INPUT_INVALID, f"{where}: a parameters name is lowercase letters, digits and underscore, at most 32: {name!r}", field=field)
        if not (is_typed("bool", setting) or is_typed("int", setting) or is_typed("string", setting)):
            raise Failure(INPUT_INVALID, f"{where}: parameters[{name}] is a bool, an int or a string of at most {MAX_VALUE_TEXT} characters",
                          field=f"{field}/{name}")
        out[name] = setting
    return out


def effective(declared: list[dict] | None, settings: dict | None) -> tuple[dict, list[tuple[str, str]]]:
    """The configuration one member is planned and built with: every declared default, then what
    the composition set over it. Returns the map and the problems, each ``(name, message)``
    naming the parameter and the rule it broke; a member with a problem has no configuration and
    the plan refuses."""
    rows = declared or []
    by_name = {row["name"]: row for row in rows}
    values = {row["name"]: row["default"] for row in rows}
    problems: list[tuple[str, str]] = []
    for name, setting in (settings or {}).items():
        row = by_name.get(name)
        if row is None:
            declares = f"it declares {sorted(by_name)}" if by_name else "it declares no parameters"
            problems.append((name, f"is not declared by the module ({declares})"))
            continue
        bad = violation(row, setting)
        if bad:
            problems.append((name, f"{setting!r} {bad}"))
            continue
        values[name] = setting
    return values, problems
