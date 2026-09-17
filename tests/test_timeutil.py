from app.timeutil import format_br


def test_utc_midnight_is_previous_evening_in_brazil():
    assert format_br("2026-09-15T00:00:00Z") == "14/09/2026 21:00"


def test_utc_afternoon_is_brazil_morning():
    assert format_br("2026-09-14T23:07:59Z") == "14/09/2026 20:07"


def test_empty_stays_empty():
    assert format_br("") == ""


def test_official_date_keeps_day_and_time():
    from app.timeutil import official_date

    assert official_date("14/09/2026 07:27") == "14/09/2026 07:27"
    assert official_date("14/09/2026 07:11:35") == "14/09/2026 07:11"
    assert official_date("14/09/2026 00:00:00") == "14/09/2026 00:00"
    assert official_date("14/09/2026") == "14/09/2026"
    assert official_date("") == ""
