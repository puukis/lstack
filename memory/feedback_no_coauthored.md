---
name: feedback-no-coauthored-by
description: Never add Co-Authored-By Claude lines to git commits
metadata:
  type: feedback
---

Never include "Co-Authored-By: Claude" (or any variant) in git commit messages.

**Why:** User explicitly rejected this — does not want Claude authorship attributed in commits.

**How to apply:** All git commits must be plain messages with no Co-Authored-By trailer of any kind.
