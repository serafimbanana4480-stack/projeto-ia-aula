r"""ARCHIVED, NEUTRALISED. DO NOT RUN.

Originally: frontend/fix_jsx.py
Archived:   2026-09-26, per AGENTS.md rule 1 (nothing is deleted; history goes
            to archive/).

What it was
-----------
A one-off codemod that restored a lost `<` in JSX closing tags
(`}CardEmpty>` -> `</CardEmpty>`) in exactly one file, using this hardcoded
absolute path:

    C:/Users/rodri/Desktop/nexus/nexus-ide/frontend/components/dashboard/MissionPanel.tsx

and then wrote the result back over that source file in place.

Why it was dangerous
--------------------
1. Machine-specific: an absolute `C:/Users/rodri/...` path, so it cannot work on
   any other machine or in CI.
2. It MUTATES a source file. Line 25 reopens the same path in write mode. A
   codemod that someone might run "to see what it does" would silently rewrite
   MissionPanel.tsx -- irreversibly, with no diff shown first and no backup.
3. It was committed, so it was one `python fix_jsx.py` away from firing in a
   clone. AGENTS.md rule 2 exists precisely because agents write .py into the
   tree and a stray script in the tree is a stray mutation waiting to happen.
4. It was not idempotent-safe: running it twice on already-fixed source is
   harmless, but running it on a *different* MissionPanel.tsx version (another
   agent mid-edit) would rewrite that instead.

What this file is now
---------------------
The original source is preserved verbatim below the guard, for history only.
Execution is impossible: importing or running this module raises immediately.
To actually perform this rewrite again, write a fresh, reviewable codemod that
takes the target path as an argument, prints a unified diff, and requires an
explicit --write flag. Do not restore this file to a runnable state.

----- ORIGINAL SOURCE (inert, never executed) -----

import re

path = r'C:/Users/rodri/Desktop/nexus/nexus-ide/frontend/components/dashboard/MissionPanel.tsx'
with open(path, encoding='utf-8') as f:
    src = f.read()

# Restore opening < before /tag> when we lost it.
# Pattern: ...}/CardEmpty>  -> ...</CardEmpty>
# Generic: {X</tag>  -> should be {X</tag>  (already done)
# But we may have broken ones: {X}/tag>  -> {X</tag>

# Match: }/tagname>
pat = re.compile(r'\}/([A-Za-z]+)>')
matches = list(pat.finditer(src))
print('matches with }/tag>:', len(matches))
for m in matches[:20]:
    print(repr(m.group(0)))

def fix(match):
    tag = match.group(1)
    return '</' + tag + '>'

new = pat.sub(fix, src)
print('changed:', src != new)
with open(path, 'w', encoding='utf-8') as f:
    f.write(new)

remaining = re.findall(r'\}/[A-Za-z]+>', new)
print('remaining:', len(remaining))
"""

from __future__ import annotations

_MESSAGE = (
    "archive/codemods/fix_jsx.py is an archived, neutralised codemod. "
    "It is preserved for history only and MUST NOT be run: the original "
    "rewrote components/dashboard/MissionPanel.tsx in place via a hardcoded "
    "absolute path. See this module's docstring for how to write a safe "
    "replacement."
)

raise RuntimeError(_MESSAGE)
