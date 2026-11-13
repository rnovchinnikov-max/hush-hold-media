"""Point an existing nginx site (the autoreply bot) at the website, keeping the bot's own paths.

Usage: python3 nginx_patch.py /etc/nginx/sites-available/hush-autoreply
- inserts `include snippets/hush-autoreply-paths.conf;` before every `location / {`
- inside every `location / { ... }` switches proxy_pass 127.0.0.1:8000 -> 127.0.0.1:8010
- raises client_max_body_size to 12m for picture uploads
Idempotent: running twice changes nothing.
"""
import re
import sys

path = sys.argv[1]
src = open(path).read()
out = src.replace("client_max_body_size 2m;", "client_max_body_size 12m;")

INC = "include snippets/hush-autoreply-paths.conf;"
res, i = [], 0
for m in re.finditer(r"location\s+/\s*\{", out):
    start = m.start()
    # find the matching closing brace of this location block
    depth, j = 0, m.end() - 1
    while j < len(out):
        if out[j] == "{":
            depth += 1
        elif out[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    block = out[start:j + 1].replace("proxy_pass http://127.0.0.1:8000;", "proxy_pass http://127.0.0.1:8010;")
    before = out[i:start]
    indent = re.search(r"([ \t]*)$", before).group(1)
    if INC not in before[-200:]:
        before = before + INC + "\n" + indent
    res.append(before + block)
    i = j + 1
res.append(out[i:])
new = "".join(res)
if new != src:
    open(path, "w").write(new)
    print("nginx: сайт подключён к", path)
else:
    print("nginx: уже настроено")
