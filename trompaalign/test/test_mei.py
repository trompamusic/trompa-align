from pathlib import Path
from trompaalign.mei import count_notes_in_expansions, get_expansions_from_mei, Expansion

test_dir = Path(__file__).parent / "data"


def test_get_expansions_from_mei():
    test_path = test_dir / "Beethoven_Op119_Nr08-Breitkopf.mei"
    with open(test_path, "r") as f:
        mei_text = f.read()
    expansions = get_expansions_from_mei(mei_text)

    expected_expansions = [
        Expansion(id="expansion-default", elements=["#A", "#A", "#B", "#B"]),
        Expansion(id="expansion-minimal", elements=["#A", "#B"]),
        Expansion(id="expansion-nested", elements=["#expansion-default", "#expansion-minimal"]),
    ]

    assert expansions == expected_expansions


def test_count_notes_in_expansions():
    test_path = test_dir / "Beethoven_Op119_Nr08-Breitkopf.mei"
    with open(test_path, "r") as f:
        mei_text = f.read()
    expansion_counts = count_notes_in_expansions(mei_text)
    assert expansion_counts["expansion-default"] == 442
    assert expansion_counts["expansion-minimal"] == 221
    assert expansion_counts["expansion-nested"] == 663
