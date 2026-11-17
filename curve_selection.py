"""Shared groom-curve selection helpers."""

from __future__ import annotations

import math


def select_group_curves(
    curves: list[dict],
    guide_limit: int,
    guide_label: str = "guide",
) -> list[int]:
    """Select a balanced subset of source curves while retaining every group."""
    if not curves:
        raise ValueError("The JSON contains no curves to import.")
    if isinstance(guide_limit, bool) or not isinstance(guide_limit, int):
        raise ValueError(f"The {guide_label} limit must be an integer.")
    if guide_limit < 1:
        raise ValueError(f"The {guide_label} limit must be at least 1.")

    groups: dict[int, list[int]] = {}
    for index, curve in enumerate(curves):
        group = curve["group"]
        if isinstance(group, bool) or not isinstance(group, int):
            raise ValueError(f"Curve {index} has an invalid group index.")
        groups.setdefault(group, []).append(index)

    limit = min(guide_limit, len(curves))
    if limit < len(groups):
        raise ValueError(
            f"The {guide_label} limit must be at least the number of "
            f"groom groups ({len(groups)})."
        )

    quotas = {group: 1 for group in groups}
    remaining = limit - len(groups)
    while remaining:
        capacities = {
            group: len(indices) - quotas[group]
            for group, indices in groups.items()
            if quotas[group] < len(indices)
        }
        total_capacity = sum(capacities.values())
        if not total_capacity:
            break

        allocated = 0
        remainders = []
        for group, capacity in capacities.items():
            share, remainder = divmod(remaining * capacity, total_capacity)
            share = min(share, capacity)
            quotas[group] += share
            allocated += share
            if quotas[group] < len(groups[group]):
                remainders.append((remainder, group))
        remaining -= allocated

        if remaining:
            for _, group in sorted(remainders, reverse=True):
                if remaining == 0:
                    break
                if quotas[group] < len(groups[group]):
                    quotas[group] += 1
                    remaining -= 1

    selected = []
    for group, indices in groups.items():
        quota = quotas[group]
        for sample_index in range(quota):
            source_index = int(
                math.floor((sample_index + 0.5) * len(indices) / quota)
            )
            selected.append(indices[source_index])
    return sorted(selected)
