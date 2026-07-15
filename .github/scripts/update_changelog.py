"""Prepend a new release entry to CHANGELOG.md.

Called by .github/workflows/update-changelog.yml with these env vars set:
  RELEASE_TAG   - e.g. "1.02"
  RELEASE_DATE  - ISO date, e.g. "2026-08-01"
  RELEASE_BODY  - the release description written on GitHub
  REPO          - e.g. "pwernette/shoreline-surf"
"""
import os
import sys

tag  = os.environ["RELEASE_TAG"]
date = os.environ["RELEASE_DATE"][:10]   # keep YYYY-MM-DD only
body = os.environ.get("RELEASE_BODY", "").strip()
repo = os.environ["REPO"]

entry = f"## [{tag}] — {date}\n\n{body}\n\n---\n\n"
link  = f"[{tag}]: https://github.com/{repo}/releases/tag/{tag}\n"

with open("CHANGELOG.md", "r", encoding="utf-8") as f:
    content = f.read()

# Insert after the first "---\n\n" separator (end of the file header block)
marker = "---\n\n"
idx = content.find(marker)
if idx == -1:
    content = content + entry
else:
    insert_at = idx + len(marker)
    content = content[:insert_at] + entry + content[insert_at:]

# Append comparison link at the bottom if not already present
if link.strip() not in content:
    content = content.rstrip("\n") + "\n" + link + "\n"

with open("CHANGELOG.md", "w", encoding="utf-8") as f:
    f.write(content)

print(f"Prepended [{tag}] ({date}) to CHANGELOG.md")
