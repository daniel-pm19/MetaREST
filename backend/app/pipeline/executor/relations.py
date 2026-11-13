"""Evaluation of the closed relation catalog (see docs/MR_SCHEMA.md §4).

``S`` is the source selection and ``F[i]`` the selection of follow-up ``i``.
Elements are canonicalized as sorted-key JSON so whole objects can be compared.
Messages are shown to the QA Auditor, so they are in Spanish.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from typing import Any

from app.models.mr import Direction, Measure, RelationSpec, RelationType

MAX_LISTED = 5


class RelationEvaluationError(ValueError):
    """The selections cannot be evaluated under this relation (e.g. measure=value on a list)."""


@dataclass(frozen=True)
class RelationCheck:
    holds: bool
    message: str


def canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _canon_list(values: list[Any]) -> list[str]:
    return [canon(v) for v in values]


def _show(items: Any) -> str:
    items = sorted(items)
    shown = ", ".join(items[:MAX_LISTED])
    return f"[{shown}{', …' if len(items) > MAX_LISTED else ''}] ({len(items)})"


def _label(i: int) -> str:
    return f"follow-up {i + 1}"


def evaluate(relation: RelationSpec, source: list[Any], followups: list[list[Any]]) -> RelationCheck:
    if not followups:
        raise RelationEvaluationError("no hay follow-ups para evaluar")
    s = _canon_list(source)
    fs = [_canon_list(f) for f in followups]
    match relation.type:
        case RelationType.EQUALITY:
            return _each(fs, lambda f, i: (f == s, f"{_label(i)} difiere de la fuente (orden o elementos)"))
        case RelationType.EQUIVALENCE:
            return _each(fs, lambda f, i: _equivalent(s, f, i))
        case RelationType.SUBSET:
            return _each(fs, lambda f, i: _subset(s, f, i, relation.direction))
        case RelationType.DISJOINT:
            return _disjoint([s, *fs])
        case RelationType.COMPLETE:
            union = set().union(*map(set, fs))
            missing, extra = set(s) - union, union - set(s)
            if missing or extra:
                return RelationCheck(
                    False,
                    "la unión de los follow-ups no coincide con la fuente; "
                    f"faltan {_show(missing)}, sobran {_show(extra)}",
                )
            return RelationCheck(True, "la unión de los follow-ups coincide con la fuente")
        case RelationType.DIFFERENCE:
            if len(fs) != 2:
                raise RelationEvaluationError("'difference' requiere exactamente 2 follow-ups")
            diff, expected = set(s) - set(fs[0]), set(fs[1])
            if diff != expected:
                return RelationCheck(
                    False,
                    f"fuente \\ follow-up 1 = {_show(diff)} pero follow-up 2 = {_show(expected)}",
                )
            return RelationCheck(True, "fuente \\ follow-up 1 coincide con follow-up 2")
        case RelationType.COUNT_LEQ:
            return _count_leq(relation, source, followups)
        case RelationType.SAME_ORDER:
            return _each(fs, lambda f, i: _same_order(s, f, i))
    raise RelationEvaluationError(f"relación no soportada: {relation.type}")  # pragma: no cover


def _each(fs: list[list[str]], check) -> RelationCheck:
    for i, f in enumerate(fs):
        ok, msg = check(f, i)
        if not ok:
            return RelationCheck(False, msg)
    return RelationCheck(True, "la relación se cumple para todos los follow-ups")


def _equivalent(s: list[str], f: list[str], i: int) -> tuple[bool, str]:
    cs, cf = Counter(s), Counter(f)
    if cs == cf:
        return True, ""
    missing, extra = cs - cf, cf - cs
    return False, f"{_label(i)} no es equivalente: faltan {_show(missing.elements())}, sobran {_show(extra.elements())}"


def _subset(s: list[str], f: list[str], i: int, direction: Direction | None) -> tuple[bool, str]:
    if direction is Direction.SOURCE_IN_FOLLOWUP:
        outside = set(s) - set(f)
        return not outside, f"elementos de la fuente ausentes en {_label(i)}: {_show(outside)}"
    outside = set(f) - set(s)
    return not outside, f"elementos de {_label(i)} ausentes en la fuente: {_show(outside)}"


def _disjoint(groups: list[list[str]]) -> RelationCheck:
    names = ["fuente", *(_label(i) for i in range(len(groups) - 1))]
    sets = [set(g) for g in groups]
    for a in range(len(sets)):
        for b in range(a + 1, len(sets)):
            common = sets[a] & sets[b]
            if common:
                return RelationCheck(False, f"{names[a]} y {names[b]} comparten {_show(common)}")
    return RelationCheck(True, "todas las selecciones son disjuntas")


def _measure(values: list[Any], measure: Measure, who: str) -> float:
    if measure is Measure.COUNT:
        return len(values)
    if len(values) != 1 or isinstance(values[0], bool) or not isinstance(values[0], int | float):
        raise RelationEvaluationError(f"measure=value requiere un único número en {who}, se obtuvo {values!r:.200}")
    return values[0]


def _count_leq(relation: RelationSpec, source: list[Any], followups: list[list[Any]]) -> RelationCheck:
    ms = _measure(source, relation.measure, "la fuente")
    for i, f in enumerate(followups):
        mf = _measure(f, relation.measure, _label(i))
        if relation.direction is Direction.SOURCE_IN_FOLLOWUP:
            ok, msg = ms <= mf, f"fuente ({ms:g}) > {_label(i)} ({mf:g})"
        else:
            ok, msg = mf <= ms, f"{_label(i)} ({mf:g}) > fuente ({ms:g})"
        if not ok:
            return RelationCheck(False, msg)
    return RelationCheck(True, "la medida se cumple para todos los follow-ups")


def _same_order(s: list[str], f: list[str], i: int) -> tuple[bool, str]:
    common = set(s) & set(f)
    seq_s = list(dict.fromkeys(x for x in s if x in common))
    seq_f = list(dict.fromkeys(x for x in f if x in common))
    if seq_s == seq_f:
        return True, ""
    pos = next(k for k, (a, b) in enumerate(zip(seq_s, seq_f, strict=True)) if a != b)
    return False, f"{_label(i)} cambia el orden relativo: posición {pos} es {seq_f[pos]} en vez de {seq_s[pos]}"
