import requests
import sys
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.db import SessionLocal
from app.models import Article
from app.utils import extract_full_text, clean_for_summarization
from app.summarizer import generate_summary
from app.sentiment import get_dual_sentiment
from app.category_classifier import classify_category

NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
NEWSAPI_URL = "https://newsapi.org/v2/top-headlines"
COUNTRIES = ["us", "sg", "gb"]  # Add more country codes as needed
PAGE_SIZE = 100  # Max is 100 per request

_fetch_status_lock = threading.Lock()
_fetch_status = {
    "state": "idle",
    "message": "Idle",
    "total": 0,
    "processed": 0,
    "started_at_utc": None,
    "finished_at_utc": None,
}
_fetch_stop_event = threading.Event()

def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _set_fetch_status(**updates):
    with _fetch_status_lock:
        _fetch_status.update(updates)


def get_fetch_status():
    with _fetch_status_lock:
        return dict(_fetch_status)

def mark_fetch_requested():
    _set_fetch_status(
        state="starting",
        message="Starting fetch...",
        total=0,
        processed=0,
        started_at_utc=_now_utc_iso(),
        finished_at_utc=None,
    )

def request_fetch_stop():
    _fetch_stop_event.set()

def clear_fetch_stop():
    _fetch_stop_event.clear()

def _should_stop_fetch() -> bool:
    return _fetch_stop_event.is_set()


def build_article(article, country):
    title = article.get("title")
    url = article.get("url")
    source = article.get("source", {}).get("name", "Unknown")
    published = article.get("publishedAt")
    image_url = article.get("urlToImage")

    full_text = extract_full_text(url)
    content_to_summarize = full_text if full_text else article.get("description", "No summary")
    if (source or "").lower() == "financial times":
        desc = article.get("description") or ""
        content = article.get("content") or ""
        print(f"[FT debug] url={url}")
        print(f"[FT debug] full_text_len={len(full_text)}")
        print(f"[FT debug] description_len={len(desc)} snippet={desc[:200]!r}")
        print(f"[FT debug] content_len={len(content)} snippet={content[:200]!r}")
    clean_text = clean_for_summarization(content_to_summarize)
    summary = generate_summary(clean_text)
    sentiment_emotional, sentiment_contextual, confidence, impact_level, impact_reason = get_dual_sentiment(title, summary)
    category = classify_category(f"{title} {summary}")

    try:
        published_at = datetime.strptime(published, "%Y-%m-%dT%H:%M:%SZ")
    except:
        published_at = datetime.utcnow()

    return Article(
        title=title,
        summary=summary,
        sentiment_emotional=sentiment_emotional,
        sentiment_contextual=sentiment_contextual,
        sentiment_confidence=confidence,
        impact_level=impact_level,
        impact_reason=impact_reason,
        image_url=image_url,
        source=source,
        url=url,
        category=category,
        country=country.upper(),
        published_at=published_at
    )


def fetch_and_store_articles():
    clear_fetch_stop()
    print("Starting fetch...")
    _set_fetch_status(
        state="starting",
        message="Starting fetch...",
        total=0,
        processed=0,
        started_at_utc=_now_utc_iso(),
        finished_at_utc=None,
    )
    if not NEWSAPI_KEY:
        msg = "NEWSAPI_KEY is not set. Skipping fetch."
        print(msg)
        _set_fetch_status(state="error", message=msg, finished_at_utc=_now_utc_iso())
        return

    db = SessionLocal()
    all_articles = []
    per_country_counts = {country: 0 for country in COUNTRIES}

    try:
        _set_fetch_status(state="fetching", message="Fetching articles from NewsAPI...")
        for country in COUNTRIES:
            print(f"Fetching top headlines for {country.upper()}...")
            if _should_stop_fetch():
                _set_fetch_status(
                    state="canceled",
                    message="Fetch canceled.",
                    finished_at_utc=_now_utc_iso(),
                )
                return
            for page in range(1, 2):  # 1 page of 100 results each
                print(f"Fetching {country.upper()} page {page}...")
                if _should_stop_fetch():
                    _set_fetch_status(
                        state="canceled",
                        message="Fetch canceled.",
                        finished_at_utc=_now_utc_iso(),
                    )
                    return
                params = {
                    "country": country,
                    "pageSize": PAGE_SIZE,
                    "page": page,
                    "apiKey": NEWSAPI_KEY,
                }
                response = requests.get(NEWSAPI_URL, params=params)
                if response.status_code != 200:
                    print(f"Error fetching from {country} page {page}:", response.status_code)
                    continue

                articles = response.json().get("articles", [])
                if not articles:
                    print(f"No articles returned for {country.upper()} page {page}.")
                    break

                for article in articles:
                    all_articles.append((article, country))
                    per_country_counts[country] += 1
            print(f"Fetched {per_country_counts[country]} articles for {country.upper()}.")

        urls = [article.get("url") for article, _ in all_articles if article.get("url")]
        existing_urls = set()
        if urls:
            existing_urls = {row[0] for row in db.query(Article.url).filter(Article.url.in_(urls)).all()}

        seen_urls = set()
        new_articles = []
        skipped_duplicates = 0
        for article, country in all_articles:
            url = article.get("url")
            if url:
                if url in existing_urls or url in seen_urls:
                    skipped_duplicates += 1
                    continue
                seen_urls.add(url)
            new_articles.append((article, country))

        if skipped_duplicates:
            print(f"Skipped {skipped_duplicates} duplicate articles.")
        total = len(new_articles)
        _set_fetch_status(
            state="processing",
            message=f"Processing 0/{total} articles",
            total=total,
            processed=0,
        )

        processed = 0
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(build_article, article, country) for article, country in new_articles]
            for future in as_completed(futures):
                if _should_stop_fetch():
                    _set_fetch_status(
                        state="canceled",
                        message="Fetch canceled.",
                        finished_at_utc=_now_utc_iso(),
                    )
                    return
                try:
                    new_article = future.result()
                except Exception as exc:
                    print("Error processing article:", exc)
                    processed += 1
                    _set_fetch_status(
                        processed=processed,
                        message=f"Processing {processed}/{total} articles",
                    )
                    continue

                if new_article:
                    try:
                        with db.begin_nested():
                            db.add(new_article)
                            db.flush()
                    except IntegrityError:
                        db.rollback()
                        skipped_duplicates += 1
                    else:
                        print(
                            f"Fetched news article {new_article.title}, from country: {new_article.country}, source: {new_article.source}"
                        )

                processed += 1
                _set_fetch_status(
                    processed=processed,
                    message=f"Processing {processed}/{total} articles",
                )

        db.commit()
        print(f"?. Stored {len(all_articles)} articles from {len(COUNTRIES)} countries.")
        _set_fetch_status(
            state="done",
            message=f"Stored {len(all_articles)} articles from {len(COUNTRIES)} countries.",
            finished_at_utc=_now_utc_iso(),
        )
    except Exception as exc:
        msg = f"Fetch failed: {exc}"
        print(msg)
        _set_fetch_status(state="error", message=msg, finished_at_utc=_now_utc_iso())
        raise
    finally:
        db.close()


if __name__ == "__main__":
    fetch_and_store_articles()
