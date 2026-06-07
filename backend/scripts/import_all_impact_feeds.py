import argparse
import os
import subprocess
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
FEEDS_DIR = BASE_DIR / "data" / "impact_feeds"


def run_one_feed(feed_path: Path, limit_each: int, dry_run: bool = False) -> int:
    print("\n" + "=" * 80)
    print("Importing feed:", feed_path.name)
    print("Source:", feed_path)
    print("=" * 80)

    code = (
        "from importers.impact import import_impact; "
        f"import_impact(feed_path={repr(str(feed_path))}, limit={limit_each}, dry_run={dry_run}, governed=True)"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(BASE_DIR),
        text=True,
    )

    return result.returncode


def main():
    parser = argparse.ArgumentParser(description="Ofertix governed multi Impact importer")
    parser.add_argument("--limit-each", type=int, default=200, help="Max products per feed file")
    parser.add_argument("--folder", type=str, default=str(FEEDS_DIR), help="Folder with .txt Impact feed files")
    parser.add_argument("--dry-run", action="store_true", help="Classify products without writing to Firestore")
    args = parser.parse_args()

    feeds_dir = Path(args.folder)

    print("Ofertix governed multi Impact importer")
    print("Feeds folder:", feeds_dir)
    print("Limit each:", args.limit_each)
    print("Dry run:", args.dry_run)

    if not feeds_dir.exists():
        print("ERROR: feeds folder not found:", feeds_dir)
        print("Create it and put your Impact .txt files inside.")
        sys.exit(1)

    feeds = sorted(
        f for f in feeds_dir.glob("*.txt")
        if not f.name.upper().startswith("README")
    )

    if not feeds:
        print("ERROR: no .txt Impact feeds found in:", feeds_dir)
        sys.exit(1)

    print("Found feeds:", len(feeds))
    for feed in feeds:
        print("-", feed.name)

    failed = 0

    for feed in feeds:
        rc = run_one_feed(feed, args.limit_each, dry_run=args.dry_run)
        if rc != 0:
            failed += 1
            print("FAILED:", feed.name)
        else:
            print("DONE:", feed.name)

    print("\n" + "=" * 80)
    print("Multi Impact importer finished")
    print("Total feeds:", len(feeds))
    print("Failed:", failed)
    print("=" * 80)

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
