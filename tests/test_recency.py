from apofika.formatting import episode_recency_key


def test_rfc822_day_names_sort_chronologically():
    # Lexicographic string sort would put "Thu" before "Mon" (wrong).
    mon = episode_recency_key("Mon, 12 Oct 2026 03:00:00 +0000", None, 1)
    thu = episode_recency_key("Thu, 08 Oct 2026 22:01:00 +0000", None, 2)
    sat = episode_recency_key("Sat, 11 Oct 2026 03:00:00 +0000", None, 3)
    assert mon > sat > thu
