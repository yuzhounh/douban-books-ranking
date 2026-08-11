from pathlib import Path

from douban_books.parsers import parse_listing_page
from douban_books.text import clean_text


FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_tag_with_unicode_missing_rating_and_next_page() -> None:
    html = (FIXTURES / "tag.html").read_text(encoding="utf-8")
    result = parse_listing_page(html, "https://book.douban.com/tag/test?start=0", "tag")

    assert len(result.books) == 2
    assert result.books[0].douban_id == 1234567
    assert result.books[0].title == 'A, "B" 😺 <C>'
    assert result.books[0].rating == 9.1
    assert result.books[0].votes == 12345
    assert result.books[1].rating is None
    assert result.books[1].votes is None
    assert result.next_url == "https://book.douban.com/tag/测试?start=20&type=T"


def test_parse_doulist() -> None:
    html = (FIXTURES / "doulist.html").read_text(encoding="utf-8")
    result = parse_listing_page(html, "https://www.douban.com/doulist/42/?start=0", "doulist")

    assert len(result.books) == 1
    assert result.books[0].douban_id == 24681012
    assert result.books[0].rating == 8.6
    assert result.books[0].votes == 88
    assert "出版社: 某社" in (result.books[0].metadata or "")


def test_parse_top250_preserves_page_order_and_next_page() -> None:
    html = (FIXTURES / "top250.html").read_text(encoding="utf-8")
    result = parse_listing_page(html, "https://book.douban.com/top250?start=0", "top250")

    assert len(result.books) == 1
    assert result.books[0].douban_id == 1007305
    assert result.books[0].title == "红楼梦"
    assert result.books[0].rating == 9.7
    assert result.books[0].votes == 467206
    assert "曹雪芹" in (result.books[0].metadata or "")
    assert result.next_url == "https://book.douban.com/top250?start=25"


def test_block_page_is_rejected() -> None:
    html = "<html><body>检测到有异常请求，请输入验证码 captcha</body></html>"
    try:
        parse_listing_page(html, "https://book.douban.com/tag/test", "tag")
    except Exception as exc:
        assert "验证码" in str(exc)
    else:
        raise AssertionError("blocked page should not be parsed")


def test_clean_text_collapses_layout_whitespace_and_replaces_other_controls() -> None:
    assert clean_text("甲\n\t乙\x00丙") == "甲 乙�丙"
