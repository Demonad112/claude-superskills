# Changelog - youtube-summarizer

All notable changes to the youtube-summarizer skill will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.2.0] - 2026-09-24

### 🐛 Fixed

- **`extract-transcript.py` broken on youtube-transcript-api 1.x** — `get_transcript()` / `list_transcripts()` were removed upstream, so every fresh install failed. Migrated to `YouTubeTranscriptApi().fetch()` / `.list()` and pinned `youtube-transcript-api>=1.0`.
- SKILL.md Mode A snippets updated to the same API.

### ✨ Added

- **Multi-URL batch mode** — pass several URLs/IDs in one call; duplicates are fetched once.
- Accepts full URLs (`youtu.be/`, `watch?v=`, `/shorts/`, `/live/`, `/embed/`, `?si=` tracking params) as well as bare IDs.
- `--out-dir` (one file per video with title/channel header via oEmbed), `--timestamps` (`[mm:ss]` prefixes for citations).
- Explicit IP-block error message (cloud/CI hosts) pointing to Mode B/C.

---

## [1.2.1] - 2026-02-04

### 🐛 Fixed

- **Exit code propagation in `--list` mode**
  - **Issue:** Script always exited with status 0 even when `list_available_transcripts()` failed
  - **Risk:** Broke automation pipelines that rely on exit codes to detect failures
  - **Root Cause:** Return value from `list_available_transcripts()` was ignored
  - **Solution:** Now properly checks return value and exits with code 1 on failure
  - **Impact:** Scripts in automation can now correctly detect when transcript listing fails (invalid video ID, network errors, etc.)

### 🔧 Changed

- `extract-transcript.py` (lines 58-60)
  - Before: `list_available_transcripts(video_id); sys.exit(0)`
  - After: `success = list_available_transcripts(video_id); sys.exit(0 if success else 1)`

### 📝 Notes

- **Breaking Change:** None - only affects error handling behavior
- **Backward Compatibility:** Scripts that check exit codes will now work correctly
- **Migration:** No changes needed for existing users

---

## [1.2.0] - 2026-02-04

### ✨ Added

- Intelligent prompt workflow integration
- LLM processing with Claude CLI or GitHub Copilot CLI
- Progress indicators with rich terminal UI
- Multiple output formats
- Enhanced error handling

### 🔧 Changed

- Major refactor of transcript extraction logic
- Improved documentation in SKILL.md
- Updated installation requirements

---

## [1.0.0] - 2025-02-01

### ✨ Initial Release

- YouTube transcript extraction
- Language detection and selection
- Basic summarization
- Markdown output format
- Support for multiple languages
