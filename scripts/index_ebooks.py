import os
import json
from pathlib import Path
from datetime import datetime, timezone

SEARCH_DIRS = [
    Path(r"Z:\My Drive\03_Reading & Library\Ebooks"),
    Path(r"Z:\My Drive\ebooks"),
    Path(r"Z:\ebooks"),
]

VALID_EXTENSIONS = {".pdf", ".epub", ".mobi", ".azw3", ".azw", ".djvu", ".txt"}


def clean_title(filename: str) -> str:
    """Derive a human-readable title from a file name."""
    name = Path(filename).stem
    # Remove common scraper suffixes
    for tag in ["(z-lib.org)", "(Z-Library)", "(1stEd)", "(2ndEd)", "mantesh", "[z-lib.org]"]:
        name = name.replace(tag, "")
    # Clean up dots, underscores, dashes
    clean = name.replace(".", " ").replace("_", " ").strip()
    return " ".join(clean.split())


def scan_ebooks() -> list:
    indexed = []
    seen_paths = set()

    for base_dir in SEARCH_DIRS:
        if not base_dir.exists():
            continue
        print(f"Scanning ebooks in {base_dir}...")
        for root, dirs, files in os.walk(base_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and "trash" not in d.lower()]
            rel_folder = os.path.relpath(root, base_dir)
            category = "General" if rel_folder == "." else rel_folder.replace("\\", " > ")

            for file in files:
                p = Path(root) / file
                ext = p.suffix.lower()
                if ext in VALID_EXTENSIONS:
                    norm_path = str(p)
                    if norm_path in seen_paths:
                        continue
                    seen_paths.add(norm_path)

                    try:
                        size_mb = round(p.stat().st_size / (1024 * 1024), 2)
                    except Exception:
                        size_mb = 0.0

                    indexed.append({
                        "title": clean_title(file),
                        "file_name": file,
                        "format": ext.lstrip(".").upper(),
                        "category": category,
                        "size_mb": size_mb,
                        "path": norm_path,
                    })

    # Sort alphabetically by title
    indexed.sort(key=lambda x: x["title"].lower())
    return indexed


def main():
    books = scan_ebooks()
    output_path = Path(__file__).resolve().parent.parent / "ebook_index.json"
    
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_books": len(books),
        "books": books,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(f"Successfully indexed {len(books)} ebooks to {output_path}")


if __name__ == "__main__":
    main()
