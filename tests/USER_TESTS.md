# ExcelBot User Acceptance Tests

Manual test checklist for verifying the full email-to-reply flow in a live environment.

---

## Prerequisites

- [ ] Cloud Run service deployed and accessible
- [ ] `ANTHROPIC_API_KEY` set in Cloud Run environment
- [ ] `GMAIL_WEBHOOK_SECRET` set in Cloud Run environment
- [ ] `AUTHORIZED_USERS` set (e.g., `shannon@gmail.com`)
- [ ] Gmail Apps Script installed and configured with correct webhook URL and secret
- [ ] Gmail filter created: emails to `+excelbot` address auto-labeled "excelbot"
- [ ] Apps Script 1-minute trigger enabled

---

## 1. Basic Question (No Attachment)

**Steps:**
1. Send an email to your `+excelbot` address
2. Subject: `How do I use VLOOKUP?`
3. Body: `I want to look up employee names from one sheet in another sheet`
4. Wait ~1-2 minutes

**Expected:**
- [ ] Reply arrives in the same email thread
- [ ] Reply contains a relevant VLOOKUP explanation
- [ ] Email is marked as read
- [ ] "excelbot" label is removed

---

## 2. Question With .xlsx Attachment

**Steps:**
1. Create a simple `.xlsx` with two sheets (e.g., Employees and Salaries)
2. Send an email to your `+excelbot` address
3. Body: `What is the average salary?`
4. Attach the `.xlsx` file
5. Wait ~1-2 minutes

**Expected:**
- [ ] Reply arrives in the same thread
- [ ] Reply references actual data from the spreadsheet (column names, values)
- [ ] Reply answers the question using the attached data

---

## 3. Multiple Attachments

**Steps:**
1. Send an email with 2-3 `.xlsx` files attached
2. Body: `Compare the data across these files`

**Expected:**
- [ ] Reply references data from all attached spreadsheets
- [ ] No errors about missing or unreadable files

---

## 4. Large Spreadsheet

**Steps:**
1. Send an email with a `.xlsx` containing 200+ rows
2. Body: `Summarize this data`

**Expected:**
- [ ] Reply arrives (may take slightly longer)
- [ ] Reply acknowledges the data is large / was previewed
- [ ] No timeout or error

---

## 5. No Body — Subject as Question

**Steps:**
1. Send an email with a question only in the subject line
2. Subject: `What does the SUMIF function do?`
3. Leave body empty

**Expected:**
- [ ] Reply answers the question from the subject

---

## 6. Unauthorized Sender

**Steps:**
1. Send an email from an address NOT in `AUTHORIZED_USERS`
2. Body: `Can you help me?`

**Expected:**
- [ ] Reply says something like "not authorized"
- [ ] No Claude API call is made (check Cloud Run logs)

---

## 7. Duplicate Email

**Steps:**
1. Send the same email (same message ID) twice rapidly (or trigger Apps Script manually twice)

**Expected:**
- [ ] Only one reply is sent
- [ ] Second attempt is silently skipped as a duplicate

---

## 8. Non-.xlsx Attachment

**Steps:**
1. Send an email with a `.pdf` or `.csv` attachment (not `.xlsx`)
2. Body: `Analyze this file`

**Expected:**
- [ ] Reply processes the question but ignores the non-xlsx attachment
- [ ] No crash or error in the reply

---

## 9. Corrupt .xlsx Attachment

**Steps:**
1. Rename a `.txt` file to `.xlsx` and attach it
2. Body: `What's in this file?`

**Expected:**
- [ ] Reply contains a friendly error message about the file
- [ ] No internal error details leaked (no stack traces, no file paths)

---

## 10. Reply Chain

**Steps:**
1. Get a reply from ExcelBot
2. Reply to that reply with a follow-up question in the same thread
3. Body includes the quoted previous conversation

**Expected:**
- [ ] ExcelBot processes only the new question, not the quoted reply text
- [ ] Reply arrives in the same thread

---

## 11. Webhook Secret Validation

**Steps:**
1. Use `curl` to hit the `/email` endpoint with the wrong secret:
   ```
   curl -X POST https://YOUR_SERVICE_URL/email \
     -H "Content-Type: application/json" \
     -H "X-Webhook-Secret: wrong-secret" \
     -d '{"sender":"test@test.com","body":"hi","message_id":"test-1","attachments":[]}'
   ```

**Expected:**
- [ ] Response is `401 Unauthorized`

---

## 12. Health Check

**Steps:**
1. `curl https://YOUR_SERVICE_URL/`

**Expected:**
- [ ] Response: `{"status": "ok"}`

---

## Notes

_Use this space for observations, bugs, or follow-up items._

-
-
-
