from pathlib import Path

from yoto_iconer import yotoicons

MARKUP = (Path(__file__).parent / "fixtures" / "yotoicons_page.html").read_text()


def test_parse_page_extracts_every_icon():
    icons = yotoicons.parse_page(MARKUP)
    assert [i["id"] for i in icons] == ["2706", "12583", "342"]


def test_parse_page_reads_fields():
    bingo = yotoicons.parse_page(MARKUP)[1]
    assert bingo["title"] == "Grannies Bingo"
    assert bingo["tags"] == ["grannies bingo", "bluey book reads"]
    assert bingo["category"] == "animals"
    assert bingo["artist"] == "curiouscat"
    assert bingo["downloads"] == 9751


def test_empty_second_tag_is_dropped():
    assert yotoicons.parse_page(MARKUP)[0]["tags"] == ["bluey"]


def test_parse_total():
    assert yotoicons.parse_total(MARKUP) == 22739


def test_page_url_paginates_and_tags():
    url = yotoicons.page_url(3, tag="dinosaur")
    assert "page=3" in url and "tag=dinosaur" in url and "type=singles" in url


def test_png_url():
    assert yotoicons.png_url("1346").endswith("/static/uploads/1346.png")
