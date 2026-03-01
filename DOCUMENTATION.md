# AI Fact-Checking Pipeline -- Documentation

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture](#2-architecture)
3. [How It Works](#3-how-it-works)
4. [Classification Categories](#4-classification-categories)
5. [Web Search Integration](#5-web-search-integration)
6. [Setup and Usage](#6-setup-and-usage)
7. [Technical Details](#7-technical-details)
8. [Security Considerations](#8-security-considerations)
9. [Bug Fixes and Reliability Improvements](#9-bug-fixes-and-reliability-improvements)
10. [Development History](#10-development-history)

---

## 1. Project Overview

The AI Fact-Checking Pipeline is a tool that extracts and classifies factual claims from social media posts. It is built for Columbia University research and aligned with the **International Fact-Checking Network (IFCN) Code of Principles**.

The tool takes the text of a social media post as input, sends it to Anthropic's Claude AI model with a carefully designed system prompt, and receives back a structured analysis. Each distinct factual claim in the post is identified, classified into a misinformation category, and accompanied by detailed reasoning, confidence levels, and source citations from live web searches.

**Key characteristics:**

- AI-assisted, not AI-autonomous: all classifications are explicitly labeled as requiring human verification
- Evidence-based: Claude performs live web searches before classifying each claim, rather than relying solely on training data
- Transparent methodology: every classification includes a detailed reasoning section explaining the evidence and techniques used
- Standards-aligned: the system prompt encodes the five IFCN commitments (nonpartisanship, source transparency, organizational transparency, methodological transparency, and open corrections)
- Research-oriented: results are exportable as CSV for further analysis

---

## 2. Architecture

The project operates in two distinct modes, each suited to different use cases.

### Frontend-Only Mode (`docs/`)

A self-contained single-page application that runs entirely in the browser. There is no backend server involved.

```
User's Browser
  |
  |--> docs/index.html (HTML structure and layout)
  |      |
  |      |--> docs/app.js (all application logic, loaded as external script)
  |      |      |
  |      |      |--> Anthropic Messages API (https://api.anthropic.com/v1/messages)
  |      |      |      - Direct browser-to-API calls
  |      |      |      - User provides their own API key
  |      |      |      - Uses anthropic-dangerous-direct-browser-access header
  |      |      |
  |      |      |--> localStorage
  |      |             - API key persistence
  |      |             - Claims queue persistence
  |      |             - CSV export generation
  |      |
  |      |--> docs/style.css (all styles)
```

**Files:**
- `docs/index.html` -- HTML structure only; references `app.js` as an external script and `style.css` for styling. Contains a hardened Content Security Policy meta tag.
- `docs/app.js` -- All frontend JavaScript: system prompt, API key management, Claude API calls, response parsing, queue management, CSV export, and UI rendering. Extracted from the former inline script in `index.html` to enable strict CSP (see [Security Considerations](#8-security-considerations)).
- `docs/style.css` -- Stylesheet with category color-coding, responsive layout, visual components, password input styling, keyboard focus outlines, source list formatting, IFCN fact-checks box styling (`.fact-checks-box`, `.fact-checks-label`, `.fact-checks-list`, `.fc-verdict`), and a mobile-responsive queue grid

This mode is ideal for individual researchers or fact-checkers who have their own Anthropic API key and want a zero-setup tool.

### Backend Mode (`backend/`)

A Python FastAPI server that adds URL scraping capabilities. Instead of pasting text manually, users can submit a social media URL and the server will extract the post content automatically before sending it to Claude.

```
Client (browser or API consumer)
  |
  |--> FastAPI Server (backend/main.py)
         |
         |--> Scraper (backend/scraper.py)
         |      - Reddit: public JSON API
         |      - YouTube: yt-dlp + youtube-transcript-api
         |      - X/Twitter: Playwright browser automation
         |      - Instagram: Playwright browser automation
         |      - Facebook: Playwright browser automation
         |
         |--> Claims Processor (backend/claims.py)
                |
                |--> Anthropic Messages API
                       - Server-side API key (environment variable)
                       - Claude with web search tool
```

**Files:**
- `backend/main.py` -- FastAPI application with CORS middleware, input validation, and the `/analyze` endpoint
- `backend/claims.py` -- Claude API communication, system prompt, response parsing, and validation
- `backend/scraper.py` -- Platform-specific scrapers for Reddit, YouTube, X/Twitter, Instagram, and Facebook
- `backend/requirements.txt` -- Python dependencies
- `railway.toml` -- Deployment configuration for Railway

---

## 3. How It Works

The fact-checking pipeline follows these steps from input to output:

### Step 1: Input

The user pastes the full text of a social media post into the text area (frontend mode) or submits a URL/text to the `/analyze` endpoint (backend mode).

In backend mode, if a URL is provided, the scraper module detects the platform and extracts the post text, images, and video metadata before proceeding.

### Step 2: Prompt Construction

The post text is wrapped in a structured user message:

```
Please analyze this social media post and extract all factual claims:

---
[post text here]
---
```

This is paired with a system prompt that instructs Claude to act as an IFCN-aligned fact-checker. The system prompt specifies:
- The five IFCN commitments Claude must uphold
- The exact task (extract claims, classify, label media, explain reasoning, rate confidence)
- The four valid classification categories with definitions
- The requirement to search the web for every claim before classifying
- Rules about defaulting to "unclassified" when uncertain
- The exact JSON response format expected

### Step 3: Claude API Call with Web Search

The request is sent to Claude (model: `claude-sonnet-4-20250514`) with:
- `max_tokens: 4096`
- The web search tool enabled: `{ type: "web_search_20250305", name: "web_search", max_uses: 10 }`

Claude reads the post, identifies factual claims, and for each one performs web searches to find corroborating or contradicting evidence from real sources. It also searches for existing fact-checks from IFCN signatory organizations (see [IFCN Signatory Fact-Check Search](#ifcn-signatory-fact-check-search)). It then classifies each claim based on the evidence found.

### Step 4: Response Parsing

Claude's response with web search enabled contains mixed content blocks:
- `text` blocks -- Claude's written output (containing the JSON result)
- `web_search_tool_use` blocks -- the search queries Claude issued
- `web_search_tool_result` blocks -- search results with URLs, titles, and snippets

The parser:
1. Concatenates all `text` blocks to get the raw output
2. Extracts unique source URLs from all `web_search_tool_result` blocks (deduplicating by URL)
3. Strips markdown code fences if Claude wrapped the JSON in them
4. Attempts direct JSON parsing; if that fails, uses a brace-depth algorithm to extract the outermost `{ ... }` JSON object from surrounding text
5. Validates and normalizes all category and confidence values

### Step 5: Results Display

The parsed results are displayed in the UI:
- **Overall assessment** -- A 2-3 sentence summary of the post
- **Sources** -- Deduplicated list of URLs from Claude's web searches, displayed as clickable links
- **Individual claim cards** -- Each claim shown with:
  - The claim text (quoted or paraphrased)
  - Classification category (color-coded badge)
  - Confidence level (high, medium, or low)
  - Detailed reasoning explaining the evidence and methodology
  - Existing fact-checks from IFCN signatories (green box listing signatory names as links with their verdicts)
  - Media type labels (if applicable)

### Step 6: Queue and Export

Each analysis is stored as an entry in the Claims Queue:
- Persisted to `localStorage` so results survive page refreshes
- Entries can be archived or restored
- Clicking a queue entry shows its full analysis detail
- The entire queue is exportable as a CSV file

---

## 4. Classification Categories

Each extracted claim is assigned exactly one of the following categories:

### Fabricated

The claim asserts something entirely false. There is no credible corroboration in regional or international news sources.

**Example:** A post claims "The Eiffel Tower collapsed last night" when no such event occurred and no credible news outlet reports it.

**When to use:** The claim describes an event, statistic, or fact that has no basis in reality and cannot be verified by any credible source.

### Out-of-Context

Real media (photo, video, or audio) is paired with a false or misleading context. The underlying content is genuine, but the narrative around it is wrong.

**Example:** A video genuinely filmed during a 2019 flood in India is shared with the caption "Flooding in Pakistan today." The video is real; the context is false.

**When to use:** The media or underlying event is authentic, but the claim misattributes the time, location, participants, or significance.

### Manipulated/Doctored

The claim involves images, videos, or audio that appear to be edited, AI-generated, or otherwise synthetically altered.

**Example:** A photograph of a political figure has been digitally altered to show them in a compromising situation that never occurred.

**When to use:** The media itself has been technically modified -- through Photoshop, deepfake generation, selective cropping that changes meaning, or other forms of synthetic alteration.

### Unclassified

There is not enough information to confidently assign one of the above three categories. This is the default when evidence is insufficient.

**When to use:** The claim cannot be definitively verified or debunked with available evidence, or it falls outside the scope of the other categories. The system is designed to default here rather than guess.

---

## 5. Web Search Integration

### Why Web Search Was Added

Without web search, Claude classifies claims based solely on its training data (with a knowledge cutoff). This created a significant problem: claims about recent events or region-specific news would often be classified as "unclassified" because Claude had no evidence to work with, even when ample evidence existed online. Adding web search allows Claude to find real-time evidence before making a classification decision.

### How It Works

The Anthropic Messages API supports a built-in web search tool (`web_search_20250305`). When enabled, Claude can issue web search queries mid-response, receive results, and incorporate those results into its reasoning.

The tool is configured in the API request:

```json
{
  "tools": [
    {
      "type": "web_search_20250305",
      "name": "web_search",
      "max_uses": 10
    }
  ]
}
```

The `max_uses: 10` parameter limits Claude to ten search queries per analysis. This was increased from the original five to accommodate both general evidence searches and dedicated IFCN signatory fact-check searches for each claim.

### Response Structure with Web Search

When web search is active, the `content` array in Claude's response contains interleaved blocks of different types:

```
[
  { type: "text",                   text: "..." },
  { type: "web_search_tool_use",    id: "...", input: { query: "..." } },
  { type: "web_search_tool_result", content: [
      { type: "web_search_result", url: "...", title: "...", ... },
      ...
    ]
  },
  { type: "text",                   text: "..." },
  ...
]
```

### Source Extraction and Deduplication

The parser iterates through all content blocks and:

1. Filters `text` blocks and concatenates them to form the raw JSON output
2. For each `web_search_tool_result` block, iterates through its `content` array
3. For each `web_search_result` item, extracts the `url` and `title`
4. Uses a `Set` (JavaScript) or `set` (Python) to track seen URLs and prevent duplicates
5. Attaches the deduplicated source list to the final result object

Sources are displayed in the UI as a clickable list under the "Sources" heading in the summary panel.

### IFCN Signatory Fact-Check Search

In addition to general evidence searches, the system prompt instructs Claude to specifically search for existing fact-checks published by verified IFCN (International Fact-Checking Network) signatories for every claim it analyzes.

**How it works:**

A curated list of key IFCN signatory domains is embedded directly in the system prompt, organized by region:

- **Global/English** -- e.g., Snopes, PolitiFact, FactCheck.org, Full Fact, Reuters Fact Check, AP Fact Check, Logically Facts
- **Africa** -- e.g., Africa Check, PesaCheck, Dubawa
- **Americas** -- e.g., Chequeado, Aos Fatos, Lupa, Colombiacheck, Animal Politico
- **Asia-Pacific** -- e.g., BOOM, Alt News, Vishvas News, Fact Crescendo, VERA Files, Tirto, AAP FactCheck
- **Europe** -- e.g., Maldita.es, Newtral, Correctiv, Les Decodeurs, Pagella Politica, EUvsDisinfo
- **Middle East** -- e.g., Fatabyyano, Misbar, Verify-Sy
- **Wire services** -- AFP Fact Check, Reuters Fact Check

The full list of all 172 IFCN signatory domains is maintained in `list.txt` at the project root.

**Region-aware prioritization:** For region-specific claims, the system prompt instructs Claude to prioritize signatories from the relevant region and search in the appropriate language. For example, a claim about Indian politics would trigger searches on BOOM, Alt News, and Vishvas News before broader English-language fact-checkers.

**Response format:** For each claim, Claude returns an `existing_fact_checks` array containing objects with:
- `url` -- the URL of the published fact-check article
- `source` -- the name of the IFCN signatory organization
- `verdict` -- the signatory's rating or verdict on the claim

**UI presentation:** Existing fact-checks are displayed in a green-themed box below the reasoning section on each claim card, titled "Existing Fact-Checks (IFCN Signatories)." Each entry shows the signatory name as a clickable link to the fact-check article, followed by the signatory's verdict.

---

## 6. Setup and Usage

### Frontend-Only Mode (Recommended for Most Users)

**Requirements:** A modern web browser with JavaScript enabled and an Anthropic API key.

1. Open `docs/index.html` in a browser (or access it via GitHub Pages if deployed)
2. Enter your Anthropic API key in the Settings section
   - Get a key at [console.anthropic.com](https://console.anthropic.com/)
   - The key is stored in your browser's `localStorage` and sent directly to Anthropic's API
3. Paste the text of a social media post into the input area
4. Click **Analyze Claims** (or press `Ctrl+Enter`)
5. Wait 30-60 seconds for Claude to search the web and classify claims
6. Review results in the Analysis Detail panel
7. Export your queue as CSV using the **Export as CSV** button

**Tip:** Set a monthly spending limit on your Anthropic account to prevent unexpected charges.

### Backend Mode

**Requirements:** Python 3.10+, an Anthropic API key, and (optionally) Playwright with Chromium for URL scraping.

#### Environment Setup

```bash
cd backend

# Create and configure environment variables
cp .env.example .env
# Edit .env and set:
#   ANTHROPIC_API_KEY=sk-ant-api03-...
#   CLAUDE_MODEL=claude-sonnet-4-20250514  (optional, this is the default)
#   ALLOWED_ORIGINS=http://localhost:3000   (optional, for CORS)
#   ENVIRONMENT=production                  (optional, disables browser-based scrapers)

# Install Python dependencies
pip install -r requirements.txt

# (Optional) Install Playwright for URL scraping
python -m playwright install chromium
```

#### Running the Server

```bash
cd backend
uvicorn main:app --reload
```

The server starts at `http://localhost:8000`.

#### API Endpoints

**Health check:**
```
GET /
Response: { "status": "ok", "message": "Fact-checking pipeline is running." }
```

**Analyze a post:**
```
POST /analyze
Content-Type: application/json

{
  "text": "Full text of the social media post",
  "url": ""
}
```

Or with a URL (triggers scraping):
```json
{
  "text": "",
  "url": "https://www.reddit.com/r/example/comments/abc123/post_title/"
}
```

**Response format:**
```json
{
  "claims": [
    {
      "claim_text": "The specific claim",
      "category": "fabricated",
      "reasoning": "Detailed explanation...",
      "media_labels": [],
      "confidence": "high",
      "existing_fact_checks": [
        {
          "url": "https://www.snopes.com/fact-check/example/",
          "source": "Snopes",
          "verdict": "False"
        }
      ]
    }
  ],
  "summary": "Overall assessment of the post",
  "sources": [
    { "title": "Source Title", "url": "https://example.com/article" }
  ],
  "scraped": { "platform": "reddit", "text": "...", "author": "...", ... }
}
```

#### Supported Platforms for URL Scraping

| Platform    | Method                         | Login Required | Notes                                      |
|-------------|--------------------------------|----------------|--------------------------------------------|
| Reddit      | Public JSON API                | No             | Append `.json` to the URL; very reliable   |
| YouTube     | yt-dlp + youtube-transcript-api| No             | Extracts title, description, and transcript |
| X/Twitter   | Playwright browser automation  | Yes (first run)| Opens a browser window for manual login    |
| Instagram   | Playwright browser automation  | Yes (first run)| Uses Open Graph meta tags                  |
| Facebook    | Playwright browser automation  | Yes (first run)| Uses Open Graph meta tags                  |

For platforms requiring login (X/Twitter, Instagram, Facebook): on the first run, a Chrome window opens and you log in manually. Session cookies are saved to `backend/sessions/<platform>/` so subsequent runs are automatic. These scrapers are disabled in production environments (`ENVIRONMENT=production`) since there is no browser available on a remote server.

### Deployment on Railway

The project includes a `railway.toml` configuration file:

```toml
[build]
rootDirectory = "backend"
buildCommand = "pip3 install -r requirements.txt && python3 -m playwright install --with-deps chromium"

[deploy]
startCommand = "uvicorn main:app --host 0.0.0.0 --port $PORT --workers 2 --timeout-keep-alive 65"
healthcheckPath = "/"
restartPolicyType = "on_failure"
```

**Required Railway environment variables:**
- `ANTHROPIC_API_KEY` -- Your Anthropic API key
- `ENVIRONMENT=production` -- Disables browser-based scrapers (since Railway has no GUI)
- `ALLOWED_ORIGINS` -- Comma-separated list of allowed CORS origins

---

## 7. Technical Details

### System Prompt Design

The system prompt is the core of the pipeline's accuracy and consistency. It is identical in both frontend (`app.js`) and backend (`claims.py`) modes -- both include the same category definitions, the same India/Pakistan out-of-context example, and the same web search mandate. The prompt encodes:

1. **IFCN identity:** Claude is instructed to act as an expert fact-checker trained on the IFCN Code of Principles. The five IFCN commitments are listed explicitly.

2. **Structured task:** The prompt defines a five-step task: extract claims, assign categories, label media types, explain reasoning, and rate confidence.

3. **Category definitions:** Each of the four categories is defined with clear criteria and examples (including the India/Pakistan out-of-context example). The categories are deliberately limited to avoid ambiguity.

4. **Reasoning requirements:** Claude must explain what evidence it used, what methodology it applied, and why the evidence supports the chosen category. This enforces transparency.

5. **Web search mandate:** The prompt includes a "CRITICAL" instruction to search the web for every factual claim before classifying it.

6. **IFCN signatory fact-check search:** The prompt embeds a curated list of IFCN verified signatory domains organized by region and instructs Claude to search for existing fact-checks from these organizations for every claim. For region-specific claims, Claude is directed to prioritize signatories from the relevant region and search in the appropriate language.

7. **Guardrails:** Rules about defaulting to "unclassified" when uncertain, not inventing claims, and being specific with claim text.

8. **Output format:** The exact JSON schema is specified, with the instruction to return "ONLY a valid JSON object -- no extra text, no markdown." Each claim object now includes an `existing_fact_checks` array alongside the existing fields.

### Response Parsing

Claude's response requires robust parsing because:

- With web search enabled, the response `content` array contains mixed block types (text, tool use, tool results)
- Claude occasionally wraps JSON in markdown code fences (`` ```json ... ``` ``) despite being told not to
- Claude may include explanatory text before or after the JSON when web search is active

The parsing strategy (implemented identically in frontend JavaScript and backend Python):

1. **Block filtering:** Iterate through `content` blocks, concatenate all `text` blocks, and separately collect sources from `web_search_tool_result` blocks.

2. **Code fence stripping:** If the text starts with `` ``` ``, split on newlines, drop the first line (the fence opener), and remove the closing fence.

3. **Direct parse attempt:** Try `JSON.parse()` / `json.loads()` on the cleaned text.

4. **String-aware brace-depth extraction (fallback):** If direct parsing fails, find the first `{` character and walk forward tracking brace depth, while also tracking whether the current position is inside a JSON string value. The algorithm skips `{` and `}` characters that appear inside quoted strings (and handles backslash escapes), so that JSON values containing literal braces do not break the depth counter. When depth returns to zero, extract that substring and attempt to parse it as JSON. This handles cases where Claude writes prose around the JSON, even when the JSON itself contains brace characters in string values.

5. **Graceful degradation:** If all parsing fails, the raw text is returned as the `summary` field with an error message, so the user still sees Claude's output.

### Validation and Normalization

After parsing, every claim is validated:

- **Category normalization:** The `category` field is lowercased and checked against the set `{"out-of-context", "fabricated", "manipulated/doctored", "unclassified"}`. Any unrecognized value defaults to `"unclassified"`.

- **Confidence normalization:** The `confidence` field is lowercased and checked against `{"high", "medium", "low"}`. Any unrecognized value defaults to `"low"`.

This ensures the UI always receives predictable values for rendering badges and colors, regardless of minor variations in Claude's output.

### CSV Export Format

The CSV export contains one row per claim (posts with multiple claims produce multiple rows). Columns:

| Column              | Description                                              |
|---------------------|----------------------------------------------------------|
| Serial Number       | Auto-incrementing ID of the queue entry                  |
| Post Text (preview) | First 80 characters of the original post text            |
| Claim               | The extracted claim text                                 |
| Classification      | One of the four category values                          |
| Reasoning           | Claude's detailed explanation                            |
| Confidence          | high, medium, or low                                     |
| IFCN Fact-Checks    | Pipe-separated list of existing fact-checks from IFCN signatories, formatted as `Source: Verdict (URL) | Source: Verdict (URL)` |
| Sources             | Pipe-separated (`|`) list of source URLs from web search |
| Date Searched       | Date of analysis (YYYY-MM-DD format)                     |
| Time Searched       | Time of analysis (HH:MM:SS format)                       |
| Status              | Active or Archived                                       |

Fields containing commas or quotes are properly escaped using double-quoting.

---

## 8. Security Considerations

### API Key Handling (Frontend Mode)

- The Anthropic API key is stored in the browser's `localStorage` under the key `fc_api_key`
- The key is sent directly from the browser to `https://api.anthropic.com` -- it never passes through any intermediary server
- The `anthropic-dangerous-direct-browser-access: true` header is required by Anthropic for direct browser-to-API calls
- A "Clear" button is provided to delete the key from `localStorage`
- The UI warns users not to use the tool on shared or public computers

### Content Security Policy (Hardened)

The frontend includes a strict CSP meta tag that does **not** allow `'unsafe-inline'` for scripts:

```
default-src 'self';
script-src 'self';
connect-src https://api.anthropic.com;
style-src 'self' 'unsafe-inline';
```

This restricts:
- **Script execution to same-origin only** -- no inline scripts, no `eval()`, no injected `<script>` tags. All JavaScript lives in the external `app.js` file loaded via `<script src="app.js"></script>`.
- **Network requests to only `https://api.anthropic.com`** (via `connect-src`) -- even if an attacker injects HTML, they cannot exfiltrate data to a third-party server.
- **Style sources to inline and same-origin** -- `'unsafe-inline'` is retained for styles only, since CSS injection does not pose the same exfiltration risk as script injection.

**Why this matters:** The application stores the user's Anthropic API key in `localStorage`. When hosted on GitHub Pages, all repositories under the same `*.github.io` origin share `localStorage`. Without strict CSP, a cross-site scripting (XSS) vulnerability in any page on that origin could read the API key. By removing `'unsafe-inline'` from `script-src` and moving all JavaScript to an external file, the attack surface for XSS-based key theft is significantly reduced. An attacker would need to compromise the hosted `app.js` file itself, rather than simply injecting a `<script>` tag.

### Backend Mode Security

- The API key is loaded from environment variables (`ANTHROPIC_API_KEY`), never hardcoded
- CORS middleware restricts allowed origins (configurable via `ALLOWED_ORIGINS` environment variable)
- URL input is validated: scheme must be `http` or `https`, and a valid host must be present
- The scraper includes **SSRF protection**: each platform has a whitelist of allowed domains, and URLs are validated against these before any request is made
- Reddit API requests disable redirects (`allow_redirects=False`) to prevent redirect-based SSRF
- Browser session cookies (saved by Playwright) are stored in `backend/sessions/` and excluded from git via `.gitignore`

### Data Privacy

- In frontend mode, all data stays in the user's browser. No server stores post text, analysis results, or API keys.
- In backend mode, post text is sent to the FastAPI server and then to Anthropic's API. No data is persisted on the backend server.
- The `.gitignore` excludes `.env` files, session directories, and local reference documents.

---

## 9. Bug Fixes and Reliability Improvements

This section documents specific bugs that were identified and fixed during development, along with reliability and accessibility improvements.

### JSON Parsing: String-Aware Brace Matching

**Problem:** The fallback JSON extraction algorithm (used when Claude wraps JSON in surrounding prose) tracked brace depth by counting `{` and `}` characters. If a JSON string value contained literal braces -- for example, `"reasoning": "The post uses {sic} formatting..."` -- the depth counter would be thrown off, causing the extraction to return an incomplete or invalid JSON substring.

**Fix:** Both the frontend (`extractJSON()` in `app.js`) and backend (`_extract_json_object()` in `claims.py`) now use a string-aware brace matching algorithm. The parser tracks whether it is currently inside a JSON string (between unescaped `"` characters) and skips all brace characters encountered inside strings. Backslash escape sequences (`\"`) are also handled correctly.

### API Key Race Condition

**Problem:** The `analyzePost()` function read the API key from `localStorage`, but if the user had just typed a key and clicked "Analyze" without first blurring the input field, the `blur` event (which saves the key to `localStorage`) would not have fired yet. The function would read a stale or empty key.

**Fix:** `analyzePost()` now reads the key directly from the input element (`keyInput.value.trim()`) first, saves it to `localStorage` immediately, and only falls back to `localStorage` if the input is empty. This eliminates the timing dependency on the `blur` event.

### Variable Shadowing in claims.py

**Problem:** In the web search source extraction loop in `claims.py`, the variable name `url` was used for the URL extracted from each search result. This shadowed the `url` parameter of the `extract_and_classify()` function, which could cause subtle bugs if the parameter was referenced after the loop.

**Fix:** The loop variable was renamed from `url` to `result_url` to avoid shadowing the function parameter.

### Browser Cleanup in scraper.py

**Problem:** In the Playwright-based scraper (`scrape_playwright()`), if content extraction raised an unexpected exception, the `browser.close()` call could be skipped, leaving an orphaned browser process.

**Fix:** The content extraction call is now wrapped in a `try/finally` block that ensures `browser.close()` is always called, regardless of whether extraction succeeds or raises an exception.

### localStorage Quota Error Handling

**Problem:** The `saveQueue()` function wrote to `localStorage` without checking for quota errors. If the user accumulated a large queue (localStorage has a 5-10 MB limit depending on the browser), the write would throw an uncaught exception and silently fail.

**Fix:** `saveQueue()` now wraps the `localStorage.setItem()` calls in a `try/catch` block. If a quota error occurs, the user sees a clear message instructing them to export their data as CSV and archive or clear old entries.

### Fetch Timeout

**Problem:** The `fetch()` call to the Anthropic API had no timeout. If the API was slow to respond or the connection stalled, the UI would remain in its loading state indefinitely with no way for the user to recover.

**Fix:** An `AbortController` with a 2-minute timeout is now attached to the `fetch()` request. If the request exceeds 120 seconds, it is aborted and the user sees a clear timeout error message.

### Input Length Validation

**Problem:** There was no limit on the length of text a user could submit. Extremely long inputs could cause excessive API costs, slow responses, or token limit errors from the Anthropic API.

**Fix:** A `MAX_INPUT_LENGTH` constant (50,000 characters) is enforced before sending the request. If the input exceeds this limit, the user sees an error message showing the current length and the maximum allowed.

### CSV Blob URL Memory Leak

**Problem:** The CSV export created a blob URL via `URL.createObjectURL()` but never revoked it, causing a small memory leak each time the user exported.

**Fix:** A `setTimeout(() => URL.revokeObjectURL(a.href), 10000)` call was added after the download is triggered, giving the browser 10 seconds to complete the download before the blob URL is revoked and its memory freed.

### UI and Accessibility Improvements

**Password input styling:** The CSS selectors for text inputs (`input[type="text"]`) were updated to also include `input[type="password"]`, ensuring the API key field has consistent styling (width, padding, border, focus state) regardless of whether the key is shown or hidden.

**Keyboard focus outlines:** A `button:focus-visible` rule was added to the stylesheet, providing a visible 2px blue outline when buttons are focused via keyboard navigation. This improves accessibility for users who navigate without a mouse.

**Mobile responsive queue:** A media query breakpoint at 640px collapses the queue grid from a five-column row layout to a single-column stacked layout, so that queue entries remain readable on narrow screens.

**Sources list styling:** A dedicated `.sources-list` CSS component was added to render web search source URLs as a cleanly formatted list below the overall assessment, with link-arrow prefixes and truncation for long URLs.

### dotenv Syntax Fix

**Problem:** The `backend/.env` file contained invalid syntax that prevented `python-dotenv` from loading environment variables correctly.

**Fix:** The `.env` file was corrected to use standard `KEY=value` syntax without extraneous quotes or spaces around the `=` sign.

---

## 10. Development History

The project was developed in phases as a research prototype at Columbia University.

### Phase 1: Basic Claim Classification

The initial version used Claude's internal knowledge (training data) to classify factual claims from social media posts. The system prompt was designed around IFCN principles, and the pipeline could extract claims, assign categories, and provide reasoning. However, claims about recent events or region-specific news were frequently classified as "unclassified" because Claude had no access to current information.

### Phase 2: Web Search Integration

To address the limitation of relying solely on training data, Claude's built-in web search tool (`web_search_20250305`) was integrated into the pipeline. This allowed Claude to search the web in real time for corroborating or contradicting evidence before assigning a category. This significantly reduced the number of false "unclassified" results and improved overall classification accuracy by grounding decisions in current, verifiable sources.

The system prompt was updated with a "CRITICAL" instruction mandating web search for every claim, and the response parsing was enhanced to handle the mixed content block format that web search produces (interleaved text, tool use, and tool result blocks). Source extraction and deduplication were added so that users can see exactly which sources informed each classification.

The frontend was built as a standalone single-page application to provide a zero-setup experience for researchers, while the backend was developed with URL scraping support for automated workflows and deployed on Railway.

### Phase 3: Security Hardening, Bug Fixes, and Accessibility

A comprehensive review of the codebase identified several reliability and security issues that were addressed in this phase:

**Security hardening:** The most significant change was extracting all inline JavaScript from `index.html` into a separate `app.js` file and tightening the Content Security Policy to remove `'unsafe-inline'` from `script-src`. This was motivated by the fact that the application stores the user's Anthropic API key in `localStorage`, and when hosted on GitHub Pages, all repositories under the same `*.github.io` origin share that storage. The strict CSP prevents injected scripts from accessing the key.

**Bug fixes:** Several parsing and race condition bugs were identified and fixed. The JSON extraction fallback was upgraded to use string-aware brace matching, preventing failures when JSON string values contain literal `{` or `}` characters. An API key race condition (where the key could be read before it was saved to `localStorage`) was fixed by reading directly from the input element. A variable shadowing issue in `claims.py` was corrected, and browser cleanup in the Playwright scraper was made reliable with `try/finally`.

**Reliability improvements:** A 2-minute fetch timeout was added to prevent the UI from hanging indefinitely. Input length validation (50,000 characters) was added to prevent excessive API costs. `localStorage` quota errors are now caught and surfaced to the user. CSV blob URLs are properly revoked after download.

**Accessibility and responsiveness:** Button focus outlines were added for keyboard navigation. The password input field received proper CSS styling. The queue grid was made mobile-responsive with a breakpoint at 640px. A dedicated sources list component was added to the stylesheet.

**System prompt synchronization:** The frontend and backend system prompts were aligned to be identical, including the India/Pakistan example for the out-of-context category, ensuring consistent classification behavior regardless of which mode is used.

**File structure change:** The `docs/` directory now contains three files (`index.html`, `app.js`, `style.css`) instead of having all JavaScript inline in `index.html`. This separation of concerns improves maintainability and enables the strict CSP.

### Phase 4: IFCN Signatory Fact-Check Search

To further ground classifications in the work of established fact-checking organizations, the system prompt was expanded to instruct Claude to search for existing fact-checks from IFCN (International Fact-Checking Network) verified signatories for every claim it analyzes.

**System prompt expansion:** A curated list of key IFCN signatory domains was embedded directly in the system prompt, organized by region (Global/English, Africa, Americas, Asia-Pacific, Europe, Middle East, and wire services). The full list of 172 signatory domains is maintained in `list.txt`. The prompt instructs Claude to prioritize signatories from the relevant region and language for region-specific claims -- for example, searching Indian fact-checkers (BOOM, Alt News, Vishvas News) for claims about Indian politics, or Latin American signatories (Chequeado, Aos Fatos) for claims about that region.

**Web search budget increase:** The `max_uses` parameter for the web search tool was increased from 5 to 10 to accommodate both general evidence searches and dedicated IFCN fact-check lookups without hitting the search limit prematurely.

**New response field:** Each claim object in the JSON response now includes an `existing_fact_checks` array containing objects with `url`, `source` (the signatory name), and `verdict` (the signatory's rating). This allows the UI and any downstream consumers to distinguish between Claude's own classification and the verdicts of established fact-checking organizations.

**Frontend UI additions:** A new green-themed "Existing Fact-Checks (IFCN Signatories)" box appears below the reasoning section on each claim card. Each entry displays the signatory name as a clickable link to the fact-check article, followed by the signatory's verdict. New CSS classes (`.fact-checks-box`, `.fact-checks-label`, `.fact-checks-list`, `.fc-verdict`) provide the green styling that visually distinguishes the IFCN fact-check box from the reasoning box.

**CSV export expansion:** A new "IFCN Fact-Checks" column was added to the CSV export between the Confidence and Sources columns. Each entry is formatted as `Source: Verdict (URL)`, with multiple entries separated by pipes (`|`).
