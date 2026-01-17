from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class ArticleOut(BaseModel):
    id: int
    title: str
    summary: str
    sentiment_emotional: str
    sentiment_contextual: str
    sentiment_confidence: str
    impact_level: Optional[str] = None
    impact_reason: Optional[str] = None
    image_url: Optional[str] = None
    source: str
    url: str
    category: str
    country: str
    published_at: datetime

    class Config:
        from_attributes = True
