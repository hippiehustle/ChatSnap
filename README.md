# ChatSnap Deep Scanner

A feature-rich recursive scanner for searching keywords and regex patterns across:

- Plain text/code/config files
- Binary files (ASCII string extraction mode)
- Images with OCR (`--scan-images`)
- Videos with OCR over sampled frames (`--scan-videos`)

## Features

- Recursive directory traversal with hidden-file controls
- Keyword and regex searching in a single run
- Case-sensitive and case-insensitive search modes
- Include/exclude glob filters and extension filters
- File size limits to avoid huge files
- Multi-threaded scanning for performance
- Configurable snippet context and max matches per file
- JSON output mode for automation pipelines
- Graceful fallback when OCR dependencies are unavailable

## Quick Start

```bash
python3 scanner.py /path/to/folder -k "password" -k "token" -p "AKIA[0-9A-Z]{16}"
```

### Useful examples

Search markdown files only:

```bash
python3 scanner.py . -k "roadmap" --include "*.md"
```

Search all files including hidden files and binary string extraction:

```bash
python3 scanner.py . -k "secret" --include-hidden --scan-binary-strings
```

Enable OCR for images and videos:

```bash
python3 scanner.py ./media -k "invoice" --scan-images --scan-videos --video-frame-interval 20
```

Output JSON:

```bash
python3 scanner.py . -k "TODO" --json
```

## Installation

Base scanner requires only Python 3.10+.

Optional OCR dependencies:

```bash
pip install pillow pytesseract opencv-python
```

You also need the `tesseract` binary installed on the system for OCR to work.

## CLI Options

Run:

```bash
python3 scanner.py --help
```

Highlights:

- `--keyword/-k`: add keyword(s)
- `--pattern/-p`: add regex pattern(s)
- `--include` / `--exclude`: glob filters
- `--include-ext` / `--exclude-ext`: extension filters
- `--scan-images`: OCR images
- `--scan-videos`: OCR video frames
- `--scan-binary-strings`: search printable ASCII strings in binary files
- `--json`: machine-readable output

## Notes

- Video OCR is frame-based and intentionally samples frames for speed.
- OCR quality depends on image/video quality, language packs, and Tesseract configuration.
- Large scans are CPU-intensive; tune `--workers` and `--max-file-size` as needed.
