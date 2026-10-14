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


def test_build_chapters_numbered_cuts():
    chapters, warnings = build_chapters(
        ["Alpha", "Beta", "Gamma"],
        [100.0, 200.0, 14.0],
    )
    assert chapters[0].title == "Intro"
    assert chapters[0].start == 0.0
    assert [(c.start, c.title) for c in chapters[1:]] == [
        (14.0, "1"),
        (100.0, "2"),
        (200.0, "3"),
    ]
    assert any("ignored" in w.lower() for w in warnings)


def test_build_chapters_no_jingles():
    chapters, warnings = build_chapters([], [])
    assert len(chapters) == 1
    assert chapters[0].title == "Intro"
    assert chapters[0].start == 0.0
    assert any("no jingles" in w.lower() for w in warnings)
