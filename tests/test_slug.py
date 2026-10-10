from apofika.db import suggest_slug


def test_suggest_slug_from_title():
    assert suggest_slug("Apokalypse & Filterkaffee") == "apokalypse-filterkaffee"


def test_suggest_slug_fallback_host():
    assert suggest_slug("", "https://example.com/feed/mp3") == "example-com"
