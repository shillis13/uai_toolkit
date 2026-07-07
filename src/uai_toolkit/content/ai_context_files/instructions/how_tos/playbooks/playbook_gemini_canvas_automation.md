# Gemini Canvas Automation Playbook

## Metadata

| Field | Value |
|-------|-------|
| Version | 1.1.0 |
| Created | 2025-12-19 |
| Updated | 2025-12-19 |
| Author | PianoMan + Claude |
| Status | validated |
| Tags | gemini, canvas, automation, browser, download, artifacts |

## Summary

End-to-end automation for Gemini Canvas workflows: new chat → enable Canvas → upload file (optional) → send prompt → download artifacts.

Canvas uses Monaco editor (VS Code's editor) - NOT HTML5 canvas. Artifacts appear as "Open" buttons that launch side panel editor.

## When to Use

- Automating code generation workflows in Gemini
- Batch downloading Canvas artifacts with filters
- Integrating Gemini Canvas into AI orchestration pipelines
- When you need programmatic access to Gemini-generated code

## Prerequisites

**Browser:**
- Google Chrome with active Gemini session (logged in)
- "Allow JavaScript from Apple Events" enabled (View > Developer menu)
- Gemini tab visible and active

**Tools:**
- cliclick: `brew install cliclick`
- Desktop Commander MCP (for Claude orchestration)

**Scripts:**

| Location | Scripts |
|----------|---------|
| ~/AI/ai_root/ai_general/scripts/gemini_chat/ | gemini_download_canvas_filtered.js, gemini_list_files.js |
| ~/bin/applescript/ | gemini_canvas_enable.scpt, gemini_file_upload.scpt, gemini_drag_drop_upload.scpt |

## Steps

### 1. Navigate to New Chat

**Action:** Open fresh Gemini chat

**Example:**
```bash
osascript -e 'tell application "Google Chrome" to set URL of active tab of front window to "https://gemini.google.com/app"'
```

**Wait:** 2 seconds for page load

---

### 2. Enable Canvas Mode

**Action:** Enable Canvas via keyboard navigation (Tab×4 to reach Canvas in Tools menu)

**Example:**
```bash
osascript ~/bin/applescript/gemini_canvas_enable.scpt
```

**Rule:** Focus must be on input field first. Menu order is: Deep Research, Videos, Images, Canvas (4th item).

**Verification:** Canvas panel appears on right side of screen.

---

### 3. Upload File (Optional)

**Action:** Attach file to prompt if needed

**Example (file picker method):**
```bash
osascript ~/bin/applescript/gemini_file_upload.scpt "/path/to/your/file.pdf"
```

**Example (drag-drop method):**
```bash
osascript ~/bin/applescript/gemini_drag_drop_upload.scpt "/path/to/your/file.pdf"
```

**Wait:** 2-5 seconds for upload to complete

**Verification:** File appears attached in input area

---

### 4. Send Prompt

**Action:** Type prompt requesting code artifacts and send

**Example:**
```applescript
tell application "System Events"
    keystroke "Create a Python script that..."
    delay 0.3
    keystroke return
end tell
```

**Wait:** 5-15 seconds depending on complexity

---

### 5. Download Artifacts

**Action:** Download Canvas artifacts with optional filters

**Example:**
```javascript
// In Chrome console or via AppleScript injection
window.GEMINI_CANVAS_CONFIG = { extFilter: '.py' };
// Then execute gemini_download_canvas_filtered.js
```

**Rule:** Check `window.GEMINI_CANVAS_RESULTS` for download status and any errors.


## Filter Options

| Option | Type | Example | Description |
|--------|------|---------|-------------|
| extFilter | string/array | `".py"` or `[".py", ".js"]` | Filter by detected file extension |
| nameFilter | string | `"fibonacci"` | Partial match on title or code content |
| newest | integer | `3` | Only N most recent artifacts |
| oldest | integer | `2` | Only N oldest artifacts |
| dryRun | boolean | `true` | List matches without downloading |
| delayMs | integer | `800` | Milliseconds between artifact processing |

## Monitoring Commands

```javascript
// Check for Canvas artifacts
document.querySelectorAll('button').forEach(b => { 
  if(b.textContent.includes('Open')) console.log('Found:', b); 
});

// View download results
console.log(JSON.stringify(window.GEMINI_CANVAS_RESULTS, null, 2));

// List detected artifacts without downloading
window.GEMINI_CANVAS_CONFIG = { dryRun: true };
```

## Common Issues

### Canvas Not Enabling

**Symptom:** Canvas panel doesn't appear after keyboard sequence

**Causes:**
- Wrong tab count (must be exactly 4 tabs after Tools menu opens)
- Focus not on input field before starting
- Tools menu didn't open (timing issue)

**Fix:** Verify input focused first. Increase delays between keystrokes. Try manually once to verify menu order hasn't changed.

---

### No Artifacts Found

**Symptom:** Script returns empty artifacts array

**Causes:**
- Canvas not enabled for this chat
- Gemini put code inline instead of Canvas
- Response still generating

**Fix:** Check for "Open" buttons in chat. Use gemini_download_filtered.js for inline code. Wait longer before running download.

---

### Wrong Extension Detected

**Symptom:** .js file saved as .txt

**Causes:**
- Detection patterns didn't match
- Minified or unusual code format

**Fix:** Check detection logic in script. Use nameFilter instead of extFilter. Download all then rename manually.


## Canvas vs Inline Code

Gemini outputs code two ways - know which you're dealing with:

| Type | Appearance | Download Script | When Used |
|------|------------|-----------------|-----------|
| Canvas | "Open" button, Monaco editor panel | gemini_download_canvas_filtered.js | Multi-file, complex code, Canvas enabled |
| Inline | Code block in chat message | gemini_download_filtered.js | Simple snippets, Canvas not enabled |

## Example Deployment

**Full workflow via AppleScript:**
```bash
# 1. New chat
osascript -e 'tell application "Google Chrome" to set URL of active tab of front window to "https://gemini.google.com/app"'
sleep 2

# 2. Enable Canvas
osascript ~/bin/applescript/gemini_canvas_enable.scpt
sleep 1

# 3. Upload file (optional)
osascript ~/bin/applescript/gemini_file_upload.scpt "/path/to/input.pdf"
sleep 3

# 4. Send prompt
osascript -e 'tell application "System Events" to keystroke "Analyze this and create Python scripts"'
osascript -e 'tell application "System Events" to keystroke return'
sleep 10

# 5. Download Python artifacts
osascript -e 'tell application "Google Chrome" to execute active tab of front window javascript "window.GEMINI_CANVAS_CONFIG = { extFilter: \".py\" };"'
# Load and execute download script...
```

## Automation Backend Preference

When automating Gemini (or other AI platforms), prefer backends in this order:

1. **AppleScript** - Most reliable for macOS, direct keystroke injection, works with System Events
2. **Playwright** - Modern, cross-platform, better than Puppeteer for most use cases
3. **Puppeteer** - Still works but Playwright preferred for new development

AppleScript is preferred because it:
- Works at the OS level (not sandboxed in browser)
- Can interact with any application (Chrome, Finder, etc.)
- Integrates with Claude via Desktop Commander's `osascript` execution
- Handles keyboard sequences that browser-based tools struggle with

## Related Docs

- ai_general/scripts/gemini_chat/README.md
- ai_general/docs/60_playbooks/cli_browser_automation_guide.md
- ai_general/docs/60_playbooks/playbook.chatgpt_browser_automation.md (ChatGPT equivalent)

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.2.0 | 2026-01-03 | Added automation backend preference section, linked ChatGPT playbook |
| 1.1.0 | 2025-12-19 | Added file upload step with file picker and drag-drop methods |
| 1.0.0 | 2025-12-19 | Initial playbook from validated end-to-end test |
