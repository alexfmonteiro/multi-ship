# tests/test_handoff.py
from multi_ship.handoff import init_handoff, HANDOFF_SECTIONS

def test_init_writes_all_sections(tmp_path):
    p = tmp_path / "HANDOFF.md"
    init_handoff(p)
    text = p.read_text()
    for sec in HANDOFF_SECTIONS:
        assert f"## {sec}" in text

def test_init_does_not_clobber_existing(tmp_path):
    p = tmp_path / "HANDOFF.md"
    p.write_text("## Open notes\n- existing\n")
    init_handoff(p)  # must be a no-op if present
    assert "existing" in p.read_text()
