from newspaper import Article as NewsArticle
from readability import Document
import requests
import re
import html

# Domains that usually block scraping (e.g. MarketWatch)
blocked_domains = ["ft.com"]

def normalize_url(url: str) -> str:
    if not url:
        return url
    return (
        url.replace("\\u003d", "=")
           .replace("\\u0026", "&")
           .replace("\\/", "/")
           .replace("\\=", "=")
    )

def extract_full_text(url: str) -> str:
    try:
        url = normalize_url(url)
        if not url:
            return ""
        parts = url.split("/")
        domain = parts[2] if len(parts) > 2 else ""
        if domain and any(blocked in domain for blocked in blocked_domains):
            print(f"Full text blocked for domain: {domain}. Using NewsAPI description/content fallback.")
            return ""

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept-Language": "en-US,en;q=0.9",
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        # Try Readability first using downloaded HTML.
        doc = Document(response.text)
        summary_html = doc.summary()
        readability_text = re.sub(r"<[^>]+>", " ", summary_html)
        readability_text = html.unescape(readability_text)
        readability_text = " ".join(readability_text.split())
        if readability_text:
            return readability_text

        # Fallback to Newspaper extraction when Readability yields empty text.
        article = NewsArticle(url)
        article.set_html(response.text)
        article.parse()

        text = article.text.strip()
        text = " ".join(text.split())  # clean up excess whitespace
        if not text:
            print(f"Full text empty for {url}. Using NewsAPI description/content fallback.")
            return ""
        return text
    except Exception as e:
        print(f"Failed to extract full text from {url}: {e}")
        print("Using NewsAPI description/content fallback.")
        return ""

def clean_for_summarization(text: str) -> str:
    if not text:
        return ""
    text = text.strip()
    text = re.sub(r"\n+", " ", text)  # remove excessive line breaks
    text = re.sub(r"\s{2,}", " ", text)  # remove extra spaces
    text = re.sub(r"(Read more.*?)(\.|\n|$)", "", text, flags=re.IGNORECASE)
    return text
