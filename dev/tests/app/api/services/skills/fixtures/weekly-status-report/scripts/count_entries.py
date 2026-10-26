"""Count log entries per project (helper the AI may run in its own sandbox). The server never executes this."""

import sys
from collections import Counter

counts = Counter(line.split(":", 1)[0].strip() for line in sys.stdin if ":" in line)
for project, n in counts.most_common():
    print(f"{project}\t{n}")
