import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
FEEDS_DIR = BASE_DIR / "data" / "impact_feeds"
ACTIVE_FEED = BASE_DIR / "data" / "impact_dhgate.txt"


def run_one_feed(feed_path: Path, limit_each: int) -> int:
    print("\n" + "=" * 80)
    print("Importing feed:", feed_path.name)
    print("Source:", feed_path)
    print("=" * 80)

    ACTIVE_FEED.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(feed_path, ACTIVE_FEED)

    code = (
        "from importers.impact import import_impact; "
        f"import_impact(limit={limit_each})"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(BASE_DIR),
        text=True,
    )

    return result.returncode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit-each", type=int, default=200)
    parser.add_argument("--folder", type=str, default=str(FEEDS_DIR))
    args = parser.parse_args()

    feeds_dir = Path(args.folder)

    print("Ofertix multi Impact importer")
    print("Feeds folder:", feeds_dir)
    print("Limit each:", args.limit_each)

    if not feeds_dir.exists():
        print("ERROR: feeds folder not found:", feeds_dir)
        print("Create it and put your Impact .txt files inside.")
        sys.exit(1)

    feeds = sorted(feeds_dir.glob("*.txt"))

    if not feeds:
        print("ERROR: no .txt Impact feeds found in:", feeds_dir)
        sys.exit(1)

    print("Found feeds:", len(feeds))
    for feed in feeds:
        print("-", feed.name)

    failed = 0

    for feed in feeds:
        rc = run_one_feed(feed, args.limit_each)
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
