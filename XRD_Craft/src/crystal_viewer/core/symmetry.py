from __future__ import annotations

import ast
import operator
from dataclasses import dataclass
from fractions import Fraction

import numpy as np

from crystal_viewer.core.model import AtomSite

_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


@dataclass(frozen=True, slots=True)
class AffineSymmetry:
    rotation: np.ndarray
    translation: np.ndarray


def _linear_expression(node: ast.AST) -> tuple[tuple[Fraction, Fraction, Fraction], Fraction]:
    if isinstance(node, ast.Expression):
        return _linear_expression(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return (Fraction(0), Fraction(0), Fraction(0)), Fraction(str(node.value))
    if isinstance(node, ast.Name) and node.id in {"x", "y", "z"}:
        coefficients = [Fraction(0), Fraction(0), Fraction(0)]
        coefficients[("x", "y", "z").index(node.id)] = Fraction(1)
        return tuple(coefficients), Fraction(0)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        coefficients, constant = _linear_expression(node.operand)
        sign = Fraction(1) if isinstance(node.op, ast.UAdd) else Fraction(-1)
        return tuple(sign * value for value in coefficients), sign * constant
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
        left_coefficients, left_constant = _linear_expression(node.left)
        right_coefficients, right_constant = _linear_expression(node.right)
        sign = Fraction(1) if isinstance(node.op, ast.Add) else Fraction(-1)
        return (
            tuple(
                left + sign * right
                for left, right in zip(left_coefficients, right_coefficients, strict=True)
            ),
            left_constant + sign * right_constant,
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        left_coefficients, left_constant = _linear_expression(node.left)
        right_coefficients, right_constant = _linear_expression(node.right)
        if any(left_coefficients) and any(right_coefficients):
            raise ValueError("Symmetry operation is not affine.")
        if any(left_coefficients):
            return tuple(value * right_constant for value in left_coefficients), left_constant * right_constant
        if any(right_coefficients):
            return tuple(value * left_constant for value in right_coefficients), right_constant * left_constant
        return (Fraction(0), Fraction(0), Fraction(0)), left_constant * right_constant
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        numerator_coefficients, numerator_constant = _linear_expression(node.left)
        denominator_coefficients, denominator_constant = _linear_expression(node.right)
        if any(denominator_coefficients) or denominator_constant == 0:
            raise ValueError("Symmetry-operation divisor must be a nonzero constant.")
        return (
            tuple(value / denominator_constant for value in numerator_coefficients),
            numerator_constant / denominator_constant,
        )
    raise ValueError("Unsupported expression in symmetry operation.")


def parse_affine_operation(operation: str) -> AffineSymmetry:
    parts = operation.strip().strip("'\"").lower().replace("−", "-").split(",")
    if len(parts) != 3:
        raise ValueError(f"Invalid symmetry operation: {operation}")
    rows: list[tuple[Fraction, Fraction, Fraction]] = []
    translations: list[Fraction] = []
    for expression in parts:
        coefficients, constant = _linear_expression(ast.parse(expression.strip(), mode="eval"))
        if any(value.denominator != 1 for value in coefficients):
            raise ValueError("Symmetry rotation must have integral coefficients.")
        rows.append(coefficients)
        translations.append(constant % 1)
    rotation = np.asarray([[int(value) for value in row] for row in rows], dtype=int)
    determinant = float(np.linalg.det(rotation))
    if not np.isclose(abs(determinant), 1.0):
        raise ValueError("Symmetry rotation must be unimodular.")
    translation = np.asarray([float(value) for value in translations], dtype=float)
    rotation.setflags(write=False)
    translation.setflags(write=False)
    return AffineSymmetry(rotation, translation)


def _evaluate(node: ast.AST, variables: dict[str, float]) -> float:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body, variables)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.Name) and node.id in variables:
        return variables[node.id]
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        return _BINARY[type(node.op)](_evaluate(node.left, variables), _evaluate(node.right, variables))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_evaluate(node.operand, variables))
    raise ValueError("Unsupported expression in symmetry operation.")


def apply_operation(operation: str, fractional: tuple[float, float, float]) -> tuple[float, float, float]:
    parts = operation.strip().strip("'\"").lower().replace("−", "-").split(",")
    if len(parts) != 3:
        raise ValueError(f"Invalid symmetry operation: {operation}")
    variables = dict(zip(("x", "y", "z"), map(float, fractional), strict=True))
    result = []
    for expression in parts:
        parsed = ast.parse(expression.strip(), mode="eval")
        value = _evaluate(parsed, variables) % 1.0
        result.append(0.0 if np.isclose(value, 0.0) or np.isclose(value, 1.0) else float(value))
    return tuple(result)


def expand_sites(
    sites: list[AtomSite],
    operations: list[str],
    tolerance_decimals: int = 6,
) -> list[AtomSite]:
    expanded: list[AtomSite] = []
    seen: set[tuple[str, float, float, float]] = set()
    for site in sites:
        # Refined coordinates on a special position are commonly rounded in
        # CIFs (for example 0.16667 instead of exactly 1/6).  Two symmetry
        # operations can therefore produce positions a few 1e-5 apart.  They
        # are the same crystallographic site, not two atoms.  Keep this check
        # local to the asymmetric site so genuinely distinct input rows are
        # never collapsed merely because they are close.
        equivalent_positions: list[np.ndarray] = []
        for index, operation in enumerate(operations or ["x,y,z"], start=1):
            fractional = apply_operation(operation, site.fractional)
            position = np.asarray(fractional, dtype=float)
            if any(
                np.max(
                    np.abs(
                        (position - previous)
                        - np.rint(position - previous)
                    )
                )
                <= 1e-4
                for previous in equivalent_positions
            ):
                continue
            key = (site.element, *(round(value, tolerance_decimals) for value in fractional))
            if key in seen:
                continue
            seen.add(key)
            equivalent_positions.append(position)
            expanded.append(
                AtomSite(
                    label=site.label if index == 1 else f"{site.label}·{index}",
                    element=site.element,
                    fractional=fractional,
                    occupancy=site.occupancy,
                    u_iso=site.u_iso,
                    reported=site.reported,
                    components=site.components,
                    disorder_group=site.disorder_group,
                    assembly=site.assembly,
                    source_site_key=site.source_site_key,
                )
            )
    return expanded
