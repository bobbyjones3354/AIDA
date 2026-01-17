# app/category_classifier.py - local + LLM classifier (CPU safe fallback)

from transformers import pipeline
from groq import Groq
import os
import json
import re
import time

# Force CPU usage (no CUDA)
_local_classifier = pipeline(
    "zero-shot-classification",
    model="facebook/bart-large-mnli",
    device=-1
)

_GROQ_CATEGORY_API_KEY = os.getenv("GROQ_CATEGORY_API_KEY")
_groq_client = Groq(api_key=_GROQ_CATEGORY_API_KEY) if _GROQ_CATEGORY_API_KEY else None

_RATE_LIMIT_RE = re.compile(r"try again in ([0-9.]+)s", re.IGNORECASE)
_RETRY_BUFFER_S = 2.0
_DEFAULT_RETRY_S = 2.0
_MAX_RETRIES = 20
USE_KEYWORD_FILTER = True
_MIN_FILTER_CHARS = 280
_MAX_LLM_INPUT_CHARS = 1200

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "he", "in", "is", "it", "its", "of", "on", "that", "the", "to", "was",
    "were", "will", "with", "you", "your", "they", "their", "them", "this",
    "these", "those", "or", "but", "not", "have", "had", "been", "if",
}

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
                            "LLM category rate limited (TPM). "
                            f"Retrying in {delay:.2f}s (attempt {attempt_label})..."
                        )
                        time.sleep(max(delay, 0.5))
                        waited = time.perf_counter() - wait_start
                        print(f"LLM category retry wait complete: {waited:.2f}s.")
                        continue
                    print("LLM category rate limited (TPM). Retries exhausted.")
                else:
                    print("LLM category rate limited (RPD). Skipping retry.")
            raise

def _split_sentences(text: str) -> list[str]:
    cleaned = " ".join(text.split())
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", cleaned)
    return [part.strip() for part in parts if part.strip()]

def _extract_keywords(sentences: list[str], top_n: int = 12) -> set[str]:
    tokens = re.findall(r"[A-Za-z0-9']+", " ".join(sentences))
    freq = {}
    for token in tokens:
        key = token.lower()
        if key in _STOPWORDS:
            continue
        if len(key) < 3 and not key.isdigit():
            continue
        freq[key] = freq.get(key, 0) + 1
    sorted_items = sorted(freq.items(), key=lambda item: item[1], reverse=True)
    return {word for word, _ in sorted_items[:top_n]}

def _select_summary_input(text: str, max_sentences: int = 4) -> str:
    sentences = _split_sentences(text)
    if len(sentences) <= max_sentences:
        return text
    keywords = _extract_keywords(sentences)
    if not keywords:
        return " ".join(sentences[:max_sentences])

    def score(sentence: str) -> int:
        words = set(re.findall(r"[A-Za-z0-9']+", sentence.lower()))
        return len(words & keywords)

    lead = sentences[:2]
    tail = sorted(sentences[2:], key=lambda s: (score(s), len(s)), reverse=True)
    selected = list(lead)
    for sentence in tail:
        if score(sentence) == 0:
            continue
        selected.append(sentence)
        if len(selected) >= max_sentences:
            break
    if len(selected) < 3:
        selected = sentences[:max_sentences]
    selected_set = set(selected)
    ordered = [sentence for sentence in sentences if sentence in selected_set]
    return " ".join(ordered)

def classify_category(text: str) -> str:
    labels = [
        "politics",
        "geopolitics",
        "war",
        "economy",
        "finance",
        "stocks",
        "business",
        "technology",
        "science",
        "health",
        "energy",
        "environment",
        "crypto",
        "sports",
        "entertainment",
        "travel",
        "education",
        "crime",
        "global",
        "general",
    ]

    if not _groq_client:
        print("LLM category disabled: GROQ_CATEGORY_API_KEY not set.")
    elif not text or not text.strip():
        print("LLM category skipped: empty text.")
    else:
        try:
            text_for_llm = " ".join(text.split())
            if USE_KEYWORD_FILTER:
                filtered = _select_summary_input(text_for_llm)
                if len(filtered) >= _MIN_FILTER_CHARS:
                    text_for_llm = filtered
            prompt = {
                "task": "Choose the best category for the news item.",
                "rules": [
                    "Pick exactly one label from the list.",
                    "Use 'global' for cross-border, international items that are not primarily politics/war.",
                    "Use 'general' when nothing else fits.",
                    "Return JSON only: {\"category\": \"<label>\"}."
                ],
                "labels": labels,
                "text": text_for_llm[:_MAX_LLM_INPUT_CHARS]
            }
            response = _call_groq_with_retry(
                _groq_client,
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": json.dumps(prompt)}],
                temperature=0.0,
                max_tokens=60,
            )
            raw = response.choices[0].message.content.strip()
            if not raw:
                print("LLM category empty response, using local.")
            else:
                category = _parse_llm_category(raw, labels)
                if category:
                    print(">>> LLM CATEGORY CLASSIFIER <<<")
                    return category
                print(f"LLM category raw response: {raw[:400]}")
                print("LLM category response unparseable, using local.")
        except Exception as exc:
            print(f"Category LLM failed, using local classifier: {exc}")

    print(">>> LOCAL CATEGORY CLASSIFIER (CPU) <<<")

    try:
        result = _local_classifier(
            text,
            candidate_labels=labels
        )
        return result["labels"][0]

    except Exception as e:
        print(f"Category classification failed: {e}")
        return "general"

def _parse_llm_category(raw: str, labels: list[str]) -> str | None:
    cleaned = raw.strip().strip("`").strip()
    if not cleaned:
        return None

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
            category = (parsed.get("category") or "").strip().lower()
            if category in labels:
                return category
        except Exception:
            pass

    for line in cleaned.splitlines():
        line_clean = line.strip()
        if not line_clean:
            continue
        lower_line = line_clean.lower()
        if lower_line.startswith("category"):
            if ":" in line_clean:
                candidate = line_clean.split(":", 1)[1].strip().lower().strip("\"'`")
            elif "-" in line_clean:
                candidate = line_clean.split("-", 1)[1].strip().lower().strip("\"'`")
            else:
                candidate = ""
            if candidate in labels:
                return candidate

    lowered = cleaned.lower()
    for label in labels:
        if re.search(rf"\\b{re.escape(label)}\\b", lowered):
            return label
    return None
