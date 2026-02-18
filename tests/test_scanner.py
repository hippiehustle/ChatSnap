from pathlib import Path

from scanner import ScannerConfig, build_config, parse_args, scan


def make_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_recursive_text_scan(tmp_path: Path) -> None:
    make_file(tmp_path / "a.txt", "alpha bravo")
    make_file(tmp_path / "nested" / "b.md", "charlie token delta")

    args = parse_args([str(tmp_path), "-k", "token"])
    cfg: ScannerConfig = build_config(args)
    results = scan(cfg)

    assert len(results) == 1
    assert results[0].path.endswith("nested/b.md")


def test_include_exclude_filters(tmp_path: Path) -> None:
    make_file(tmp_path / "one.txt", "hello token")
    make_file(tmp_path / "two.log", "hello token")

    args = parse_args([str(tmp_path), "-k", "token", "--include-ext", ".txt"])
    cfg = build_config(args)
    results = scan(cfg)

    assert len(results) == 1
    assert results[0].path.endswith("one.txt")
