"""Grader: spatial correctness for nearest-asset queries."""

from __future__ import annotations

from .base import GradeResult


def grade_spatial(
    mock_output: dict,
    max_distance_m: int | None = None,
    min_assets: int | None = None,
    allowed_types: list[str] | None = None,
    distances_monotonic: bool = False,
) -> GradeResult:
    """Check spatial properties of the mock tool output.

    Validates that returned assets satisfy radius, type-filtering,
    and distance-ordering constraints.

    Args:
        mock_output: The full mock output dict (with "data" key).
        max_distance_m: All assets must be within this distance.
        min_assets: At least this many assets must be returned.
        allowed_types: Only these asset_types may appear.
        distances_monotonic: Distances must be non-decreasing.
    """
    data = mock_output.get("data", {})
    assets = data.get("assets", [])
    failures: list[str] = []

    if min_assets is not None and len(assets) < min_assets:
        failures.append(
            f"expected at least {min_assets} assets, got {len(assets)}"
        )

    if max_distance_m is not None:
        for a in assets:
            dist = a.get("distance_m", 0)
            if dist > max_distance_m:
                failures.append(
                    f"asset '{a.get('name', '?')}' at {dist}m exceeds "
                    f"max radius {max_distance_m}m"
                )

    if allowed_types is not None:
        for a in assets:
            atype = a.get("asset_type", "")
            if atype not in allowed_types:
                failures.append(
                    f"asset '{a.get('name', '?')}' has type '{atype}', "
                    f"allowed: {allowed_types}"
                )

    if distances_monotonic and len(assets) > 1:
        dists = [a.get("distance_m", 0) for a in assets]
        for i in range(1, len(dists)):
            if dists[i] < dists[i - 1]:
                failures.append(
                    f"distance not monotonic: asset {i-1} at {dists[i-1]}m "
                    f"> asset {i} at {dists[i]}m"
                )
                break

    passed = len(failures) == 0
    return GradeResult(
        grader="spatial",
        passed=passed,
        detail="; ".join(failures) if failures else "spatial checks passed",
        expected={
            "max_distance_m": max_distance_m,
            "min_assets": min_assets,
            "allowed_types": allowed_types,
            "distances_monotonic": distances_monotonic,
        },
    )
