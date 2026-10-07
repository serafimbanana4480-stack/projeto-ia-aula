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
