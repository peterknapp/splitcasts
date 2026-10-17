from apofika.fetch import EpisodeMeta
from apofika.queue import select_copublish_batch


def _meta(guid: str, published: str, title: str = "") -> EpisodeMeta:
    return EpisodeMeta(
        guid=guid,
        title=title or guid,
        description="",
        summary="",
        link="",
        published=published,
        enclosure_url="http://example.com/a.mp3",
        enclosure_type="audio/mpeg",
        enclosure_length=1,
        duration=60,
        image_url=None,
        author=None,
        episode_number=None,
    )


def test_copublish_keeps_near_simultaneous_only():
    items = [
        _meta("a", "Sat, 17 Oct 2026 03:01:00 +0000", "Presseklub"),
        _meta("b", "Sat, 17 Oct 2026 03:00:00 +0000", "Pringles"),
        _meta("c", "Fri, 16 Oct 2026 03:00:00 +0000", "Old one"),
    ]
    batch = select_copublish_batch(items, window_sec=2 * 60 * 60)
    assert [m.guid for m in batch] == ["a", "b"]


def test_copublish_single_newest():
    items = [
        _meta("a", "Sat, 17 Oct 2026 03:01:00 +0000"),
        _meta("c", "Fri, 10 Oct 2026 03:00:00 +0000"),
    ]
    batch = select_copublish_batch(items, window_sec=2 * 60 * 60)
    assert [m.guid for m in batch] == ["a"]
