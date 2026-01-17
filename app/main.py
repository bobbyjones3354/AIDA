from fastapi import FastAPI, Depends, Query
from sqlalchemy.orm import Session
from app.db import SessionLocal
from app.models import Article
from app.schema import ArticleOut
from app.news_fetcher import fetch_and_store_articles, get_fetch_status, request_fetch_stop, mark_fetch_requested
from typing import List, Optional
import threading
import schedule
import time
import os
from datetime import datetime, timezone

app = FastAPI()
_last_fetch_time_utc: Optional[str] = None
_LAST_FETCH_PATH = os.path.join(os.path.dirname(__file__), "last_fetch_time.txt")
_AUTO_FETCH_MIN_SECONDS = 2 * 60 * 60


def _parse_last_fetch_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _load_last_fetch_time():
    global _last_fetch_time_utc
    try:
        with open(_LAST_FETCH_PATH, "r", encoding="utf-8") as handle:
            value = handle.read().strip()
    except FileNotFoundError:
        return
    except OSError as exc:
        print(f"Could not read last fetch time: {exc}")
        return
    if value:
        _last_fetch_time_utc = value


def _save_last_fetch_time(value: str):
    try:
        with open(_LAST_FETCH_PATH, "w", encoding="utf-8") as handle:
            handle.write(value)
    except OSError as exc:
        print(f"Could not write last fetch time: {exc}")


def _record_fetch_time():
    global _last_fetch_time_utc
    _last_fetch_time_utc = datetime.now(timezone.utc).isoformat()
    _save_last_fetch_time(_last_fetch_time_utc)


def _should_auto_fetch() -> bool:
    last_fetch = _parse_last_fetch_time(_last_fetch_time_utc)
    if not last_fetch:
        return True
    age_seconds = (datetime.now(timezone.utc) - last_fetch).total_seconds()
    return age_seconds >= _AUTO_FETCH_MIN_SECONDS


_load_last_fetch_time()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/summaries", response_model=List[ArticleOut])
def read_articles(
    sentiment_contextual: Optional[str] = Query(None),
    sentiment_emotional: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    query = db.query(Article)
    if sentiment_contextual:
        query = query.filter(Article.sentiment_contextual == sentiment_contextual)
    if sentiment_emotional:
        query = query.filter(Article.sentiment_emotional == sentiment_emotional)
    if category:
        query = query.filter(Article.category == category)
    if source:
        query = query.filter(Article.source == source)
    return query.order_by(Article.published_at.desc()).all()

@app.post("/refresh-news")
def refresh_news():
    def _run_fetch():
        try:
            fetch_and_store_articles()
        except Exception as exc:
            print(f"Manual fetch failed: {exc}")
            return
        _record_fetch_time()

    mark_fetch_requested()
    thread = threading.Thread(target=_run_fetch, daemon=True)
    thread.start()
    return {"message": "News refresh started"}

@app.get("/last-fetch-time")
def last_fetch_time():
    return {"last_fetch_time_utc": _last_fetch_time_utc}

@app.get("/fetch-status")
def fetch_status():
    return get_fetch_status()


def run_scheduler():
    print("scheduler started")
    def _maybe_auto_fetch():
        if not _should_auto_fetch():
            return
        print(f"Auto-fetch starting at {datetime.now(timezone.utc).isoformat()}")
        try:
            fetch_and_store_articles()
        except Exception as exc:
            print(f"Scheduled fetch failed: {exc}")
            return
        _record_fetch_time()
        print("Auto-fetch finished.")

    schedule.every(2).hours.do(_maybe_auto_fetch)
    _maybe_auto_fetch()
    while True:
        schedule.run_pending()
        time.sleep(1)

@app.on_event("startup")
def start_background_news_scheduler():
    if os.getenv("RUN_MAIN") not in (None, "true"):
        return
    thread = threading.Thread(target=run_scheduler, daemon=True)
    thread.start()

@app.on_event("shutdown")
def stop_background_news_scheduler():
    request_fetch_stop()
