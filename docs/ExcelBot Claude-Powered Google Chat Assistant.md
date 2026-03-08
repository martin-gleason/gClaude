# ExcelBot: Claude-Powered Google Chat Assistant

## Architecture & Planning Document

---

## 1. Project Overview

**ExcelBot** is an always-on Google Chat bot that monitors a chat space and answers Excel-related questions from a designated user. When @mentioned, it uses the Claude API to provide text guidance, analyze uploaded spreadsheets, and generate .xlsx files — all within the Google Chat interface.

### Tech Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Runtime | Python 3.12 | Mature Google Chat + Excel libraries; fastest path to robust deployment |
| Framework | FastAPI | Async-native, lightweight, easy Cloud Run integration |
| AI | Claude API (claude-sonnet-4-5-20250929) | Cost-effective for Q&A; escalate to Opus for complex analysis |
| Excel Processing | openpyxl + pandas | Read/write .xlsx; pandas for data analysis |
| Hosting | Google Cloud Run | Serverless, auto-scaling, native Google Chat integration |
| Storage | Google Cloud Storage (GCS) | Temporary file staging for uploads/downloads |
| Auth | Google Service Account | Workspace Chat API access |

### System Context Diagram

```
┌─────────────┐     @mention      ┌──────────────────┐
│  Google Chat │ ──── HTTP POST ──▶│  Cloud Run        │
│  (User)      │◀── response ──────│  (FastAPI)        │
└─────────────┘                    └────────┬─────────┘
                                            │
                              ┌─────────────┼─────────────┐
                              ▼             ▼             ▼
                        ┌──────────┐ ┌──────────┐ ┌──────────┐
                        │ Claude   │ │ GCS      │ │ openpyxl │
                        │ API      │ │ (files)  │ │ + pandas │
                        └──────────┘ └──────────┘ └──────────┘
```

---

## 2. Architecture Components

### 2.1 Google Chat Integration Layer

Google Chat sends HTTP POST requests to a registered endpoint when the bot is @mentioned. Cloud Run receives these as JSON payloads.

**Interaction model:** The bot uses Google Chat's **HTTP endpoint** mode (not Pub/Sub). Google Chat sends events directly to the Cloud Run URL. The bot processes them synchronously and returns a response.

**Key event types to handle:**

- `ADDED_TO_SPACE` — bot added to a room; send welcome message
- `MESSAGE` — user sends a message; route to processing pipeline
- `CARD_CLICKED` — user interacts with a card button (future: confirmations, options)

**Message filtering logic:**

1. Check if message is from the authorized user (configurable allowlist)
2. Check if bot was @mentioned (or if in DM, respond to all)
3. Strip the @mention prefix before passing to Claude

### 2.2 Message Processing Pipeline

```
Incoming Message
       │
       ▼
┌─────────────────┐
│ Auth & Filter    │──▶ Reject if unauthorized user
└────────┬────────┘
         ▼
┌─────────────────┐
│ Attachment Check │──▶ If .xlsx/.csv attached → download to GCS
└────────┬────────┘
         ▼
┌─────────────────┐
│ Context Builder  │──▶ Build Claude prompt with system context,
│                  │    user question, and spreadsheet summary
└────────┬────────┘
         ▼
┌─────────────────┐
│ Claude API Call  │──▶ Send to Claude; parse response
└────────┬────────┘
         ▼
┌─────────────────┐
│ Response Router  │──▶ Text only? → return message
│                  │──▶ File generated? → upload to GCS → return link
└─────────────────┘
```

### 2.3 Claude Integration Layer

The bot maintains a **system prompt** specialized for Excel assistance:

- Excel formula syntax, common functions, best practices
- Instruction to ask clarifying questions when ambiguous
- Guidance to provide step-by-step instructions the user can follow
- When a file is attached, instruction to analyze and describe findings
- When file generation is needed, instruction to output structured JSON describing the workbook

**Model selection strategy:**

- Default: `claude-sonnet-4-5-20250929` (fast, cost-effective for how-to questions)
- Escalation trigger: if the user's question involves multi-sheet analysis, pivot tables, or complex transformations, use `claude-opus-4-5-20250514`

### 2.4 Excel Processing Layer

**Reading uploaded files:**

1. Download attachment from Google Chat via the Chat API
2. Save temporarily to GCS (or in-memory if small)
3. Use openpyxl to extract: sheet names, dimensions, headers, sample rows, formulas
4. Build a structured summary for Claude's context window

**Generating files:**

1. Claude returns structured instructions (JSON) describing the workbook to create
2. Python code uses openpyxl/pandas to build the .xlsx
3. Upload to GCS with a signed URL (time-limited)
4. Return the download link in the Chat response

### 2.5 File Storage (GCS)

- **Bucket:** `excelbot-temp-files`
- **Retention:** Auto-delete after 24 hours (lifecycle policy)
- **Access:** Signed URLs for download links; no public access
- **Upload path:** `uploads/{user_id}/{timestamp}_{filename}`
- **Generated path:** `generated/{user_id}/{timestamp}_{filename}`

### 2.6 Configuration & Secrets

| Config Item | Storage | Notes |
|-------------|---------|-------|
| ANTHROPIC_API_KEY | Secret Manager | Claude API key |
| AUTHORIZED_USERS | Environment variable | Comma-separated user IDs |
| GCS_BUCKET | Environment variable | Temp file bucket name |
| MENTION_TRIGGER | Environment variable | Default: true (require @mention) |
| DEFAULT_MODEL | Environment variable | Default: claude-sonnet-4-5-20250929 |
| LOG_LEVEL | Environment variable | Default: INFO |

---

## 3. Deployment Architecture

### 3.1 Infrastructure

```
Google Chat App (configured in Google Cloud Console)
       │
       │  HTTP endpoint
       ▼
Google Cloud Run (excelbot-service)
  ├── Container: python:3.12-slim
  ├── Memory: 512MB
  ├── CPU: 1
  ├── Min instances: 0 (scale to zero when idle)
  ├── Max instances: 3
  ├── Timeout: 60s
  └── Concurrency: 10
       │
       ├──▶ Secret Manager (API keys)
       ├──▶ Cloud Storage (temp files)
       └──▶ Cloud Logging (structured logs)
```

### 3.2 Docker Container

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

### 3.3 CI/CD Pipeline (GitHub Actions)

```
Push to main → Build Docker image → Push to Artifact Registry → Deploy to Cloud Run
```

---

## 4. Project Scaffolding

```
excelbot/
├── .github/
│   └── workflows/
│       └── deploy.yml              # CI/CD pipeline
├── src/
│   ├── __init__.py
│   ├── main.py                     # FastAPI app, Google Chat webhook handler
│   ├── config.py                   # Environment config + secrets loading
│   ├── auth.py                     # User authorization + message filtering
│   ├── chat/
│   │   ├── __init__.py
│   │   ├── events.py               # Google Chat event type handlers
│   │   ├── messages.py             # Message parsing, @mention stripping
│   │   └── responses.py            # Response formatting (text, cards, links)
│   ├── claude/
│   │   ├── __init__.py
│   │   ├── client.py               # Claude API wrapper
│   │   ├── prompts.py              # System prompts, context builders
│   │   └── models.py               # Model selection logic
│   ├── excel/
│   │   ├── __init__.py
│   │   ├── reader.py               # Read + summarize uploaded spreadsheets
│   │   ├── writer.py               # Generate .xlsx from Claude instructions
│   │   └── analyzer.py             # Data analysis helpers (pandas)
│   └── storage/
│       ├── __init__.py
│       └── gcs.py                  # GCS upload/download, signed URLs
├── tests/
│   ├── __init__.py
│   ├── conftest.py                 # Shared fixtures
│   ├── unit/
│   │   ├── test_auth.py
│   │   ├── test_messages.py
│   │   ├── test_prompts.py
│   │   ├── test_reader.py
│   │   ├── test_writer.py
│   │   └── test_models.py
│   └── integration/
│       ├── test_chat_webhook.py
│       ├── test_claude_pipeline.py
│       └── test_excel_roundtrip.py
├── Dockerfile
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
├── .env.example
└── README.md
```

---

## 5. User Stories (TDD Template)

Each user story follows the format: **As a [role], I want [goal], so that [benefit]**. Each includes acceptance criteria written as test cases.

### Epic 1: Bot Activation & Presence

**US-1.1: Bot joins a space**
> As a workspace admin, I want to add ExcelBot to a Google Chat space, so that it's available for my Excel questions.

Acceptance criteria / test cases:
- `test_bot_responds_to_added_to_space_event`: When bot receives `ADDED_TO_SPACE` event → returns welcome message with usage instructions
- `test_bot_welcome_message_content`: Welcome message includes @mention syntax and supported capabilities
- `test_bot_handles_removed_from_space`: When bot receives `REMOVED_FROM_SPACE` → logs event, no error

**US-1.2: Bot only responds when @mentioned**
> As a user, I want ExcelBot to only respond when I @mention it, so that it doesn't interrupt other conversations.

Acceptance criteria / test cases:
- `test_bot_responds_to_at_mention`: Message with @ExcelBot → processes and responds
- `test_bot_ignores_non_mention`: Message without @mention → returns empty response (HTTP 200, no chat message)
- `test_bot_responds_to_dm`: Direct message (no @mention needed) → processes and responds
- `test_mention_config_toggle`: When MENTION_TRIGGER=false → responds to all messages

### Epic 2: Authorization

**US-2.1: Authorized user access**
> As an authorized user, I want ExcelBot to answer my questions, so that I get Excel help quickly.

Acceptance criteria / test cases:
- `test_authorized_user_gets_response`: Message from user in AUTHORIZED_USERS → processes normally
- `test_unauthorized_user_rejected`: Message from user NOT in AUTHORIZED_USERS → returns polite decline message
- `test_empty_allowlist_allows_all`: When AUTHORIZED_USERS is empty → all users allowed (open mode)

### Epic 3: Text-Based Excel Q&A

**US-3.1: Simple Excel question**
> As a user, I want to ask how to do something in Excel and get a clear answer, so that I can complete my task.

Acceptance criteria / test cases:
- `test_simple_question_returns_answer`: "How do I use VLOOKUP?" → response contains formula syntax and example
- `test_response_under_timeout`: Response returned within 30 seconds
- `test_claude_api_error_graceful`: Claude API returns 500 → user gets friendly error message, not a stack trace
- `test_rate_limit_handling`: Claude API returns 429 → user gets "busy, try again" message

**US-3.2: Follow-up context (thread awareness)**
> As a user, I want to ask follow-up questions in a thread and have ExcelBot remember the context, so that I don't have to repeat myself.

Acceptance criteria / test cases:
- `test_thread_context_maintained`: Second message in same thread includes prior Q&A in Claude context
- `test_separate_threads_independent`: Messages in different threads don't share context
- `test_context_window_limit`: Thread with 20+ messages → older messages gracefully truncated

### Epic 4: Spreadsheet Upload & Analysis

**US-4.1: Upload and analyze a spreadsheet**
> As a user, I want to upload an .xlsx file and ask questions about it, so that I can understand my data.

Acceptance criteria / test cases:
- `test_xlsx_upload_detected`: Message with .xlsx attachment → file downloaded and processed
- `test_csv_upload_detected`: Message with .csv attachment → file downloaded and processed
- `test_spreadsheet_summary_in_context`: Uploaded file's headers, dimensions, sample data included in Claude prompt
- `test_large_file_handling`: File >5MB → summarize first 1000 rows, warn user about truncation
- `test_unsupported_format_message`: .xls (legacy) attachment → message explaining only .xlsx/.csv supported

**US-4.2: Ask questions about uploaded data**
> As a user, I want to ask "what's the average of column B?" about my uploaded file and get a computed answer, so that I don't have to open Excel.

Acceptance criteria / test cases:
- `test_data_question_uses_pandas`: Question about column statistics → pandas computes actual answer
- `test_formula_question_returns_formula`: "How do I calculate this in Excel?" → returns Excel formula, not just the answer
- `test_multi_sheet_awareness`: "What sheets are in this file?" → lists all sheet names

### Epic 5: Spreadsheet Generation

**US-5.1: Generate a new spreadsheet**
> As a user, I want to ask ExcelBot to create a spreadsheet for me, so that I get a ready-to-use file.

Acceptance criteria / test cases:
- `test_generate_simple_xlsx`: "Make me a budget tracker" → .xlsx file created with appropriate columns and formatting
- `test_generated_file_downloadable`: Generated file uploaded to GCS → signed URL returned in chat
- `test_signed_url_expires`: Signed URL expires after 24 hours
- `test_generated_file_valid`: Generated .xlsx opens without errors in Excel and Google Sheets

**US-5.2: Modify an uploaded spreadsheet**
> As a user, I want to upload a spreadsheet and ask ExcelBot to add a column or fix formulas, so that I save time.

Acceptance criteria / test cases:
- `test_add_column_to_existing`: "Add a total column" → modified file returned with new column
- `test_fix_formulas`: "My SUM formulas are wrong" → corrected file returned
- `test_original_preserved`: Original file in GCS unchanged; new file created

### Epic 6: Error Handling & Resilience

**US-6.1: Graceful failure**
> As a user, I want clear error messages when something goes wrong, so that I know what to do next.

Acceptance criteria / test cases:
- `test_claude_timeout_message`: Claude API timeout → "I'm taking too long, try a simpler question"
- `test_gcs_failure_message`: GCS upload fails → "I couldn't save the file, try again"
- `test_malformed_xlsx_message`: Corrupted .xlsx uploaded → "I couldn't read this file — it may be corrupted"
- `test_google_chat_verification`: Request without valid Google token → HTTP 401

---

## 6. Risk Register

| ID | Risk | Likelihood | Impact | Severity | Mitigation | Owner | Status |
|----|------|-----------|--------|----------|------------|-------|--------|
| R-01 | **Claude API costs escalate** — high message volume or large file contexts drive unexpected costs | Medium | High | High | Set daily/monthly spend caps in Anthropic console; default to Sonnet; log token usage per request; alert at 80% of budget | Developer | Open |
| R-02 | **Google Chat API quota limits** — Chat API has rate limits that could block responses during heavy use | Low | Medium | Medium | Implement exponential backoff; monitor quota usage; design for async responses if sync times out | Developer | Open |
| R-03 | **Sensitive data in spreadsheets** — user uploads files containing PII or confidential data that gets sent to Claude API | Medium | High | High | Add a disclaimer in the welcome message; never persist file contents beyond 24hrs; consider Anthropic's data retention policies; document what data flows where | Developer | Open |
| R-04 | **Google Chat webhook verification bypass** — unauthorized requests to the Cloud Run endpoint | Low | High | Medium | Verify Google Chat bearer tokens on every request; reject unverified requests with 401; restrict Cloud Run ingress to Google internal | Developer | Open |
| R-05 | **Large file processing timeout** — Cloud Run 60s timeout exceeded when analyzing large spreadsheets | Medium | Medium | Medium | Limit file analysis to first 1000 rows; stream partial results; increase timeout to 300s if needed; warn user about large files | Developer | Open |
| R-06 | **Claude hallucination on Excel formulas** — Claude provides incorrect formula syntax or logic | Medium | Medium | Medium | Include formula validation in system prompt; test common formulas against known outputs; add disclaimer about verifying formulas | Developer | Open |
| R-07 | **GCS signed URL security** — signed URLs could be shared or accessed by unauthorized users | Low | Medium | Low | Set 24hr expiration; use per-user paths; monitor access logs; consider requiring Google auth on URLs | Developer | Open |
| R-08 | **Service account key leakage** — credentials exposed in code or logs | Low | Critical | High | Use Workload Identity (no keys needed on Cloud Run); never log credentials; rotate keys if used locally; store in Secret Manager | Developer | Open |
| R-09 | **Thread context window overflow** — long conversation threads exceed Claude's context limit | Medium | Low | Low | Implement sliding window (keep last N messages); summarize older context; warn user when context is truncated | Developer | Open |
| R-10 | **Google Workspace policy changes** — Google changes Chat API terms, pricing, or capabilities | Low | Medium | Low | Monitor Google Workspace blog; design abstraction layer so Chat integration is swappable; document API version dependencies | Developer | Open |
| R-11 | **Cold start latency** — Cloud Run scale-from-zero adds 3-10s to first request | Medium | Low | Low | Set min-instances=1 during business hours (slight cost increase); or accept cold start with user-facing "thinking..." indicator | Developer | Open |
| R-12 | **Anthropic API breaking changes** — Claude API changes model names, response format, or deprecates models | Low | Medium | Medium | Pin SDK version; subscribe to Anthropic changelog; abstract model selection behind config | Developer | Open |

### Risk Matrix

```
              Low Impact    Medium Impact    High Impact    Critical
High Likely  │             │                │              │
Medium Likely│             │ R-05, R-06,    │ R-01, R-03   │
             │             │ R-09, R-11     │              │
Low Likely   │ R-10        │ R-02, R-07,    │ R-04         │ R-08
             │             │ R-12           │              │
```

---

## 7. Next Steps

1. **Set up Google Cloud project** — enable Chat API, Cloud Run, Cloud Storage, Secret Manager
2. **Register Google Chat App** — configure HTTP endpoint, bot name, avatar, permissions
3. **Scaffold the repo** — create project structure per Section 4
4. **TDD red-green-refactor** — start with Epic 1 (US-1.1), write failing tests, implement
5. **Local development** — use ngrok to tunnel Google Chat webhooks to localhost during development
6. **Deploy MVP** — text Q&A only (Epics 1-3), then iterate to add file handling (Epics 4-5)

### Suggested Sprint Plan

| Sprint | Scope | Stories |
|--------|-------|---------|
| Sprint 1 | Bot presence + auth + basic Q&A | US-1.1, US-1.2, US-2.1, US-3.1 |
| Sprint 2 | Thread context + file upload | US-3.2, US-4.1, US-4.2 |
| Sprint 3 | File generation + error handling | US-5.1, US-5.2, US-6.1 |

---

March 05, 2026

#AI/Claude
