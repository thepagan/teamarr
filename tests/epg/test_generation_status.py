"""Characterization of the global generation status tracker (#830, Packet 0).

``teamarr/consumers/generation_status.py`` is what the polling endpoint and the
SSE stream serialize, so its ``to_dict()`` keys, its monotonic-percent clamp and
its cancellation lifecycle are public contracts for the pipeline extraction.

The monotonic clamp is the load-bearing half of a pair: ``run_full_generation``
emits raw percentages that go *backwards* (channel reassignment reports 94 under
the "groups" phase, the ordering stage that follows reports 93 — see
``test_generation_contract.py::test_raw_progress_percentages_are_not_monotonic``).
Displayed progress is monotonic only because ``update_status`` refuses to lower
it. Both halves must survive Packet 3.
"""

import pytest

from teamarr.consumers import generation_status as status_mod
from teamarr.consumers.generation_status import (
    GenerationStatus,
    complete_generation,
    create_progress_callback,
    fail_generation,
    get_status,
    is_cancellation_requested,
    is_in_progress,
    request_cancellation,
    start_generation,
    update_status,
)

STATUS_KEYS = {
    "in_progress",
    "status",
    "message",
    "percent",
    "phase",
    "current",
    "total",
    "item_name",
    "started_at",
    "completed_at",
    "error",
    "result",
    "cancellation_requested",
}


@pytest.fixture(autouse=True)
def _clean_global_status():
    """The tracker is process-global; reset it around every case."""
    with status_mod._status_lock:
        status_mod._status.reset()
    yield
    with status_mod._status_lock:
        status_mod._status.reset()


# ---------------------------------------------------------------------------
# Serialized shape
# ---------------------------------------------------------------------------


def test_to_dict_keys_are_exact():
    """Both the polling endpoint and every SSE frame ship exactly these keys."""
    assert set(GenerationStatus().to_dict()) == STATUS_KEYS
    assert set(get_status()) == STATUS_KEYS


def test_idle_status_defaults():
    status = get_status()

    assert status["in_progress"] is False
    assert status["status"] == "idle"
    assert status["message"] == ""
    assert status["percent"] == 0
    assert status["phase"] == ""
    assert status["current"] == 0
    assert status["total"] == 0
    assert status["item_name"] == ""
    assert status["started_at"] is None
    assert status["completed_at"] is None
    assert status["error"] is None
    assert status["result"] == {}
    assert status["cancellation_requested"] is False


def test_timestamps_serialize_as_isoformat_strings():
    assert start_generation() is True
    assert isinstance(get_status()["started_at"], str)

    complete_generation({"success": True})
    completed = get_status()["completed_at"]
    assert isinstance(completed, str)
    assert "T" in completed


# ---------------------------------------------------------------------------
# Start / complete / fail lifecycle
# ---------------------------------------------------------------------------


def test_start_generation_marks_in_progress_and_rejects_a_second_start():
    assert start_generation() is True
    status = get_status()
    assert status["in_progress"] is True
    assert status["status"] == "starting"
    assert status["message"] == "Initializing EPG generation..."
    assert status["percent"] == 0
    assert is_in_progress() is True

    # The 409 the API answers with is this False.
    assert start_generation() is False


def test_start_generation_resets_a_previous_run():
    assert start_generation() is True
    update_status(percent=70, phase="groups", message="halfway", item_name="Group A")
    complete_generation({"success": True})

    assert start_generation() is True
    status = get_status()
    assert status["percent"] == 0
    assert status["phase"] == ""
    assert status["item_name"] == ""
    assert status["result"] == {}
    assert status["completed_at"] is None


def test_complete_generation_shape():
    assert start_generation() is True
    complete_generation({"success": True, "run_id": 7})

    status = get_status()
    assert status["in_progress"] is False
    assert status["status"] == "complete"
    assert status["message"] == "EPG generation complete"
    assert status["percent"] == 100
    assert status["result"] == {"success": True, "run_id": 7}
    assert status["error"] is None


def test_fail_generation_shape():
    assert start_generation() is True
    fail_generation("provider exploded")

    status = get_status()
    assert status["in_progress"] is False
    assert status["status"] == "error"
    assert status["message"] == "Error: provider exploded"
    assert status["error"] == "provider exploded"
    assert status["completed_at"] is not None


# ---------------------------------------------------------------------------
# Monotonic percent
# ---------------------------------------------------------------------------


def test_percent_never_goes_backwards_but_other_fields_still_update():
    assert start_generation() is True

    update_status(status="progress", phase="groups", percent=94, message="reassigning")
    assert get_status()["percent"] == 94

    # The real regression: ordering reports 93 right after reassignment's 94.
    update_status(
        status="progress",
        phase="ordering",
        percent=93,
        message="Applying stream ordering rules...",
        current=2,
        total=9,
        item_name="Channel 5",
    )

    status = get_status()
    assert status["percent"] == 94, "displayed percent regressed"
    assert status["phase"] == "ordering"
    assert status["message"] == "Applying stream ordering rules..."
    assert status["current"] == 2
    assert status["total"] == 9
    assert status["item_name"] == "Channel 5"


def test_equal_percent_is_also_not_re_applied():
    """The clamp is strict ``>``; an equal value changes nothing."""
    assert start_generation() is True
    update_status(percent=50)
    update_status(percent=50, message="still fifty")
    status = get_status()
    assert status["percent"] == 50
    assert status["message"] == "still fifty"


def test_none_arguments_leave_fields_untouched():
    assert start_generation() is True
    update_status(status="progress", phase="teams", percent=20, message="m", current=1, total=4)
    update_status(percent=30)

    status = get_status()
    assert status["percent"] == 30
    assert status["phase"] == "teams"
    assert status["message"] == "m"
    assert status["current"] == 1
    assert status["total"] == 4


def test_zero_total_pins_the_phase_start_percent():
    """``create_progress_callback`` must not divide by zero."""
    callback = create_progress_callback("teams", 5, 50)
    callback(0, 0, "Nothing to do")

    status = get_status()
    assert status["percent"] == 5
    assert status["phase"] == "teams"
    assert status["total"] == 0


def test_phase_callback_maps_into_its_band():
    callback = create_progress_callback("groups", 50, 95)
    callback(1, 2, "Group A")

    status = get_status()
    assert status["percent"] == 72  # 50 + int(0.5 * 45)
    assert status["phase"] == "groups"
    assert status["status"] == "progress"
    assert status["message"] == "Processing Group A (1/2)"
    assert status["item_name"] == "Group A"


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


def test_cancellation_is_rejected_while_idle():
    assert is_in_progress() is False
    assert request_cancellation() is False
    assert is_cancellation_requested() is False
    assert get_status()["cancellation_requested"] is False


def test_cancellation_is_accepted_while_running():
    assert start_generation() is True
    assert is_cancellation_requested() is False

    assert request_cancellation() is True
    assert is_cancellation_requested() is True
    assert get_status()["cancellation_requested"] is True
    # Still in progress: the run stops at its next checkpoint, not immediately.
    assert get_status()["in_progress"] is True


def test_cancel_generation_is_the_terminal_state():
    assert start_generation() is True
    assert request_cancellation() is True

    status_mod.cancel_generation()

    status = get_status()
    assert status["in_progress"] is False
    assert status["status"] == "cancelled"
    assert status["message"] == "Generation cancelled by user"
    assert status["completed_at"] is not None
    # Pinned as-is: the terminal state does NOT clear the request flag. It is
    # harmless only because ``is_cancellation_requested`` is consulted by a run
    # in progress, and the next ``start_generation()`` resets it (below).
    assert status["cancellation_requested"] is True


def test_a_fresh_start_clears_a_previous_cancellation_request():
    assert start_generation() is True
    assert request_cancellation() is True
    status_mod.cancel_generation()

    assert start_generation() is True
    assert is_cancellation_requested() is False
