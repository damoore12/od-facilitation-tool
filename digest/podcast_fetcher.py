#!/usr/bin/env python3
"""Podcast RSS fetcher → Whisper transcription → Claude CPO summary."""

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import requests
from anthropic import Anthropic
from openai import OpenAI

from prompts import PODCAST_SUMMARY_SYSTEM, PODCAST_SUMMARY_PROMPT

SEVEN_DAYS_AGO = datetime.now(timezone.utc) - timedelta(days=7)
MAX_AUDIO_BYTES = 25 * 1024 * 1024  # 25 MB Whisper API hard limit
MAX_TRANSCRIPT_CHARS = 10_000       # ~2,500 tokens; enough for a solid summary


def fetch_podcast_summaries(podcast_configs: list[dict]) -> list[dict]:
    """Return CPO-focused summaries for new episodes from the past 7 days."""
    summaries = []
    for podcast in podcast_configs:
        try:
            episodes = _get_new_episodes(podcast)
            if not episodes:
                print(f"    No new episodes: {podcast['name']}")
                continue
            episode = episodes[0]  # one episode per show per week
            print(f"    Transcribing: {podcast['name']} — {episode['title'][:55]}")
            transcript = _transcribe(episode["audio_url"])
            if not transcript:
                continue
            summary = _summarize(episode, podcast, transcript)
            if summary:
                summaries.append({**episode, **summary, "show": podcast["name"]})
        except Exception as exc:
            print(f"    [warn] Skipping {podcast['name']}: {exc}")
    return summaries


def _get_new_episodes(podcast: dict) -> list[dict]:
    parsed = feedparser.parse(podcast["url"])
    episodes = []
    for entry in parsed.entries:
        published = _parse_date(entry)
        if published and published < SEVEN_DAYS_AGO:
            break  # feeds are newest-first; stop at first old entry

        audio_url = _extract_audio_url(entry)
        if not audio_url:
            continue

        episodes.append({
            "title": entry.get("title", "Untitled"),
            "url": entry.get("link", ""),
            "audio_url": audio_url,
            "published": published.strftime("%B %d, %Y") if published else "",
        })
    return episodes


def _parse_date(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        val = getattr(entry, attr, None)
        if val:
            return datetime(*val[:6], tzinfo=timezone.utc)
    return None


def _extract_audio_url(entry) -> str | None:
    for enc in entry.get("enclosures", []):
        if enc.get("type", "").startswith("audio/"):
            return enc.get("href")
    return None


def _transcribe(audio_url: str) -> str | None:
    """Download audio (up to MAX_AUDIO_BYTES) and return Whisper transcript."""
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    resp = requests.get(audio_url, stream=True, timeout=120)
    resp.raise_for_status()

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        downloaded = 0
        for chunk in resp.iter_content(chunk_size=65_536):
            tmp.write(chunk)
            downloaded += len(chunk)
            if downloaded >= MAX_AUDIO_BYTES:
                break  # truncate — still yields a useful partial transcript
        tmp_path = tmp.name

    try:
        with open(tmp_path, "rb") as audio_file:
            result = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="text",
            )
        return result[:MAX_TRANSCRIPT_CHARS]
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _summarize(episode: dict, podcast: dict, transcript: str) -> dict | None:
    """Return Claude-generated CPO summary dict or None on failure."""
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model="claude-sonnet-5-20251101",
        max_tokens=512,
        system=PODCAST_SUMMARY_SYSTEM,
        messages=[{
            "role": "user",
            "content": PODCAST_SUMMARY_PROMPT.format(
                show=podcast["name"],
                title=episode["title"],
                host=podcast.get("host", podcast["name"]),
                transcript=transcript,
            ),
        }],
    )
    try:
        return json.loads(response.content[0].text)
    except (json.JSONDecodeError, IndexError, KeyError):
        return None
