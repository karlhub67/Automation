"""Caption cues -> ASS with individual-word fade and editable top on-screen text layers."""
import re
from .trim import remap

def build_cues(segs, keep, max_chars=24, max_lines=2, keywords=()):
    words = []
    for s in segs:
        for w in s.get("words", []):
            ts, te = remap(w["start"], keep), remap(w["end"], keep)
            if ts is None or te is None: continue
            words.append((w["w"], ts, max(te, ts + 0.05)))
    cues, cur = [], []
    limit = max_chars * max_lines
    def flush():
        if cur:
            cues.append(dict(start=round(cur[0][1], 2), end=round(cur[-1][2], 2), text=" ".join(x[0] for x in cur),
                             words=[[x[0], round(x[1], 3), round(x[2], 3)] for x in cur], words_status="fresh"))
    for w in words:
        txt = " ".join(x[0] for x in cur + [w])
        gap = cur and w[1] - cur[-1][2] > 0.8
        if cur and (len(txt) > limit or gap): flush(); cur.clear()
        cur.append(w)
        if re.search(r"[.!?]$", w[0]) and len(" ".join(x[0] for x in cur)) > limit * 0.5: flush(); cur.clear()
    flush()
    for i in range(len(cues) - 1):
        if cues[i]["end"] > cues[i + 1]["start"]: cues[i]["end"] = cues[i + 1]["start"]
    return cues

def retime_edited_cues(old_cues, new_cues):
    """Preserve word timing when a manual cue edit remains structurally reliable.

    If the edited cue has the same number of words, word offsets are scaled into the new
    cue interval and word text is replaced with the edited tokens. Otherwise the cue is
    marked stale so the renderer will use cue-level animation rather than claiming exact timing.
    """
    import math
    out = []
    for i, nc in enumerate(new_cues or []):
        n = dict(nc)
        oc = old_cues[i] if i < len(old_cues or []) else None
        old_words = (oc or {}).get("words") or []
        toks = (n.get("text") or "").split()
        if old_words and len(old_words) == len(toks) and float(n.get("end", 0)) > float(n.get("start", 0)):
            os_, oe = float((oc or {}).get("start", 0)), float((oc or {}).get("end", 0))
            ns, ne = float(n.get("start", 0)), float(n.get("end", 0))
            if oe > os_:
                span = oe - os_; newspan = ne - ns
                words = []
                for j, ow in enumerate(old_words):
                    a = (float(ow[1]) - os_) / span
                    b = (float(ow[2]) - os_) / span
                    a = max(0.0, min(1.0, a)); b = max(a, min(1.0, b))
                    words.append([toks[j], round(ns + a * newspan, 3), round(max(ns + a * newspan + 0.05, ns + b * newspan), 3)])
                n["words"] = words; n["words_status"] = "fresh"
        elif "words" in n:
            n["words_status"] = "stale"
        out.append(n)
    return out

def _t(x):
    x = max(0, x); h, m, s = int(x // 3600), int(x % 3600 // 60), x % 60
    return "%d:%02d:%05.2f" % (h, m, s)

def _bgr(hexcol, alpha=0):
    h = (hexcol or "#FFFFFF").lstrip("#"); h = (h + "FFFFFF")[:6]
    r, g, b = h[0:2], h[2:4], h[4:6]
    return "&H%02X%s%s%s" % (alpha, b, g, r)

def _wrap_words(words, max_chars, max_lines):
    lines, cur, n = [], [], 0
    for i, w in enumerate(words):
        if cur and n + 1 + len(w) > max_chars: lines.append(cur); cur, n = [], 0
        n += (1 if cur else 0) + len(w); cur.append(i)
    if cur: lines.append(cur)
    return lines[:max(1, int(max_lines))]

def _style_header(name, family, H, style):
    fs = max(1, int(H * style.get("size", 0.045))); ol = max(0, int(H * style.get("outline", 0.004))); sh = max(0, int(H * style.get("shadow", 0.002)))
    al = {"left": 1, "center": 2, "right": 3}.get(style.get("align", "center"), 2)
    border = 3 if style.get("box") else 1
    back = _bgr(style.get("box_color", "#000000"), 0x40 if style.get("box") else 0x80)
    outc = back if style.get("box") else _bgr(style.get("outline_color", "#000000"))
    vals = [name, family, fs, _bgr(style.get("color", "#FFFFFF")), _bgr(style.get("color", "#FFFFFF")), outc, back, -1 if style.get("bold", True) else 0, 0, 0, 0, 100, 100, 0, 0, border, ol, sh, al, 0, 0, max(1, int(H * (1 - float(style.get("pos_y", 0.8))))), 1]
    return "Style: " + ",".join(map(str, vals))

def write_ass(path, cues, W, H, style, keywords=(), font_family=None):
    st = dict(font="Poppins", size=0.045, bold=True, color="#FFFFFF", outline_color="#000000", outline=0.004, shadow=0.002,
              align="center", pos_x=0.50, pos_y=0.80, box=False, box_color="#000000", fade_in=120, fade_out=120,
              max_chars=24, max_lines=2, emphasis=True, emph_color="#FFD43B", margin_x=0.08, word_fade=True, fade_in_on=True)
    st.update(style or {})
    fam = font_family or st["font"]
    hdr = ("[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
           "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
           "%s\n\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n") % (W, H, _style_header("Cap", fam, H, st))
    kw = {k.lower() for k in keywords}
    # Caption Fade In master switch (default ON for projects saved before the toggle existed). OFF = no word-by-word reveal and no \\fad tag at all.
    fade_on = st.get("fade_in_on", True) is not False
    stats = dict(word_cues=0, fallback_cues=0, instant_cues=0, fade_in=fade_on)
    x = max(0, min(W, int(float(st.get("pos_x", 0.50)) * W))); y = max(0, min(H, int(float(st.get("pos_y", 0.80)) * H)))
    an = {"left": 1, "center": 2, "right": 3}[st.get("align", "center")]
    def clr(w): return _bgr(st["emph_color"]) if st["emphasis"] and kw and w.lower().strip(".,!?'\"") in kw else _bgr(st["color"])
    lines = []
    for c in cues:
        if c.get("deleted"): continue
        text = c.get("text", "").replace("{", "(").replace("}", ")"); toks = text.split(); ws = c.get("words")
        ok = bool(fade_on and st["word_fade"] and c.get("words_status", "fresh") == "fresh" and ws and len(ws) == len(toks) and [w[0].replace("{", "(").replace("}", ")") for w in ws] == toks)
        prefix = "{\\an%d\\pos(%d,%d)}" % (an, x, y)
        if ok:
            stats["word_cues"] += 1; fade = max(10, int(st["fade_in"])); cs = c["start"]; body = []
            for ln in _wrap_words(toks, int(st["max_chars"]), int(st["max_lines"])):
                parts = []
                for i in ln:
                    t0 = int(max(0.0, ws[i][1] - cs) * 1000)
                    parts.append("{\\alpha&HFF&\\c%s\\t(%d,%d,\\alpha&H00&)}%s" % (clr(toks[i]), t0, t0 + fade, toks[i]))
                body.append(" ".join(parts))
            lines.append("Dialogue: 0,%s,%s,Cap,,0,0,0,,%s%s" % (_t(c["start"]), _t(c["end"]), prefix, "\\N".join(body)))
        elif not fade_on:
            stats["instant_cues"] += 1
            body = [" ".join(("{\\c%s}%s" % (clr(toks[i]), toks[i])) for i in ln) for ln in _wrap_words(toks, int(st["max_chars"]), int(st["max_lines"]))]
            lines.append("Dialogue: 0,%s,%s,Cap,,0,0,0,,%s%s" % (_t(c["start"]), _t(c["end"]), prefix, "\\N".join(body)))
        else:
            stats["fallback_cues"] += 1
            body = [" ".join(("{\\c%s}%s" % (clr(toks[i]), toks[i])) for i in ln) for ln in _wrap_words(toks, int(st["max_chars"]), int(st["max_lines"]))]
            lines.append("Dialogue: 0,%s,%s,Cap,,0,0,0,,%s{\\fad(%d,%d)}%s" % (_t(c["start"]), _t(c["end"]), prefix, int(st["fade_in"]), int(st["fade_out"]), "\\N".join(body)))
    open(path, "w", encoding="utf-8").write(hdr + "\n".join(lines) + "\n")
    return stats

def write_top_ass(path, layers, duration, W, H, font_map=None):
    """Write persistent on-screen text layers. Each layer is independent and uses normalized x/y."""
    font_map = font_map or {}; usable = []
    for i, layer in enumerate(layers or []):
        if not layer.get("enabled", True) or not (layer.get("text") or "").strip(): continue
        st = dict(font="Poppins", size=0.04, color="#FFFFFF", bold=True, align="center", outline=0.002, outline_color="#000000", shadow=0.002)
        st.update(layer); fam = font_map.get(layer.get("font"), layer.get("font") or "Poppins"); name = "Top%d" % i
        usable.append((name, fam, st))
    hdr = ("[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
           "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n") % (W, H)
    styles, events = [], []
    for name, fam, st in usable:
        styles.append(_style_header(name, fam, H, st))
        an = {"left": 1, "center": 2, "right": 3}.get(st.get("align", "center"), 2)
        x = max(0, min(W, int(float(st.get("x", 0.50)) * W))); y = max(0, min(H, int(float(st.get("y", 0.11)) * H)))
        text = (st.get("text") or "").replace("{", "(").replace("}", ")")
        # ASS can wrap long top lines naturally, while keeping the layer at the user-selected anchor.
        prefix = "{\\an%d\\pos(%d,%d)}" % (an, x, y)
        events.append("Dialogue: 10,0:00:00.00,%s,%s,,0,0,0,,%s%s" % (_t(duration), name, prefix, text.replace("\n", "\\N")))
    body = hdr + "\n".join(styles) + "\n\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n" + "\n".join(events) + "\n"
    open(path, "w", encoding="utf-8").write(body)
    return len(usable)
