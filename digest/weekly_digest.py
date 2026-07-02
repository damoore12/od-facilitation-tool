#!/usr/bin/env python3
"""
CPO Weekly Thought Leadership Digest
Fetches HR/People & Culture content, scores it with Claude, and delivers
a curated HTML email digest every Monday morning.

Usage:
  python weekly_digest.py           # Fetch, score, and send email
  python weekly_digest.py --dry-run # Render to digest_YYYYMMDD.html, no send
"""

import argparse
import json
import os
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import feedparser
import requests
import yaml
from anthropic import Anthropic
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader

from podcast_fetcher import fetch_podcast_summaries
from prompts import ARTICLE_SCORING_SYSTEM, ARTICLE_SCORING_PROMPT

DIGEST_DIR = Path(__file__).parent
SEVEN_DAYS_AGO = datetime.now(timezone.utc) - timedelta(days=7)
BATCH_SIZE = 10
BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"

CATEGORIES = [
    "Workforce Strategy & Planning",
    "Org Design & Change",
    "Talent & Succession",
    "Culture & Employee Experience",
    "Leadership Development",
    "Total Rewards",
    "DEI & Belonging",
    "HR Technology & AI",
    "Learning & Development",
]


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="CPO Weekly Digest Generator")
    parser.add_argument("--dry-run", action="store_true",
                        help="Render to HTML file instead of sending email")
    args = parser.parse_args()

    week_date = datetime.now().strftime("%B %d, %Y")
    print(f"\n=== CPO Weekly Digest — {week_date} ===\n")

    sources = _load_sources()

    print(f"[1/4] Fetching articles from {len(sources['feeds'])} sources...")
    articles = _fetch_articles(sources["feeds"])
    print(f"      {len(articles)} articles found in the past 7 days")

    print("[2/4] Scoring articles with Claude...")
    scored = _score_articles(articles)
    print(f"      {len(scored)} articles scored 3+ (CPO-relevant)")

    print(f"[3/4] Processing podcasts from {len(sources['podcasts'])} shows...")
    podcasts = fetch_podcast_summaries(sources["podcasts"])
    print(f"      {len(podcasts)} podcast episodes summarized")

    print("[4/4] Rendering digest...")
    by_category = _group_by_category(scored)
    html = _render(by_category, podcasts, week_date)

    if args.dry_run:
        out = DIGEST_DIR / f"digest_{datetime.now().strftime('%Y%m%d')}.html"
        out.write_text(html, encoding="utf-8")
        print(f"\nDry run complete. Open in browser:\n  {out}\n")
    else:
        _send_email(html, week_date)
        recipients = os.environ.get("EMAIL_TO", "")
        print(f"\nDigest delivered to: {recipients}\n")


def _load_sources() -> dict:
    with open(DIGEST_DIR / "sources.yaml") as f:
        return yaml.safe_load(f)


def _fetch_feed(url: str):
    """Fetch a feed using a browser User-Agent to avoid bot-blocking."""
    try:
        resp = requests.get(url, headers={"User-Agent": BROWSER_UA}, timeout=15, allow_redirects=True)
        return feedparser.parse(resp.text)
    except Exception:
        return feedparser.parse(url)  # fall back to direct feedparser


def _fetch_articles(feeds: list[dict]) -> list[dict]:
    articles = []
    for feed_cfg in feeds:
        try:
            parsed = _fetch_feed(feed_cfg["url"])
            for entry in parsed.entries:
                published = _parse_date(entry)
                if published and published < SEVEN_DAYS_AGO:
                    continue
                articles.append({
                    "title": entry.get("title", "").strip(),
                    "url": entry.get("link", ""),
                    "summary": _clean_text(entry.get("summary", entry.get("description", "")))[:600],
                    "source": feed_cfg["name"],
                    "tier": feed_cfg.get("tier", 2),
                    "published": published.strftime("%b %d") if published else "",
                })
        except Exception as exc:
            print(f"    [warn] {feed_cfg['name']}: {exc}")
    return articles


def _score_articles(articles: list[dict]) -> list[dict]:
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    scored = []

    for i in range(0, len(articles), BATCH_SIZE):
        batch = articles[i:i + BATCH_SIZE]
        articles_text = "\n\n".join(
            f"[{j+1}] SOURCE: {a['source']} (Tier {a['tier']})\n"
            f"TITLE: {a['title']}\n"
            f"EXCERPT: {a['summary']}"
            for j, a in enumerate(batch)
        )
        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=4096,
                system=ARTICLE_SCORING_SYSTEM,
                messages=[{
                    "role": "user",
                    "content": ARTICLE_SCORING_PROMPT.format(articles=articles_text),
                }],
            )
            text_block = next((b for b in response.content if hasattr(b, "text")), None)
            if not text_block:
                raise ValueError("No text block in response")
            results = json.loads(text_block.text)
            for item in results:
                idx = item.get("index", 0) - 1
                if 0 <= idx < len(batch):
                    scored.append({
                        **batch[idx],
                        "score": item.get("score", 3),
                        "digest_summary": item.get("summary", ""),
                        "cpo_action": item.get("cpo_action", ""),
                        "category": item.get("category", "Workforce Strategy & Planning"),
                    })
        except Exception as exc:
            print(f"    [warn] Claude scoring batch {i//BATCH_SIZE + 1}: {exc}")

    return sorted(scored, key=lambda x: x["score"], reverse=True)


def _group_by_category(articles: list[dict]) -> dict:
    grouped = {cat: [] for cat in CATEGORIES}
    grouped["Other"] = []
    for article in articles:
        cat = article.get("category", "Other")
        bucket = cat if cat in grouped else "Other"
        grouped[bucket].append(article)
    return {k: v for k, v in grouped.items() if v}


def _render(by_category: dict, podcasts: list[dict], week_date: str) -> str:
    env = Environment(loader=FileSystemLoader(DIGEST_DIR), autoescape=True)
    template = env.get_template("email_template.html")
    return template.render(
        week_date=week_date,
        articles_by_category=by_category,
        podcasts=podcasts,
        total_articles=sum(len(v) for v in by_category.values()),
        total_podcasts=len(podcasts),
    )


def _send_email(html: str, week_date: str) -> None:
    recipients = [r.strip() for r in os.environ["EMAIL_TO"].split(",") if r.strip()]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"CPO Weekly Digest — {week_date}"
    msg["From"] = os.environ["EMAIL_FROM"]
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(os.environ["EMAIL_FROM"], os.environ["GMAIL_APP_PASSWORD"])
        server.sendmail(os.environ["EMAIL_FROM"], recipients, msg.as_string())


def _parse_date(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        val = getattr(entry, attr, None)
        if val:
            return datetime(*val[:6], tzinfo=timezone.utc)
    return None


def _clean_text(text: str) -> str:
    import re
    text = re.sub(r"<[^>]+>", " ", text)   # strip HTML tags
    text = re.sub(r"\s+", " ", text)        # collapse whitespace
    return text.strip()


if __name__ == "__main__":
    main()
