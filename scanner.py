#!/usr/bin/env python3
"""Deep content scanner for keyword and regex search across folders, files, images, and videos."""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import fnmatch
import json
import mimetypes
import os
import re
import sys
from pathlib import Path
from typing import Iterable, Sequence

_TEXT_MIME_PREFIXES = ("text/",)
_TEXT_MIME_EXACT = {
    "application/json",
    "application/xml",
    "application/javascript",
    "application/x-javascript",
    "application/x-yaml",
    "application/yaml",
    "application/x-sh",
}


@dataclasses.dataclass
class ScannerConfig:
    root: Path
    keywords: list[str]
    regexes: list[re.Pattern[str]]
    case_sensitive: bool
    include_hidden: bool
    include_patterns: list[str]
    exclude_patterns: list[str]
    include_ext: set[str]
    exclude_ext: set[str]
    max_file_size: int | None
    context_chars: int
    max_matches_per_file: int
    workers: int
    scan_binary_strings: bool
    enable_image_scan: bool
    enable_video_scan: bool
    video_frame_interval: int


@dataclasses.dataclass
class Match:
    term: str
    start: int
    end: int
    snippet: str


@dataclasses.dataclass
class FileResult:
    path: str
    source: str
    matches: list[Match]
    error: str | None = None


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scan a folder recursively for keywords/regex in text files, optional binary strings, "
            "image OCR, and video frame OCR."
        )
    )
    parser.add_argument("root", type=Path, help="Folder to scan recursively")
    parser.add_argument(
        "-k",
        "--keyword",
        action="append",
        default=[],
        help="Keyword to search for (can be repeated)",
    )
    parser.add_argument(
        "-p",
        "--pattern",
        action="append",
        default=[],
        help="Regular expression to search for (can be repeated)",
    )
    parser.add_argument("--case-sensitive", action="store_true", help="Enable case-sensitive search")
    parser.add_argument("--include-hidden", action="store_true", help="Include hidden files and folders")
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        help="Glob of files to include (e.g. '*.md'). Can be repeated",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Glob of files to exclude. Can be repeated",
    )
    parser.add_argument("--include-ext", action="append", default=[], help="Extension to include (e.g. .txt)")
    parser.add_argument("--exclude-ext", action="append", default=[], help="Extension to exclude")
    parser.add_argument(
        "--max-file-size",
        type=int,
        default=None,
        help="Skip files larger than this byte count",
    )
    parser.add_argument("--context", type=int, default=60, help="Snippet context chars around each match")
    parser.add_argument(
        "--max-matches-per-file",
        type=int,
        default=25,
        help="Maximum matches to report per file",
    )
    parser.add_argument("--workers", type=int, default=max((os.cpu_count() or 2) - 1, 1), help="Worker threads")
    parser.add_argument("--scan-binary-strings", action="store_true", help="Extract ASCII strings from binary files")
    parser.add_argument("--scan-images", action="store_true", help="OCR image files (requires pillow + pytesseract)")
    parser.add_argument("--scan-videos", action="store_true", help="OCR video frames (requires opencv + pillow + pytesseract)")
    parser.add_argument(
        "--video-frame-interval",
        type=int,
        default=30,
        help="Process every Nth frame when --scan-videos is enabled",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON")
    return parser.parse_args(argv)


def build_config(args: argparse.Namespace) -> ScannerConfig:
    if not args.keyword and not args.pattern:
        raise SystemExit("Provide at least one --keyword or --pattern")

    flags = 0 if args.case_sensitive else re.IGNORECASE
    regexes = [re.compile(pattern, flags=flags) for pattern in args.pattern]

    keywords = args.keyword if args.case_sensitive else [k.lower() for k in args.keyword]

    include_ext = {normalize_ext(ext) for ext in args.include_ext}
    exclude_ext = {normalize_ext(ext) for ext in args.exclude_ext}

    return ScannerConfig(
        root=args.root.resolve(),
        keywords=keywords,
        regexes=regexes,
        case_sensitive=args.case_sensitive,
        include_hidden=args.include_hidden,
        include_patterns=args.include,
        exclude_patterns=args.exclude,
        include_ext=include_ext,
        exclude_ext=exclude_ext,
        max_file_size=args.max_file_size,
        context_chars=max(0, args.context),
        max_matches_per_file=max(1, args.max_matches_per_file),
        workers=max(1, args.workers),
        scan_binary_strings=args.scan_binary_strings,
        enable_image_scan=args.scan_images,
        enable_video_scan=args.scan_videos,
        video_frame_interval=max(1, args.video_frame_interval),
    )


def normalize_ext(ext: str) -> str:
    ext = ext.strip().lower()
    if not ext:
        return ext
    if not ext.startswith("."):
        ext = f".{ext}"
    return ext


def is_hidden(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts if part not in (".", ".."))


def should_scan_file(path: Path, cfg: ScannerConfig) -> bool:
    rel = str(path.relative_to(cfg.root))

    if not cfg.include_hidden and is_hidden(path.relative_to(cfg.root)):
        return False

    if cfg.include_patterns and not any(fnmatch.fnmatch(rel, pattern) for pattern in cfg.include_patterns):
        return False

    if cfg.exclude_patterns and any(fnmatch.fnmatch(rel, pattern) for pattern in cfg.exclude_patterns):
        return False

    ext = path.suffix.lower()
    if cfg.include_ext and ext not in cfg.include_ext:
        return False
    if cfg.exclude_ext and ext in cfg.exclude_ext:
        return False

    if cfg.max_file_size is not None:
        try:
            if path.stat().st_size > cfg.max_file_size:
                return False
        except OSError:
            return False

    return True


def detect_file_kind(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    if mime:
        if mime.startswith("image/"):
            return "image"
        if mime.startswith("video/"):
            return "video"
        if mime.startswith(_TEXT_MIME_PREFIXES) or mime in _TEXT_MIME_EXACT:
            return "text"
    if path.suffix.lower() in {".txt", ".md", ".py", ".js", ".ts", ".java", ".rb", ".go", ".rs", ".c", ".cpp", ".h", ".hpp", ".csv", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".log", ".html", ".css", ".sql"}:
        return "text"
    return "binary"


def collect_files(cfg: ScannerConfig) -> list[Path]:
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(cfg.root):
        base = Path(dirpath)
        if not cfg.include_hidden:
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            path = base / name
            if should_scan_file(path, cfg):
                files.append(path)
    return files


def search_text(content: str, cfg: ScannerConfig) -> list[Match]:
    haystack = content if cfg.case_sensitive else content.lower()
    matches: list[Match] = []

    for keyword in cfg.keywords:
        start = 0
        while True:
            idx = haystack.find(keyword, start)
            if idx == -1:
                break
            end = idx + len(keyword)
            snippet = snippet_around(content, idx, end, cfg.context_chars)
            matches.append(Match(term=keyword, start=idx, end=end, snippet=snippet))
            start = idx + 1
            if len(matches) >= cfg.max_matches_per_file:
                return matches

    for pattern in cfg.regexes:
        for found in pattern.finditer(content):
            snippet = snippet_around(content, found.start(), found.end(), cfg.context_chars)
            matches.append(Match(term=pattern.pattern, start=found.start(), end=found.end(), snippet=snippet))
            if len(matches) >= cfg.max_matches_per_file:
                return matches

    matches.sort(key=lambda m: (m.start, m.end))
    return matches[: cfg.max_matches_per_file]


def snippet_around(content: str, start: int, end: int, context_chars: int) -> str:
    left = max(0, start - context_chars)
    right = min(len(content), end + context_chars)
    snippet = content[left:right].replace("\n", "\\n")
    return snippet


def extract_binary_strings(raw: bytes, min_len: int = 4) -> str:
    found: list[str] = []
    current: list[str] = []
    for b in raw:
        if 32 <= b <= 126:
            current.append(chr(b))
            continue
        if len(current) >= min_len:
            found.append("".join(current))
        current = []
    if len(current) >= min_len:
        found.append("".join(current))
    return "\n".join(found)


def scan_image(path: Path) -> tuple[str | None, str | None]:
    try:
        from PIL import Image
        import pytesseract
    except Exception as exc:  # noqa: BLE001
        return None, f"Image OCR unavailable ({exc})"

    try:
        text = pytesseract.image_to_string(Image.open(path))
        return text, None
    except Exception as exc:  # noqa: BLE001
        return None, f"Image OCR failed: {exc}"


def scan_video(path: Path, frame_interval: int) -> tuple[str | None, str | None]:
    try:
        import cv2
        from PIL import Image
        import pytesseract
    except Exception as exc:  # noqa: BLE001
        return None, f"Video OCR unavailable ({exc})"

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        return None, "Unable to open video"

    frame_index = 0
    chunks: list[str] = []
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if frame_index % frame_interval == 0:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = Image.fromarray(rgb)
                text = pytesseract.image_to_string(image)
                if text.strip():
                    chunks.append(f"[frame {frame_index}]\n{text.strip()}")
            frame_index += 1
    finally:
        capture.release()

    return "\n\n".join(chunks), None


def scan_file(path: Path, cfg: ScannerConfig) -> FileResult | None:
    kind = detect_file_kind(path)
    source = "file"
    try:
        if kind == "text":
            content = path.read_text(encoding="utf-8", errors="ignore")
        elif kind == "image" and cfg.enable_image_scan:
            source = "image_ocr"
            content, err = scan_image(path)
            if err:
                return FileResult(path=str(path), source=source, matches=[], error=err)
            if content is None:
                return None
        elif kind == "video" and cfg.enable_video_scan:
            source = "video_ocr"
            content, err = scan_video(path, cfg.video_frame_interval)
            if err:
                return FileResult(path=str(path), source=source, matches=[], error=err)
            if content is None:
                return None
        elif cfg.scan_binary_strings:
            raw = path.read_bytes()
            source = "binary_strings"
            content = extract_binary_strings(raw)
        else:
            return None

        matches = search_text(content, cfg)
        if not matches:
            return None
        return FileResult(path=str(path), source=source, matches=matches)
    except Exception as exc:  # noqa: BLE001
        return FileResult(path=str(path), source=source, matches=[], error=str(exc))


def scan(cfg: ScannerConfig) -> list[FileResult]:
    files = collect_files(cfg)
    results: list[FileResult] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=cfg.workers) as executor:
        futures = [executor.submit(scan_file, path, cfg) for path in files]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                results.append(result)

    return sorted(results, key=lambda r: r.path)


def render_human(results: Sequence[FileResult]) -> str:
    if not results:
        return "No matches found."

    lines: list[str] = []
    for result in results:
        lines.append(f"\n==> {result.path} [{result.source}]")
        if result.error:
            lines.append(f"ERROR: {result.error}")
            continue
        for m in result.matches:
            lines.append(f"- term={m.term!r} span={m.start}:{m.end}")
            lines.append(f"  snippet: {m.snippet}")
    lines.append(f"\nTotal matching files: {len(results)}")
    return "\n".join(lines)


def render_json(results: Sequence[FileResult]) -> str:
    payload = [
        {
            "path": r.path,
            "source": r.source,
            "error": r.error,
            "matches": [dataclasses.asdict(m) for m in r.matches],
        }
        for r in results
    ]
    return json.dumps(payload, indent=2)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    cfg = build_config(args)

    if not cfg.root.exists() or not cfg.root.is_dir():
        print(f"Root path is not a directory: {cfg.root}", file=sys.stderr)
        return 2

    results = scan(cfg)
    output = render_json(results) if args.json else render_human(results)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
