"""Turns a natural-language request into an internal intent representation.
Rule/lexicon based (no LLM required): concepts, literal topic terms, exclusions, duration preferences."""
import re

LEX = {
 "happy": "happy joy joyful love loved amazing awesome great wonderful excited exciting congrats congratulations yay proud thank thanks best fun celebrate celebration incredible beautiful win won winning finally smile laugh blessed grateful amazing perfect enjoy".split(),
 "funny": "funny joke jokes hilarious lol haha hahaha laugh laughing crazy ridiculous kidding silly weird random roast".split(),
 "money": "money dollar dollars peso pesos price pay paid salary income invest investing investment profit cash budget rich cost million billion business sales revenue savings save earn earning wealth".split(),
 "emotional": "cry cried crying tears hurt miss grief struggle struggled pain heart feel feeling emotional lonely scared fear vulnerable healing trauma loss".split(),
 "surprising": "wow surprise surprised unexpected shocking shocked unbelievable suddenly twist secret nobody never actually insane".split(),
 "story": "remember once story stories happened childhood grew years ago when i was one day then".split(),
 "insight": "learn learned realize realized truth lesson mindset key important understand know yourself purpose identity growth".split(),
}
CONCEPT_ALIASES = {
 "happy": ["happy", "happiest", "joy", "uplifting", "positive", "celebrat", "excited", "wholesome", "good moments", "good vibes"],
 "funny": ["funny", "funniest", "humor", "hilarious", "laugh", "comedic", "reaction"],
 "money": ["money", "financ", "invest", "salary", "income", "business", "wealth", "price"],
 "emotional": ["emotional", "touching", "sad", "cry", "vulnerable", "heartfelt", "deep"],
 "surprising": ["surpris", "shock", "unexpected", "twist", "wow"],
 "story": ["story", "stories", "storytelling", "anecdote"],
 "insight": ["insight", "advice", "lesson", "wisdom", "quote", "motivat", "inspir", "best moments", "strongest", "key point"],
}
STOP = set("choose find pick select the a an of in on at to for and or only keep moments moment clips clip parts part where when speaker talks talk talking about discusses discuss that this those these with from is are be best most strongest second seconds sec minute minutes long short give me please show all any some top number just".split())
NEG_WORDS = {"not", "no", "never", "don't", "dont", "isn't", "isnt", "wasn't", "wasnt", "can't", "cant", "without", "hardly"}
SARCASM = ("yeah right", "as if", "sure,", "oh great", "just great", "whatever")

def parse(text):
    t = (text or "").lower().strip()
    intent = dict(raw=text, concepts=[], terms=[], exclusions=[], target=None, min=None, max=None, teaser=False)
    for c, al in CONCEPT_ALIASES.items():
        if any(a in t for a in al): intent["concepts"].append(c)
    # exclusions
    m = re.search(r"\b(?:except|exclude|excluding|without|avoid|not about|no)\b\s+(.*)$", t)
    if m:
        intent["exclusions"] = [w for w in re.findall(r"[a-z']{3,}", m.group(1)) if w not in STOP]
        t_pos = t[:m.start()]
    else: t_pos = t
    # durations
    m = re.search(r"(\d+)\s*(?:-|–|to)\s*(\d+)\s*(?:s|sec|secs|seconds?)", t)
    if m: intent["min"], intent["max"] = float(m.group(1)), float(m.group(2)); intent["target"] = (intent["min"] + intent["max"]) / 2
    else:
        m = re.search(r"(?:under|below|less than|max(?:imum)?)\s*(\d+)\s*(s|sec|seconds?|min|minutes?)", t)
        if m:
            v = float(m.group(1)) * (60 if m.group(2).startswith("m") else 1); intent["max"] = v
        m = re.search(r"(\d+)\s*(?:s|sec|seconds?)\b", t)
        if m and not intent["max"]: intent["target"] = float(m.group(1))
    if "teaser" in t or "cliffhanger" in t: intent["teaser"] = True
    # literal topic terms (anything not a stop word / concept keyword)
    words = re.findall(r"[a-z']{3,}", t_pos)
    cw = {x for al in CONCEPT_ALIASES.values() for x in al}
    for w in words:
        if w in STOP or any(w.startswith(c) or c.startswith(w) for c in cw if len(c) > 3): continue
        intent["terms"].append(w)
    if not intent["concepts"] and not intent["terms"]: intent["concepts"] = ["insight"]  # "best moments" default
    return intent

def lexicon(intent):
    w = {}
    for c in intent["concepts"]:
        for x in LEX[c]: w[x] = max(w.get(x, 0), 1.0)
    for x in intent["terms"]:
        w[x] = 2.5
        if len(x) > 4: w[x.rstrip("s")] = 2.5
    return w

def score_text(text, lex, exclusions=()):
    """Context-aware text relevance in [0, ~1]. Negated / sarcastic positives do not count."""
    low = text.lower()
    toks = re.findall(r"[a-z']+|\$|\d+", low)
    sc, hits = 0.0, []
    for i, tk in enumerate(toks):
        wt = lex.get(tk) or lex.get(tk.rstrip("s")) or 0
        if not wt: continue
        if any(n in NEG_WORDS for n in toks[max(0, i - 3):i]): continue  # negation -> skip
        sc += wt; hits.append(tk)
    if any(s in low for s in SARCASM): sc *= 0.3
    if any(e in toks for e in exclusions): sc *= 0.2
    if "!" in text: sc *= 1.1
    return min(1.0, sc / 4.0), hits
