"""The validator's headline for a failed test run: coverage shortfall vs failing tests."""
from cartograph.validator import _test_failure_message

COVERAGE = "Coverage below threshold - add tests to reach 80%."
FAILED = "Tests failed. Fix before checkin."


def test_failing_test_with_healthy_coverage_reports_test_failure():
    # pytest-cov prints its "reached" line even when a test failed.
    out = ("FAILED tests/test_x.py::test_y - IndexError\n"
           "Required test coverage of 80% reached. Total coverage: 92.86%\n"
           "1 failed, 2 passed")
    assert _test_failure_message(out) == FAILED


def test_pytest_cov_shortfall_reports_coverage():
    out = "FAIL Required test coverage of 80% not reached. Total coverage: 62.50%"
    assert _test_failure_message(out) == COVERAGE


def test_other_engines_threshold_messages_report_coverage():
    assert _test_failure_message("ERROR: Coverage for lines (61%) does not meet global threshold (80%)") == COVERAGE
    assert _test_failure_message("coverage 61.0% is below the 80% threshold") == COVERAGE


def test_plain_failure_reports_test_failure():
    assert _test_failure_message("AssertionError: expected 2 got 3") == FAILED


def test_engine_gated_coverage_messages_report_coverage():
    # go, rust, php, java, c# and flutter all word it this way
    assert _test_failure_message("Coverage 61.0% is below the required 80% - add tests") == COVERAGE
