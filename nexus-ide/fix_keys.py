# -*- coding: utf-8 -*-
file_path = r"frontend\components\chat\MessageBubble.tsx"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# Fix the Object.entries key issue - use index in addition to key for uniqueness
old = '            {Object.entries(message.metrics).map(([k, v]) => (\n              <span\n                key={k}\n                className="rounded-lg bg-nexus-bg/80 px-2.5 py-1 backdrop-blur-sm"\n              >\n                {k}: {v}\n              </span>\n            ))}'
new = '            {Object.entries(message.metrics).map(([k, v], idx) => (\n              <span\n                key={`${idx}-${k}`}\n                className="rounded-lg bg-nexus-bg/80 px-2.5 py-1 backdrop-blur-sm"\n              >\n                {k}: {v}\n              </span>\n            ))}'

if old in content:
    content = content.replace(old, new)
    print("FIXED metrics map")
else:
    print("OLD NOT FOUND")

# Also check for any other potential duplicate-key issues with `key={k}` in same file
import re
matches = re.findall(r'key=\{[a-zA-Z]+\}(?![\w-]*-[a-zA-Z])', content)
print(f"Other key patterns found: {len(matches)}")

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)
print("DONE")