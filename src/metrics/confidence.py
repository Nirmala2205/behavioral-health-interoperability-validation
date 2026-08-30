"""Confidence intervals for benchmark performance metrics."""

from __future__ import annotations

import math


def wilson_interval(
    successes: int,
    total: int,
    z: float = 1.959963984540054,
) -> tuple[float, float]:
    """Return a two-sided Wilson score interval for a binomial proportion.

    The default z value produces a 95% confidence interval.
    """

    if total <= 0:
        raise ValueError("total must be greater than zero.")

    if successes < 0 or successes > total:
        raise ValueError(
            "successes must be between zero and total."
        )

    proportion = successes / total
    z_squared = z**2
    denominator = 1 + (z_squared / total)

    center = (
        proportion
        + (z_squared / (2 * total))
    ) / denominator

    margin = (
        z
        * math.sqrt(
            (
                proportion * (1 - proportion) / total
                + z_squared / (4 * total**2)
            )
        )
        / denominator
    )

    return center - margin, center + margin