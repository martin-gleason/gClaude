/**
 * Gmail Apps Script for ExcelBot
 *
 * Polls for unread emails with the "excelbot" label, sends them to
 * the Cloud Run webhook, and replies in-thread with Claude's response.
 *
 * Setup:
 * 1. Open https://script.google.com and create a new project
 * 2. Paste this entire file into Code.gs
 * 3. Set script properties (Project Settings > Script Properties):
 *    - WEBHOOK_URL: Your Cloud Run /email endpoint URL
 *    - WEBHOOK_SECRET: Must match GMAIL_WEBHOOK_SECRET in Cloud Run
 * 4. Create a Gmail label called "excelbot"
 * 5. Create a Gmail filter: to:your.email+excelbot@gmail.com → apply label "excelbot"
 * 6. Run createTrigger() once to set up the 1-minute polling
 */

var LABEL_NAME = "excelbot";

function processEmails() {
  var props = PropertiesService.getScriptProperties();
  var webhookUrl = props.getProperty("WEBHOOK_URL");
  var webhookSecret = props.getProperty("WEBHOOK_SECRET");

  if (!webhookUrl || !webhookSecret) {
    Logger.log("ERROR: WEBHOOK_URL and WEBHOOK_SECRET must be set in script properties.");
    return;
  }

  var label = GmailApp.getUserLabelByName(LABEL_NAME);
  if (!label) {
    Logger.log("Label '" + LABEL_NAME + "' not found. Create it first.");
    return;
  }

  var threads = label.getThreads(0, 10);
  for (var i = 0; i < threads.length; i++) {
    var thread = threads[i];
    if (!thread.isUnread()) {
      continue;
    }

    var messages = thread.getMessages();
    var message = messages[messages.length - 1];

    try {
      var payload = buildPayload(message);
      var response = sendToWebhook(payload, webhookUrl, webhookSecret);

      if (response && response.reply) {
        thread.reply(response.reply);
      } else if (response && response.error) {
        thread.reply("ExcelBot encountered an error: " + response.error);
      }
    } catch (e) {
      Logger.log("Error processing message " + message.getId() + ": " + e.toString());
      thread.reply("ExcelBot encountered an unexpected error. Please try again later.");
    }

    thread.markRead();
    thread.removeLabel(label);
  }
}

function buildPayload(message) {
  var payload = {
    sender: message.getFrom(),
    subject: message.getSubject(),
    body: message.getPlainBody(),
    message_id: message.getId(),
    attachments: []
  };

  var attachments = message.getAttachments();
  for (var j = 0; j < attachments.length; j++) {
    var att = attachments[j];
    var mimeType = att.getContentType();
    var filename = att.getName();

    if (filename.toLowerCase().indexOf(".xlsx") === -1 &&
        mimeType !== "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" &&
        mimeType !== "application/vnd.ms-excel") {
      continue;
    }

    payload.attachments.push({
      filename: filename,
      mime_type: mimeType,
      data: Utilities.base64Encode(att.getBytes())
    });
  }

  return payload;
}

function sendToWebhook(payload, webhookUrl, webhookSecret) {
  var options = {
    method: "post",
    contentType: "application/json",
    headers: {
      "X-Webhook-Secret": webhookSecret
    },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  };

  var response = UrlFetchApp.fetch(webhookUrl, options);
  var code = response.getResponseCode();

  if (code !== 200) {
    Logger.log("Webhook returned HTTP " + code + ": " + response.getContentText());
    return null;
  }

  return JSON.parse(response.getContentText());
}

/**
 * Run this function once to create the 1-minute trigger.
 * Go to Run > createTrigger in the Apps Script editor.
 */
function createTrigger() {
  // Remove any existing triggers for processEmails
  var triggers = ScriptApp.getProjectTriggers();
  for (var i = 0; i < triggers.length; i++) {
    if (triggers[i].getHandlerFunction() === "processEmails") {
      ScriptApp.deleteTrigger(triggers[i]);
    }
  }

  ScriptApp.newTrigger("processEmails")
    .timeBased()
    .everyMinutes(1)
    .create();

  Logger.log("Trigger created: processEmails will run every 1 minute.");
}
