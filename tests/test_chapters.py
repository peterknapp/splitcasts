from apofika.chapters import build_chapters, parse_topics


def test_parse_topics_semicolon():
    desc = (
        "Die Themen: Thema A; Thema B; Thema C\n\n"
        "Du möchtest mehr über unsere Werbepartner erfahren?"
    )
    assert parse_topics(desc) == ["Thema A", "Thema B", "Thema C"]


def test_parse_topics_html():
    desc = (
        "<p>Die Themen: Eins; Zwei; Drei</p>"
        "<p>Du möchtest mehr ...</p>"
    )
    assert parse_topics(desc) == ["Eins", "Zwei", "Drei"]


def test_build_chapters_mapping():
    chapters, warnings = build_chapters(
        ["Alpha", "Beta", "Gamma"],
        [100.0, 200.0],
    )
    assert chapters[0].title == "Intro"
    assert chapters[0].start == 0.0
    assert chapters[1].title == "Alpha"
    assert chapters[1].start == 100.0
    assert chapters[2].title.startswith("Beta")
    assert "Gamma" in chapters[2].title or any("Gamma" in w for w in warnings)
