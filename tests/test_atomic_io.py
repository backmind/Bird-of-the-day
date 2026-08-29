from scripts.atomic_io import write_text_if_changed


def test_writes_a_new_file(tmp_path):
    target = tmp_path / "sub" / "page.html"
    assert write_text_if_changed(target, "hello") is True
    assert target.read_text(encoding="utf-8") == "hello"


def test_identical_content_is_not_rewritten(tmp_path):
    target = tmp_path / "page.html"
    write_text_if_changed(target, "hello")
    before = target.stat().st_mtime_ns
    assert write_text_if_changed(target, "hello") is False
    assert target.stat().st_mtime_ns == before


def test_changed_content_is_rewritten(tmp_path):
    target = tmp_path / "page.html"
    write_text_if_changed(target, "hello")
    assert write_text_if_changed(target, "goodbye") is True
    assert target.read_text(encoding="utf-8") == "goodbye"


def test_no_temporary_files_are_left_behind(tmp_path):
    target = tmp_path / "page.html"
    write_text_if_changed(target, "hello")
    assert [p.name for p in tmp_path.iterdir()] == ["page.html"]


def test_newlines_are_written_verbatim(tmp_path):
    # Deterministic bytes across platforms: a Windows run and a Linux run
    # must produce the same file, or every run flips the whole site in git.
    target = tmp_path / "page.html"
    write_text_if_changed(target, "a\nb\n")
    assert target.read_bytes() == b"a\nb\n"
