import os
import re
import time
import requests


SEARCH_URL = "https://archive.org/advancedsearch.php"
DETAILS_URL = "https://archive.org/details"


class TVArchiveScraper:
    """Pull closed-caption transcripts from the Internet Archive TV News Archive."""

    def __init__(self, name, output_dir=None, rows=50, sort="date desc"):
        """
        Args:
            name: Politician name to search for (e.g. "Bernie Sanders").
            output_dir: Override output folder. Defaults to "{name} TV archive transcripts".
            rows: Max number of results per search page.
            sort: Sort order for results.
        """
        self.name = name
        self.output_dir = output_dir or f"{name} TV archive transcripts"
        self.rows = rows
        self.sort = sort
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "tv-archive-transcripts/1.0"})

    def search(self, start=0):
        """Search the TV Archive for mentions of self.name. Returns list of docs."""
        params = {
            "q": f'collection:tvarchive "{self.name}"',
            "fl[]": ["identifier", "title", "date"],
            "sort[]": self.sort,
            "rows": self.rows,
            "start": start,
            "output": "json",
        }
        resp = self.session.get(SEARCH_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data["response"]["numFound"], data["response"]["docs"]

    def _extract_transcript_from_details(self, identifier):
        """Fetch the details page and extract caption text from embedded snippets."""
        url = f"{DETAILS_URL}/{identifier}"
        resp = self.session.get(url, timeout=60)
        resp.raise_for_status()

        # Caption text is in <div class="snipin ..."> elements
        snippets = re.findall(
            r'<div class="snipin[^"]*"[^>]*>(.*?)</div>', resp.text, re.DOTALL
        )
        if not snippets:
            return None

        lines = []
        for s in snippets:
            # Clean HTML entities and extra whitespace
            text = s.strip()
            text = text.replace("&amp;", "&")
            text = text.replace("&lt;", "<")
            text = text.replace("&gt;", ">")
            text = text.replace("&quot;", '"')
            text = text.replace("&#39;", "'")
            text = re.sub(r"<[^>]+>", "", text)  # strip any remaining tags
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                lines.append(text)

        return "\n\n".join(lines) if lines else None

    @staticmethod
    def _parse_date(date_str):
        """Extract YYYY-MM-DD from an ISO date string."""
        if not date_str:
            return "unknown-date"
        return date_str[:10]

    @staticmethod
    def _safe_filename(text, max_len=120):
        """Sanitize a string for use as a filename."""
        text = re.sub(r'[<>:"/\\|?*]', "", text)
        text = text.strip(". ")
        return text[:max_len]

    def download_all(self, max_results=None, delay=1.0):
        """
        Search and download all transcripts.

        Args:
            max_results: Stop after this many items. None = fetch all.
            delay: Seconds to wait between requests.

        Returns:
            List of paths to saved transcript files.
        """
        os.makedirs(self.output_dir, exist_ok=True)
        saved = []
        skipped = 0
        start = 0

        while True:
            num_found, docs = self.search(start=start)
            if not docs:
                break

            for doc in docs:
                if max_results and len(saved) >= max_results:
                    print(f"\nDone. {len(saved)} transcripts saved to: {self.output_dir}/")
                    return saved

                identifier = doc["identifier"]
                title = doc.get("title", identifier)
                date = self._parse_date(doc.get("date"))

                print(f"[{len(saved)+1}] {date} - {title}")

                time.sleep(delay)
                try:
                    transcript = self._extract_transcript_from_details(identifier)
                except requests.HTTPError as e:
                    print(f"  ! Download failed: {e}")
                    skipped += 1
                    continue

                if not transcript:
                    print(f"  ! No caption text found, skipping.")
                    skipped += 1
                    continue

                safe_title = self._safe_filename(title)
                out_name = f"{date}_{safe_title}.txt"
                out_path = os.path.join(self.output_dir, out_name)

                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(transcript)

                print(f"  Saved: {out_name}")
                saved.append(out_path)

            start += self.rows
            if start >= num_found:
                break

        print(f"\nDone. {len(saved)} transcripts saved, {skipped} skipped.")
        print(f"Output: {self.output_dir}/")
        return saved
