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
