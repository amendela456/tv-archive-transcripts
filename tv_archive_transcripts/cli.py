import argparse
import sys

from .scraper import ArchiveScraper


def main():
    parser = argparse.ArgumentParser(
        description="Download transcripts from Internet Archive TV News and Video collections."
    )
    parser.add_argument("name", help='Name to search (e.g. "Eli Crane")')
    parser.add_argument(
        "-n", "--max-results", type=int, default=None,
        help="Maximum number of items to download (default: all)"
    )
    parser.add_argument(
        "-o", "--output-dir", default=None,
        help='Output directory (default: "{name} TV archive transcripts")'
    )
    parser.add_argument(
        "-s", "--source", choices=["all", "tv", "video"], default="all",
        help='Which collections to search: "all", "tv", or "video" (default: all)'
    )
    parser.add_argument(
        "--rows", type=int, default=50,
        help="Results per search page (default: 50)"
    )
    parser.add_argument(
        "--sort", default="date desc",
        help='Sort order (default: "date desc")'
    )
    parser.add_argument(
        "--delay", type=float, default=1.0,
        help="Delay in seconds between requests (default: 1.0)"
    )

    args = parser.parse_args()

    scraper = ArchiveScraper(
        name=args.name,
        output_dir=args.output_dir,
        rows=args.rows,
        sort=args.sort,
    )

    scraper.download_all(
        source=args.source,
        max_results=args.max_results,
        delay=args.delay,
    )


if __name__ == "__main__":
    main()
