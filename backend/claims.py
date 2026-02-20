"""
Fact-Checking Pipeline — Claim Extraction & Classification
-----------------------------------------------------------
This module handles all communication with the Claude API.
It sends the post text to Claude and gets back structured claim data.
"""

import os
import json
from anthropic import Anthropic
from dotenv import load_dotenv

# load_dotenv() reads the .env file and makes its values available
# as environment variables. This is how we keep API keys out of the code.
load_dotenv()

client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


# This is the "system prompt" — the set of instructions we give Claude
# before showing it any user content. Think of it as Claude's job description
# for this specific task. It references the IFCN Code of Principles.
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

4. For each claim, briefly explain your reasoning (1-2 sentences).

5. Rate your confidence: "high", "medium", or "low".

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
      "reasoning": "Brief explanation of why this category applies",
      "media_labels": ["contains image"],
      "confidence": "medium"
    }
  ],
  "summary": "A 2-3 sentence overall assessment of the post"
}
"""


def extract_and_classify(text: str, url: str = "") -> dict:
    """
    Sends post text to Claude and returns structured claim data.

    Args:
        text: The full text of the social media post
        url:  The original URL (optional, included as context for Claude)

    Returns:
        A dict with 'claims' (list) and 'summary' (string)
    """

    # Build the user message. If a URL was provided, include it as context.
    url_context = f"Original post URL: {url}\n\n" if url else ""
    user_message = (
        f"{url_context}"
        f"Please analyze this social media post and extract all factual claims:\n\n"
        f"---\n{text}\n---"
    )

    # Make the API call to Claude.
    # "model" specifies which AI model to use.
    # "max_tokens" limits how long Claude's response can be (controls cost).
    # "messages" is the conversation — here just one user turn.
    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": user_message}
        ]
    )

    # Claude returns a list of content blocks. We want the text of the first one.
    raw_text = response.content[0].text.strip()

    # Parse the JSON response from Claude.
    # Claude sometimes wraps JSON in markdown code fences (```json ... ```)
    # so we strip those if present.
    try:
        if raw_text.startswith("```"):
            # Remove the opening fence (```json or ```) and the closing ```
            raw_text = raw_text.split("\n", 1)[1]           # drop first line
            raw_text = raw_text.rsplit("```", 1)[0].strip() # drop last ```

        result = json.loads(raw_text)

    except json.JSONDecodeError:
        # If parsing fails, return the raw text as a fallback so the user
        # sees something rather than a silent error.
        result = {
            "claims": [],
            "summary": raw_text,
            "error": "Claude returned a response that could not be parsed as structured data. The raw response is shown in 'summary'."
        }

    return result
