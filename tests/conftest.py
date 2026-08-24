import pytest

from yoto_iconer import catalog


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Never touch the real ~/.config/yoto-iconer during tests."""
    monkeypatch.setenv("YOTO_ICONER_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("YOTO_CLIENT_ID", raising=False)
    return tmp_path


@pytest.fixture
def conn():
    return catalog.connect(":memory:")


@pytest.fixture
def seeded(conn):
    catalog.upsert(
        conn,
        [
            {"key": "official:MEDIA_MUSIC", "source": "official", "ref": "MEDIA_MUSIC",
             "title": "Music notes", "tags": "music note song", "category": "",
             "author": "yoto", "downloads": 0, "media_id": "MEDIA_MUSIC", "img_url": None},
            {"key": "official:MEDIA_BUS", "source": "official", "ref": "MEDIA_BUS",
             "title": "School bus", "tags": "bus school vehicle", "category": "",
             "author": "yoto", "downloads": 0, "media_id": "MEDIA_BUS", "img_url": None},
            {"key": "community:1346", "source": "community", "ref": "1346",
             "title": "Dinosaur", "tags": "dinosaur rex", "category": "animals",
             "author": "someone", "downloads": 900, "media_id": None,
             "img_url": "https://www.yotoicons.com/static/uploads/1346.png"},
            {"key": "community:99", "source": "community", "ref": "99",
             "title": "Twinkle star", "tags": "star night sky", "category": "space",
             "author": "someone", "downloads": 40, "media_id": None,
             "img_url": "https://www.yotoicons.com/static/uploads/99.png"},
        ],
    )
    return conn


@pytest.fixture
def card():
    return {
        "cardId": "CARD1",
        "title": "Bedtime Mix",
        "metadata": {"description": "keep me"},
        "content": {
            "chapters": [
                {
                    "key": "01",
                    "title": "Twinkle Twinkle Little Star",
                    "display": {"icon16x16": None},
                    "customField": "must survive",
                    "tracks": [
                        {"key": "01", "title": "Twinkle Twinkle Little Star",
                         "trackUrl": "yoto:#abc", "duration": 60, "format": "mp3",
                         "type": "audio", "overlayLabel": "1"},
                    ],
                },
                {
                    "key": "02",
                    "title": "Vehicles",
                    "display": {"icon16x16": "yoto:#OLD"},
                    "tracks": [
                        {"key": "01", "title": "The Wheels on the Bus",
                         "trackUrl": "yoto:#d", "duration": 90, "format": "mp3",
                         "type": "audio", "overlayLabel": "2"},
                        {"key": "02", "title": "Big Red Dinosaur Stomp",
                         "trackUrl": "yoto:#e", "duration": 95, "format": "mp3",
                         "type": "audio", "overlayLabel": "3",
                         "display": {"icon16x16": "yoto:#MEDIA_MUSIC"}},
                    ],
                },
            ]
        },
    }
