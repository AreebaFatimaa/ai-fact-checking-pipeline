"""
Fact-Checking Pipeline — Backend
---------------------------------
Entry point for the backend server.

Run with:  uvicorn main:app --reload
"""

import logging
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from urllib.parse import urlparse

from claims import extract_and_classify
from scraper import scrape

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("factcheck")

app = FastAPI(title="Fact-Checking Pipeline")

ALLOWED_ORIGINS = os.environ.get(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:8000",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["POST", "GET"],
    allow_headers=["Content-Type"],
)


class PostInput(BaseModel):
    text: str = Field(default="", max_length=50_000)
    url:  str = Field(default="", max_length=2048)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v:
            return v
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("URL must use http or https scheme")
        if not parsed.netloc:
            raise ValueError("URL must have a valid host")
        return v


@app.get("/")
def health_check():
    return {"status": "ok", "message": "Fact-checking pipeline is running."}


@app.post("/analyze")
def analyze_post(post: PostInput):
    """
    If a URL is provided, scrape it first to get the post content.
    If only text is provided, analyze it directly.
    Either way, the content goes to Claude for claim extraction and classification.
    """
    if not post.url and not post.text:
        raise HTTPException(status_code=422, detail="Provide either a URL or post text.")

    scraped = None

    if post.url:
        logger.info("Analyzing URL: %s", post.url)
        scraped = scrape(post.url)

        if scraped.get("error"):
            return JSONResponse(
                status_code=502,
                content={
                    "error":   scraped["error"],
                    "scraped": scraped,
                    "claims":  [],
                    "summary": "",
                },
            )

        # Build the text we'll send to Claude.
        # Include a note about any images/videos so Claude can factor them in.
        text_to_analyze = scraped["text"]

        if scraped.get("image_urls"):
            n = len(scraped["image_urls"])
            text_to_analyze += f"\n\n[Note: this post contains {n} image(s)]"

        if scraped.get("video_urls"):
            n = len(scraped["video_urls"])
            text_to_analyze += f"\n\n[Note: this post contains {n} video(s)]"

    else:
        logger.info("Analyzing pasted text (%d chars)", len(post.text))
        text_to_analyze = post.text

    if not text_to_analyze.strip():
        raise HTTPException(status_code=422, detail="No text content could be extracted from this post.")

    # --- Run Claude analysis ---
    result = extract_and_classify(text_to_analyze, post.url)

    if result.get("error"):
        logger.warning("Analysis returned error: %s", result["error"])

    # Attach the scraped metadata to the response so the frontend can show it
    if scraped:
        result["scraped"] = scraped

    return result
