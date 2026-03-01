// ── System prompt (mirrors backend/claims.py) ─────────────────────────
const SYSTEM_PROMPT = `You are an expert fact-checker trained on the IFCN (International Fact-Checking Network) Code of Principles. You uphold the following IFCN commitments in all your work:
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

3. Label which types of media the claim references:
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
- If the post makes no checkable factual claims, return an empty claims list and explain why in the summary.

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
}`;

// ── Constants ────────────────────────────────────────────────────────
const MAX_INPUT_LENGTH = 50000;

// ── API key management ────────────────────────────────────────────────
const keyInput = document.getElementById("api-key-input");
keyInput.value = localStorage.getItem("fc_api_key") || "";

// Save key when field loses focus (not on every keystroke)
keyInput.addEventListener("blur", () => {
  localStorage.setItem("fc_api_key", keyInput.value.trim());
});

// Show / hide key
document.getElementById("key-visibility-btn").addEventListener("click", () => {
  keyInput.type = keyInput.type === "password" ? "text" : "password";
});

// Clear key from localStorage
document.getElementById("key-clear-btn").addEventListener("click", () => {
  keyInput.value = "";
  localStorage.removeItem("fc_api_key");
});

// Collapse settings panel if key already exists
const settingsBody = document.getElementById("settings-body");
const settingsToggle = document.getElementById("settings-toggle");
if (keyInput.value) {
  settingsBody.classList.add("hidden");
  settingsToggle.textContent = "Show";
}
settingsToggle.addEventListener("click", function () {
  const hidden = settingsBody.classList.toggle("hidden");
  this.textContent = hidden ? "Show" : "Hide";
});

// ── Persistent queue ──────────────────────────────────────────────────
let queue  = JSON.parse(localStorage.getItem("fc_queue")   || "[]");
let nextId = parseInt(localStorage.getItem("fc_next_id")   || "1", 10);

function saveQueue() {
  try {
    localStorage.setItem("fc_queue",   JSON.stringify(queue));
    localStorage.setItem("fc_next_id", String(nextId));
  } catch (e) {
    showError("Storage is full. Please export your data as CSV and archive or clear old entries.");
  }
}

// ── Event wiring ──────────────────────────────────────────────────────
document.getElementById("analyze-btn").addEventListener("click", analyzePost);
document.getElementById("export-csv-btn").addEventListener("click", exportCSV);
document.getElementById("close-results-btn").addEventListener("click", hideResults);

// Ctrl/Cmd+Enter in textarea submits
document.getElementById("post-text").addEventListener("keydown", function (e) {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    analyzePost();
  }
});

// ── Analyze ───────────────────────────────────────────────────────────
async function analyzePost() {
  // Save current input value before reading to avoid race condition
  const currentKey = keyInput.value.trim();
  if (currentKey) {
    localStorage.setItem("fc_api_key", currentKey);
  }
  const apiKey = currentKey || localStorage.getItem("fc_api_key") || "";
  const text   = document.getElementById("post-text").value.trim();

  if (!apiKey) {
    showError("Please enter your Anthropic API key in the Settings section above.");
    document.getElementById("settings-body").classList.remove("hidden");
    settingsToggle.textContent = "Hide";
    return;
  }

  if (!text) {
    showError("Please paste the post text to analyze.");
    return;
  }

  if (text.length > MAX_INPUT_LENGTH) {
    showError("Input too long (" + text.length.toLocaleString() + " characters). Maximum is " + MAX_INPUT_LENGTH.toLocaleString() + ".");
    return;
  }

  setLoading(true);
  hideResults();
  hideError();

  try {
    const data = await callClaude(text, apiKey);

    const entry = {
      id:              nextId++,
      textPreview:     text.slice(0, 80) + (text.length > 80 ? "\u2026" : ""),
      classifications: (data.claims || []).map(c => c.category || "unclassified"),
      dateTime:        new Date().toISOString(),
      archived:        false,
      data:            data,
    };
    queue.unshift(entry);
    saveQueue();
    renderQueue();

    document.getElementById("post-text").value = "";

    showResults(data);

  } catch (err) {
    showError("Analysis failed.\n\nError: " + err.message);
  } finally {
    setLoading(false);
  }
}

// ── Direct Anthropic API call ─────────────────────────────────────────
async function callClaude(text, apiKey) {
  const userMessage = (
    "Please analyze this social media post and extract all factual claims:\n\n" +
    "---\n" + text + "\n---"
  );

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 120000);

  let response;
  try {
    response = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      signal: controller.signal,
      headers: {
        "x-api-key":                                apiKey,
        "anthropic-version":                        "2023-06-01",
        "content-type":                             "application/json",
        "anthropic-dangerous-direct-browser-access": "true",
      },
      body: JSON.stringify({
        model:      "claude-sonnet-4-20250514",
        max_tokens: 4096,
        system:     SYSTEM_PROMPT,
        messages:   [{ role: "user", content: userMessage }],
        tools:      [{ type: "web_search_20250305", name: "web_search", max_uses: 10 }],
      }),
    });
  } catch (err) {
    clearTimeout(timeoutId);
    if (err.name === "AbortError") {
      throw new Error("Request timed out after 2 minutes. Please try again.");
    }
    throw err;
  }
  clearTimeout(timeoutId);

  if (!response.ok) {
    let msg = "API error " + response.status;
    try {
      msg = (await response.json()).error?.message || msg;
    } catch (_) { /* non-JSON error body; fall back to status code */ }
    throw new Error(msg);
  }

  const body = await response.json();
  const contentBlocks = body.content || [];

  // Extract text from text blocks (skip search tool use/result blocks)
  let rawText = contentBlocks
    .filter(b => b.type === "text")
    .map(b => b.text)
    .join("")
    .trim();

  // Extract unique source URLs from web_search_tool_result blocks
  const sources = [];
  const seenUrls = new Set();
  for (const block of contentBlocks) {
    if (block.type === "web_search_tool_result" && Array.isArray(block.content)) {
      for (const item of block.content) {
        if (item.type === "web_search_result" && item.url && !seenUrls.has(item.url)) {
          seenUrls.add(item.url);
          sources.push({ title: item.title || item.url, url: item.url });
        }
      }
    }
  }

  // Strip markdown code fences if Claude wraps the JSON
  if (rawText.startsWith("```")) {
    rawText = rawText.split("\n").slice(1).join("\n").replace(/```\s*$/, "").trim();
  }

  const VALID_CATEGORIES = new Set(["out-of-context", "fabricated", "manipulated/doctored", "unclassified"]);
  const VALID_CONFIDENCES = new Set(["high", "medium", "low"]);

  let result;
  try {
    result = JSON.parse(rawText);
  } catch {
    // If direct parse fails, try extracting JSON from surrounding text
    const jsonStr = extractJSON(rawText);
    if (jsonStr) {
      try {
        result = JSON.parse(jsonStr);
      } catch {
        result = null;
      }
    }
    if (!result) {
      return {
        claims:  [],
        summary: rawText,
        sources: sources,
        error:   "Response could not be parsed as structured data. Raw response shown in summary.",
      };
    }
  }

  // Validate and normalize categories/confidence from Claude's response
  for (const claim of (result.claims || [])) {
    const cat = (claim.category || "").toLowerCase();
    claim.category = VALID_CATEGORIES.has(cat) ? cat : "unclassified";
    const conf = (claim.confidence || "").toLowerCase();
    claim.confidence = VALID_CONFIDENCES.has(conf) ? conf : "low";
  }

  // Attach sources to the result
  result.sources = sources;

  return result;
}

// ── JSON extraction (string-aware brace matching) ─────────────────────
function extractJSON(str) {
  const start = str.indexOf("{");
  if (start === -1) return null;
  let depth = 0;
  let inString = false;
  let escape = false;
  for (let i = start; i < str.length; i++) {
    const ch = str[i];
    if (escape) { escape = false; continue; }
    if (ch === "\\" && inString) { escape = true; continue; }
    if (ch === '"') { inString = !inString; continue; }
    if (inString) continue;
    if (ch === "{") depth++;
    else if (ch === "}") depth--;
    if (depth === 0) return str.slice(start, i + 1);
  }
  return null;
}

// ── Queue rendering ───────────────────────────────────────────────────
function renderQueue() {
  const list          = document.getElementById("queue-list");
  const activeItems   = queue.filter(e => !e.archived);
  const archivedItems = queue.filter(e => e.archived);

  if (queue.length === 0) {
    list.innerHTML = '<p class="empty-queue">No claims analyzed yet. Submit text above to get started.</p>';
    return;
  }

  let html = "";
  if (activeItems.length)   html += renderGroup("Active",   activeItems,   false);
  if (archivedItems.length) html += renderGroup("Archived", archivedItems, true);
  list.innerHTML = html;

  // Row click -> show detail
  list.querySelectorAll(".queue-row").forEach(row => {
    row.addEventListener("click", function (e) {
      if (e.target.closest(".queue-row-btn")) return;
      const entry = queue.find(item => item.id === parseInt(this.dataset.id, 10));
      if (!entry) return;
      list.querySelectorAll(".queue-row").forEach(r => r.classList.remove("queue-row-selected"));
      this.classList.add("queue-row-selected");
      showResults(entry.data);
    });
  });

  list.querySelectorAll(".btn-archive").forEach(btn => {
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      setArchived(parseInt(this.dataset.id, 10), true);
    });
  });

  list.querySelectorAll(".btn-restore").forEach(btn => {
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      setArchived(parseInt(this.dataset.id, 10), false);
    });
  });
}

function renderGroup(label, items, isArchived) {
  const cls  = isArchived ? " queue-group-label-archived" : "";
  const rows = items.map(renderRow).join("");
  return '<div class="queue-group-label' + cls + '">' + label + '</div>' + rows;
}

function renderRow(entry) {
  const cats = entry.classifications.length
    ? [...new Set(entry.classifications)].map(c => {
        const cls = c.toLowerCase().replace(/[\s/]+/g, "-");
        return '<span class="cat-badge cat-badge-' + cls + '">' + escapeHtml(c) + '</span>';
      }).join(" ")
    : '<span class="cat-badge cat-badge-unclassified">unclassified</span>';

  const dt      = new Date(entry.dateTime);
  const dateStr = dt.toLocaleDateString();
  const timeStr = dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const preview = entry.textPreview || entry.url || "(no text)";

  const actionBtn = entry.archived
    ? '<button class="queue-row-btn btn-restore" data-id="' + escapeHtml(String(entry.id)) + '" type="button">Restore</button>'
    : '<button class="queue-row-btn btn-archive" data-id="' + escapeHtml(String(entry.id)) + '" type="button">Archive</button>';

  return '<div class="queue-row' + (entry.archived ? " queue-row-archived" : "") + '" data-id="' + escapeHtml(String(entry.id)) + '" title="Click to view full analysis">' +
    '<span class="queue-serial">#' + escapeHtml(String(entry.id)) + '</span>' +
    '<span class="queue-preview" title="' + escapeHtml(preview) + '">' + escapeHtml(preview) + '</span>' +
    '<span class="queue-cats">' + cats + '</span>' +
    '<span class="queue-datetime">' + escapeHtml(dateStr) + ', ' + escapeHtml(timeStr) + '</span>' +
    '<span class="queue-action">' + actionBtn + '</span>' +
    '</div>';
}

function setArchived(id, archived) {
  const entry = queue.find(item => item.id === id);
  if (entry) { entry.archived = archived; saveQueue(); renderQueue(); }
}

// ── CSV export ────────────────────────────────────────────────────────
function exportCSV() {
  if (queue.length === 0) {
    alert("The queue is empty \u2014 nothing to export.");
    return;
  }

  const headers = ["Serial Number", "Post Text (preview)", "Claim", "Classification", "Reasoning", "Confidence", "IFCN Fact-Checks", "Sources", "Date Searched", "Time Searched", "Status"];
  const rows = [];
  queue.forEach(entry => {
    const dt      = new Date(entry.dateTime);
    const date    = dt.toLocaleDateString("en-CA");
    const time    = dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    const status  = entry.archived ? "Archived" : "Active";
    const preview = entry.textPreview || entry.url || "";
    const claims  = entry.data?.claims || [];
    const sourcesStr = (entry.data?.sources || []).map(s => s.url).join(" | ");

    if (claims.length === 0) {
      rows.push([entry.id, preview, "", "unclassified", "", "", "", sourcesStr, date, time, status]);
    } else {
      claims.forEach(c => {
        const fcStr = (c.existing_fact_checks || [])
          .map(fc => (fc.source || "") + ": " + (fc.verdict || "") + " (" + (fc.url || "") + ")")
          .join(" | ");
        rows.push([
          entry.id,
          preview,
          c.claim_text || "",
          c.category || "unclassified",
          c.reasoning || "",
          c.confidence || "",
          fcStr,
          sourcesStr,
          date,
          time,
          status,
        ]);
      });
    }
  });

  const csv = [headers, ...rows]
    .map(row => row.map(cell => '"' + String(cell).replace(/"/g, '""') + '"').join(","))
    .join("\n");

  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const a    = document.createElement("a");
  a.href     = URL.createObjectURL(blob);
  a.download = "fact-check-queue-" + new Date().toISOString().slice(0, 10) + ".csv";
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 10000);
}

// ── Results panel ─────────────────────────────────────────────────────
function showResults(data) {
  const section = document.getElementById("results");
  section.classList.remove("hidden");

  if (data.error && (!data.claims || data.claims.length === 0)) {
    showError(data.error);
    section.classList.add("hidden");
    return;
  }

  const summaryBox = document.getElementById("summary-box");
  let html = '<p><strong>Overall assessment:</strong> ' + escapeHtml(data.summary || "No summary provided.") + '</p>';
  if (data.error) html += '<p class="parse-error">&#9888; ' + escapeHtml(data.error) + '</p>';

  // Display sources from web search
  if (data.sources && data.sources.length > 0) {
    html += '<div class="sources-list">' +
      '<span class="sources-label">Sources</span>' +
      '<ul>' + data.sources.map(s =>
        '<li><a href="' + escapeHtml(s.url) + '" target="_blank" rel="noopener">' + escapeHtml(s.title) + '</a></li>'
      ).join("") + '</ul>' +
      '</div>';
  }

  summaryBox.innerHTML = html;

  const claimsList = document.getElementById("claims-list");
  claimsList.innerHTML = "";

  if (!data.claims || data.claims.length === 0) {
    claimsList.innerHTML = '<p class="no-claims">No specific factual claims were extracted from this post.</p>';
  } else {
    data.claims.forEach((claim, i) => {
      const catClass   = (claim.category || "unclassified").toLowerCase().replace(/[\s/]+/g, "-");
      const mediaHtml  = (claim.media_labels || [])
        .map(l => '<span class="media-tag">' + escapeHtml(l) + '</span>').join("");

      // Build existing fact-checks HTML if any
      const fcChecks = claim.existing_fact_checks || [];
      let fcHtml = "";
      if (fcChecks.length > 0) {
        fcHtml = '<div class="fact-checks-box">' +
          '<span class="fact-checks-label">Existing Fact-Checks (IFCN Signatories)</span>' +
          '<ul class="fact-checks-list">' +
          fcChecks.map(fc =>
            '<li>' +
              '<a href="' + escapeHtml(fc.url || "") + '" target="_blank" rel="noopener">' + escapeHtml(fc.source || "Unknown") + '</a>' +
              (fc.verdict ? ' &mdash; <span class="fc-verdict">' + escapeHtml(fc.verdict) + '</span>' : "") +
            '</li>'
          ).join("") +
          '</ul></div>';
      }

      const card = document.createElement("div");
      card.className = "claim-card cat-" + catClass;
      card.innerHTML =
        '<div class="claim-header">' +
          '<span class="claim-num">Claim ' + (i + 1) + '</span>' +
          '<span class="cat-badge cat-badge-' + catClass + '">' + escapeHtml(claim.category || "unclassified") + '</span>' +
          '<span class="confidence">Confidence: ' + escapeHtml(claim.confidence || "\u2014") + '</span>' +
        '</div>' +
        '<p class="claim-text">\u201C' + escapeHtml(claim.claim_text || "") + '\u201D</p>' +
        '<div class="reasoning-box">' +
          '<span class="reasoning-label">Reasoning &amp; Methodology</span>' +
          '<p class="reasoning">' + escapeHtml(claim.reasoning || "") + '</p>' +
        '</div>' +
        fcHtml +
        (mediaHtml ? '<div class="media-labels">' + mediaHtml + '</div>' : "");
      claimsList.appendChild(card);
    });
  }

  section.scrollIntoView({ behavior: "smooth", block: "start" });
}

function hideResults() {
  document.getElementById("results").classList.add("hidden");
  document.getElementById("summary-box").innerHTML = "";
  document.getElementById("claims-list").innerHTML = "";
  document.querySelectorAll(".queue-row").forEach(r => r.classList.remove("queue-row-selected"));
}

// ── Helpers ───────────────────────────────────────────────────────────
function showError(msg) {
  const box = document.getElementById("error-box");
  box.textContent = msg;
  box.classList.remove("hidden");
}

function hideError() {
  document.getElementById("error-box").classList.add("hidden");
}

function setLoading(show) {
  document.getElementById("loading").classList.toggle("hidden", !show);
  document.getElementById("analyze-btn").disabled = show;
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// ── Boot ──────────────────────────────────────────────────────────────
renderQueue();
