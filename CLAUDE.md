# YouTube Channel Scraper — Development Plan

---

## Architecture Overview

Three layers: **Scraper → Processing → Storage**, with PostgreSQL as the metadata backbone and the NAS for raw files.

---

## 1. Database Schema (PostgreSQL)

5 tables. No SHA256 or random hashes anywhere.

**`channels`**
- `id`, `channel_id` (YT channel ID, unique), `name`, `url`, `last_scraped_at`

**`videos`** — core table
- `id`, `internal_id` (unique — format: `cccc-ddmmyyyy-hhmmss-nnnn`, e.g. `BBCNews-25032026-143022-1`)
- `yt_video_id` (YouTube's official ID, unique)
- `channel_id` (FK → channels)
- `title`, `description`
- `duration` (seconds), `view_count`, `like_count`
- `thumbnail_url`, `nas_file_path`, `uploaded_at`
- `captions` (JSONB — `{"en": {"text": "...", "source": "auto|manual"}}`)
- `status` (`pending | processing | processed | failed`)

**`comments`**
- `id`, `video_id` (FK), `comment_id` (YT comment ID, unique)
- `author`, `text`, `like_count`, `reply_to` (nullable — parent comment_id for threaded replies), `published_at`

**`related_videos`**
- `id`, `video_id` (FK), `related_video_id` (YT video ID), `relation_type` (`suggested | end-screen | description-linked`)

**`linked_articles`**
- `id`, `video_id` (FK), `url`, `domain`, `title`, `found_in` (`description | pinned-comment`)

---

## 2. Video Internal ID Format

Format: `cccc-ddmmyyyy-hhmmss-nnnn`

- `cccc` — channel source name (e.g. `BBCNews`)
- `ddmmyyyy` — upload date of the video
- `hhmmss` — upload time of the video
- `nnnn` — chronological sequence number, assigned per-channel in upload order

Generated at insert time by the worker using `upload_date` + `upload_timestamp` from yt-dlp and a per-channel counter query.

---

## 3. Scraping Layer (`scraper/ytdlp.py`)

Uses the **yt-dlp Python API** (not subprocess).

**Phase A — Channel enumeration (`enumerate_channel`):**
- Flat playlist extraction — yields `VideoEntry(video_id, title)` for every video without downloading anything.

**Phase B — Per-video metadata (`get_video_metadata`):**
- Full info extraction (no download) — returns `VideoMetadata` dataclass with all fields needed to populate `videos`.

**Phase B (captions) — `fetch_captions`:**
- Tries manual subs first, falls back to auto-generated.
- Writes `.vtt` file to NAS alongside the video.
- Returns `(text, source)` — source is `"manual"` or `"auto"`.

**Phase C — Video download (`download_video`):**
- Downloads at max 1080p, merges to `.mp4`.
- Writes `.info.json` backup alongside the video on NAS.
- Returns the final file path for `videos.nas_file_path`.

**Phase D — Comments:**
- YouTube Data API v3 (`commentThreads.list`) — 10,000 units/day free quota.
- Fallback: `yt-dlp --write-comments` (no API key needed, slower).

**Phase E — Linked articles:**
- Parse `description` and pinned comment for non-YouTube URLs.
- Fetch `<title>` tag from each URL for `linked_articles.title`.

---

## 4. Impressions — Reality Check

YouTube does **not** expose impression data via any public API or yt-dlp. Only available to the channel owner via YouTube Analytics API (OAuth2). Use `view_count` and `like_count` as public substitutes.

---

## 5. Orchestration (`workers/tasks.py`)

**Stack:** Celery + Redis (sync workers — same pattern as existing article ingestion system).

**Worker flow per video:**
1. Check if `yt_video_id` exists in DB → skip if `status = processed`, re-queue if `failed`
2. Fetch metadata → build `internal_id` → insert into `videos` with `status = processing`
3. Fetch captions → update `videos.captions` JSONB
4. Download video to NAS → update `videos.nas_file_path`
5. Fetch comments → bulk insert into `comments`
6. Extract URLs from description → insert into `related_videos` and `linked_articles`
7. Set `videos.status = processed`

**Rate limiting:** 3-second delay between yt-dlp requests (`REQUEST_DELAY_SECONDS` in settings). For large channels (1000+ videos), spread over hours.

---

## 6. NAS Storage Layout

```
/volume1/youtube-archive/
  └── {channel_id}/
      ├── {video_id}.mp4
      ├── {video_id}.en.vtt       (caption file backup)
      └── {video_id}.info.json    (raw metadata backup)
```

---

## 7. Database Setup

- `init_db()` in `db/database.py` — creates the PostgreSQL database if it doesn't exist, then runs `alembic upgrade head`.
- Never use `Base.metadata.create_all()` — all schema changes go through Alembic migrations.
- Add new columns via `alembic revision --autogenerate -m "description"`.

---

## 8. Development Phases

**Phase 1 — Foundation:** PostgreSQL schema + Alembic + yt-dlp wrapper. ✅ Done.

**Phase 2 — Bulk pipeline:** Celery tasks, channel enumeration loop, NAS writes, idempotency checks.

**Phase 3 — Comments + articles:** YouTube Data API for comments, URL extraction, article title fetching.

**Phase 4 — Resilience:** Retry logic, resume support for interrupted runs, logging, CLI status summary.

---

## Key Decisions Made

- **Sync over async:** Celery workers are sync — SQLAlchemy + psycopg2, not asyncpg.
- **Captions as JSONB on `videos`:** No separate captions table. Multi-language ready.
- **No SHA256 / random hashes:** All IDs are human-readable (`internal_id` format above).
- **1080p quality cap:** `bestvideo[height<=1080]+bestaudio/best`, merged to mp4.
- **Incremental scraping:** `last_scraped_at` per channel; only process new videos on re-runs.
- **YouTube Data API for comments:** Cleaner data and quota management over `--write-comments`.
