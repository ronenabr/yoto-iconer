from yoto_iconer import catalog


def test_upsert_is_idempotent(conn):
    rec = {"key": "official:A", "source": "official", "ref": "A", "title": "Cat",
           "tags": "cat animal", "category": "", "author": "yoto", "downloads": 0,
           "media_id": "A", "img_url": None}
    catalog.upsert(conn, [rec])
    catalog.upsert(conn, [rec])
    assert conn.execute("SELECT COUNT(*) n FROM icons").fetchone()["n"] == 1
    assert conn.execute("SELECT COUNT(*) n FROM icons_fts").fetchone()["n"] == 1


def test_upsert_refreshes_metadata(conn):
    base = {"key": "community:7", "source": "community", "ref": "7", "title": "Old",
            "tags": "", "category": "", "author": "", "downloads": 1,
            "media_id": None, "img_url": None}
    catalog.upsert(conn, [base])
    catalog.upsert(conn, [{**base, "title": "New", "downloads": 50}])
    row = catalog.get(conn, "community:7")
    assert row["title"] == "New" and row["downloads"] == 50


def test_upsert_never_clears_a_resolved_media_id(conn):
    base = {"key": "community:7", "source": "community", "ref": "7", "title": "X",
            "tags": "", "category": "", "author": "", "downloads": 0,
            "media_id": None, "img_url": None}
    catalog.upsert(conn, [base])
    catalog.set_media_id(conn, "community:7", "UPLOADED")
    catalog.upsert(conn, [base])
    assert catalog.get(conn, "community:7")["media_id"] == "UPLOADED"


def test_upload_cache_round_trip(conn):
    assert catalog.upload_for_sha(conn, "abc") is None
    catalog.remember_upload(conn, "abc", "MEDIA")
    assert catalog.upload_for_sha(conn, "abc") == "MEDIA"


def test_community_record_shape():
    rec = catalog.community_record(
        {"id": "1346", "title": "Dino", "tags": ["dinosaur", "rex"],
         "category": "animals", "artist": "bob", "downloads": 12}
    )
    assert rec["key"] == "community:1346"
    assert rec["tags"] == "dinosaur rex"
    assert rec["media_id"] is None
    assert rec["img_url"].endswith("1346.png")


def test_normalize_official_reads_public_tags():
    rec = catalog._normalize_official(
        {"mediaId": "M1", "title": "Lion", "publicTags": ["Lion", "Animal"]}, "official"
    )
    assert rec["key"] == "official:M1" and rec["tags"] == "lion animal"
    assert rec["media_id"] == "M1"


def test_normalize_official_skips_entries_without_a_media_id():
    assert catalog._normalize_official({"title": "Nope"}, "official") is None


def test_stats_counts_by_source(seeded):
    stats = catalog.stats(seeded)
    assert stats["official"] == 2 and stats["community"] == 2
