---
name: Visual documentation with simulated content
description: CSS diagrams with realistic simulated content are strongly preferred
  over abstract box diagrams
status: active
---

Pure CSS/HTML architecture diagrams that show positioned boxes with **simulated realistic content** (fake session cards, tab names, terminal output, filter chips, etc.) are far more effective than abstract labeled boxes or text-only trees.

**Why:** PianoMan called the ui-layer-diagram.html "so sexy" and immediately wanted it shared with UX as an exemplar. The key was that it *looked like the actual app* — you could see the layout, proportions, and relationships at a glance without needing to run the app.

**How to apply:** When documenting UI architecture, build CSS diagrams with positioned divs that simulate the real content. Include fake data that looks plausible (real session names, realistic terminal output, actual filter chip labels). Keep the dark theme matching the app. Use colored borders per component with a legend. Layer overlays with dashed borders to show z-index relationships.
