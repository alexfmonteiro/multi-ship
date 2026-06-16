# tests/test_policy.py
from multi_ship.runlog import next_item, should_stop, worth_dreaming

def _log(items, stop=True):
    return {"stop_on_failure": stop, "items": items}

def test_next_item_skips_shipped(tmp_path):
    log = _log([{"id": "a.md", "status": "shipped"}, {"id": "b.md", "status": "pending"}])
    assert next_item(log) == "b.md"

def test_next_item_returns_failed_for_retry(tmp_path):
    log = _log([{"id": "a.md", "status": "shipped"}, {"id": "b.md", "status": "failed"}])
    assert next_item(log) == "b.md"

def test_next_item_none_when_all_shipped():
    log = _log([{"id": "a.md", "status": "shipped"}])
    assert next_item(log) is None

def test_should_stop_on_failure_when_policy_stop():
    assert should_stop(_log([], stop=True), item_failed=True) is True

def test_should_continue_on_failure_when_policy_continue():
    assert should_stop(_log([], stop=False), item_failed=True) is False

def test_should_not_stop_on_success():
    assert should_stop(_log([], stop=True), item_failed=False) is False

def test_worth_dreaming_two_shipped():
    log = _log([{"id": "a", "status": "shipped"}, {"id": "b", "status": "shipped"}])
    assert worth_dreaming(log, handoff_text="") is True

def test_worth_dreaming_nonempty_handoff_section():
    log = _log([{"id": "a", "status": "shipped"}])
    text = "## Errors and fixes\n- broke X, fixed by Y\n## Open notes\n"
    assert worth_dreaming(log, handoff_text=text) is True

def test_not_worth_dreaming_trivial():
    log = _log([{"id": "a", "status": "shipped"}])
    text = "## Errors and fixes\n## Discovered knowledge\n## Open notes\n"
    assert worth_dreaming(log, handoff_text=text) is False
