import argparse
import sys

from .scraper import ArchiveScraper


def main():
    parser = argparse.ArgumentParser(
        description="Download transcripts and videos from Internet Archive TV News and Video collections."
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
        "--download-videos", action="store_true",
        help="Use yt-dlp to download video files for non-TV items (requires yt-dlp)"
    )
    parser.add_argument(
        "--max-video-mb", type=int, default=500,
        help="Skip video downloads larger than this size in MB (default: 500, 0=no limit)"
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
        download_videos=args.download_videos,
        max_video_mb=args.max_video_mb,
    )

    scraper.download_all(
        source=args.source,
        max_results=args.max_results,
        delay=args.delay,
    )


if __name__ == "__main__":
    main()
