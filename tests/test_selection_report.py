"""El run dice cuándo el ave del día ya había salido antes."""

from scripts import generate


ENTRIES = [
    {"speciesCode": "a", "date": "2026-01-01"},
    {"speciesCode": "b", "date": "2026-01-02"},
    {"speciesCode": "a", "date": "2026-03-04"},
]


def test_note_names_the_previous_publication():
    note = generate._republished_note(ENTRIES, "a", "Mirlo común")
    assert "2026-03-04" in note
    assert "Mirlo común" in note


def test_note_is_empty_on_a_debut():
    assert generate._republished_note(ENTRIES, "zzz", "Otra") == ""


def test_note_uses_the_most_recent_previous_date():
    note = generate._republished_note(ENTRIES + [
        {"speciesCode": "a", "date": "2026-06-06"}
    ], "a", "Mirlo común")
    assert "2026-06-06" in note
