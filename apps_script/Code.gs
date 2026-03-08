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
