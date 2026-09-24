#!/usr/bin/env python3
"""
Extract YouTube video transcripts (one or many videos).

Usage:
  extract-transcript.py URL_OR_ID [URL_OR_ID ...] [--lang CODE] [--out-dir DIR] [--timestamps]
  extract-transcript.py URL_OR_ID --list     (list available transcripts)

Accepts full URLs (youtube.com/watch?v=, youtu.be/, /shorts/, /live/, /embed/)
or bare 11-character video IDs. Duplicate videos are fetched once.

Requires youtube-transcript-api >= 1.0.
"""

import argparse
import json
import os
import re
import sys
import urllib.request

from youtube_transcript_api import (
    NoTranscriptFound,
    TranscriptsDisabled,
    YouTubeTranscriptApi,
)

try:
    from youtube_transcript_api import IpBlocked, RequestBlocked
    BLOCKED_ERRORS = (IpBlocked, RequestBlocked)
except ImportError:
    BLOCKED_ERRORS = ()

ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
URL_PATTERN = re.compile(
    r"(?:v=|youtu\.be/|/shorts/|/live/|/embed/)([A-Za-z0-9_-]{11})"
)


def parse_video_id(value):
    """Return the 11-character video ID from a URL or bare ID, or None."""
    match = URL_PATTERN.search(value)
    if match:
        return match.group(1)
    if ID_PATTERN.match(value):
        return value
    return None


def fetch_metadata(video_id):
    """Fetch title and channel via oEmbed (no API key). Best effort."""
    url = (
        "https://www.youtube.com/oembed?format=json&url="
        f"https://www.youtube.com/watch?v={video_id}"
    )
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.load(resp)
        return {"title": data.get("title", "?"), "channel": data.get("author_name", "?")}
    except Exception:
        return {"title": "?", "channel": "?"}


def format_segment(segment, timestamps):
    if not timestamps:
        return segment.text
    total = int(segment.start)
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    stamp = f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"
    return f"[{stamp}] {segment.text}"


def extract_transcript(api, video_id, languages, timestamps):
    """Return (text, error). Exactly one of them is None."""
    try:
        fetched = api.fetch(video_id, languages=languages)
    except TranscriptsDisabled:
        return None, "transcripts are disabled"
    except NoTranscriptFound:
        return None, f"no transcript found for languages {languages}"
    except BLOCKED_ERRORS:
        return None, (
            "YouTube is blocking requests from this IP (common on cloud/CI hosts). "
            "Run from a residential network, or fall back to Mode B/C"
        )
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''}"

    separator = "\n" if timestamps else " "
    return separator.join(format_segment(s, timestamps) for s in fetched), None


def list_available_transcripts(api, video_id):
    """List all available transcripts for a video"""
    try:
        transcript_list = api.list(video_id)
        print(f"✅ Available transcripts for {video_id}:")
        for transcript in transcript_list:
            generated = "[Auto-generated]" if transcript.is_generated else "[Manual]"
            translatable = "(translatable)" if transcript.is_translatable else ""
            print(f"  - {transcript.language} ({transcript.language_code}) {generated} {translatable}")
        return True
    except Exception as e:
        print(f"❌ Error listing transcripts: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Extract YouTube transcripts")
    parser.add_argument("videos", nargs="+", help="YouTube URLs or video IDs")
    parser.add_argument("--lang", default="en", help="preferred language code (falls back to en)")
    parser.add_argument("--out-dir", help="write one <video_id>.txt per video instead of stdout")
    parser.add_argument("--timestamps", action="store_true", help="prefix each line with [mm:ss]")
    parser.add_argument("--list", action="store_true", help="list available transcripts and exit")
    args = parser.parse_args()

    video_ids = []
    for value in args.videos:
        video_id = parse_video_id(value)
        if not video_id:
            print(f"❌ Not a YouTube URL or video ID: {value}", file=sys.stderr)
            sys.exit(1)
        if video_id not in video_ids:
            video_ids.append(video_id)

    api = YouTubeTranscriptApi()

    if args.list:
        results = [list_available_transcripts(api, v) for v in video_ids]
        sys.exit(0 if all(results) else 1)

    languages = [args.lang] if args.lang == "en" else [args.lang, "en"]
    multiple = len(video_ids) > 1
    if args.out_dir:
        os.makedirs(args.out_dir, exist_ok=True)

    failures = 0
    for video_id in video_ids:
        meta = fetch_metadata(video_id) if (multiple or args.out_dir) else None
        text, error = extract_transcript(api, video_id, languages, args.timestamps)
        if error:
            failures += 1
            print(f"❌ {video_id}: {error}", file=sys.stderr)
            continue

        header = ""
        if meta:
            header = (
                f"# {meta['title']}\n# Channel: {meta['channel']}\n"
                f"# URL: https://youtu.be/{video_id}\n\n"
            )

        if args.out_dir:
            path = os.path.join(args.out_dir, f"{video_id}.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(header + text + "\n")
            print(f"✅ {video_id}: {len(text.split())} words → {path}", file=sys.stderr)
        else:
            print(header + text)
            if multiple:
                print("\n" + "=" * 80 + "\n")

    if failures:
        print(f"⚠️  {failures}/{len(video_ids)} video(s) failed", file=sys.stderr)
    sys.exit(1 if failures == len(video_ids) else 0)


if __name__ == "__main__":
    main()
