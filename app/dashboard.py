import time
import uuid
import os
import streamlit as st
import requests
import threading
import html
import re
import sys
from pathlib import Path
from datetime import timedelta
import pandas as pd
import altair as alt
from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError
from zoneinfo import ZoneInfo

_APP_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _APP_DIR.parent
for _path in (str(_ROOT_DIR), str(_APP_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

try:
    from app.digest_summary import generate_digest_summary
    from app.db import SessionLocal
    from app.models import UserStreak, UserRead
except Exception:
    try:
        from digest_summary import generate_digest_summary
        from db import SessionLocal
        from models import UserStreak, UserRead
    except Exception as exc:
        raise ImportError(f"Failed to import dashboard dependencies: {exc}") from exc


API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000")

st.set_page_config(layout="wide", page_title="AIDA News Dashboard")
welcome_banner = st.empty()
goal_streak_container = st.container()
st.title("AIDA News Summaries")
st.markdown(
    """
    <style>
    html {
        scroll-behavior: smooth;
    }
    .aida-metric {
        padding: 8px 0 8px 0;
    }
    .aida-metric .label {
        color: #6b7280;
        font-size: 0.9rem;
        letter-spacing: 0.02em;
        text-transform: uppercase;
    }
    .aida-metric .value {
        font-size: 2.4rem;
        font-weight: 700;
        color: #111827;
        line-height: 1.1;
    }
    .aida-last-fetch {
        font-size: 1.05rem;
        font-weight: 400;
        color: #6b7280;
    }
    .aida-section-title {
        font-size: 0.85rem;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        font-weight: 700;
        color: #6b7280;
        margin-bottom: 6px;
    }
    .aida-section-hint {
        font-size: 0.85rem;
        color: #94a3b8;
        margin-top: -4px;
        margin-bottom: 10px;
    }
    .aida-goal-card.aida-streak-new {
        animation: aida-streak-pulse 0.9s ease-out 0s 3;
        box-shadow: 0 16px 36px rgba(251, 191, 36, 0.45);
        animation-fill-mode: none;
    }
    @keyframes aida-streak-pulse {
        0% {
            transform: scale(1);
            box-shadow: 0 0 0 rgba(251, 191, 36, 0.0);
            background: #fff7ed;
        }
        45% {
            transform: scale(1.08);
            box-shadow: 0 20px 44px rgba(251, 191, 36, 0.6);
            background: #fde68a;
        }
        100% {
            transform: scale(1);
            box-shadow: 0 16px 36px rgba(251, 191, 36, 0.45);
            background: #fffbeb;
        }
    }
    .aida-welcome-banner {
        border: 1px solid #fde68a;
        background: #fffbeb;
        border-radius: 12px;
        padding: 12px 16px;
        color: #92400e;
        font-weight: 600;
        text-align: center;
        font-size: 1.05rem;
        box-shadow: 0 10px 24px rgba(251, 191, 36, 0.2);
        margin-bottom: 16px;
        animation: aida-welcome-fade 0.6s ease 3.5s forwards;
    }
    .aida-goal-card {
        border: 1px solid #fbbf24;
        background: #fffbeb;
        box-shadow: 0 14px 30px rgba(251, 191, 36, 0.25);
        border-radius: 12px;
        padding: 10px 12px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        min-width: 220px;
        min-height: 84px;
        margin-bottom: 12px;
    }
    .aida-goal-label {
        font-size: 0.75rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        font-weight: 700;
        color: #b45309;
    }
    .aida-goal-value {
        font-size: 1.1rem;
        font-weight: 700;
        color: #92400e;
        margin-top: 2px;
    }
    .aida-goal-row {
        display: flex;
        gap: 16px;
        align-items: stretch;
        flex-wrap: wrap;
        margin-bottom: 8px;
    }
    .aida-read-tag {
        display: inline-block;
        font-size: 0.72rem;
        font-weight: 600;
        color: #16a34a;
        border: 1px solid #86efac;
        border-radius: 999px;
        padding: 2px 8px;
        margin-bottom: 6px;
        background: #f0fdf4;
    }
    .aida-undo-text {
        font-size: 0.8rem;
        color: #64748b;
        margin-top: 6px;
    }
    .aida-undo-button button {
        background: transparent;
        border: none;
        color: #2563eb;
        padding: 0;
        font-size: 0.85rem;
        font-weight: 600;
    }
    .aida-undo-button button:hover {
        text-decoration: underline;
    }
    div[data-testid="stForm"]:has(.aida-card-marker) .stButton {
        margin-top: 8px;
    }
    @keyframes aida-welcome-fade {
        to {
            opacity: 0;
            max-height: 0;
            margin-bottom: 0;
            padding-top: 0;
            padding-bottom: 0;
        }
    }
    .aida-card-marker {
        height: 0;
        margin: 0;
        padding: 0;
        scroll-margin-top: 90px;
    }
    div[data-testid="stForm"]:has(.aida-card-marker),
    div[data-testid="stColumn"] div[data-testid="stVerticalBlock"]:has(.aida-card-marker) {
        border: 1px solid #e5e7eb;
        border-radius: 10px;
        padding: 12px;
        background: #ffffff;
        min-height: 180px;
        display: flex;
        flex-direction: column;
        gap: 6px;
        margin-bottom: 18px;
        position: relative;
        z-index: 0;
        transition: transform 0.15s ease, box-shadow 0.15s ease;
    }
    div[data-testid="stForm"]:has(.aida-card-marker):hover,
    div[data-testid="stColumn"] div[data-testid="stVerticalBlock"]:has(.aida-card-marker):hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 24px rgba(17, 24, 39, 0.12);
    }
    @keyframes aida-card-flash {
        0% {
            box-shadow:
                0 0 0 6px rgba(37, 99, 235, 0.35),
                0 12px 28px rgba(37, 99, 235, 0.25);
            border-color: #1d4ed8;
            background: #dbeafe;
        }
        60% {
            box-shadow:
                0 0 0 3px rgba(37, 99, 235, 0.2),
                0 8px 18px rgba(37, 99, 235, 0.18);
            border-color: #2563eb;
            background: #eff6ff;
        }
        100% {
            box-shadow: 0 0 0 0 rgba(37, 99, 235, 0.0);
            border-color: #e5e7eb;
            background: #ffffff;
        }
    }
    div[data-testid="stForm"]:has(.aida-card-marker:target),
    div[data-testid="stColumn"] div[data-testid="stVerticalBlock"]:has(.aida-card-marker:target) {
        animation: aida-card-flash 2.8s ease-out;
        z-index: 2;
    }
    .aida-title {
        font-weight: 700;
        font-size: 1.05rem;
        line-height: 1.35;
        color: #111827;
        display: -webkit-box;
        -webkit-line-clamp: 3;
        -webkit-box-orient: vertical;
        overflow: hidden;
    }
    .aida-meta { color: #6b7280; font-size: 0.9rem; }
    .aida-time { color: #6b7280; font-size: 0.85rem; }
    .aida-reason {
        color: #94a3b8;
        font-size: 0.82rem;
        line-height: 1.3;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
    }
    .aida-article-row {
        display: flex;
        gap: 14px;
        align-items: stretch;
    }
    .aida-article-media {
        flex: 0 0 auto;
        border-radius: 10px;
        overflow: hidden;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    .aida-article-media,
    .aida-article-media img,
    .aida-article-placeholder {
        width: 240px;
    }
    .aida-article-media img {
        height: 70%;
        width: 100%;
        max-height: 220px;
        border-radius: 10px;
        object-fit: cover;
        display: block;
    }
    .aida-article-placeholder {
        width: 240px;
        height: 160px;
        background: #f1f5f9;
        border: 1px solid #e2e8f0;
        color: #94a3b8;
        font-size: 0.7rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }
    .aida-article-body {
        flex: 1;
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: 6px;
    }
    @media (max-width: 720px) {
        .aida-article-row {
            flex-direction: column;
        }
        .aida-article-media {
            width: 100%;
        }
        .aida-article-media img {
            width: 100%;
            height: 200px;
            max-width: none;
            max-height: none;
        }
        .aida-article-placeholder {
            width: 100%;
            height: 200px;
        }
    }
    .aida-summary {
        color: #111827;
        display: -webkit-box;
        -webkit-line-clamp: 5;
        -webkit-box-orient: vertical;
        overflow: hidden;
    }
    .aida-link { color: #2563eb; text-decoration: none; display: inline-block; }
    .aida-footer { margin-top: auto; margin-bottom: 8px; }
    .aida-digest-card {
        border: 1px solid #e5e7eb;
        border-radius: 10px;
        padding: 12px;
        background: #ffffff;
        min-height: 220px;
        min-width: 320px;
        max-width: 340px;
        display: flex;
        flex-direction: column;
        gap: 6px;
        cursor: pointer;
        transition: transform 0.15s ease, box-shadow 0.15s ease;
    }
    .aida-digest-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 20px rgba(17, 24, 39, 0.12);
    }
    .aida-digest-title {
        font-weight: 700;
        font-size: 0.98rem;
        line-height: 1.3;
        color: #111827;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
    }
    .aida-digest-summary {
        color: #111827;
        font-size: 0.9rem;
        line-height: 1.35;
        display: -webkit-box;
        -webkit-line-clamp: 3;
        -webkit-box-orient: vertical;
        overflow: hidden;
    }
    .aida-digest-readmore {
        margin-top: 4px;
    }
    .aida-digest-link {
        display: block;
        text-decoration: none !important;
        color: inherit !important;
    }
    .aida-digest-link * {
        text-decoration: none !important;
        color: inherit !important;
    }
    .aida-digest-link:link,
    .aida-digest-link:visited,
    .aida-digest-link:hover,
    .aida-digest-link:active {
        text-decoration: none !important;
        color: inherit !important;
    }
    .aida-highlight {
        background: #fde68a;
        color: #111827;
        padding: 0 2px;
        border-radius: 4px;
    }
    .stMultiSelect label,
    .stSelectbox label,
    .stTextInput label {
        font-size: 0.8rem;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: #6b7280;
        font-weight: 600;
    }
    .aida-field-label {
        font-size: 0.8rem;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: #6b7280;
        font-weight: 600;
        margin-bottom: 6px;
    }
    div[data-baseweb="select"] > div {
        background: #f8fafc;
        border: 1px solid #e5e7eb;
        border-radius: 12px;
        min-height: 44px;
    }
    div[data-baseweb="input"] > div {
        background: #f8fafc;
        border: 1px solid #e5e7eb;
        border-radius: 12px;
    }
    .aida-impact-pill {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 999px;
        font-size: 0.75rem;
        font-weight: 600;
        color: #ffffff;
        width: fit-content;
    }
    .aida-breaking-pill {
        background: #b91c1c;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
    .aida-pill-row {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        margin: 2px 0;
    }
    .aida-pill {
        display: inline-flex;
        align-items: center;
        padding: 2px 8px;
        border-radius: 999px;
        font-size: 0.75rem;
        font-weight: 600;
        color: #ffffff;
        white-space: nowrap;
    }
    .aida-digest-summary-box {
        border: 1px solid #e5e7eb;
        border-radius: 12px;
        padding: 14px 16px;
        background: #f8fafc;
        color: #111827;
        font-size: 0.95rem;
        line-height: 1.5;
    }
    .aida-digest-scroll {
        display: flex;
        gap: 16px;
        overflow-x: auto;
        padding-bottom: 6px;
        scroll-snap-type: x mandatory;
        align-items: stretch;
    }
    .aida-digest-card {
        scroll-snap-align: start;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

SENTIMENT_COLORS = {
    "positive": "#1b9e4b",
    "negative": "#d64545",
    "neutral": "#f0ad4e",
    "mixed": "#f0ad4e",
    "uncertain": "#5bc0de",
}

def sentiment_color(value: str) -> str:
    if not value:
        return SENTIMENT_COLORS["neutral"]
    key = value.strip().lower()
    for label in ("positive", "negative", "neutral", "mixed", "uncertain"):
        if label in key:
            return SENTIMENT_COLORS[label]
    return SENTIMENT_COLORS["neutral"]

def impact_sentiment_label(value: str) -> str:
    if not value:
        return ""
    return value.split(" for ", 1)[0].strip()

def normalize_impact_level(value: str) -> str:
    if not value:
        return ""
    key = str(value).strip().lower()
    mapping = {
        "high": "critical",
        "medium": "important",
        "low": "routine",
        "critical": "critical",
        "important": "important",
        "routine": "routine",
    }
    return mapping.get(key, key)

def published_date_key(published_at_raw: str, tz_name: str) -> str:
    if not published_at_raw:
        return ""
    try:
        iso_text = published_at_raw.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(iso_text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return ""

_ZERO_WIDTH_TRANSLATION = str.maketrans("", "", "\u200b\u200c\u200d\ufeff")

def normalize_display_text(value) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    value = html.unescape(value)
    value = value.replace("\u00a0", " ")
    value = value.translate(_ZERO_WIDTH_TRANSLATION)
    return " ".join(value.split())

def _get_device_id() -> str:
    params = st.query_params
    device_id = None
    try:
        device_id = params.get("device_id")
    except Exception:
        device_id = None
    if isinstance(device_id, list):
        device_id = device_id[0] if device_id else None
    if not device_id:
        device_id = uuid.uuid4().hex
        st.query_params["device_id"] = device_id
        st.stop()
    return device_id


def _parse_date(value: str):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None

def _record_daily_checkin(device_id: str, tz_name: str) -> tuple[int, bool]:
    today = datetime.now(ZoneInfo(tz_name)).date()
    today_str = today.isoformat()
    db = SessionLocal()
    try:
        streak = db.query(UserStreak).filter(UserStreak.device_id == device_id).one_or_none()
        if not streak:
            streak = UserStreak(
                device_id=device_id,
                streak_count=1,
                last_checkin_date=today_str,
            )
            db.add(streak)
            db.commit()
            db.refresh(streak)
            return streak.streak_count, True

        last_date = _parse_date(streak.last_checkin_date)
        if last_date == today:
            return streak.streak_count, False
        if last_date and last_date == today - timedelta(days=1):
            streak.streak_count = (streak.streak_count or 0) + 1
        else:
            streak.streak_count = 1
        streak.last_checkin_date = today_str
        db.commit()
        db.refresh(streak)
        return streak.streak_count, True
    finally:
        db.close()

def _today_key(tz_name: str) -> str:
    return datetime.now(ZoneInfo(tz_name)).date().isoformat()

def _get_read_urls(device_id: str, read_date: str) -> set[str]:
    db = SessionLocal()
    try:
        rows = (
            db.query(UserRead.article_url)
            .filter(UserRead.device_id == device_id, UserRead.read_date == read_date)
            .all()
        )
        return {row[0] for row in rows if row and row[0]}
    finally:
        db.close()

def _mark_article_read(device_id: str, read_date: str, article_url: str) -> bool:
    if not article_url:
        return False
    db = SessionLocal()
    try:
        entry = UserRead(device_id=device_id, article_url=article_url, read_date=read_date)
        db.add(entry)
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False
    finally:
        db.close()

def _mark_read_callback(device_id: str, read_date: str, article_url: str) -> None:
    if not article_url:
        return
    if _mark_article_read(device_id, read_date, article_url):
        st.session_state["last_read_action"] = {
            "device_id": device_id,
            "read_date": read_date,
            "article_url": article_url,
            "timestamp": time.time(),
        }

def _undo_mark_read(device_id: str, read_date: str, article_url: str) -> bool:
    if not article_url:
        return False
    db = SessionLocal()
    try:
        deleted = (
            db.query(UserRead)
            .filter(
                UserRead.device_id == device_id,
                UserRead.article_url == article_url,
                UserRead.read_date == read_date,
            )
            .delete(synchronize_session=False)
        )
        if deleted:
            db.commit()
            return True
        db.rollback()
        return False
    finally:
        db.close()

def _undo_mark_read_callback(device_id: str, read_date: str, article_url: str) -> None:
    if not article_url:
        return
    if _undo_mark_read(device_id, read_date, article_url):
        st.session_state.pop("last_read_action", None)

def highlight_text(text: str, needle: str) -> str:
    if not text:
        return ""
    if not needle:
        return html.escape(text)
    try:
        pattern = re.compile(re.escape(needle), re.IGNORECASE)
    except re.error:
        return html.escape(text)
    parts = []
    last = 0
    for match in pattern.finditer(text):
        start, end = match.span()
        parts.append(html.escape(text[last:start]))
        parts.append(f'<span class="aida-highlight">{html.escape(text[start:end])}</span>')
        last = end
    parts.append(html.escape(text[last:]))
    return "".join(parts)

device_id = _get_device_id()
timezone_options = [
    "UTC",
    "Asia/Singapore",
    "Asia/Tokyo",
    "Asia/Shanghai",
    "Asia/Kolkata",
    "Europe/London",
    "Europe/Paris",
    "America/New_York",
    "America/Chicago",
    "America/Los_Angeles",
    "Australia/Sydney",
]
control_row = st.columns([2.2, 2.2, 1.6])
with control_row[0]:
    st.markdown('<div class="aida-section-title">Timezone</div>', unsafe_allow_html=True)
    selected_timezone = st.selectbox(
        "Timezone",
        timezone_options,
        index=1,
        label_visibility="collapsed",
    )
with control_row[1]:
    st.markdown("<div style=\"height: 1px;\"></div>", unsafe_allow_html=True)
with control_row[2]:
    st.markdown('<div class="aida-section-title">&nbsp;</div>', unsafe_allow_html=True)
    refresh_clicked = st.button("Fetch Latest News", use_container_width=True)

last_fetch_caption = st.empty()

streak_count, did_checkin = _record_daily_checkin(device_id, selected_timezone)
welcome_banner.markdown(
    f"<div class=\"aida-welcome-banner\">"
    f"Welcome back to AIDA — day {streak_count} in a row sharpening your view of the world."
    f"</div>",
    unsafe_allow_html=True,
)

today_key = _today_key(selected_timezone)
read_urls = _get_read_urls(device_id, today_key)
UNDO_WINDOW_SECONDS = 6
last_read_action = st.session_state.get("last_read_action")
undo_state = None
if last_read_action:
    try:
        timestamp = float(last_read_action.get("timestamp", 0))
    except (TypeError, ValueError):
        timestamp = 0
    if time.time() - timestamp <= UNDO_WINDOW_SECONDS:
        undo_state = last_read_action
    else:
        st.session_state.pop("last_read_action", None)
DAILY_GOAL = 10
read_count = len(read_urls)
goal_ratio = min(read_count / DAILY_GOAL, 1.0) if DAILY_GOAL > 0 else 0.0
streak_class = "aida-goal-card aida-streak-new" if did_checkin else "aida-goal-card"
with goal_streak_container:
    streak_unit = "day" if streak_count == 1 else "days"
    streak_html = (
        f"<div class=\"{streak_class}\">"
        f"<div class=\"aida-goal-label\">Daily Streak</div>"
        f"<div class=\"aida-goal-value\">{streak_count} {streak_unit}</div>"
        f"</div>"
    )
    goal_html = (
        f"<div class=\"aida-goal-card\">"
        f"<div class=\"aida-goal-label\">Daily Articles Read</div>"
        f"<div class=\"aida-goal-value\">{read_count} articles</div>"
        f"</div>"
    )
    st.markdown(
        f"<div class=\"aida-goal-row\">{streak_html}{goal_html}</div>",
        unsafe_allow_html=True,
    )

last_fetch_time_display = "-"
next_fetch_time_display = "-"
last_fetch_raw = None
try:
    last_fetch_response = requests.get(f"{API_BASE}/last-fetch-time", timeout=10)
    last_fetch_response.raise_for_status()
    last_fetch_payload = last_fetch_response.json()
    last_fetch_raw = last_fetch_payload.get("last_fetch_time_utc")
    if last_fetch_raw:
        iso_text = last_fetch_raw.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(iso_text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        last_fetch_time_display = parsed.astimezone(ZoneInfo(selected_timezone)).strftime(
            "%Y-%m-%d %H:%M:%S %Z"
        )
        next_auto = parsed + timedelta(hours=2)
        next_fetch_time_display = next_auto.astimezone(ZoneInfo(selected_timezone)).strftime(
            "%Y-%m-%d %H:%M:%S %Z"
        )
except requests.RequestException:
    pass

if "last_fetch_time_ack" not in st.session_state:
    st.session_state["last_fetch_time_ack"] = last_fetch_raw

if last_fetch_raw and st.session_state.get("last_fetch_time_ack") != last_fetch_raw:
    banner_cols = st.columns([6, 1, 1])
    with banner_cols[0]:
        st.info("News was recently fetched. Refresh to see the latest headlines.")
    with banner_cols[1]:
        if st.button("Refresh now"):
            st.session_state["last_fetch_time_ack"] = last_fetch_raw
            if hasattr(st, "rerun"):
                st.rerun()
            else:
                st.experimental_rerun()
    with banner_cols[2]:
        if st.button("✕", help="Dismiss"):
            st.session_state["last_fetch_time_ack"] = last_fetch_raw
            if hasattr(st, "rerun"):
                st.rerun()
            else:
                st.experimental_rerun()

last_fetch_caption.markdown(
    f"<div class=\"aida-last-fetch\">Last fetch: {last_fetch_time_display}<br/>Next auto fetch: {next_fetch_time_display}</div>",
    unsafe_allow_html=True,
)

if refresh_clicked:
    status = st.empty()
    log = st.empty()
    progress = st.progress(0.0)
    status.info("Starting fetch...")

    def trigger_refresh():
        try:
            refresh_response = requests.post(f"{API_BASE}/refresh-news", timeout=300)
            refresh_response.raise_for_status()
        except requests.RequestException as exc:
            status.error(f"Refresh failed: {exc}")

    refresh_thread = threading.Thread(target=trigger_refresh, daemon=True)
    refresh_thread.start()

    start = time.perf_counter()
    last_state = None
    poll_interval_s = 2.0
    while True:
        try:
            fetch_response = requests.get(f"{API_BASE}/fetch-status", timeout=5)
            fetch_response.raise_for_status()
            payload = fetch_response.json()
        except requests.RequestException as exc:
            log.warning(f"Status check failed: {exc}")
            time.sleep(poll_interval_s)
            continue

        state = payload.get("state", "unknown")
        message = payload.get("message", "")
        total = payload.get("total", 0) or 0
        processed = payload.get("processed", 0) or 0
        if total > 0:
            progress.progress(min(processed / total, 1.0))
        else:
            progress.progress(0.0)
        log.info(message or f"Status: {state}")
        last_state = state
        if state in {"done", "error"}:
            break
        time.sleep(poll_interval_s)

    elapsed = time.perf_counter() - start
    if last_state == "done":
        status.success(f"Latest news fetched in {elapsed:.1f}s.")
    elif last_state == "error":
        status.error(message or f"Refresh failed after {elapsed:.1f}s.")
    else:
        status.success(f"Fetch completed in {elapsed:.1f}s.")

    if st.button("Dismiss messages", key="dismiss_fetch_messages"):
        if hasattr(st, "rerun"):
            st.rerun()
        else:
            st.experimental_rerun()

try:
    response = requests.get(f"{API_BASE}/summaries", timeout=15)
    response.raise_for_status()
    data = response.json()
except requests.RequestException as exc:
    st.error(f"Failed to load summaries: {exc}")
    data = []

if not isinstance(data, list):
    st.error("Unexpected response from server.")
    data = []

categories = sorted({item.get("category", "") for item in data if item.get("category")})
sources = sorted({item.get("source", "") for item in data if item.get("source")})
countries = sorted({item.get("country", "") for item in data if item.get("country")})
impact_levels = sorted(
    {
        normalize_impact_level(item.get("impact_level", ""))
        for item in data
        if item.get("impact_level")
    },
    key=lambda level: {"critical": 0, "important": 1, "routine": 2}.get(level, 99),
)
dates = sorted(
    {
        published_date_key(item.get("published_at"), selected_timezone)
        for item in data
        if item.get("published_at")
    }
)
dates = [d for d in dates if d]

def _sync_multiselect(key: str, options: list[str]) -> None:
    current = st.session_state.get(key, [])
    if current:
        filtered = [value for value in current if value in options]
        if filtered != current:
            st.session_state[key] = filtered

_sync_multiselect("filter_category", categories)
_sync_multiselect("filter_country", countries)
_sync_multiselect("filter_impact", impact_levels)
_sync_multiselect("filter_date", dates)
_sync_multiselect("filter_source", sources)

filter_header = st.columns([5, 1])
with filter_header[0]:
    st.markdown('<div class="aida-section-title">Filters</div>', unsafe_allow_html=True)
    st.markdown('<div class="aida-section-hint">Refine the feed with topic, source, or keyword.</div>', unsafe_allow_html=True)
with filter_header[1]:
    if st.button("Clear all", use_container_width=True):
        st.session_state["filter_category"] = []
        st.session_state["filter_country"] = []
        st.session_state["filter_impact"] = []
        st.session_state["filter_date"] = []
        st.session_state["filter_source"] = []

def sentiment_bucket(value: str) -> str:
    if not value:
        return "neutral"
    key = value.strip().lower()
    if "positive" in key:
        return "positive"
    if "negative" in key:
        return "negative"
    if "neutral" in key:
        return "neutral"
    return "neutral"

def contextual_sentiment_bucket(value: str) -> str:
    if not value:
        return "neutral"
    label = impact_sentiment_label(value).lower()
    if "positive" in label:
        return "positive"
    if "negative" in label:
        return "negative"
    if "neutral" in label:
        return "neutral"
    return "neutral"

def _parse_published_datetime(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        iso_text = raw.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(iso_text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (ValueError, TypeError):
        return None

def _summary_first_sentence(text: str) -> str:
    if not text:
        return ""
    cleaned = normalize_display_text(text)
    if not cleaned:
        return ""
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", cleaned)
    if parts:
        return parts[0].strip()
    return cleaned

filter_row1 = st.columns([2, 2, 2])
with filter_row1[0]:
    category = st.multiselect("Category", categories, key="filter_category")
with filter_row1[1]:
    country = st.multiselect("Country", countries, key="filter_country")
with filter_row1[2]:
    date_filter = st.multiselect("Date", dates, key="filter_date")

filter_row2 = st.columns([2, 2, 3])
with filter_row2[0]:
    source = st.multiselect("Source", sources, key="filter_source")
with filter_row2[1]:
    impact_level_filter = st.multiselect("Priority", impact_levels, key="filter_impact")
with filter_row2[2]:
    keyword = st.text_input(
        "Search",
        placeholder="Search title or summary",
    )

if category:
    data = [item for item in data if item.get("category") in category]

if country:
    data = [item for item in data if item.get("country") in country]

if source:
    data = [item for item in data if item.get("source") in source]

if impact_level_filter:
    selected_levels = {level.lower() for level in impact_level_filter}
    data = [
        item
        for item in data
        if normalize_impact_level(item.get("impact_level") or "") in selected_levels
    ]

if date_filter:
    data = [
        item
        for item in data
        if published_date_key(item.get("published_at"), selected_timezone) in date_filter
    ]

if keyword:
    needle = keyword.strip().lower()
    if needle:
        data = [
            item
            for item in data
            if needle in (item.get("title") or "").lower()
            or needle in (item.get("summary") or "").lower()
        ]

highlight_term = keyword.strip() if keyword else ""

data = [item for item in data if (item.get("summary") or "").strip()]

if not data:
    st.warning("No articles found with current filters.")
else:
    for idx, item in enumerate(data):
        item["_anchor"] = f"article-{idx}"

st.markdown("---")
st.subheader("Daily Digest — Top Priority")

BREAKING_WINDOW_HOURS = 6

def _impact_level(item) -> str:
    return normalize_impact_level(item.get("impact_level") or "")

def _sorted_by_time(items: list[dict]) -> list[dict]:
    return sorted(
        items,
        key=lambda item: _parse_published_datetime(item.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

digest_items = []
digest_date_key = None
impact_level_colors = {
    "critical": "#dc2626",
    "important": "#f59e0b",
    "routine": "#16a34a",
}

digest_source = list(data)
if digest_source:
    today_key = datetime.now(ZoneInfo(selected_timezone)).strftime("%Y-%m-%d")
    today_items = [
        item
        for item in digest_source
        if published_date_key(item.get("published_at"), selected_timezone) == today_key
    ]
    if not today_items:
        available_dates = [
            published_date_key(item.get("published_at"), selected_timezone)
            for item in digest_source
        ]
        available_dates = [d for d in available_dates if d]
        if available_dates:
            fallback_date = max(available_dates)
            digest_date_key = fallback_date
            today_items = [
                item
                for item in digest_source
                if published_date_key(item.get("published_at"), selected_timezone) == fallback_date
            ]
        else:
            digest_date_key = today_key
    else:
        digest_date_key = today_key

    high_items = _sorted_by_time([item for item in today_items if _impact_level(item) == "critical"])
    medium_items = _sorted_by_time([item for item in today_items if _impact_level(item) == "important"])
    low_items = _sorted_by_time([item for item in today_items if _impact_level(item) == "routine"])

    DIGEST_COUNT = 8
    digest_items = high_items[:DIGEST_COUNT]
    if len(digest_items) < DIGEST_COUNT:
        selected_urls = {item.get("url") for item in digest_items if item.get("url")}
        for item in medium_items:
            if len(digest_items) >= DIGEST_COUNT:
                break
            if item.get("url") and item.get("url") in selected_urls:
                continue
            digest_items.append(item)
            if item.get("url"):
                selected_urls.add(item.get("url"))
        for item in low_items:
            if len(digest_items) >= DIGEST_COUNT:
                break
            if item.get("url") and item.get("url") in selected_urls:
                continue
            digest_items.append(item)
            if item.get("url"):
                selected_urls.add(item.get("url"))

if digest_date_key:
    try:
        digest_date_label = datetime.strptime(digest_date_key, "%Y-%m-%d").strftime("%b %d, %Y")
    except ValueError:
        digest_date_label = digest_date_key
    st.caption(f"Digest date: {digest_date_label}")

if digest_items:
    digest_summary = generate_digest_summary(digest_items, last_fetch_raw)
    if digest_summary:
        st.markdown(
            f"<div class=\"aida-digest-summary-box\">{html.escape(digest_summary)}</div>",
            unsafe_allow_html=True,
        )
    cards = []
    now_utc = datetime.now(timezone.utc)
    for item in digest_items:
        title = normalize_display_text(item.get("title")) or "Untitled"
        source = normalize_display_text(item.get("source")) or "-"
        published_at_raw = item.get("published_at")
        published_at_display = published_at_raw or "-"
        parsed = _parse_published_datetime(published_at_raw)
        if parsed:
            published_at_display = parsed.astimezone(ZoneInfo(selected_timezone)).strftime(
                "%Y-%m-%d %H:%M %Z"
            )
        impact_level = _impact_level(item)
        impact_label = impact_level.capitalize() if impact_level else "Unknown"
        impact_color = impact_level_colors.get(impact_level, "#6b7280")
        summary_text = normalize_display_text(item.get("summary"))
        url = item.get("url")
        anchor = item.get("_anchor") or ""
        anchor_href = f"#{anchor}" if anchor else ""
        link_html = (
            f'<span class="aida-link">Read more</span>'
            if anchor_href
            else ""
        )
        is_breaking = False
        if impact_level == "critical" and parsed:
            age_seconds = (now_utc - parsed.astimezone(timezone.utc)).total_seconds()
            is_breaking = 0 <= age_seconds <= BREAKING_WINDOW_HOURS * 3600
        breaking_html = (
            '<span class="aida-impact-pill aida-breaking-pill">Breaking</span>'
            if is_breaking
            else ""
        )
        pill_row = (
            f'<div class="aida-pill-row">'
            f'{breaking_html}'
            f'<span class="aida-impact-pill" style="background:{impact_color};">Priority: {html.escape(impact_label)}</span>'
            f'</div>'
        )
        title_html = highlight_text(title, highlight_term)
        summary_html = highlight_text(summary_text, highlight_term)
        card_inner = (
            f'<div class="aida-digest-card">'
            f'<div class="aida-digest-title">{title_html}</div>'
            f'<div class="aida-meta">{html.escape(source)} | {html.escape(published_at_display)}</div>'
            f'{pill_row}'
            f'<div class="aida-digest-summary">{summary_html}</div>'
            f'<div class="aida-digest-readmore">{link_html}</div>'
            f'</div>'
        )
        card_html = (
            f'<a class="aida-digest-link" href="{anchor_href}">{card_inner}</a>'
            if anchor_href
            else card_inner
        )
        cards.append(card_html)

    digest_row_html = f"<div class=\"aida-digest-scroll\">{''.join(cards)}</div>"
    st.markdown(digest_row_html, unsafe_allow_html=True)
else:
    st.caption("No articles available for the daily digest.")

total_articles = len(data)
sentiment_counts = {"positive": 0, "negative": 0, "neutral": 0}
impact_counts = {"critical": 0, "important": 0, "routine": 0}
category_counts = {}
source_counts = {}
for item in data:
    bucket = contextual_sentiment_bucket(item.get("sentiment_contextual", ""))
    sentiment_counts[bucket] += 1
    impact_level = normalize_impact_level(item.get("impact_level") or "")
    if impact_level in impact_counts:
        impact_counts[impact_level] += 1
    category = item.get("category") or "Unknown"
    category_counts[category] = category_counts.get(category, 0) + 1
    source = item.get("source") or "Unknown"
    source_counts[source] = source_counts.get(source, 0) + 1

def top_key(counts: dict) -> str:
    if not counts:
        return "-"
    return max(counts.items(), key=lambda pair: pair[1])[0]

def percent(count: int, total: int) -> str:
    if total <= 0:
        return "0%"
    return f"{(count / total) * 100:.0f}%"

st.markdown("---")
summary_cols = st.columns([1, 3, 3])
with summary_cols[0]:
    st.markdown(
        f"<div class=\"aida-metric\"><div class=\"label\">Total Articles</div>"
        f"<div class=\"value\">{total_articles}</div></div>",
        unsafe_allow_html=True,
    )
with summary_cols[1]:
    st.subheader("Sentiment Distribution")
    sentiment_df = pd.DataFrame(
        [
            {"sentiment": "Positive", "value": sentiment_counts["positive"]},
            {"sentiment": "Negative", "value": sentiment_counts["negative"]},
            {"sentiment": "Neutral", "value": sentiment_counts["neutral"]},
        ]
    )
    sentiment_colors = {
        "Positive": SENTIMENT_COLORS["positive"],
        "Negative": SENTIMENT_COLORS["negative"],
        "Neutral": SENTIMENT_COLORS["neutral"],
    }
    pie_base = alt.Chart(sentiment_df).encode(
        theta=alt.Theta(field="value", type="quantitative"),
        color=alt.Color(
            field="sentiment",
            type="nominal",
            scale=alt.Scale(domain=list(sentiment_colors.keys()), range=list(sentiment_colors.values())),
            legend=alt.Legend(title=None, orient="bottom"),
        ),
        tooltip=["sentiment", "value"],
    )
    pie = pie_base.mark_arc(innerRadius=40, outerRadius=80)
    pie_chart = pie.properties(width=320, height=280).configure_view(
        stroke="#e5e7eb",
        strokeWidth=1,
        cornerRadius=8,
    )
    st.altair_chart(pie_chart, use_container_width=True)
with summary_cols[2]:
    st.subheader("Priority Distribution")
    impact_df = pd.DataFrame(
        [
            {"impact": "Critical", "value": impact_counts["critical"]},
            {"impact": "Important", "value": impact_counts["important"]},
            {"impact": "Routine", "value": impact_counts["routine"]},
        ]
    )
    impact_colors = {
        "Critical": "#dc2626",
        "Important": "#f59e0b",
        "Routine": "#16a34a",
    }
    impact_base = alt.Chart(impact_df).encode(
        theta=alt.Theta(field="value", type="quantitative"),
        color=alt.Color(
            field="impact",
            type="nominal",
            scale=alt.Scale(domain=list(impact_colors.keys()), range=list(impact_colors.values())),
            legend=alt.Legend(title=None, orient="bottom"),
        ),
        tooltip=["impact", "value"],
    )
    impact_pie = impact_base.mark_arc(innerRadius=40, outerRadius=80)
    impact_chart = impact_pie.properties(width=320, height=280).configure_view(
        stroke="#e5e7eb",
        strokeWidth=1,
        cornerRadius=8,
    )
    st.altair_chart(impact_chart, use_container_width=True)

impact_trend = {}
for item in data:
    date_key = published_date_key(item.get("published_at"), selected_timezone)
    if not date_key:
        continue
    level = normalize_impact_level(item.get("impact_level") or "")
    if level not in {"critical", "important", "routine"}:
        continue
    impact_trend.setdefault(date_key, {"critical": 0, "important": 0, "routine": 0})
    impact_trend[date_key][level] += 1

trend_dates = sorted(impact_trend.keys())
if len(trend_dates) > 7:
    trend_dates = trend_dates[-7:]

trend_rows = []
date_labels = {}
for date_key in trend_dates:
    try:
        date_labels[date_key] = datetime.strptime(date_key, "%Y-%m-%d").strftime("%b %d")
    except ValueError:
        date_labels[date_key] = date_key
    counts = impact_trend.get(date_key, {"critical": 0, "important": 0, "routine": 0})
    for level in ("critical", "important", "routine"):
        trend_rows.append(
            {
                "date": date_key,
                "date_label": date_labels[date_key],
                "impact": level.capitalize(),
                "count": counts.get(level, 0),
            }
        )

st.markdown("---")
st.subheader("Priority Trend (Daily)")
if trend_rows:
    trend_df = pd.DataFrame(trend_rows)
    impact_colors = {
        "Critical": "#dc2626",
        "Important": "#f59e0b",
        "Routine": "#16a34a",
    }
    date_order = [date_labels[date_key] for date_key in trend_dates]
    trend_chart = (
        alt.Chart(trend_df)
        .mark_line(point=True)
        .encode(
            x=alt.X("date_label:N", title="Date", sort=date_order),
            y=alt.Y("count:Q", title="Articles"),
            color=alt.Color(
                "impact:N",
                scale=alt.Scale(domain=list(impact_colors.keys()), range=list(impact_colors.values())),
                legend=alt.Legend(title=None, orient="bottom"),
            ),
            tooltip=["impact", "count", alt.Tooltip("date_label:N", title="Date")],
        )
        .properties(height=260)
        .configure_view(
            stroke="#e5e7eb",
            strokeWidth=1,
            cornerRadius=8,
        )
    )
    st.altair_chart(trend_chart, use_container_width=True)
else:
    st.caption("Not enough data to show impact trend yet.")

def top_counts(counts: dict, limit: int = 10) -> dict:
    items = sorted(counts.items(), key=lambda pair: pair[1], reverse=True)
    return {key: value for key, value in items[:limit]}

chart_cols = st.columns(2)
with chart_cols[0]:
    st.subheader("Category Distribution")
    category_chart = top_counts(category_counts, limit=10)
    if category_chart:
        category_df = pd.DataFrame(
            [{"category": key, "count": value} for key, value in category_chart.items()]
        )
        category_height = max(240, 28 * len(category_df))
        category_base = (
            alt.Chart(category_df)
            .encode(
                x=alt.X("count:Q", title="Articles"),
                y=alt.Y("category:N", sort="-x", title=None),
                tooltip=["category", "count"],
            )
            .properties(height=category_height)
        )
        category_bar = category_base.mark_bar(color="#2563eb").configure_view(
            stroke="#e5e7eb",
            strokeWidth=1,
            cornerRadius=8,
        )
        st.altair_chart(category_bar, use_container_width=True)
    else:
        st.caption("No category data available.")
with chart_cols[1]:
    st.subheader("Source Distribution")
    source_chart = top_counts(source_counts, limit=10)
    if source_chart:
        source_df = pd.DataFrame(
            [{"source": key, "count": value} for key, value in source_chart.items()]
        )
        source_height = max(240, 28 * len(source_df))
        source_base = (
            alt.Chart(source_df)
            .encode(
                x=alt.X("count:Q", title="Articles"),
                y=alt.Y("source:N", sort="-x", title=None),
                tooltip=["source", "count"],
            )
            .properties(height=source_height)
        )
        source_bar = source_base.mark_bar(color="#10b981").configure_view(
            stroke="#e5e7eb",
            strokeWidth=1,
            cornerRadius=8,
        )
        st.altair_chart(source_bar, use_container_width=True)
    else:
        st.caption("No source data available.")

st.markdown("---")
card_columns = st.columns(1)
for idx, item in enumerate(data):
    col = card_columns[0]
    raw_title = normalize_display_text(item.get("title"))
    title = raw_title.strip()
    if not title:
        summary_text = normalize_display_text(item.get("summary"))
        if summary_text:
            title = summary_text.split(".", 1)[0].strip()
        if not title:
            title = "Untitled"
    published_at_raw = item.get("published_at")
    published_at_display = published_at_raw or "-"
    if published_at_raw:
        try:
            iso_text = published_at_raw.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(iso_text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            published_at_display = parsed.astimezone(ZoneInfo(selected_timezone)).strftime(
                "%Y-%m-%d %H:%M %Z"
            )
        except (ValueError, TypeError):
            published_at_display = published_at_raw
    tone_value = item.get("sentiment_emotional", "-")
    tone_pill_color = "#64748b"
    impact_value = item.get("sentiment_contextual", "-")
    impact_label = impact_sentiment_label(impact_value)
    impact_color = sentiment_color(impact_label)
    impact_reason = normalize_display_text(item.get("impact_reason"))
    impact_level_value = normalize_impact_level(item.get("impact_level") or "")
    impact_level_display = impact_level_value.capitalize() if impact_level_value else "-"
    impact_level_key = impact_level_value
    impact_level_colors = {
        "critical": "#dc2626",
        "important": "#f59e0b",
        "routine": "#16a34a",
    }
    impact_level_color = impact_level_colors.get(impact_level_key, "#6b7280")
    confidence_raw = item.get("sentiment_confidence", "-")
    try:
        confidence_value = float(confidence_raw)
        confidence_display = f"{confidence_value * 100:.0f}%"
    except (TypeError, ValueError):
        confidence_display = str(confidence_raw)
    source = normalize_display_text(item.get("source")) or "-"
    category = normalize_display_text(item.get("category")) or "-"
    country = normalize_display_text(item.get("country")) or "-"
    summary = normalize_display_text(item.get("summary"))
    url = item.get("url")
    image_url = item.get("image_url")
    if not isinstance(image_url, str):
        image_url = ""
    image_url = image_url.strip()
    is_read_today = bool(url and url in read_urls)
    read_tag_html = '<div class="aida-read-tag">Read today</div>' if is_read_today else ""
    read_full_link = (
        f'<a class="aida-link" href="{html.escape(url)}" target="_blank">Read Full Article</a>'
        if url
        else ""
    )

    pills = []
    if tone_value and tone_value != "-":
        pills.append(
            f'<span class="aida-pill" style="background:{tone_pill_color};">Tone: {html.escape(tone_value)}</span>'
        )
    if impact_level_display and impact_level_display != "-":
        pills.append(
            f'<span class="aida-pill" style="background:{impact_level_color};">Priority: {html.escape(impact_level_display)}</span>'
        )
    pill_row = f'<div class="aida-pill-row">{"".join(pills)}</div>' if pills else ""
    reason_html = (
        f'<div class="aida-reason">Why priority: {html.escape(impact_reason)}</div>'
        if impact_reason
        else ""
    )

    title_html = highlight_text(title, highlight_term)
    summary_html = highlight_text(summary.strip(), highlight_term)
    image_html = (
        f'<div class="aida-article-media"><img src="{html.escape(image_url)}" alt="Article image" loading="lazy"/></div>'
        if image_url
        else '<div class="aida-article-media aida-article-placeholder">No image</div>'
    )
    card_html = (
        f'<div class="aida-article-row">'
        f'{image_html}'
        f'<div class="aida-article-body">'
        f'<div class="aida-title">{title_html}</div>'
        f'<div class="aida-meta">{html.escape(source)} | {html.escape(category)} | {html.escape(country)}</div>'
        f'<div class="aida-time">{html.escape(published_at_display)}</div>'
        f'{read_tag_html}'
        f'{pill_row}'
        f'{reason_html}'
        f'<div><span style="color:{impact_color}; font-weight:600;">Sentimental Impact: {html.escape(impact_value)}</span></div>'
        f'<div class="aida-meta">Impact confidence: {html.escape(confidence_display)}</div>'
        f'<div class="aida-summary">{summary_html}</div>'
        f'<div class="aida-footer">{read_full_link}</div>'
        f'</div>'
        f'</div>'
    )
    anchor_id = html.escape(item.get("_anchor") or "")
    anchor_attr = f' id="{anchor_id}"' if anchor_id else ""
    marker_html = f'<div class="aida-card-marker"{anchor_attr}></div>'
    show_undo = bool(
        undo_state
        and url
        and is_read_today
        and undo_state.get("device_id") == device_id
        and undo_state.get("read_date") == today_key
        and undo_state.get("article_url") == url
    )
    with col:
        if url and not is_read_today:
            with st.form(key=f"read_form_{idx}"):
                st.markdown(marker_html, unsafe_allow_html=True)
                st.markdown(card_html, unsafe_allow_html=True)
                st.form_submit_button(
                    "Mark as read",
                    use_container_width=True,
                    on_click=_mark_read_callback,
                    args=(device_id, today_key, url),
                )
        else:
            with st.container():
                st.markdown(marker_html, unsafe_allow_html=True)
                st.markdown(card_html, unsafe_allow_html=True)
                if show_undo:
                    st.markdown(
                        '<div class="aida-undo-text">Marked as read.</div>',
                        unsafe_allow_html=True,
                    )
                    st.markdown('<div class="aida-undo-button">', unsafe_allow_html=True)
                    st.button(
                        "Undo",
                        key=f"undo_read_{idx}",
                        on_click=_undo_mark_read_callback,
                        args=(device_id, today_key, url),
                    )
                    st.markdown("</div>", unsafe_allow_html=True)
