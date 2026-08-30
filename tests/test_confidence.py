import pytest

from metrics.confidence import wilson_interval


def test_wilson_interval_for_perfect_result_is_conservative():
    lower, upper = wilson_interval(10, 10)

    assert lower == pytest.approx(0.7225, abs=0.0001)
    assert upper == pytest.approx(1.0)


def test_wilson_interval_for_half_success_is_symmetric():
    lower, upper = wilson_interval(5, 10)

    assert lower == pytest.approx(0.2366, abs=0.0001)
    assert upper == pytest.approx(0.7634, abs=0.0001)


@pytest.mark.parametrize(
    ("successes", "total"),
    [
        (-1, 10),
        (11, 10),
        (0, 0),
    ],
)
def test_wilson_interval_rejects_invalid_counts(
    successes,
    total,
):
    with pytest.raises(ValueError):
     wilson_interval(successes, total)