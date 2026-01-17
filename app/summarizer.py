from transformers import BartTokenizer, pipeline
from groq import Groq
import os
import json
import re
import time
from collections import Counter

# Load tokenizer first
tokenizer = BartTokenizer.from_pretrained("facebook/bart-large-cnn")

# CPU-only pipeline to avoid CUDA issues
summarizer = pipeline(
    "summarization",
    model="facebook/bart-large-cnn",
    device=-1
)

GROQ_SUMMARIZER_API_KEY = os.getenv("GROQ_SUMMARIZER_API_KEY")
_groq_client = Groq(api_key=GROQ_SUMMARIZER_API_KEY) if GROQ_SUMMARIZER_API_KEY else None

USE_KEYWORD_FILTER = True
_MIN_FILTER_CHARS = 280

_RATE_LIMIT_RE = re.compile(r"try again in ([0-9.]+)s", re.IGNORECASE)
_RETRY_BUFFER_S = 2.0
_DEFAULT_RETRY_S = 2.0
_MAX_RETRIES = 20

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
                            "LLM summarizer rate limited (TPM). "
                            f"Retrying in {delay:.2f}s (attempt {attempt_label})..."
                        )
                        time.sleep(max(delay, 0.5))
                        waited = time.perf_counter() - wait_start
                        print(f"LLM summarizer retry wait complete: {waited:.2f}s.")
                        continue
                    print("LLM summarizer rate limited (TPM). Retries exhausted.")
                else:
                    print("LLM summarizer rate limited (RPD). Skipping retry.")
            raise

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "he", "in", "is", "it", "its", "of", "on", "that", "the", "to", "was",
    "were", "will", "with", "you", "your", "they", "their", "them", "this",
    "these", "those", "or", "but", "not", "have", "had", "been", "if",
}

def _split_sentences(text: str) -> list[str]:
    cleaned = " ".join(text.split())
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", cleaned)
    return [part.strip() for part in parts if part.strip()]

def _extract_keywords(sentences: list[str], top_n: int = 12) -> set[str]:
    tokens = re.findall(r"[A-Za-z0-9']+", " ".join(sentences))
    freq = Counter()
    for token in tokens:
        key = token.lower()
        if key in _STOPWORDS:
            continue
        if len(key) < 3 and not key.isdigit():
            continue
        freq[key] += 1
    return {word for word, _ in freq.most_common(top_n)}

def _select_summary_input(text: str) -> str:
    sentences = _split_sentences(text)
    if len(sentences) <= 3:
        return text
    keywords = _extract_keywords(sentences)
    if not keywords:
        return " ".join(sentences[:5])

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
        if len(selected) >= 5:
            break
    if len(selected) < 3:
        selected = sentences[:5]
    selected_set = set(selected)
    ordered = [sentence for sentence in sentences if sentence in selected_set]
    return " ".join(ordered)

def _llm_summary(text: str) -> str | None:
    if not _groq_client:
        print("LLM summarizer disabled: GROQ_SUMMARIZER_API_KEY not set.")
        return None
    try:
        clean_text = " ".join(text.split())
        if USE_KEYWORD_FILTER:
            filtered = _select_summary_input(clean_text)
            if len(filtered) >= _MIN_FILTER_CHARS:
                clean_text = filtered
        prompt = {
            "task": "Summarize the news article in 2-3 sentences max.",
            "rules": [
                "Write a concise, factual summary.",
                "Capture the key points of the article.",
                "No bullet points.",
                "No opinions.",
                "Return JSON only: {\"summary\": \"...\"}."
            ],
            "text": clean_text[:3000]
        }

        response = _call_groq_with_retry(
            _groq_client,
            model="groq/compound-mini",
            messages=[{"role": "user", "content": json.dumps(prompt)}],
            temperature=0.2,
            max_tokens=120,
        )
        raw = response.choices[0].message.content.strip()
        if not raw:
            print("LLM summarizer empty response, using local.")
            return None
        summary = _parse_llm_summary(raw)
        if summary:
            return _limit_sentences(summary, 4)
        print("LLM summarizer response unparseable, using local.")
        return None
    except Exception as exc:
        print(f"LLM summarization failed, using local: {exc}")
        return None

def _parse_llm_summary(raw: str) -> str | None:
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
            summary = (parsed.get("summary") or "").strip()
            if summary:
                return summary
        except Exception:
            pass

    if cleaned.lower().startswith("summary:"):
        cleaned = cleaned.split(":", 1)[1].strip()
    return cleaned or None

def _limit_sentences(text: str, max_sentences: int) -> str:
    normalized = " ".join(text.split())
    if not normalized:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", normalized)
    if len(sentences) <= max_sentences:
        return normalized
    return " ".join(sentences[:max_sentences]).strip()


def generate_summary(text: str) -> str:
    try:
        if not text or len(text.strip()) < 30:
            print("LLM summarizer skipped: text too short.")
            return text

        clean_text = text.strip()
        llm_summary = _llm_summary(clean_text)
        if llm_summary:
            print(">>> LLM SUMMARIZER <<<")
            return llm_summary

        print(">>> LOCAL SUMMARIZER (CPU, TOKEN-SAFE) <<<")

        # STEP 1: tokenize
        tokens = tokenizer.encode(clean_text, truncation=False)

        # STEP 2: truncate tokens if necessary
        MAX_ALLOWED = 900  # safe number for BART (below 1024)
        if len(tokens) > MAX_ALLOWED:
            tokens = tokens[:MAX_ALLOWED]
            clean_text = tokenizer.decode(tokens, skip_special_tokens=True)

        result = summarizer(
            clean_text,
            max_length=200,
            min_length=80,
            do_sample=False,
        )

        return result[0]["summary_text"].strip()

    except Exception as e:
        print(f"Summarization failed: {e}")
        return text
