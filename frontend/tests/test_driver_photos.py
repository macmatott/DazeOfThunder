from app.services.driver_photos import driver_photo_slug, driver_photo_url


def test_slug_lowercases_and_hyphenates():
    assert driver_photo_slug("Lando Norris") == "lando-norris"


def test_slug_strips_accents():
    assert driver_photo_slug("Nico Hülkenberg") == "nico-hulkenberg"
    assert driver_photo_slug("Sergio Pérez") == "sergio-perez"


def test_slug_handles_three_part_names():
    assert driver_photo_slug("Andrea Kimi Antonelli") == "andrea-kimi-antonelli"


def test_photo_url_shape():
    assert driver_photo_url("Max Verstappen") == "/static/img/drivers/max-verstappen.png"
