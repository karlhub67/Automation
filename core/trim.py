"""Context-aware dead-air removal. Returns 'keep' intervals (absolute source time) and time remapping."""
LEVELS = {  # level: (cut pauses longer than, keep this much of each pause)
    "off": None, "light": (1.2, 0.7), "balanced": (0.7, 0.4), "aggressive": (0.45, 0.22)}

def plan_keep(start, end, silences, level="balanced", segs=(), bursts=()):
    cfg = LEVELS.get(level)
    if not cfg: return [(start, end)]
    min_pause, keep_len = cfg
    keep, cur = [], start
    for a, b in silences:
        if b <= start or a >= end: continue
        a, b = max(a, start), min(b, end)
        if b - a < min_pause or a <= start + 0.05 or b >= end - 0.05: continue  # never trim the clip edges
        # preserve intentional pauses: after a question, or right before laughter/cheering (comic timing)
        prev = [s for s in segs if s["end"] <= a + 0.3 and s["end"] >= a - 0.6]
        if prev and prev[-1]["text"].rstrip().endswith("?"): continue
        if any(0 <= bb["start"] - b <= 1.0 for bb in bursts): continue
        h = keep_len / 2
        if a + h > cur: keep.append((cur, a + h))
        cur = b - h
    keep.append((cur, end))
    return [(round(x, 3), round(y, 3)) for x, y in keep if y - x > 0.05]

def remap(t, keep):
    """source time -> output timeline time (None if t falls in a removed gap)."""
    acc = 0.0
    for a, b in keep:
        if a - 1e-6 <= t <= b + 1e-6: return acc + (t - a)
        acc += b - a
    return None

def out_duration(keep): return sum(b - a for a, b in keep)
