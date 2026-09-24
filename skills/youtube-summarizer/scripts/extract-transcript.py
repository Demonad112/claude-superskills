#!/usr/bin/env python3
"""
Extract YouTube video transcripts (one or many videos).

Usage:
  extract-transcript.py URL_OR_ID [URL_OR_ID ...] [--lang CODE] [--out-dir DIR] [--timestamps]
  extract-transcript.py URL_OR_ID --list     (list available transcripts)

Accepts full URLs (youtube.com/watch?v=, youtu.be/, /shorts/, /live/, /embed/)
or bare 11-character video IDs. Duplicate videos are fetched once.

Providers (--provider):
  youtube   fetch directly from YouTube (default when SUPADATA_API_KEY is unset)
  supadata  fetch via the Supadata transcript API (needs SUPADATA_API_KEY);
            works on cloud/CI hosts that YouTube IP-blocks
  auto      try YouTube first, fall back to Supadata when blocked
            (default when SUPADATA_API_KEY is set)

Requires youtube-transcript-api >= 1.0.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
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


SUPADATA_BASE = "https://api.supadata.ai/v1"


class Blocked(Exception):
    """YouTube refused the request from this IP."""


def supadata_request(path, api_key):
    request = urllib.request.Request(
        f"{SUPADATA_BASE}{path}", headers={"x-api-key": api_key}
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            body = json.load(e)
        except Exception:
            body = {}
        return e.code, body


def fetch_supadata(video_id, language, api_key, mode, timeout=600):
    """Return a list of segments (with .start seconds and .text) from Supadata."""
    query = urllib.parse.urlencode({
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "lang": language,
        "mode": mode,
    })
    status, body = supadata_request(f"/transcript?{query}", api_key)

    if status == 202 and "jobId" in body:
        job_id = body["jobId"]
        deadline = time.time() + timeout
        while True:
            time.sleep(1)
            status, body = supadata_request(f"/transcript/{job_id}", api_key)
            if body.get("status") == "completed":
                break
            if body.get("status") == "failed" or time.time() > deadline:
                raise RuntimeError(f"Supadata job {body.get('status', 'timed out')}: {body.get('error', '')}")
    elif status != 200:
        detail = body.get("message") or body.get("error") or body
        raise RuntimeError(f"Supadata HTTP {status}: {detail}")

    return [
        SimpleSegment(start=chunk.get("offset", 0) / 1000, text=chunk.get("text", ""))
        for chunk in body.get("content", [])
    ]


class SimpleSegment:
    def __init__(self, start, text):
        self.start = start
        self.text = text


def fetch_youtube(api, video_id, languages):
    try:
        return api.fetch(video_id, languages=languages)
    except BLOCKED_ERRORS as e:
        raise Blocked() from e


def extract_transcript(api, video_id, languages, timestamps, provider="youtube",
                       api_key=None, mode="native"):
    """Return (text, source, error). text/source are None on error."""
    try:
        if provider == "supadata":
            fetched, source = fetch_supadata(video_id, languages[0], api_key, mode), "supadata"
        else:
            try:
                fetched, source = fetch_youtube(api, video_id, languages), "youtube"
            except Blocked:
                if provider != "auto":
                    raise
                fetched, source = fetch_supadata(video_id, languages[0], api_key, mode), "supadata"
    except TranscriptsDisabled:
        return None, None, "transcripts are disabled"
    except NoTranscriptFound:
        return None, None, f"no transcript found for languages {languages}"
    except Blocked:
        return None, None, (
            "YouTube is blocking requests from this IP (common on cloud/CI hosts). "
            "Set SUPADATA_API_KEY and use --provider auto/supadata, run from a "
            "residential network, or fall back to Mode B/C"
        )
    except Exception as e:
        return None, None, f"{type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''}"

    separator = "\n" if timestamps else " "
    return separator.join(format_segment(s, timestamps) for s in fetched), source, None


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
    parser.add_argument("videos", nargs="*", help="YouTube URLs or video IDs")
    parser.add_argument("--lang", default="en", help="preferred language code (falls back to en)")
    parser.add_argument("--out-dir", help="write one <video_id>.txt per video instead of stdout")
    parser.add_argument("--timestamps", action="store_true", help="prefix each line with [mm:ss]")
    parser.add_argument("--list", action="store_true", help="list available transcripts and exit")
    parser.add_argument("--provider", choices=["youtube", "supadata", "auto"],
                        help="transcript source (default: auto if SUPADATA_API_KEY is set, else youtube)")
    parser.add_argument("--mode", choices=["native", "auto", "generate"], default="native",
                        help="Supadata mode: native = existing captions only (cheapest); "
                             "auto/generate allow AI transcription (costs more credits)")
    # Video IDs can start with "-" (e.g. -R5KjDJQu9w), which argparse would
    # treat as options, so pull them out before parsing.
    dash_ids = [a for a in sys.argv[1:] if a.startswith("-") and ID_PATTERN.match(a)]
    args = parser.parse_args([a for a in sys.argv[1:] if a not in dash_ids])
    args.videos += dash_ids
    if not args.videos:
        parser.error("at least one YouTube URL or video ID is required")

    api_key = os.environ.get("SUPADATA_API_KEY")
    provider = args.provider or ("auto" if api_key else "youtube")
    if provider in ("supadata", "auto") and not api_key:
        print(f"❌ --provider {provider} needs the SUPADATA_API_KEY environment variable", file=sys.stderr)
        sys.exit(1)

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
        text, source, error = extract_transcript(
            api, video_id, languages, args.timestamps, provider, api_key, args.mode
        )
        if error:
            failures += 1
            print(f"❌ {video_id}: {error}", file=sys.stderr)
            continue

        header = ""
        if meta:
            header = (
                f"# {meta['title']}\n# Channel: {meta['channel']}\n"
                f"# URL: https://youtu.be/{video_id}\n# Source: {source}\n\n"
            )

        if args.out_dir:
            path = os.path.join(args.out_dir, f"{video_id}.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(header + text + "\n")
            print(f"✅ {video_id} ({source}): {len(text.split())} words → {path}", file=sys.stderr)
        else:
            print(header + text)
            if multiple:
                print("\n" + "=" * 80 + "\n")

    if failures:
        print(f"⚠️  {failures}/{len(video_ids)} video(s) failed", file=sys.stderr)
    sys.exit(1 if failures == len(video_ids) else 0)


if __name__ == "__main__":
    main()
