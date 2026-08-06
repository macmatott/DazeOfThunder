from app.services.driver_photos import driver_photo_url, slugify_name


def test_slug_lowercases_and_hyphenates():
    assert slugify_name("Lando Norris") == "lando-norris"


def test_slug_strips_accents():
    assert slugify_name("Nico Hülkenberg") == "nico-hulkenberg"
    assert slugify_name("Sergio Pérez") == "sergio-perez"


def test_slug_handles_three_part_names():
    assert slugify_name("Andrea Kimi Antonelli") == "andrea-kimi-antonelli"


def test_photo_url_shape():
    assert driver_photo_url("Max Verstappen") == "/static/img/drivers/max-verstappen.png"
