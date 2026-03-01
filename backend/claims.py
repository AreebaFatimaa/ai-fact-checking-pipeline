"""
Fact-Checking Pipeline — Claim Extraction & Classification
-----------------------------------------------------------
This module handles all communication with the Claude API.
It sends the post text to Claude and gets back structured claim data.
"""

import os
import json
import logging

import anthropic
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("factcheck.claims")

_api_key = os.environ.get("ANTHROPIC_API_KEY")
if not _api_key:
    raise RuntimeError(
        "ANTHROPIC_API_KEY environment variable is required. "
        "Copy .env.example to .env and set your key."
    )

client = Anthropic(api_key=_api_key)

MODEL_NAME = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-20250514")

VALID_CATEGORIES = {"out-of-context", "fabricated", "manipulated/doctored", "unclassified"}
VALID_CONFIDENCES = {"high", "medium", "low"}

SYSTEM_PROMPT = """
You are an expert fact-checker trained on the IFCN (International Fact-Checking Network) Code of Principles. You uphold the following IFCN commitments in all your work:
- Nonpartisanship and fairness: you examine all sides, you have no political agenda
- Standards and transparency of sources: you only make claims based on evidence, and you disclose your reasoning
- Transparency of funding and organisation: you operate openly
- Transparency of methodology: you explain how you reached your conclusion
- Open and honest corrections: when uncertain, you say so clearly

YOUR TASK:
Given the text of a social media post, you must:

1. Extract every distinct factual claim made in the post.
2. For each claim, assign ONE category from this exact list:
   - "out-of-context": Real media (photo/video/audio) is paired with a false or misleading context. Example: a video genuinely filmed in India is used to claim an event happened in Pakistan.
   - "fabricated": The claim asserts something entirely false. There is no credible corroboration in regional or international news sources.
   - "manipulated/doctored": The claim involves images or videos that appear to be edited, AI-generated, or otherwise synthetically altered.
   - "unclassified": You do not have enough information to confidently assign one of the above three categories.

3. Label which types of media the claim references (based on what the text describes or implies):
   - "contains image"
   - "contains video"
   - "contains audio"
   Only apply labels that clearly apply. If no media is referenced, use an empty list.

4. For each claim, explain your reasoning in detail (3-5 sentences). Your reasoning MUST include:
   - What specific evidence or information you used to reach your classification
   - What methodology or technique you applied (e.g., cross-referencing with known news reports, analyzing linguistic patterns, checking for known misinformation narratives, identifying inconsistencies in the claim)
   - Why this evidence supports the chosen category over other categories

5. Rate your confidence: "high", "medium", or "low".

CRITICAL: You have access to web search. For EVERY factual claim, you MUST:
1. Search the web to find corroborating or contradicting evidence before assigning a category. Do not rely solely on your training data.
2. Search for EXISTING FACT-CHECKS written by IFCN (International Fact-Checking Network) verified signatories. These are professional fact-checking organizations. For each claim, search using the claim keywords plus terms like "fact check" or "fact-check" and look specifically for articles from IFCN signatory websites. Key IFCN signatories include (but are not limited to):
   - Global/English: snopes.com, politifact.com, factcheck.org, fullfact.org, leadstories.com, checkyourfact.com, washingtonpost.com, pa.media, thedispatch.com
   - Africa: africacheck.org, dubawa.org, pesacheck.org, ghanafact.com, factcheckafrica.net
   - Americas: chequeado.com, colombiacheck.com, aosfatos.org, verificado.com.mx, animalpolitico.com, fastcheck.cl
   - Asia-Pacific: boomlive.in, factly.in, vishvasnews.com, rappler.com, verafiles.org, news.abs-cbn.com, kompas.com, aap.com.au
   - Europe: correctiv.org, maldita.es, newtral.es, pagellapolitica.it, facta.news, faktisk.no, tjekdet.dk, ellinikahoaxes.gr, demagog.org.pl, stopfake.org
   - Middle East: teyit.org, dogrulukpayi.com, verify-sy.com, factnameh.com, kashif.ps
   - Wire services: afp.com, dpa-factchecking.com, efe.com, reutersagency.com, observers.france24.com
   If a claim is region-specific, prioritize searching IFCN signatories from that region in the relevant language.
3. If you find an existing fact-check from an IFCN signatory, include the URL, the signatory name, and their verdict in the existing_fact_checks array for that claim.

IMPORTANT RULES:
- When in doubt, use "unclassified". Do not guess.
- Do not invent claims that are not in the post.
- Be specific: quote or closely paraphrase the actual claim text.
- If the post makes no checkable factual claims (e.g., it's purely an opinion), return an empty claims list and explain why in the summary.

RESPONSE FORMAT:
Return ONLY a valid JSON object with this exact structure — no extra text, no markdown:
{
  "claims": [
    {
      "claim_text": "The specific claim, quoted or closely paraphrased",
      "category": "fabricated",
      "reasoning": "Detailed explanation of why this category applies, what evidence and methodology were used",
      "media_labels": ["contains image"],
      "confidence": "medium",
      "existing_fact_checks": [
        {
          "url": "https://example-factchecker.com/article",
          "source": "Name of IFCN signatory",
          "verdict": "Their verdict or rating (e.g., False, Misleading, True, etc.)"
        }
      ]
    }
  ],
  "summary": "A 2-3 sentence overall assessment of the post"
}
"""


def _extract_json_object(text: str):
    """Extract the first valid JSON object from text, handling braces in strings."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if depth == 0:
            try:
                return json.loads(text[start:i + 1])
            except json.JSONDecodeError:
                return None
    return None


def _validate_claims(result: dict) -> dict:
    """Normalize categories and confidence values to expected enums."""
    for claim in result.get("claims", []):
        cat = (claim.get("category") or "").lower()
        if cat not in VALID_CATEGORIES:
            claim["category"] = "unclassified"

        conf = (claim.get("confidence") or "").lower()
        if conf not in VALID_CONFIDENCES:
            claim["confidence"] = "low"
        else:
            claim["confidence"] = conf
    return result


def extract_and_classify(text: str, url: str = "") -> dict:
    """
    Sends post text to Claude and returns structured claim data.

    Args:
        text: The full text of the social media post
        url:  The original URL (optional, included as context for Claude)

    Returns:
        A dict with 'claims' (list) and 'summary' (string)
    """
    url_context = f"Original post URL: {url}\n\n" if url else ""
    user_message = (
        f"{url_context}"
        f"Please analyze this social media post and extract all factual claims:\n\n"
        f"---\n{text}\n---"
    )

    logger.info("Calling Claude (%s) with %d chars of input", MODEL_NAME, len(user_message))

    try:
        response = client.messages.create(
            model=MODEL_NAME,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 10}],
            timeout=120.0,
        )
    except anthropic.RateLimitError:
        logger.warning("Anthropic API rate limited")
        return {"claims": [], "summary": "", "sources": [], "error": "Rate limited by Anthropic API. Please wait and retry."}
    except anthropic.APITimeoutError:
        logger.warning("Anthropic API request timed out")
        return {"claims": [], "summary": "", "sources": [], "error": "Anthropic API request timed out."}
    except anthropic.APIError as e:
        logger.error("Anthropic API error: %s", e)
        return {"claims": [], "summary": "", "sources": [], "error": f"Anthropic API error: {e}"}

    if not response.content:
        logger.warning("Claude returned empty response. Stop reason: %s", response.stop_reason)
        return {
            "claims": [],
            "summary": "",
            "sources": [],
            "error": f"Claude returned empty response (stop_reason: {response.stop_reason}).",
        }

    # Extract text from text blocks and sources from web search result blocks
    raw_text = ""
    sources = []
    seen_urls = set()
    for block in response.content:
        if block.type == "text":
            raw_text += block.text
        elif block.type == "web_search_tool_result":
            for item in getattr(block, "content", []):
                if getattr(item, "type", None) == "web_search_result":
                    result_url = getattr(item, "url", "")
                    if result_url and result_url not in seen_urls:
                        seen_urls.add(result_url)
                        sources.append({"title": getattr(item, "title", result_url), "url": result_url})

    raw_text = raw_text.strip()

    if response.stop_reason == "max_tokens":
        logger.warning("Response truncated (max_tokens reached)")
        return {
            "claims": [],
            "summary": raw_text[:500],
            "sources": sources,
            "error": "Response was truncated (max_tokens reached). Try shorter input.",
        }

    try:
        if raw_text.startswith("```"):
            raw_text = raw_text.split("\n", 1)[1]
            raw_text = raw_text.rsplit("```", 1)[0].strip()

        result = json.loads(raw_text)
    except json.JSONDecodeError:
        # With web search, Claude may output text around the JSON.
        # Try to extract the JSON object with string-aware brace matching.
        result = _extract_json_object(raw_text)
        if result is None:
            logger.warning("Failed to parse Claude response as JSON")
            result = {
                "claims": [],
                "summary": raw_text,
                "error": "Claude returned a response that could not be parsed as structured data. The raw response is shown in 'summary'."
            }

    result = _validate_claims(result)
    result["sources"] = sources

    logger.info("Analysis complete: %d claims extracted, %d sources found", len(result.get("claims", [])), len(sources))
    return result
