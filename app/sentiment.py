from groq import Groq
import os
import json
import re
import time

GROQ_SENTIMENT_API_KEY = os.getenv("GROQ_SENTIMENT_API_KEY") or os.getenv("GROQ_API_KEY")
groq_client = Groq(api_key=GROQ_SENTIMENT_API_KEY) if GROQ_SENTIMENT_API_KEY else None

_sentiment_cache = {}

_RATE_LIMIT_RE = re.compile(r"try again in ([0-9.]+)s", re.IGNORECASE)
_RETRY_BUFFER_S = 3.0
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
                            "LLM sentiment rate limited (TPM). "
                            f"Retrying in {delay:.2f}s (attempt {attempt_label})..."
                        )
                        time.sleep(max(delay, 0.5))
                        waited = time.perf_counter() - wait_start
                        print(f"LLM sentiment retry wait complete: {waited:.2f}s.")
                        continue
                    print("LLM sentiment rate limited (TPM). Retries exhausted.")
                else:
                    print("LLM sentiment rate limited (RPD). Skipping retry.")
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


def get_dual_sentiment(title: str, summary: str) -> tuple[str, str, str, str, str]:
    try:
        combined = f"{(title or '').strip()}\n{(summary or '').strip()}".strip()
        if combined in _sentiment_cache:
            print("LLM sentiment cache hit.")
            cached = _sentiment_cache[combined]
            if isinstance(cached, tuple) and len(cached) == 4:
                tone, impact, confidence, impact_level = cached
                return (tone, impact, confidence, impact_level, "")
            return cached

        if not combined or len(combined) < 40:
            print("LLM sentiment skipped: text too short.")
            return ("neutral", "neutral for general market", "0.00", "important", "default: too little text")
        if not groq_client:
            print("LLM sentiment disabled: GROQ_SENTIMENT_API_KEY not set.")
            return ("neutral", "neutral for general market", "0.00", "important", "default: LLM disabled")

        text_for_llm = " ".join(combined.split())
        if USE_KEYWORD_FILTER:
            filtered = _select_summary_input(text_for_llm)
            if len(filtered) >= _MIN_FILTER_CHARS:
                text_for_llm = filtered

        prompt = {
            "task": "Return JSON for tone, impact, confidence, impact_level, reason.",
            "rules": [
                "tone: 1 word describing the tone",
                "impact: <sentiment> for <subject>",
                "impact sentiment: positive|negative|neutral|mixed|uncertain",
                "impact_level: critical|important|routine",
                "be conservative: if unsure, choose important (not critical)",
                "critical = immediate, time-sensitive, large-scale impact happening now (active threat, mass casualty, major disaster, emergency orders, system-wide outage)",
                "important = notable developments affecting a country, institution, or large community",
                "routine = informational or follow-up updates that do not require immediate attention",
                "crime/legal stories are usually important unless there is an active ongoing threat to public safety",
                "reason: 1 short sentence (max ~12 words) explaining why impact_level was chosen"
            ],
            "format": {
                "tone": "<tone>",
                "impact": "<sentiment> for <subject>",
                "confidence": "<float 0.0-1.0>",
                "impact_level": "<critical|important|routine>",
                "reason": "<short explanation>"
            },
            "text": text_for_llm[:_MAX_LLM_INPUT_CHARS]
        }

        response = _call_groq_with_retry(
            groq_client,
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": "You are a JSON API. Output JSON only."},
                {"role": "user", "content": json.dumps(prompt)},
            ],
            temperature=0.2,
            max_tokens=220,
        )

        raw = response.choices[0].message.content.strip()
        if not raw:
            print("LLM sentiment empty response, using defaults.")
            return ("neutral", "neutral for general market", "0.00", "important", "default: empty response")

        tone, impact, confidence, impact_level, reason, parsed = _parse_sentiment_payload(raw)
        if parsed:
            print(">>> LLM SENTIMENT <<<")
            _sentiment_cache[combined] = (tone, impact, confidence, impact_level, reason)
            return (tone, impact, confidence, impact_level, reason)

        print(f"LLM sentiment raw response: {raw[:400]}")
        strict_prompt = dict(prompt)
        strict_prompt["rules"] = [
            "Return JSON only. No code blocks, markdown, or explanations.",
        ] + prompt["rules"]
        try:
            response = _call_groq_with_retry(
                groq_client,
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": "You are a JSON API. Output JSON only."},
                    {"role": "user", "content": json.dumps(strict_prompt)},
                ],
                temperature=0.0,
                max_tokens=120,
            )
            raw = response.choices[0].message.content.strip()
            if raw:
                tone, impact, confidence, impact_level, reason, parsed = _parse_sentiment_payload(raw)
                if parsed:
                    print(">>> LLM SENTIMENT (STRICT) <<<")
                    _sentiment_cache[combined] = (tone, impact, confidence, impact_level, reason)
                    return (tone, impact, confidence, impact_level, reason)
        except Exception as exc:
            print(f"LLM sentiment strict retry failed: {exc}")

        print("LLM sentiment response unparseable, using defaults.")
        return ("neutral", "neutral for general market", "0.00", "important", "default: unparseable response")

    except Exception as e:
        print(f"Groq dual sentiment failed: {e}")
        return ("neutral", "neutral for general market", "0.00", "important", "default: exception")


def _normalize_impact_level(value: str) -> str:
    mapping = {
        "high": "critical",
        "medium": "important",
        "low": "routine",
        "critical": "critical",
        "important": "important",
        "routine": "routine",
    }
    return mapping.get(value.strip().lower(), "")

def _parse_sentiment_payload(raw: str) -> tuple[str, str, str, str, str, bool]:
    default = ("neutral", "neutral for general market", "0.00", "important", "")
    cleaned = raw.strip()
    json_text = None
    parsed = False
    if cleaned.startswith("{") and cleaned.endswith("}"):
        json_text = cleaned
    else:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            json_text = cleaned[start:end + 1]
    if json_text:
        try:
            parsed_json = json.loads(json_text)
            lowered = {
                str(key).lower().replace(" ", "_"): value
                for key, value in parsed_json.items()
            }
            tone = str(lowered.get("tone") or default[0]).strip()
            impact = str(lowered.get("impact") or default[1]).strip()
            confidence = str(lowered.get("confidence") or default[2]).strip()
            reason = str(
                lowered.get("reason")
                or lowered.get("impact_reason")
                or lowered.get("rationale")
                or default[4]
            ).strip()
            impact_level_raw = lowered.get("impact_level")
            if impact_level_raw is None and "priority" in lowered:
                impact_level_raw = lowered.get("priority")
            impact_level = _normalize_impact_level(str(impact_level_raw or default[3]))
            if impact_level not in {"critical", "important", "routine"}:
                impact_level = default[3]
            parsed = any(
                key in lowered
                for key in (
                    "tone",
                    "impact",
                    "confidence",
                    "impact_level",
                    "priority",
                    "reason",
                    "impact_reason",
                    "rationale",
                )
            )
            return (tone, impact, confidence, impact_level, reason, parsed)
        except Exception:
            pass

    tone, impact, confidence, impact_level, reason = default
    for line in cleaned.splitlines():
        lower = line.lower()
        if lower.startswith("tone:"):
            tone = line.split(":", 1)[-1].strip()
            parsed = True
        elif lower.startswith("impact:"):
            impact = line.split(":", 1)[-1].strip()
            parsed = True
        elif lower.startswith("confidence:"):
            confidence = line.split(":", 1)[-1].strip()
            parsed = True
        elif lower.startswith("impact_level:") or lower.startswith("impact level:"):
            impact_level = line.split(":", 1)[-1].strip().lower()
            parsed = True
        elif lower.startswith("reason:") or lower.startswith("rationale:"):
            reason = line.split(":", 1)[-1].strip()
            parsed = True
    impact_level = _normalize_impact_level(impact_level or default[3])
    if impact_level not in {"critical", "important", "routine"}:
        impact_level = default[3]
    return (tone, impact, confidence, impact_level, reason, parsed)
