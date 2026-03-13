import argparse
import sys

from .scraper import TVArchiveScraper


def main():
    parser = argparse.ArgumentParser(
        description="Download TV News Archive transcripts for a politician."
    )
    parser.add_argument("name", help='Politician name to search (e.g. "Bernie Sanders")')
    parser.add_argument(
        "-n", "--max-results", type=int, default=None,
        help="Maximum number of transcripts to download (default: all)"
    )
    parser.add_argument(
        "-o", "--output-dir", default=None,
        help='Output directory (default: "{name} TV archive transcripts")'
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

    scraper = TVArchiveScraper(
        name=args.name,
        output_dir=args.output_dir,
        rows=args.rows,
        sort=args.sort,
    )

    num_found, _ = scraper.search()
    print(f'Found {num_found} results for "{args.name}"')

    if num_found == 0:
        sys.exit(0)

    scraper.download_all(max_results=args.max_results, delay=args.delay)


if __name__ == "__main__":
    main()
