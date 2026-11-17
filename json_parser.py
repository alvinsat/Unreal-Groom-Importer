"""
JSON parser for Unreal Groom Importer.

Reads the JSON metadata exported from Unreal Engine and returns the
curve information required to build Blender Hair Curves.
"""

from __future__ import annotations

import math
from pathlib import Path
import json


def read_json(filepath: str | Path) -> list[dict]:
    """
    Read Unreal Groom JSON metadata.

    Parameters
    ----------
    filepath
        Path to the JSON file.

    Returns
    -------
    list[dict]

        List of curve dictionaries.

        Example:

        [
            {
                "first": 0,
                "count": 51,
                "group": 0,
                "uv": [0.70, 0.88],
            },
            ...
        ]
    """

    filepath = Path(filepath)

    if not filepath.exists():
        raise FileNotFoundError(filepath)

    with filepath.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if "curves" not in data:
        raise ValueError("JSON does not contain a 'curves' array.")

    curves = data["curves"]

    if not isinstance(curves, list):
        raise ValueError("'curves' must be a list.")

    return curves


def json_from_obj(obj_filepath: str | Path) -> Path:
    """
    Return the JSON path corresponding to an OBJ file.

    Example
    -------
        Hair.obj
            ->
        Hair.json
    """

    return Path(obj_filepath).with_suffix(".json")


def curve_count(curves: list[dict]) -> int:
    """
    Return the number of curves.
    """

    return len(curves)


def point_count(curves: list[dict]) -> int:
    """
    Return the total number of points.
    """

    return sum(curve["count"] for curve in curves)


def curve_point_starts(
    curves: list[dict],
    total_points: int,
) -> list[int]:
    """Resolve each curve's point start for global or per-group OBJ offsets."""
    if not curves:
        raise ValueError("JSON does not contain any curves.")
    if isinstance(total_points, bool) or not isinstance(total_points, int):
        raise ValueError("OBJ point count must be an integer.")
    if total_points < 0:
        raise ValueError("OBJ point count cannot be negative.")

    groups: dict[int, list[tuple[int, int, int]]] = {}
    group_order = []
    for curve_index, curve in enumerate(curves):
        first = curve["first"]
        count = curve["count"]
        group = curve["group"]
        if (
            isinstance(first, bool)
            or not isinstance(first, int)
            or first < 0
        ):
            raise ValueError(f"Curve {curve_index} has an invalid first point.")
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or count < 1
        ):
            raise ValueError(f"Curve {curve_index} has an invalid point count.")
        if isinstance(group, bool) or not isinstance(group, int):
            raise ValueError(f"Curve {curve_index} has an invalid group index.")

        if group not in groups:
            groups[group] = []
            group_order.append(group)
        groups[group].append((first, first + count, curve_index))

    def is_contiguous_partition(ranges, expected_end):
        cursor = 0
        for start, end, _ in sorted(ranges):
            if start != cursor:
                return False
            cursor = end
        return cursor == expected_end

    global_ranges = [
        (curve["first"], curve["first"] + curve["count"], index)
        for index, curve in enumerate(curves)
    ]
    if (
        point_count(curves) == total_points
        and is_contiguous_partition(global_ranges, total_points)
    ):
        return [curve["first"] for curve in curves]

    group_spans = {
        group: max(end for _, end, _ in ranges)
        for group, ranges in groups.items()
    }
    for group, ranges in groups.items():
        if not is_contiguous_partition(ranges, group_spans[group]):
            raise ValueError(
                f"Curve point ranges in group {group} are not a contiguous "
                "non-overlapping range starting at zero."
            )

    if sum(group_spans.values()) != total_points:
        raise ValueError(
            "Curve point ranges do not account for all OBJ vertices."
        )

    group_bases = {}
    point_base = 0
    for group in group_order:
        group_bases[group] = point_base
        point_base += group_spans[group]

    return [
        group_bases[curve["group"]] + curve["first"]
        for curve in curves
    ]


def curve_point_attribute(
    curves: list[dict],
    total_points: int,
    attribute_name: str,
) -> list | None:
    """Flatten an optional per-curve point attribute into OBJ point order."""
    has_attribute = [attribute_name in curve for curve in curves]
    if not any(has_attribute):
        return None
    if not all(has_attribute):
        raise ValueError(
            f"Curve metadata has inconsistent '{attribute_name}' data."
        )

    starts = curve_point_starts(curves, total_points)
    if attribute_name == "radius":
        values = [0.0] * total_points
        for curve, start in zip(curves, starts):
            curve_values = curve[attribute_name]
            values[start:start + curve["count"]] = curve_values
        return values

    if attribute_name == "color":
        values = [(0.0, 0.0, 0.0)] * total_points
        for curve, start in zip(curves, starts):
            curve_values = curve[attribute_name]
            values[start:start + curve["count"]] = [
                tuple(color) for color in curve_values
            ]
        return values

    raise ValueError(f"Unsupported point attribute '{attribute_name}'.")


def validate(curves: list[dict]) -> None:
    """
    Validate curve metadata.

    Raises
    ------
    ValueError
        If the JSON format is invalid.
    """

    required = {
        "first",
        "count",
        "group",
        "uv",
    }

    for index, curve in enumerate(curves):

        missing = required - curve.keys()

        if missing:
            raise ValueError(
                f"Curve {index} is missing keys: "
                f"{', '.join(sorted(missing))}"
            )

        if (
            not isinstance(curve["uv"], (list, tuple))
            or len(curve["uv"]) != 2
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in curve["uv"]
            )
        ):
            raise ValueError(
                f"Curve {index} has an invalid UV."
            )

        count = curve["count"]
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ValueError(f"Curve {index} has an invalid point count.")

        if "radius" in curve:
            radii = curve["radius"]
            if (
                not isinstance(radii, list)
                or len(radii) != count
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    for value in radii
                )
            ):
                raise ValueError(
                    f"Curve {index} has invalid per-point radii."
                )

        if "color" in curve:
            colors = curve["color"]
            if (
                not isinstance(colors, list)
                or len(colors) != count
                or any(
                    not isinstance(color, (list, tuple))
                    or len(color) != 3
                    or any(
                        isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or not math.isfinite(value)
                        or value < 0.0
                        for value in color
                    )
                    for color in colors
                )
            ):
                raise ValueError(
                    f"Curve {index} has invalid per-point colors."
                )

    for attribute_name in ("radius", "color"):
        has_attribute = [attribute_name in curve for curve in curves]
        if any(has_attribute) and not all(has_attribute):
            raise ValueError(
                f"Curve metadata has inconsistent '{attribute_name}' data."
            )