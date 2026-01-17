# AIDA News Dashboard

Streamlit dashboard + FastAPI backend for news summarization, sentiment, and priority tagging.

## Requirements
- Python 3.10+
- NewsAPI key
- Groq API key (for LLM sentiment)

## Setup
```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
```

Create env vars:
```bash
set NEWSAPI_KEY=your_key_here
set GROQ_API_KEY=your_key_here
```

## Run locally
Start the FastAPI backend:
```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Start the Streamlit dashboard (new terminal):
```bash
streamlit run app/dashboard.py
```

## Optional: shared access on local network
```bash
streamlit run app/dashboard.py --server.address 0.0.0.0 --server.port 8501
```
Open `http://<your_pc_ip>:8501` on another device on the same Wi‑Fi.

## Notes
- SQLite DB is stored in `aida.db`.
- The app caches summaries and sentiment in the DB; re-fetch to update fields like `impact_reason` and `image_url`.
