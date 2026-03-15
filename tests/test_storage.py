import base64

import pytest
from app import config
from app.storage import slugify_project


def test_slugify_basic():
    assert slugify_project("My Project") == "my-project"


def test_slugify_special_chars():
    assert slugify_project("Hello World! @#$") == "hello-world"


def test_slugify_already_clean():
    assert slugify_project("squawk") == "squawk"


def test_slugify_strips_leading_trailing_hyphens():
    assert slugify_project("--test--") == "test"


def test_slugify_collapses_multiple_hyphens():
    assert slugify_project("a---b") == "a-b"


def test_slugify_rejects_empty():
    with pytest.raises(ValueError, match="empty"):
        slugify_project("!!!")


def test_slugify_rejects_path_traversal():
    with pytest.raises(ValueError, match="(?i)invalid"):
        slugify_project("../etc")


def test_slugify_rejects_absolute_path():
    with pytest.raises(ValueError, match="(?i)invalid"):
        slugify_project("/etc/passwd")


@pytest.fixture
def tmp_data_dir(tmp_path):
    config.DATA_DIR = tmp_path
    config.DB_PATH = tmp_path / "mockups.db"
    return tmp_path


@pytest.fixture
def data_dir(tmp_data_dir):
    return tmp_data_dir


def test_write_html(data_dir):
    from app.storage import write_mockup_file
    path = write_mockup_file("test-project", "abc123", "html", "<h1>Hello</h1>")
    full_path = data_dir / path
    assert full_path.exists()
    assert full_path.read_text() == "<h1>Hello</h1>"
    assert path == "test-project/abc123.html"


def test_write_png_base64(data_dir):
    from app.storage import write_mockup_file
    raw = b"\x89PNG\r\n\x1a\nfakedata"
    content = base64.b64encode(raw).decode()
    path = write_mockup_file("test-project", "def456", "png", content)
    full_path = data_dir / path
    assert full_path.exists()
    assert full_path.read_bytes() == raw


def test_write_svg_raw_string(data_dir):
    from app.storage import write_mockup_file
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><circle r="10"/></svg>'
    path = write_mockup_file("test-project", "ghi789", "svg", svg)
    full_path = data_dir / path
    assert full_path.read_text() == svg


def test_delete_mockup_file(data_dir):
    from app.storage import write_mockup_file, delete_mockup_file
    path = write_mockup_file("test-project", "del1", "html", "<p>bye</p>")
    assert (data_dir / path).exists()
    delete_mockup_file(path)
    assert not (data_dir / path).exists()


def test_content_too_large(data_dir):
    from app.storage import write_mockup_file, MAX_CONTENT_SIZE
    big = "x" * (MAX_CONTENT_SIZE + 1)
    with pytest.raises(ValueError, match="too large"):
        write_mockup_file("test-project", "big1", "html", big)
