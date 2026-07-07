# VBA Refactoring - Gemini Workflow

## Files Created

| File | Purpose |
|------|---------|
| `bin/python/src/ai_utils/gemini_prepare_upload.py` | Combine VBA files for Gemini |
| `bin/python/src/ai_utils/gemini_parse_response.py` | Extract refactored code from response |
| `ai_general/prompts/gemini_vba_analysis_prompts.md` | Analysis prompt templates |
| `ai_general/tmp/vba_for_gemini.txt` | Pre-generated combined file |

## Quick Workflow

### Step 1: Prepare (already done)
```bash
# Combined file already at:
# ~/AI/ai_root/ai_general/tmp/vba_for_gemini.txt
# 59 files, 36K lines, ~343K tokens (34% of 1M capacity)
```

### Step 2: Upload to Gemini
1. Open Gemini (gemini.google.com or AI Studio)
2. Attach `vba_for_gemini.txt`
3. Copy prompt from `gemini_vba_analysis_prompts.md`

### Step 3: Get Analysis
Ask Gemini to analyze. Start with Prompt 1 (Dependency Chain Analysis).

### Step 4: Apply Refactoring
If Gemini provides refactored code:
```bash
# Save Gemini's response to a file
# Then parse it:
python3 ~/bin/python/src/ai_utils/gemini_parse_response.py response.txt -o ./refactored/

# Compare with originals
diff -r original/ refactored/
```

## What Gemini Should Find

Based on our analysis, expect Gemini to identify:

### 1. Duplicates
- mod_ContainerUtils vs mod_Collections overlap
- Possibly mod_Comparisons variations

### 2. Inline Candidates (used by Cell/Row/Table)
From mod_IsValid:
- `IsEmpty` wrapper → inline VBA's IsEmpty
- `IsNull` wrapper → inline
- Simple type checks

From mod_Misc:
- Small utility functions

### 3. Wrong-Layer Dependencies
- Cell.cls → mod_RangeMethods (Cell is data, not Excel)
- Row.cls → mod_RangeMethods (same issue)
- Cell/Row/Table → mod_ErrorHandling (should just Raise)

### 4. Consolidation Opportunities
- mod_Collections + parts of mod_ContainerUtils → unified container utils
- mod_Comparisons cleanup

## Alternative: Browser Automation

If you want Claude to drive Gemini directly:

```bash
# We have Puppeteer available
# Could create script to:
# 1. Open Gemini
# 2. Upload file
# 3. Submit prompt
# 4. Capture response

# But manual is probably fine for one-off analysis
```

## Next Steps

1. **Upload to Gemini** - Use the pre-generated `vba_for_gemini.txt`
2. **Run Prompt 1** - Get dependency analysis
3. **Review findings** - Compare with our Python analysis
4. **Decide actions** - Which refactorings to apply
5. **Test after each change** - Run mod_Tests.Test_* procedures
