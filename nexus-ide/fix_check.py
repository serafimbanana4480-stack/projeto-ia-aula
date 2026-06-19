# -*- coding: utf-8 -*-
file_path = r"check_thinking.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# Replace the bad function signature
content = content.replace("def req(path, method=\"GET\", data=None, token=***, timeout=60):", "def req(path, method=\"GET\", data=None, token=***, timeout=60):")

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)
print("Fixed")