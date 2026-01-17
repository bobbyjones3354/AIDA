from groq import Groq
import os
import json
import hashlib
import re
import time

GROQ_SENTIMENT_API_KEY = os.getenv("GROQ_SENTIMENT_API_KEY") or os.getenv("GROQ_API_KEY")
_groq_client = Groq(api_key=GROQ_SENTIMENT_API_KEY) if GROQ_SENTIMENT_API_KEY else None

_digest_cache: dict[str, str] = {}

_RATE_LIMIT_RE = re.compile(r"try again in ([0-9.]+)s", re.IGNORECASE)
_RETRY_BUFFER_S = 2.0
_DEFAULT_RETRY_S = 2.0
_MAX_RETRIES = 20

def _normalize_priority(value: str) -> str:
    mapping = {
        "high": "critical",
        "medium": "important",
        "low": "routine",
        "critical": "critical",
        "important": "important",
        "routine": "routine",
    }
    return mapping.get((value or "").strip().lower(), "")

def _retry_after_s(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    value = None
    if hasattr(headers, "get"):
        value = headers.get("retry-after") or headers.get("Retry-After")
    else:
        try:
            value = headers["retry-after"]
        except Exception:
            try:
                value = headers["Retry-After"]
            except Exception:
                value = None
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def _rate_limit_delay_s(error_message: str) -> float | None:
    match = _RATE_LIMIT_RE.search(error_message or "")
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None

def _is_tpm_rate_limit(exc: Exception) -> bool:
    message = str(exc).lower()
    if "requests per day" in message or "rpd" in message:
        return False
    if "tokens per minute" in message or "tpm" in message:
        return True
    return False

def _call_groq_with_retry(client: Groq, **kwargs):
    total_attempts = max(_MAX_RETRIES, 1)
    for attempt in range(total_attempts):
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as exc:
            message = str(exc)
            is_rate_limit = "rate limit" in message.lower() or "429" in message
            if is_rate_limit:
                if _is_tpm_rate_limit(exc):
                    if attempt < total_attempts - 1:
                        delay = _retry_after_s(exc)
                        if delay is None:
                            delay = _rate_limit_delay_s(message)
                        if delay is None:
                            delay = _DEFAULT_RETRY_S
                        delay = delay + _RETRY_BUFFER_S
                        attempt_label = f"{attempt + 1}/{total_attempts}"
                        wait_start = time.perf_counter()
                        print(
                            "Digest summary rate limited (TPM). "
                            f"Retrying in {delay:.2f}s (attempt {attempt_label})..."
                        )
                        time.sleep(max(delay, 0.5))
                        waited = time.perf_counter() - wait_start
                        print(f"Digest summary retry wait complete: {waited:.2f}s.")
                        continue
                    print("Digest summary rate limited (TPM). Retries exhausted.")
                else:
                    print("Digest summary rate limited (RPD). Skipping retry.")
            raise

def _digest_cache_key(items: list[dict], last_fetch_raw: str | None) -> str:
    parts = [last_fetch_raw or ""]
    for item in items:
        title = (item.get("title") or "").strip()
        impact = _normalize_priority(item.get("impact_level") or "")
        category = (item.get("category") or "").strip()
        source = (item.get("source") or "").strip()
        parts.append(f"{title}|{impact}|{category}|{source}")
    payload = "\n".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

def generate_digest_summary(items: list[dict], last_fetch_raw: str | None) -> str | None:
    if not items or not _groq_client:
        return None

    key = _digest_cache_key(items, last_fetch_raw)
    if key in _digest_cache:
        return _digest_cache[key]

    compact_items = []
    for item in items[:6]:
        compact_items.append(
            {
                "title": (item.get("title") or "").strip(),
                "priority": _normalize_priority(item.get("impact_level")),
                "category": (item.get("category") or "").strip(),
                "source": (item.get("source") or "").strip(),
            }
        )

    prompt = {
        "task": "Write a brief narrative summary of today's top priority news.",
        "rules": [
            "2-3 sentences.",
            "Focus on dominant themes and why they matter.",
            "No bullet points.",
            "Return JSON only: {\"summary\": \"...\"}."
        ],
        "items": compact_items
    }

    try:
        response = _call_groq_with_retry(
            _groq_client,
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": json.dumps(prompt)}],
            temperature=0.3,
            max_tokens=140,
        )
        raw = response.choices[0].message.content.strip()
        if not raw:
            return None
        summary = _parse_summary_json(raw)
        if summary:
            _digest_cache[key] = summary
            return summary
    except Exception as exc:
        print(f"Digest summary LLM failed: {exc}")
        return None

    return None

def _parse_summary_json(raw: str) -> str | None:
    cleaned = raw.strip()
    json_text = None
    if cleaned.startswith("{") and cleaned.endswith("}"):
        json_text = cleaned
    else:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            json_text = cleaned[start:end + 1]
    if json_text:
        try:
            parsed = json.loads(json_text)
            summary = (parsed.get("summary") or "").strip()
            return summary or None
        except Exception:
            return None
    return None
