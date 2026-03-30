import os
import re
import time
import json
import subprocess
import shutil
import requests


SEARCH_URL = "https://archive.org/advancedsearch.php"
DETAILS_URL = "https://archive.org/details"
DOWNLOAD_URL = "https://archive.org/download"


class ArchiveScraper:
    """Pull transcripts from the Internet Archive TV News Archive and Video collections."""

    def __init__(self, name, output_dir=None, parent_dir="TV Archive phase 2",
                 rows=50, sort="date desc",
                 download_videos=False, max_video_mb=500):
        """
        Args:
            name: Name to search for (e.g. "Eli Crane").
            output_dir: Override output folder. Defaults to "{parent_dir}/{name} TV Archive".
            parent_dir: Overarching folder for all targets. Defaults to "TV Archive phase 2".
            rows: Max number of results per search page.
            sort: Sort order for results.
            download_videos: Use yt-dlp to download video files for non-TV items.
            max_video_mb: Skip video downloads larger than this (MB). 0 = no limit.
        """
        self.name = name
        self.output_dir = output_dir or os.path.join(parent_dir, f"{name} TV Archive")
        self.rows = rows
        self.sort = sort
        self.download_videos = download_videos
        self.max_video_mb = max_video_mb
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "archive-transcripts/2.0"})

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def _search(self, query, start=0):
        """Run an advanced search query. Returns (total_found, docs)."""
        params = {
            "q": query,
            "fl[]": ["identifier", "title", "date", "collection"],
            "sort[]": self.sort,
            "rows": self.rows,
            "start": start,
            "output": "json",
        }
        resp = self.session.get(SEARCH_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data["response"]["numFound"], data["response"]["docs"]

    def search_tv(self, start=0):
        """Search TV News Archive only."""
        return self._search(f'collection:tvarchive "{self.name}"', start)

    def search_video(self, start=0):
        """Search all video (mediatype:movies) excluding tvarchive."""
        return self._search(
            f'"{self.name}" mediatype:movies -collection:tvarchive', start
        )

    def search_all(self, start=0):
        """Search all video (mediatype:movies) including TV archive."""
        return self._search(f'"{self.name}" mediatype:movies', start)

    # ------------------------------------------------------------------
    # Classify items
    # ------------------------------------------------------------------

    @staticmethod
    def _is_tv(doc):
        collections = doc.get("collection", [])
        if isinstance(collections, str):
            collections = [collections]
        return "tvarchive" in collections

    # ------------------------------------------------------------------
    # TV transcript extraction (from details page caption snippets)
    # ------------------------------------------------------------------

    def _extract_tv_transcript(self, identifier):
        """Fetch the TV details page and extract caption text from embedded snippets."""
        url = f"{DETAILS_URL}/{identifier}"
        resp = self.session.get(url, timeout=60)
        resp.raise_for_status()

        snippets = re.findall(
            r'<div class="snipin[^"]*"[^>]*>(.*?)</div>', resp.text, re.DOTALL
        )
        if not snippets:
            return None

        lines = []
        for s in snippets:
            text = s.strip()
            text = text.replace("&amp;", "&")
            text = text.replace("&lt;", "<")
            text = text.replace("&gt;", ">")
            text = text.replace("&quot;", '"')
            text = text.replace("&#39;", "'")
            text = re.sub(r"<[^>]+>", "", text)
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                lines.append(text)

        return "\n\n".join(lines) if lines else None

    # ------------------------------------------------------------------
    # Video transcript extraction (info.json description + metadata)
    # ------------------------------------------------------------------

    def _extract_video_transcript(self, identifier):
        """
        For non-TV video items (YouTube mirrors, Twitter clips, etc.),
        pull the description and any available metadata from info.json.
        Returns (text, metadata_dict) or (None, None).
        """
        meta_resp = self.session.get(
            f"https://archive.org/metadata/{identifier}", timeout=30
        )
        meta_resp.raise_for_status()
        meta = meta_resp.json()
        item_meta = meta.get("metadata", {})

        files = meta.get("files", [])
        info_json_name = None
        description_name = None
        for f in files:
            name = f.get("name", "")
            if name.endswith(".info.json"):
                info_json_name = name
            if name.endswith(".description"):
                description_name = name

        parts = []
        video_meta = {}

        # Try info.json first (richer metadata)
        if info_json_name:
            try:
                resp = self.session.get(
                    f"{DOWNLOAD_URL}/{identifier}/{info_json_name}", timeout=30
                )
                if resp.status_code == 200:
                    info = resp.json()
                    video_meta["title"] = info.get("title", "")
                    video_meta["upload_date"] = info.get("upload_date", "")
                    video_meta["channel"] = info.get("channel", info.get("uploader", ""))
                    video_meta["duration"] = info.get("duration", "")
                    video_meta["url"] = info.get("webpage_url", "")

                    desc = info.get("description", "")
                    if desc:
                        parts.append(desc)
            except (requests.RequestException, json.JSONDecodeError):
                pass

        # Fallback to .description file
        if not parts and description_name:
            try:
                resp = self.session.get(
                    f"{DOWNLOAD_URL}/{identifier}/{description_name}", timeout=30
                )
                if resp.status_code == 200 and resp.text.strip():
                    parts.append(resp.text.strip())
            except requests.RequestException:
                pass

        # Last resort: use the archive.org item description
        if not parts:
            desc = item_meta.get("description", "")
            if desc:
                parts.append(desc)

        if not parts:
            return None, None

        return "\n\n".join(parts), video_meta

    # ------------------------------------------------------------------
    # yt-dlp video download
    # ------------------------------------------------------------------

    @staticmethod
    def _ytdlp_available():
        return shutil.which("yt-dlp") is not None

    def _get_video_size_mb(self, identifier):
        """Check the size of the largest video file for an item (in MB)."""
        try:
            meta = self.session.get(
                f"https://archive.org/metadata/{identifier}", timeout=30
            ).json()
            max_size = 0
            for f in meta.get("files", []):
                name = f.get("name", "")
                if name.endswith((".mp4", ".webm", ".mkv", ".avi")):
                    max_size = max(max_size, int(f.get("size", 0)))
            return max_size / (1024 * 1024)
        except Exception:
            return 0

    def _download_video_with_ytdlp(self, identifier, dest_dir, date, safe_title):
        """
        Download a video from archive.org using yt-dlp.
        Returns the path to the downloaded file, or None on failure.
        """
        # Check size limit
        if self.max_video_mb > 0:
            size_mb = self._get_video_size_mb(identifier)
            if size_mb > self.max_video_mb:
                print(f"  ! Skipping video: {size_mb:.0f} MB exceeds {self.max_video_mb} MB limit")
                return None

        url = f"{DETAILS_URL}/{identifier}"
        out_template = os.path.join(dest_dir, f"{date}_{safe_title}.%(ext)s")

        cmd = [
            "yt-dlp",
            "--no-playlist",
            "-o", out_template,
            url,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=1800,  # 30 minutes for large files
            )
            if result.returncode == 0:
                # Find the downloaded file
                for line in result.stdout.splitlines():
                    if "Destination:" in line:
                        path = line.split("Destination:", 1)[1].strip()
                        return path
                    if "has already been downloaded" in line:
                        return "(already exists)"
                # Fallback: look for the file by glob
                import glob
                pattern = os.path.join(dest_dir, f"{date}_{safe_title}.*")
                matches = [m for m in glob.glob(pattern) if not m.endswith(".txt")]
                if matches:
                    return matches[0]
            else:
                err = result.stderr.strip().split("\n")[-1] if result.stderr else "unknown error"
                print(f"  ! yt-dlp error: {err}")
                return None
        except subprocess.TimeoutExpired:
            print(f"  ! yt-dlp timed out")
            return None
        except FileNotFoundError:
            print(f"  ! yt-dlp not found")
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_date(date_str):
        if not date_str:
            return "unknown-date"
        return date_str[:10]

    @staticmethod
    def _safe_filename(text, max_len=120):
        text = re.sub(r'[<>:"/\\|?*]', "", text)
        text = text.strip(". ")
        return text[:max_len]

    # ------------------------------------------------------------------
    # Download orchestration
    # ------------------------------------------------------------------

    def download_all(self, source="all", max_results=None, delay=1.0):
        """
        Search and download transcripts (and optionally videos).

        Args:
            source: "all", "tv", or "video".
            max_results: Stop after this many items. None = fetch all.
            delay: Seconds to wait between requests.

        Returns:
            List of paths to saved files.
        """
        tv_dir = os.path.join(self.output_dir, "TV")
        video_dir = os.path.join(self.output_dir, "Video")
        os.makedirs(tv_dir, exist_ok=True)
        os.makedirs(video_dir, exist_ok=True)

        if self.download_videos and not self._ytdlp_available():
            print("WARNING: --download-videos requested but yt-dlp is not installed.")
            print("Install it with: pip install yt-dlp\n")

        search_fn = {
            "all": self.search_all,
            "tv": self.search_tv,
            "video": self.search_video,
        }[source]

        saved = []
        seen = set()
        skipped = 0
        start = 0

        while True:
            num_found, docs = search_fn(start=start)
            if start == 0:
                print(f'Found {num_found} total results for "{self.name}" ({source})\n')
            if not docs:
                break

            for doc in docs:
                if max_results and len(saved) >= max_results:
                    self._print_summary(saved, skipped)
                    return saved

                identifier = doc["identifier"]
                if identifier in seen:
                    continue
                seen.add(identifier)

                title = doc.get("title", identifier)
                date = self._parse_date(doc.get("date"))
                is_tv = self._is_tv(doc)
                tag = "TV" if is_tv else "Video"
                safe_title = self._safe_filename(title)

                print(f"[{len(saved)+1}] [{tag}] {date} - {title}")

                time.sleep(delay)
                try:
                    if is_tv:
                        transcript = self._extract_tv_transcript(identifier)
                        if not transcript:
                            print(f"  ! No caption text found, skipping.")
                            skipped += 1
                            continue

                        out_name = f"{date}_{safe_title}.txt"
                        out_path = os.path.join(tv_dir, out_name)
                        with open(out_path, "w", encoding="utf-8") as f:
                            f.write(transcript)
                        print(f"  Saved: TV/{out_name}")
                        saved.append(out_path)

                        # Save JSON metadata
                        meta_name = f"{date}_{safe_title}_metadata.json"
                        meta_path = os.path.join(tv_dir, meta_name)
                        with open(meta_path, "w", encoding="utf-8") as f:
                            json.dump({
                                "identifier": identifier,
                                "title": title,
                                "date": date,
                                "type": "tv",
                                "archive_url": f"https://archive.org/details/{identifier}",
                                "collection": doc.get("collection", []),
                            }, f, indent=2)

                    else:
                        # Always save the description/metadata text file
                        text, meta = self._extract_video_transcript(identifier)
                        if text:
                            header_lines = []
                            if meta:
                                header_lines.append(f"Title: {meta.get('title', title)}")
                                if meta.get("channel"):
                                    header_lines.append(f"Channel: {meta['channel']}")
                                if meta.get("upload_date"):
                                    header_lines.append(f"Upload Date: {meta['upload_date']}")
                                if meta.get("duration"):
                                    header_lines.append(f"Duration: {meta['duration']}s")
                                if meta.get("url"):
                                    header_lines.append(f"URL: {meta['url']}")
                                header_lines.append(f"Archive: https://archive.org/details/{identifier}")
                                header_lines.append("")
                                header_lines.append("---")
                                header_lines.append("")
                            content = "\n".join(header_lines) + text

                            out_name = f"{date}_{safe_title}.txt"
                            out_path = os.path.join(video_dir, out_name)
                            with open(out_path, "w", encoding="utf-8") as f:
                                f.write(content)
                            print(f"  Saved: Video/{out_name}")
                            saved.append(out_path)

                        # Save JSON metadata
                        video_meta_obj = {
                            "identifier": identifier,
                            "title": title,
                            "date": date,
                            "type": "video",
                            "archive_url": f"https://archive.org/details/{identifier}",
                            "collection": doc.get("collection", []),
                        }
                        if meta:
                            video_meta_obj.update(meta)
                        meta_name = f"{date}_{safe_title}_metadata.json"
                        meta_path = os.path.join(video_dir, meta_name)
                        with open(meta_path, "w", encoding="utf-8") as f:
                            json.dump(video_meta_obj, f, indent=2)

                        # Download the actual video file if requested
                        if self.download_videos and self._ytdlp_available():
                            vid_path = self._download_video_with_ytdlp(
                                identifier, video_dir, date, safe_title
                            )
                            if vid_path:
                                print(f"  Downloaded video: {os.path.basename(vid_path)}")
                                saved.append(vid_path)
                            else:
                                print(f"  ! Video download failed")

                        if not text and not self.download_videos:
                            print(f"  ! No description/transcript found, skipping.")
                            skipped += 1
                            continue

                except requests.HTTPError as e:
                    print(f"  ! Download failed: {e}")
                    skipped += 1
                    continue

            start += self.rows
            if start >= num_found:
                break

        self._print_summary(saved, skipped)
        return saved

    def _print_summary(self, saved, skipped):
        tv_count = sum(1 for p in saved if "/TV/" in p)
        vid_count = sum(1 for p in saved if "/Video/" in p)
        print(f"\nDone. {len(saved)} files saved ({tv_count} TV, {vid_count} Video), {skipped} skipped.")
        print(f"Output: {self.output_dir}/")


# Keep backward compatibility
TVArchiveScraper = ArchiveScraper
