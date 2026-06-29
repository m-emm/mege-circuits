import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--runslow",
        action="store_true",
        default=False,
        help="run slow integration and optimizer regression tests",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--runslow"):
        return
    skip_slow = pytest.mark.skip(reason="need --runslow option to run")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip_slow)


@pytest.fixture(scope="session")
def tb6600_verified_plan_with_stats():
    import mege_circuits.physical as physical
    from examples.integration.tb6600_stripboard_layout import (
        create_tb6600_verified_stripboard_plan,
    )

    plan = create_tb6600_verified_stripboard_plan()
    return plan, physical._LAST_STRIPBOARD_PLANNING_STATS


@pytest.fixture(scope="session")
def tb6600_verified_plan(tb6600_verified_plan_with_stats):
    plan, _stats = tb6600_verified_plan_with_stats
    return plan


@pytest.fixture(scope="session")
def tb6600_verified_plan_stats(tb6600_verified_plan_with_stats):
    _plan, stats = tb6600_verified_plan_with_stats
    return stats
