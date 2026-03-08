# ExcelBot Web Chat: Implementation Spec

## Purpose

This document is the complete specification for adding a web-based chat interface to the ExcelBot Cloud Run backend. It is intended to be read and implemented by Claude Code. Items requiring manual human action are flagged with 🔧 MANUAL ACTION REQUIRED.

---

## Project Context

ExcelBot is a Cloud Run service that answers Excel questions using the Claude API. It currently has two endpoints: `GET /` (health check) and `POST /email` (email webhook) and `POST /chat` (Google Chat webhook). This spec adds a third interface: a browser-based chat UI deployed as a Google Apps Script Web App, backed by a new `/web-chat` endpoint on Cloud Run.

### Existing Infrastructure

| Item | Value |
|------|-------|
| GCP Project ID | `gclaude-dev` |
| GCP Project Number | `852829491271` |
| Cloud Run Service | `excelbot-api` (us-central1) |
| Service Account | `gchat-dev@gclaude-dev.iam.gserviceaccount.com` |
| GitHub Repo | `martin-gleason/gClaude` (public) |
| Deploy Branch | `develop` (auto-deploys via GitHub Actions + WIF) |
| Shannon's Email | `shannonerin@gmail.com` |
| Admin Email | `martin.gleason.ms@gmail.com` |

### Existing File Structure (relevant files only)

```
gClaude/
├── .github/workflows/deploy.yml
├── Dockerfile
├── requirements.txt
├── src/
│   ├── __init__.py
│   ├── main.py           # FastAPI app — endpoints here
│   ├── config.py          # Pydantic Settings class
│   ├── auth.py
│   ├── utils.py
│   ├── chat/              # Google Chat integration
│   ├── claude/
│   │   ├── client.py      # ClaudeClient wrapper
│   │   └── usage.py       # CostTracker, RateLimitTracker
│   ├── email/             # Email webhook handler
│   ├── excel/             # openpyxl/pandas processing
│   └── storage/           # GCS file storage
```

---

## Implementation Plan (Ordered)

### Phase 1: Cloud Run Backend Changes (Claude Code implements)

#### 1.1 Add `WEB_CHAT_SECRET` to Settings

**File:** `src/config.py`

Add this field to the `Settings` class, alongside the existing settings:

```python
WEB_CHAT_SECRET: str = ""
```

This is a shared secret that authenticates requests from the Apps Script frontend. It is set as a Cloud Run environment variable.

#### 1.2 Create `src/web_chat.py`

Create a new file `src/web_chat.py` with the following contents. This module handles the `/web-chat` endpoint: auth verification, spreadsheet parsing, Claude prompt assembly, and response formatting.

```python
"""
Web Chat endpoint for Apps Script Web App integration.
Authenticates via a shared bearer token (not Google Chat JWT).
"""

import base64
import hmac
import io
import logging
from typing import Optional

from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel

from src.config import Settings, get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class WebChatRequest(BaseModel):
    user_email: str
    message: str
    conversation_history: list[ChatMessage] = []
    file_name: Optional[str] = None
    file_data: Optional[str] = None  # base64-encoded
    file_mime_type: Optional[str] = None


class WebChatResponse(BaseModel):
    message: str
    file_name: Optional[str] = None
    file_data: Optional[str] = None  # base64-encoded
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Auth dependency — shared-secret bearer token
# ---------------------------------------------------------------------------

def verify_web_chat_secret(
    settings: Settings = Depends(get_settings),
    authorization: str = Header(default=""),
) -> None:
    """Verify the shared secret sent by Apps Script."""
    expected = settings.WEB_CHAT_SECRET
    if not expected:
        raise HTTPException(
            status_code=500,
            detail="WEB_CHAT_SECRET is not configured on the server.",
        )

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    token = authorization[len("Bearer "):]
    if not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid token")


# ---------------------------------------------------------------------------
# Excel system prompt
# ---------------------------------------------------------------------------

EXCEL_SYSTEM_PROMPT = """You are ExcelBot, a friendly and knowledgeable Excel assistant.

Your job is to help users with Excel questions — formulas, formatting, data analysis,
pivot tables, charts, VBA macros, and anything else related to spreadsheets.

Guidelines:
- Be warm, clear, and encouraging. The user may not be technical.
- When explaining formulas, always show the formula AND explain what each part does.
- Use step-by-step instructions when the user needs to do something in Excel's UI.
- If the user uploads a spreadsheet, analyze it and describe what you see before answering.
- If the user asks you to create or modify a spreadsheet, describe what you'll create,
  then output a JSON block with the key "excel_action" containing your instructions.
- If a question is ambiguous, ask a clarifying question rather than guessing.
- Keep responses concise but thorough. Use short paragraphs, not walls of text.
- Format formulas and cell references in backticks: `=VLOOKUP(A2, B:C, 2, FALSE)`

When a spreadsheet file is provided, you'll receive a summary with:
- Sheet names and dimensions
- Column headers
- Sample rows of data
- Any formulas found

Use this information to give specific, data-aware answers."""


# ---------------------------------------------------------------------------
# File processing helpers
# ---------------------------------------------------------------------------

def summarize_spreadsheet(file_data_b64: str, file_name: str) -> str:
    """Extract a text summary from an uploaded spreadsheet for Claude context."""
    try:
        raw = base64.b64decode(file_data_b64)
        buf = io.BytesIO(raw)

        if file_name.lower().endswith(".csv"):
            import pandas as pd
            df = pd.read_csv(buf)
            return _summarize_dataframe(df, file_name, sheet_name="(CSV)")

        # .xlsx
        import openpyxl
        wb = openpyxl.load_workbook(buf, read_only=True, data_only=False)
        parts: list[str] = [
            f"**File:** {file_name}",
            f"**Sheets:** {', '.join(wb.sheetnames)}",
        ]

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            parts.append(f"\n### Sheet: {sheet_name}")
            parts.append(f"Dimensions: {ws.dimensions}")

            rows = list(
                ws.iter_rows(max_row=min(ws.max_row or 1, 52), values_only=False)
            )
            if not rows:
                parts.append("(empty sheet)")
                continue

            # Headers
            headers = [
                str(cell.value) if cell.value is not None else ""
                for cell in rows[0]
            ]
            parts.append(f"Headers: {headers}")

            # Sample data (up to 50 rows after header)
            sample_lines = []
            for row in rows[1:51]:
                vals = [
                    str(cell.value) if cell.value is not None else ""
                    for cell in row
                ]
                sample_lines.append(str(vals))
            if sample_lines:
                parts.append(f"Sample data ({len(sample_lines)} rows):")
                parts.extend(sample_lines)

            # Formulas
            formulas = []
            for row in rows[:20]:
                for cell in row:
                    if (
                        cell.value
                        and isinstance(cell.value, str)
                        and cell.value.startswith("=")
                    ):
                        formulas.append(f"  {cell.coordinate}: {cell.value}")
            if formulas:
                parts.append("Formulas found:")
                parts.extend(formulas)

        wb.close()
        return "\n".join(parts)

    except Exception as e:
        logger.warning("Failed to parse spreadsheet %s: %s", file_name, e)
        return f"(Could not parse {file_name}: {e})"


def _summarize_dataframe(df, file_name: str, sheet_name: str) -> str:
    parts = [
        f"**File:** {file_name}",
        f"**Sheet:** {sheet_name}",
        f"**Shape:** {df.shape[0]} rows x {df.shape[1]} columns",
        f"**Columns:** {list(df.columns)}",
        f"\nSample data (first {min(len(df), 50)} rows):",
        df.head(50).to_string(index=False),
    ]
    return "\n".join(parts)
```

#### 1.3 Register `/web-chat` endpoint in `src/main.py`

Add these imports near the top of `src/main.py`:

```python
from src.web_chat import (
    WebChatRequest,
    WebChatResponse,
    verify_web_chat_secret,
    EXCEL_SYSTEM_PROMPT,
    summarize_spreadsheet,
)
```

Add this endpoint after the existing `/chat` endpoint:

```python
@app.post("/web-chat", response_model=WebChatResponse)
async def web_chat_endpoint(
    request: WebChatRequest,
    _auth: None = Depends(verify_web_chat_secret),
    settings: Settings = Depends(get_settings),
    claude_client: ClaudeClient = Depends(get_claude_client),
) -> WebChatResponse:
    """Chat endpoint for the Apps Script Web App frontend."""

    allowed = settings.authorized_users_list
    if allowed and request.user_email.lower() not in [u.lower() for u in allowed]:
        return WebChatResponse(
            message="Sorry, I'm not set up to help this account.",
            error="unauthorized",
        )

    messages = []
    for msg in request.conversation_history:
        messages.append({"role": msg.role, "content": msg.content})

    user_content = request.message
    if request.file_data and request.file_name:
        summary = summarize_spreadsheet(request.file_data, request.file_name)
        user_content = f"[Uploaded file]\n{summary}\n\n[Question]\n{request.message}"

    messages.append({"role": "user", "content": user_content})

    try:
        response = claude_client.messages.create(
            model=settings.DEFAULT_MODEL,
            max_tokens=4096,
            system=EXCEL_SYSTEM_PROMPT,
            messages=messages,
        )
        reply = response.content[0].text
    except Exception as e:
        import logging
        logging.error("Claude API error: %s", e)
        return WebChatResponse(
            message="Sorry, I ran into a problem. Try asking again in a moment.",
            error=str(e),
        )

    return WebChatResponse(message=reply)
```

**IMPORTANT:** The `claude_client.messages.create()` call above assumes the `ClaudeClient` wrapper exposes the Anthropic SDK's standard `.messages.create()` method. If the existing `ClaudeClient` in `src/claude/client.py` uses a different interface (e.g., a custom method name or different argument pattern), this call must be adapted to match. Review `src/claude/client.py` before implementing.

#### 1.4 Add tests for `/web-chat`

Create `tests/unit/test_web_chat.py`:

```python
"""Tests for the /web-chat endpoint."""
import base64
import pytest
from unittest.mock import MagicMock, patch
from src.web_chat import (
    WebChatRequest,
    WebChatResponse,
    summarize_spreadsheet,
    verify_web_chat_secret,
    EXCEL_SYSTEM_PROMPT,
)


class TestVerifyWebChatSecret:
    """Test shared-secret bearer token auth."""

    def test_valid_token_passes(self):
        """Valid bearer token should not raise."""
        settings = MagicMock()
        settings.WEB_CHAT_SECRET = "test-secret-123"
        # Should not raise
        verify_web_chat_secret(
            settings=settings,
            authorization="Bearer test-secret-123",
        )

    def test_wrong_token_raises_401(self):
        """Invalid token should raise HTTPException 401."""
        settings = MagicMock()
        settings.WEB_CHAT_SECRET = "test-secret-123"
        with pytest.raises(Exception) as exc_info:
            verify_web_chat_secret(
                settings=settings,
                authorization="Bearer wrong-token",
            )
        assert "401" in str(exc_info.value.status_code)

    def test_missing_bearer_prefix_raises_401(self):
        """Authorization header without 'Bearer ' prefix should raise."""
        settings = MagicMock()
        settings.WEB_CHAT_SECRET = "test-secret-123"
        with pytest.raises(Exception):
            verify_web_chat_secret(
                settings=settings,
                authorization="test-secret-123",
            )

    def test_empty_server_secret_raises_500(self):
        """If WEB_CHAT_SECRET is not configured, raise 500."""
        settings = MagicMock()
        settings.WEB_CHAT_SECRET = ""
        with pytest.raises(Exception) as exc_info:
            verify_web_chat_secret(
                settings=settings,
                authorization="Bearer anything",
            )
        assert "500" in str(exc_info.value.status_code)


class TestSummarizeSpreadsheet:
    """Test spreadsheet parsing for Claude context."""

    def test_csv_file_summarized(self, tmp_path):
        """CSV file should be parsed into a readable summary."""
        csv_content = "Name,Age,Score\nAlice,30,95\nBob,25,87\n"
        b64 = base64.b64encode(csv_content.encode()).decode()
        summary = summarize_spreadsheet(b64, "test.csv")
        assert "Name" in summary
        assert "Alice" in summary
        assert "3 columns" in summary or "Columns" in summary

    def test_corrupted_file_returns_error_message(self):
        """Corrupted file data should return an error string, not crash."""
        b64 = base64.b64encode(b"not a real xlsx").decode()
        summary = summarize_spreadsheet(b64, "bad.xlsx")
        assert "Could not parse" in summary


class TestWebChatRequest:
    """Test request schema validation."""

    def test_minimal_request(self):
        """Request with just email and message should be valid."""
        req = WebChatRequest(
            user_email="test@example.com",
            message="How do I use VLOOKUP?",
        )
        assert req.user_email == "test@example.com"
        assert req.conversation_history == []
        assert req.file_data is None

    def test_request_with_file(self):
        """Request with file attachment should be valid."""
        req = WebChatRequest(
            user_email="test@example.com",
            message="What's in this file?",
            file_name="data.xlsx",
            file_data="base64encodeddata",
            file_mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        assert req.file_name == "data.xlsx"

    def test_request_with_history(self):
        """Request with conversation history should preserve order."""
        from src.web_chat import ChatMessage
        req = WebChatRequest(
            user_email="test@example.com",
            message="Follow up question",
            conversation_history=[
                ChatMessage(role="user", content="First question"),
                ChatMessage(role="assistant", content="First answer"),
            ],
        )
        assert len(req.conversation_history) == 2
        assert req.conversation_history[0].role == "user"
```

#### 1.5 Push and deploy

After implementing 1.1–1.4, commit and push to the `develop` branch. The GitHub Actions workflow will auto-deploy to Cloud Run.

```bash
git add src/web_chat.py src/config.py src/main.py tests/unit/test_web_chat.py
git commit -m "Add /web-chat endpoint for Apps Script chat frontend"
git push origin develop
```

---

### Phase 2: Manual Configuration (Human does these)

These steps CANNOT be automated by Claude Code. They must be done by the human in this exact order.

#### 🔧 MANUAL ACTION 1: Generate a shared secret

Run this in your terminal:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Save the output. You will use this value in Manual Actions 2 and 5.

#### 🔧 MANUAL ACTION 2: Set the shared secret on Cloud Run

```bash
gcloud run services update excelbot-api \
  --region=us-central1 \
  --project=gclaude-dev \
  --update-env-vars=""
```

#### 🔧 MANUAL ACTION 3: Verify the /web-chat endpoint works

Get your Cloud Run URL:

```bash
CLOUD_RUN_URL=$(gcloud run services describe excelbot-api --region=us-central1 --project=gclaude-dev --format="value(status.url)")
```

Test the endpoint (replace `YOUR_SECRET` with the value from Manual Action 1):

```bash
curl -X POST "$CLOUD_RUN_URL/web-chat" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_SECRET" \
  -d '{"user_email":"martin.gleason.ms@gmail.com","message":"What does =SUM(A1:A10) do?"}'
```

Expected: JSON response with Claude's answer. If this fails, do not proceed to Phase 3.

#### 🔧 MANUAL ACTION 4: Create the Apps Script project

1. Go to https://script.google.com
2. Click **New Project**
3. Rename the project to **ExcelBot Chat**
4. Delete the default `Code.gs` content
5. Paste the contents of `Code.gs` (provided in Phase 3 below)
6. Click **+** next to Files → **Script** → name it `Config` → paste `Config.gs`
7. Click **+** next to Files → **HTML** → name it `ChatUI` → paste `ChatUI.html`
8. Click **+** next to Files → **HTML** → name it `AccessDenied` → paste `AccessDenied.html`
9. Click the gear icon (**Project Settings**):
   - Check **Show "appsscript.json" manifest file in editor**
   - Open `appsscript.json` and replace its contents with the provided version

#### 🔧 MANUAL ACTION 5: Configure Apps Script

Open `Config.gs` in the Apps Script editor and update:

- **`CLOUD_RUN_URL`**: Your actual Cloud Run URL (from Manual Action 3, no trailing slash)
- **`CLOUD_RUN_SECRET`**: The same secret from Manual Action 1
- **`ALLOWED_EMAILS`**: Already set to `shannonerin@gmail.com` and `martin.gleason.ms@gmail.com`

#### 🔧 MANUAL ACTION 6: Deploy the Web App

1. In the Apps Script editor, click **Deploy** → **New deployment**
2. Click the gear icon next to "Select type" → choose **Web app**
3. Settings:
   - **Description:** `v1.0 — MVP`
   - **Execute as:** `Me (martin.gleason.ms@gmail.com)`
   - **Who has access:** `Anyone with Google account`
4. Click **Deploy**
5. **Copy the Web app URL** — this is what Shannon bookmarks

#### 🔧 MANUAL ACTION 7: Test end-to-end

- Open the Web App URL in your browser → chat UI should load
- Type "How do I freeze the top row?" → should get an answer
- Open in an incognito window, sign in as a different account → should see "Access Denied"
- Send the URL to Shannon

---

## Phase 3: Apps Script Files (Human pastes these into the Apps Script editor)

These files are provided here for reference. They are pasted manually in Manual Action 4.

---

### File: `appsscript.json`

```json
{
  "timeZone": "America/Chicago",
  "dependencies": {},
  "exceptionLogging": "STACKDRIVER",
  "runtimeVersion": "V8",
  "webapp": {
    "executeAs": "USER_DEPLOYING",
    "access": "ANYONE"
  }
}
```

---

### File: `Code.gs`

```javascript
/**
 * ExcelBot Chat — Apps Script Server-Side Code
 *
 * Handles:
 *   - doGet() — serves the chat UI (with email allowlist check)
 *   - processMessage() — proxies messages to Cloud Run /web-chat endpoint
 */


/**
 * Serve the chat page or access-denied page based on user email.
 */
function doGet() {
  var userEmail = Session.getActiveUser().getEmail();

  if (!isAuthorized(userEmail)) {
    return HtmlService.createHtmlOutputFromFile('AccessDenied')
      .setTitle('ExcelBot — Access Denied')
      .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
  }

  var template = HtmlService.createTemplateFromFile('ChatUI');
  template.userEmail = userEmail;
  template.botName = CONFIG.BOT_NAME;

  return template.evaluate()
    .setTitle('ExcelBot Chat')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL)
    .addMetaTag('viewport', 'width=device-width, initial-scale=1, maximum-scale=1');
}


/**
 * Include an HTML file (used for modular templates).
 */
function include(filename) {
  return HtmlService.createHtmlOutputFromFile(filename).getContent();
}


/**
 * Check if a user email is on the allowlist.
 */
function isAuthorized(email) {
  if (!CONFIG.ALLOWED_EMAILS || CONFIG.ALLOWED_EMAILS.length === 0) {
    return true;
  }
  return CONFIG.ALLOWED_EMAILS.some(function(allowed) {
    return allowed.toLowerCase() === email.toLowerCase();
  });
}


/**
 * Process a chat message from the frontend.
 * Called by google.script.run.processMessage() from client JS.
 *
 * @param {string} messageText — the user's question
 * @param {Object[]} conversationHistory — array of {role, content} pairs
 * @param {string|null} fileBase64 — base64-encoded file data (or null)
 * @param {string|null} fileName — original file name (or null)
 * @param {string|null} fileMimeType — MIME type (or null)
 * @returns {Object} — { message, file_name, file_data, error }
 */
function processMessage(messageText, conversationHistory, fileBase64, fileName, fileMimeType) {
  // Re-verify auth on every call (defense in depth)
  var userEmail = Session.getActiveUser().getEmail();
  if (!isAuthorized(userEmail)) {
    return { message: "You're not authorized to use ExcelBot.", error: "unauthorized" };
  }

  // Build request payload
  var payload = {
    user_email: userEmail,
    message: messageText,
    conversation_history: conversationHistory || []
  };

  // Attach file if present
  if (fileBase64 && fileName) {
    payload.file_name = fileName;
    payload.file_data = fileBase64;
    payload.file_mime_type = fileMimeType || "application/octet-stream";
  }

  // Call Cloud Run
  var options = {
    method: "post",
    contentType: "application/json",
    headers: {
      "Authorization": "Bearer " + CONFIG.CLOUD_RUN_SECRET
    },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  };

  try {
    var response = UrlFetchApp.fetch(CONFIG.CLOUD_RUN_URL + "/web-chat", options);
    var statusCode = response.getResponseCode();
    var body = JSON.parse(response.getContentText());

    if (statusCode === 200) {
      return body;
    } else if (statusCode === 401) {
      return { message: "Authentication error. Please contact the admin.", error: "auth_failed" };
    } else if (statusCode === 429) {
      return { message: "I'm getting too many questions right now. Wait a moment and try again.", error: "rate_limited" };
    } else {
      Logger.log("Cloud Run error: " + statusCode + " — " + response.getContentText());
      return { message: "Something went wrong on my end. Try again in a moment.", error: "server_error" };
    }
  } catch (e) {
    Logger.log("UrlFetchApp error: " + e.message);
    return { message: "I couldn't connect to the server. Try again in a minute.", error: "connection_error" };
  }
}
```

---

### File: `Config.gs`

```javascript
/**
 * ExcelBot Chat — Configuration
 *
 * IMPORTANT: Replace the placeholder values below before deploying.
 */

var CONFIG = {

  // ── Cloud Run Backend ──────────────────────────────────────────────
  // Your Cloud Run service URL (no trailing slash)
  CLOUD_RUN_URL: "https://excelbot-api-REPLACE-THIS-uc.a.run.app",

  // Shared secret for Cloud Run auth. Must match WEB_CHAT_SECRET env var.
  CLOUD_RUN_SECRET: "REPLACE_WITH_YOUR_GENERATED_SECRET",

  // ── Access Control ─────────────────────────────────────────────────
  ALLOWED_EMAILS: [
    "shannonerin@gmail.com",
    "martin.gleason.ms@gmail.com"
  ],

  // ── UI Settings ────────────────────────────────────────────────────
  BOT_NAME: "ExcelBot",

  // Max file upload size in bytes (10MB)
  MAX_FILE_SIZE: 10 * 1024 * 1024,

  // Accepted file extensions
  ACCEPTED_EXTENSIONS: [".xlsx", ".csv", ".xls"],

  // Max conversation history pairs to send
  MAX_HISTORY_PAIRS: 20

};
```

---

### File: `ChatUI.html`

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;500;600;700&display=swap" rel="stylesheet">

  <style>
    /* ── Reset & Base ─────────────────────────────────────────── */
    *, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }

    :root {
      --bg:           #FFF8F0;
      --bg-header:    #FFFFFF;
      --bot-bubble:   #FFE8D6;
      --bot-text:     #4A3728;
      --user-bubble:  #D4E9E2;
      --user-text:    #2B4A3E;
      --accent:       #E8927C;
      --accent-hover: #D47A64;
      --muted:        #B8A99A;
      --border:       #F0E6DA;
      --input-bg:     #FFFFFF;
      --shadow:       rgba(74, 55, 40, 0.06);
      --code-bg:      #F5EDE4;
      --danger:       #E87C7C;
      --font:         'Nunito', -apple-system, BlinkMacSystemFont, sans-serif;
    }

    html, body {
      height: 100%;
      font-family: var(--font);
      background: var(--bg);
      color: var(--bot-text);
      -webkit-font-smoothing: antialiased;
    }

    /* ── Layout ───────────────────────────────────────────────── */
    .app {
      display: flex;
      flex-direction: column;
      height: 100%;
      max-width: 760px;
      margin: 0 auto;
    }

    /* ── Header ───────────────────────────────────────────────── */
    .header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0.85rem 1.25rem;
      background: var(--bg-header);
      border-bottom: 1px solid var(--border);
      box-shadow: 0 1px 4px var(--shadow);
      flex-shrink: 0;
      z-index: 10;
    }

    .header-left {
      display: flex;
      align-items: center;
      gap: 0.65rem;
    }

    .bot-avatar {
      width: 38px;
      height: 38px;
      border-radius: 50%;
      background: var(--bot-bubble);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 1.2rem;
      flex-shrink: 0;
    }

    .header-title { font-weight: 700; font-size: 1.05rem; color: var(--bot-text); }
    .header-subtitle { font-size: 0.75rem; color: var(--muted); font-weight: 500; }

    .btn-new-chat {
      background: none;
      border: 1.5px solid var(--border);
      border-radius: 20px;
      padding: 0.4rem 0.85rem;
      font-family: var(--font);
      font-size: 0.78rem;
      font-weight: 600;
      color: var(--muted);
      cursor: pointer;
      transition: all 0.2s ease;
    }

    .btn-new-chat:hover { border-color: var(--accent); color: var(--accent); }

    /* ── Chat Area ────────────────────────────────────────────── */
    .chat-area {
      flex: 1;
      overflow-y: auto;
      padding: 1.25rem;
      display: flex;
      flex-direction: column;
      gap: 0.75rem;
      scroll-behavior: smooth;
    }

    /* ── Welcome Message ──────────────────────────────────────── */
    .welcome { text-align: center; padding: 2rem 1rem; animation: fadeInUp 0.5s ease; }
    .welcome-emoji { font-size: 2.8rem; margin-bottom: 0.6rem; }
    .welcome h2 { font-size: 1.2rem; font-weight: 700; margin-bottom: 0.35rem; color: var(--bot-text); }
    .welcome p { font-size: 0.88rem; color: var(--muted); line-height: 1.55; max-width: 380px; margin: 0 auto; }

    .suggestions { display: flex; flex-wrap: wrap; gap: 0.5rem; justify-content: center; margin-top: 1.15rem; }

    .suggestion-chip {
      background: var(--input-bg);
      border: 1.5px solid var(--border);
      border-radius: 20px;
      padding: 0.45rem 0.9rem;
      font-family: var(--font);
      font-size: 0.8rem;
      font-weight: 500;
      color: var(--bot-text);
      cursor: pointer;
      transition: all 0.2s ease;
    }

    .suggestion-chip:hover { border-color: var(--accent); color: var(--accent); transform: translateY(-1px); }

    /* ── Message Bubbles ──────────────────────────────────────── */
    .message-row { display: flex; gap: 0.55rem; max-width: 88%; animation: fadeInUp 0.3s ease; }
    .message-row.user { align-self: flex-end; flex-direction: row-reverse; }
    .message-row.bot { align-self: flex-start; }

    .msg-avatar {
      width: 30px; height: 30px; border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      font-size: 0.85rem; flex-shrink: 0; margin-top: 2px;
    }
    .msg-avatar.bot { background: var(--bot-bubble); }
    .msg-avatar.user { background: var(--user-bubble); }

    .bubble { padding: 0.7rem 1rem; border-radius: 18px; font-size: 0.9rem; line-height: 1.55; word-break: break-word; }
    .bubble.bot { background: var(--bot-bubble); color: var(--bot-text); border-bottom-left-radius: 6px; }
    .bubble.user { background: var(--user-bubble); color: var(--user-text); border-bottom-right-radius: 6px; }

    .bubble code {
      background: var(--code-bg); padding: 0.15rem 0.35rem; border-radius: 4px;
      font-size: 0.82rem; font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
    }

    .bubble pre {
      background: var(--code-bg); padding: 0.65rem 0.85rem; border-radius: 8px;
      overflow-x: auto; margin: 0.5rem 0; font-size: 0.8rem;
      font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace; line-height: 1.5;
    }
    .bubble pre code { background: none; padding: 0; }

    /* ── File Badge & Download ────────────────────────────────── */
    .file-badge {
      display: inline-flex; align-items: center; gap: 0.35rem;
      background: rgba(255,255,255,0.6); border-radius: 10px;
      padding: 0.3rem 0.6rem; font-size: 0.75rem; font-weight: 600;
      margin-bottom: 0.35rem; color: var(--bot-text);
    }

    .download-link {
      display: inline-flex; align-items: center; gap: 0.3rem;
      margin-top: 0.5rem; padding: 0.4rem 0.75rem;
      background: var(--accent); color: white; border-radius: 12px;
      font-size: 0.8rem; font-weight: 600; text-decoration: none; transition: background 0.2s;
    }
    .download-link:hover { background: var(--accent-hover); }

    /* ── Typing Indicator ─────────────────────────────────────── */
    .typing-row { display: flex; gap: 0.55rem; align-self: flex-start; max-width: 88%; animation: fadeInUp 0.3s ease; }

    .typing-dots {
      display: flex; gap: 4px; padding: 0.85rem 1rem;
      background: var(--bot-bubble); border-radius: 18px; border-bottom-left-radius: 6px;
    }

    .typing-dots span {
      width: 7px; height: 7px; border-radius: 50%;
      background: var(--muted); animation: bounce 1.4s infinite ease-in-out;
    }
    .typing-dots span:nth-child(2) { animation-delay: 0.16s; }
    .typing-dots span:nth-child(3) { animation-delay: 0.32s; }

    /* ── Input Area ───────────────────────────────────────────── */
    .input-area {
      padding: 0.75rem 1.25rem;
      padding-bottom: calc(0.75rem + env(safe-area-inset-bottom, 0px));
      background: var(--bg-header); border-top: 1px solid var(--border); flex-shrink: 0;
    }

    .file-preview {
      display: none; align-items: center; gap: 0.4rem;
      padding: 0.4rem 0.65rem; margin-bottom: 0.5rem;
      background: var(--bot-bubble); border-radius: 10px; font-size: 0.78rem; font-weight: 600;
    }
    .file-preview.visible { display: inline-flex; }
    .file-preview .remove-file {
      background: none; border: none; cursor: pointer;
      font-size: 1rem; color: var(--danger); line-height: 1; padding: 0 0.15rem;
    }

    .input-row { display: flex; align-items: flex-end; gap: 0.5rem; }

    .input-wrapper {
      flex: 1; display: flex; align-items: flex-end;
      background: var(--input-bg); border: 1.5px solid var(--border);
      border-radius: 22px; padding: 0.15rem 0.25rem 0.15rem 1rem; transition: border-color 0.2s;
    }
    .input-wrapper:focus-within { border-color: var(--accent); }

    #messageInput {
      flex: 1; border: none; outline: none; font-family: var(--font);
      font-size: 0.9rem; resize: none; max-height: 120px;
      padding: 0.55rem 0; background: transparent; color: var(--bot-text); line-height: 1.4;
    }
    #messageInput::placeholder { color: var(--muted); }

    .btn-icon {
      width: 36px; height: 36px; border-radius: 50%; border: none; background: none;
      cursor: pointer; display: flex; align-items: center; justify-content: center;
      transition: all 0.2s; flex-shrink: 0; font-size: 1.15rem; color: var(--muted);
    }
    .btn-icon:hover { background: var(--bg); color: var(--accent); }

    .btn-send {
      width: 38px; height: 38px; border-radius: 50%; border: none;
      background: var(--accent); color: white; cursor: pointer;
      display: flex; align-items: center; justify-content: center;
      transition: all 0.2s; flex-shrink: 0; font-size: 1.15rem;
    }
    .btn-send:hover { background: var(--accent-hover); }
    .btn-send:disabled { opacity: 0.5; cursor: not-allowed; }

    #fileInput { display: none; }

    /* ── Drop Zone ────────────────────────────────────────────── */
    .drop-overlay {
      display: none; position: fixed; inset: 0;
      background: rgba(232, 146, 124, 0.12); border: 3px dashed var(--accent);
      border-radius: 12px; z-index: 100; align-items: center;
      justify-content: center; pointer-events: none;
    }
    .drop-overlay.visible { display: flex; }
    .drop-overlay p {
      background: white; padding: 1rem 2rem; border-radius: 16px;
      font-weight: 700; font-size: 1rem; color: var(--accent);
      box-shadow: 0 4px 20px var(--shadow);
    }

    /* ── Animations ───────────────────────────────────────────── */
    @keyframes fadeInUp {
      from { opacity: 0; transform: translateY(8px); }
      to   { opacity: 1; transform: translateY(0); }
    }
    @keyframes bounce {
      0%, 80%, 100% { transform: scale(0); }
      40% { transform: scale(1); }
    }

    /* ── Responsive ───────────────────────────────────────────── */
    @media (max-width: 600px) {
      .header { padding: 0.7rem 1rem; }
      .chat-area { padding: 1rem; }
      .input-area { padding: 0.6rem 1rem; }
      .message-row { max-width: 92%; }
      .suggestions { gap: 0.35rem; }
      .suggestion-chip { font-size: 0.75rem; padding: 0.38rem 0.7rem; }
    }
  </style>
</head>

<body>
  <div class="app">

    <!-- Header -->
    <div class="header">
      <div class="header-left">
        <div class="bot-avatar">📊</div>
        <div>
          <div class="header-title"><?= botName ?></div>
          <div class="header-subtitle">Your Excel assistant</div>
        </div>
      </div>
      <button class="btn-new-chat" onclick="newConversation()">New Chat</button>
    </div>

    <!-- Chat Area -->
    <div class="chat-area" id="chatArea">
      <div class="welcome" id="welcomeMessage">
        <div class="welcome-emoji">👋</div>
        <h2>Hi! I'm <?= botName ?>.</h2>
        <p>I can help with Excel formulas, data analysis, formatting, and more. You can also upload spreadsheets for me to look at.</p>
        <div class="suggestions">
          <button class="suggestion-chip" onclick="useSuggestion(this)">How do I use VLOOKUP?</button>
          <button class="suggestion-chip" onclick="useSuggestion(this)">Create a budget tracker</button>
          <button class="suggestion-chip" onclick="useSuggestion(this)">Explain pivot tables</button>
          <button class="suggestion-chip" onclick="useSuggestion(this)">Fix my SUM formula</button>
        </div>
      </div>
    </div>

    <!-- Drop Zone Overlay -->
    <div class="drop-overlay" id="dropOverlay">
      <p>📎 Drop your spreadsheet here</p>
    </div>

    <!-- Input Area -->
    <div class="input-area">
      <div class="file-preview" id="filePreview">
        <span>📎</span>
        <span id="filePreviewName"></span>
        <button class="remove-file" onclick="removeFile()">×</button>
      </div>
      <div class="input-row">
        <div class="input-wrapper">
          <textarea id="messageInput"
                    placeholder="Ask me about Excel..."
                    rows="1"
                    onkeydown="handleKeyDown(event)"
                    oninput="autoResize(this)"></textarea>
          <button class="btn-icon" onclick="triggerFileUpload()" title="Attach file">📎</button>
        </div>
        <button class="btn-send" id="sendBtn" onclick="sendMessage()" title="Send">➤</button>
      </div>
    </div>

    <input type="file" id="fileInput" accept=".xlsx,.csv,.xls" onchange="handleFileSelect(event)">
  </div>

  <script>
    // ── State ──────────────────────────────────────────────
    var conversationHistory = [];
    var pendingFile = null;
    var isProcessing = false;
    var userEmail = "<?= userEmail ?>";
    var MAX_HISTORY = 20;

    // ── Elements ───────────────────────────────────────────
    var chatArea        = document.getElementById('chatArea');
    var messageInput    = document.getElementById('messageInput');
    var sendBtn         = document.getElementById('sendBtn');
    var fileInput       = document.getElementById('fileInput');
    var filePreview     = document.getElementById('filePreview');
    var filePreviewName = document.getElementById('filePreviewName');
    var welcomeMessage  = document.getElementById('welcomeMessage');
    var dropOverlay     = document.getElementById('dropOverlay');

    // ── Send Message ───────────────────────────────────────
    function sendMessage() {
      var text = messageInput.value.trim();
      if ((!text && !pendingFile) || isProcessing) return;

      if (welcomeMessage) welcomeMessage.style.display = 'none';

      var displayText = text || '(Uploaded file)';
      if (pendingFile) {
        displayText = '📎 ' + pendingFile.name + (text ? '\n' + text : '');
      }
      addMessageBubble('user', displayText);

      messageInput.value = '';
      autoResize(messageInput);
      showTyping();
      setProcessing(true);

      var historyToSend = conversationHistory.slice(-MAX_HISTORY * 2);
      var fileBase64 = pendingFile ? pendingFile.data : null;
      var fileName   = pendingFile ? pendingFile.name : null;
      var fileMime   = pendingFile ? pendingFile.mimeType : null;
      removeFile();

      google.script.run
        .withSuccessHandler(function(response) {
          hideTyping();
          setProcessing(false);
          if (response && response.message) {
            addMessageBubble('bot', response.message, response.file_name, response.file_data);
            conversationHistory.push({ role: 'user', content: text || '(file upload)' });
            conversationHistory.push({ role: 'assistant', content: response.message });
          } else {
            addMessageBubble('bot', 'Hmm, I got an empty response. Try asking again?');
          }
        })
        .withFailureHandler(function(error) {
          hideTyping();
          setProcessing(false);
          addMessageBubble('bot', 'Sorry, something went wrong. Please try again. (' + error.message + ')');
        })
        .processMessage(text, historyToSend, fileBase64, fileName, fileMime);
    }

    // ── Message Bubble Rendering ───────────────────────────
    function addMessageBubble(role, text, fileName, fileData) {
      var row = document.createElement('div');
      row.className = 'message-row ' + role;

      var avatar = document.createElement('div');
      avatar.className = 'msg-avatar ' + role;
      avatar.textContent = role === 'bot' ? '📊' : '👤';

      var bubble = document.createElement('div');
      bubble.className = 'bubble ' + role;

      if (role === 'bot') {
        bubble.innerHTML = formatBotMessage(text);
        if (fileName && fileData) {
          var link = document.createElement('a');
          link.className = 'download-link';
          link.href = 'data:application/octet-stream;base64,' + fileData;
          link.download = fileName;
          link.textContent = '⬇ Download ' + fileName;
          bubble.appendChild(link);
        }
      } else {
        bubble.textContent = text;
      }

      row.appendChild(avatar);
      row.appendChild(bubble);
      chatArea.appendChild(row);
      scrollToBottom();
    }

    // ── Format Bot Message (markdown-lite) ─────────────────
    function formatBotMessage(text) {
      var safe = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
      safe = safe.replace(/```(\w*)\n?([\s\S]*?)```/g, function(_, lang, code) {
        return '<pre><code>' + code.trim() + '</code></pre>';
      });
      safe = safe.replace(/`([^`]+)`/g, '<code>$1</code>');
      safe = safe.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
      safe = safe.replace(/\n/g, '<br>');
      return safe;
    }

    // ── Typing Indicator ───────────────────────────────────
    function showTyping() {
      var row = document.createElement('div');
      row.className = 'typing-row';
      row.id = 'typingIndicator';
      var avatar = document.createElement('div');
      avatar.className = 'msg-avatar bot';
      avatar.textContent = '📊';
      var dots = document.createElement('div');
      dots.className = 'typing-dots';
      dots.innerHTML = '<span></span><span></span><span></span>';
      row.appendChild(avatar);
      row.appendChild(dots);
      chatArea.appendChild(row);
      scrollToBottom();
    }

    function hideTyping() {
      var el = document.getElementById('typingIndicator');
      if (el) el.remove();
    }

    // ── File Handling ──────────────────────────────────────
    function triggerFileUpload() { fileInput.click(); }

    function handleFileSelect(event) {
      var file = event.target.files[0];
      if (!file) return;
      processFile(file);
      fileInput.value = '';
    }

    function processFile(file) {
      var name = file.name.toLowerCase();
      var validExt = ['.xlsx', '.csv', '.xls'];
      var hasValidExt = validExt.some(function(ext) { return name.endsWith(ext); });
      if (!hasValidExt) { alert('Please upload an .xlsx, .csv, or .xls file.'); return; }
      if (file.size > 10 * 1024 * 1024) { alert('File is too large. Maximum size is 10MB.'); return; }

      var reader = new FileReader();
      reader.onload = function(e) {
        var base64 = e.target.result.split(',')[1];
        pendingFile = { name: file.name, data: base64, mimeType: file.type || 'application/octet-stream' };
        filePreviewName.textContent = file.name;
        filePreview.classList.add('visible');
      };
      reader.readAsDataURL(file);
    }

    function removeFile() {
      pendingFile = null;
      filePreview.classList.remove('visible');
      filePreviewName.textContent = '';
    }

    // ── Drag & Drop ────────────────────────────────────────
    var dragCounter = 0;
    document.addEventListener('dragenter', function(e) { e.preventDefault(); dragCounter++; dropOverlay.classList.add('visible'); });
    document.addEventListener('dragleave', function(e) { e.preventDefault(); dragCounter--; if (dragCounter <= 0) { dragCounter = 0; dropOverlay.classList.remove('visible'); } });
    document.addEventListener('dragover', function(e) { e.preventDefault(); });
    document.addEventListener('drop', function(e) { e.preventDefault(); dragCounter = 0; dropOverlay.classList.remove('visible'); if (e.dataTransfer.files.length > 0) processFile(e.dataTransfer.files[0]); });

    // ── Input Helpers ──────────────────────────────────────
    function handleKeyDown(event) { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendMessage(); } }
    function autoResize(el) { el.style.height = 'auto'; el.style.height = Math.min(el.scrollHeight, 120) + 'px'; }
    function scrollToBottom() { requestAnimationFrame(function() { chatArea.scrollTop = chatArea.scrollHeight; }); }
    function setProcessing(state) { isProcessing = state; sendBtn.disabled = state; messageInput.disabled = state; }

    // ── Suggestion Chips ───────────────────────────────────
    function useSuggestion(chip) { messageInput.value = chip.textContent; autoResize(messageInput); sendMessage(); }

    // ── New Conversation ───────────────────────────────────
    function newConversation() {
      conversationHistory = [];
      pendingFile = null;
      removeFile();
      chatArea.innerHTML = '';
      var welcome = document.createElement('div');
      welcome.className = 'welcome';
      welcome.id = 'welcomeMessage';
      welcome.innerHTML =
        '<div class="welcome-emoji">👋</div>' +
        '<h2>Hi! I\'m ExcelBot.</h2>' +
        '<p>I can help with Excel formulas, data analysis, formatting, and more. You can also upload spreadsheets for me to look at.</p>' +
        '<div class="suggestions">' +
          '<button class="suggestion-chip" onclick="useSuggestion(this)">How do I use VLOOKUP?</button>' +
          '<button class="suggestion-chip" onclick="useSuggestion(this)">Create a budget tracker</button>' +
          '<button class="suggestion-chip" onclick="useSuggestion(this)">Explain pivot tables</button>' +
          '<button class="suggestion-chip" onclick="useSuggestion(this)">Fix my SUM formula</button>' +
        '</div>';
      chatArea.appendChild(welcome);
      welcomeMessage = welcome;
    }

    messageInput.focus();
  </script>
</body>
</html>
```

---

### File: `AccessDenied.html`

```html
<!DOCTYPE html>
<html>
<head>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700&display=swap');
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: 'Nunito', sans-serif;
      background: #FFF8F0;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      color: #4A3728;
    }
    .container { text-align: center; padding: 3rem; max-width: 420px; }
    .icon { font-size: 4rem; margin-bottom: 1rem; }
    h1 { font-size: 1.4rem; font-weight: 700; margin-bottom: 0.75rem; color: #4A3728; }
    p { font-size: 1rem; line-height: 1.6; color: #7A6B5D; }
  </style>
</head>
<body>
  <div class="container">
    <div class="icon">🔒</div>
    <h1>Access Denied</h1>
    <p>Sorry, this chat is only available to authorized users. If you think you should have access, please contact the administrator.</p>
  </div>
</body>
</html>
```

---

## Dependency Check

The existing `requirements.txt` already includes all needed packages:

- `fastapi` — web framework
- `uvicorn` — ASGI server
- `anthropic` — Claude API
- `pydantic-settings` — config
- `openpyxl` — .xlsx read/write
- `pandas` — data analysis
- `google-auth` — token verification
- `google-cloud-storage` — GCS (future file storage)

No new dependencies are required.

---

## Implementation Warnings

1. **Review `src/claude/client.py` before implementing the endpoint.** The spec assumes `claude_client.messages.create()` follows the standard Anthropic SDK pattern. If `ClaudeClient` wraps this differently (e.g., custom method, different kwargs), the call in the `/web-chat` endpoint must be adapted.

2. **Do not modify the existing `/chat` endpoint.** The new `/web-chat` endpoint is intentionally separate — it uses shared-secret auth instead of Google Chat JWT verification.

3. **The `WEB_CHAT_SECRET` environment variable must be set on Cloud Run BEFORE the Apps Script frontend calls it.** The endpoint returns 500 if the secret is not configured.

4. **The Apps Script files are NOT part of the GitHub repo.** They live in the Apps Script editor (script.google.com) and are deployed separately. The human handles this in Manual Actions 4–6.

---

## Summary: Manual Action Checklist

| Order | Action | Where | Depends On |
|-------|--------|-------|------------|
| 🔧 1 | Generate shared secret | Terminal | Nothing |
| ✅ 2 | Implement Phase 1 code changes | Claude Code / GitHub | Nothing |
| ✅ 3 | Push to `develop` and verify CI/CD deploys | GitHub Actions | Step 2 |
| 🔧 4 | Set `WEB_CHAT_SECRET` on Cloud Run | Terminal (gcloud) | Steps 1, 3 |
| 🔧 5 | Test `/web-chat` with curl | Terminal | Step 4 |
| 🔧 6 | Create Apps Script project + paste files | script.google.com | Nothing (can parallel) |
| 🔧 7 | Configure `Config.gs` with URL + secret | script.google.com | Steps 1, 4 |
| 🔧 8 | Deploy Web App | script.google.com | Steps 6, 7 |
| 🔧 9 | Test end-to-end | Browser | Step 8 |
| 🔧 10 | Send URL to Shannon | Email/text | Step 9 |

Items marked ✅ can be done by Claude Code. Items marked 🔧 require human action.

---

March 08, 2026

#AI/Claude
