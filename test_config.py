import config


def test_server_url_points_to_production():
    assert config.SERVER_URL == "https://api.studytracker.cloud"
