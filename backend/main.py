"""
Fact-Checking Pipeline — Backend
---------------------------------
Entry point for the backend server.

Run with:  uvicorn main:app --reload
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from claims import extract_and_classify
from scraper import scrape

app = FastAPI(title="Fact-Checking Pipeline")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class PostInput(BaseModel):
    text: str = ""   # Optional: manual text input (used if no URL is provided)
    url:  str = ""   # Optional: post URL (triggers scraping if provided)


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
    scraped = None

    if post.url:
        # --- Scrape the URL ---
        scraped = scrape(post.url)

        if scraped.get("error"):
            # Return the error so the frontend can display it clearly
            return {
                "error":   scraped["error"],
                "scraped": scraped,
                "claims":  [],
                "summary": "",
            }

        # Build the text we'll send to Claude.
        # Include a note about any images/videos so Claude can factor them in.
        text_to_analyze = scraped["text"]

        if scraped.get("image_urls"):
            n = len(scraped["image_urls"])
            text_to_analyze += f"\n\n[Note: this post contains {n} image(s)]"

        if scraped.get("video_urls"):
            n = len(scraped["video_urls"])
            text_to_analyze += f"\n\n[Note: this post contains {n} video(s)]"

    elif post.text:
        # --- Use manually pasted text ---
        text_to_analyze = post.text

    else:
        return {"error": "Please provide either a URL or some post text.", "claims": [], "summary": ""}

    if not text_to_analyze.strip():
        return {"error": "No text content could be extracted from this post.", "claims": [], "summary": ""}

    # --- Run Claude analysis ---
    result = extract_and_classify(text_to_analyze, post.url)

    # Attach the scraped metadata to the response so the frontend can show it
    if scraped:
        result["scraped"] = scraped

    return result
