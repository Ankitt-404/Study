import json
import re
from pathlib import Path

from app.search import search

K = 10
cases = json.loads((Path(__file__).parent / "tests" / "questions.json").read_text(encoding="utf-8"))


def norm(s):
    return re.sub(r"\s+", " ", s.lower())


ranks = []
for c in cases:
    rank = None
    for i, r in enumerate(search(c["question"], None, K), 1):
        text = norm(r["content"])
        if all(norm(t) in text for t in c["must_contain"]):
            rank = i
            break
    ranks.append(rank)
    print(f"[{rank if rank else 'MISS':>4}] {c['question']}")

n = len(ranks)
print()
for k in (1, 3, 5):
    print(f"Hit@{k}: {sum(1 for r in ranks if r and r <= k)}/{n}")
print(f"MRR: {sum(1 / r for r in ranks if r) / n:.3f}")