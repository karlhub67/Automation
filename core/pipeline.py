"""Orchestration: ingest -> analysis -> transcript -> selection -> (render). Checkpointed so jobs resume."""
import os, json, time, traceback
from . import ingest, analysis, transcript, intent as I, select, trim, captions as CAP, sfx, render, templates

STAGES = ["ingesting", "analyzing audio", "analyzing video", "transcription", "candidate selection", "thumbnails"]

def _fp(*parts):
    import hashlib
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]

def _src_fp(meta):  # source identity: path + size + duration (+ mtime when readable)
    try: mt = os.path.getmtime(meta["path"])
    except OSError: mt = None
    return [meta.get("path"), meta.get("size_bytes"), meta.get("duration"), mt]

def _ck(pdir, name, fn, fp=None):
    """Load a checkpoint if it exists AND its fingerprint matches, else compute and save (resume after crash/restart)."""
    p = os.path.join(pdir, "ck_%s.json" % name)
    if os.path.isfile(p):
        try:
            d = json.load(open(p))
            if isinstance(d, dict) and d.get("_fp") == fp and "data" in d: return d["data"], True
        except Exception: pass
    r = fn()
    json.dump({"_fp": fp, "data": r}, open(p + ".tmp", "w"), default=lambda o: o.item() if hasattr(o, "item") else str(o)); os.replace(p + ".tmp", p)
    return r, False

def run_analysis(proj, pdir, instruction, params, job):
    src = proj["source"]["path"]
    job.stage("ingesting", 0.02)
    meta = ingest.probe(src); proj["source"].update(meta)
    ingest.check_disk(pdir, int(meta["size_bytes"] * 0.1) + (50 << 20))
    job.log("Source: %dx%d %.2f fps %s, %.1fs%s" % (meta["width"], meta["height"], meta["fps"], meta["vcodec"], meta["duration"], " (variable frame rate)" if meta["vfr"] else ""))
    if not meta["has_audio"]: job.log("WARNING: no audio stream - audio/transcript signals unavailable.")
    job.stage("analyzing audio", 0.05)
    aud, hit = _ck(pdir, "audio", lambda: analysis.analyze_audio(src, progress=lambda f: job.stage("analyzing audio", 0.05 + 0.2 * f), duration=meta["duration"]), fp=_fp("audio", _src_fp(meta))) if meta["has_audio"] else ({}, False)
    job.log("Audio %s: %d silences, %d noise-like bursts" % ("(cached)" if hit else "analyzed", len(aud.get("silences", [])), len(aud.get("bursts", []))))
    job.stage("analyzing video", 0.28)
    vis, hit = _ck(pdir, "visual", lambda: analysis.analyze_visual(src, progress=lambda f: job.stage("analyzing video", 0.28 + 0.25 * f), duration=meta["duration"]), fp=_fp("visual", _src_fp(meta)))
    job.log("Visual %s: %d scene cuts" % ("(cached)" if hit else "analyzed", len(vis["cuts"])))
    job.stage("transcription", 0.55)
    segs = proj.get("transcript")
    if not segs:
        segs = transcript.load_sidecar(src)
        if segs: job.log("Using sidecar subtitle file (%d segments)" % len(segs))
    if not segs:
        try:
            segs, hit = _ck(pdir, "transcript", lambda: transcript.transcribe(src, params.get("asr_model", "base"), params.get("language") or None, lambda f: job.stage("transcription", 0.55 + 0.25 * f)), fp=_fp("transcript", _src_fp(meta), params.get("asr_model", "base"), params.get("language") or None))
            job.log("Transcript %s: %d segments" % ("(cached)" if hit else "generated", len(segs)))
        except transcript.TranscriptUnavailable as e:
            segs = []; job.log("NO TRANSCRIPT: %s Continuing with audio/visual evidence only." % e)
    proj["transcript"] = segs
    job.stage("candidate selection", 0.82)
    it = I.parse(instruction); proj["intent"] = it
    job.log("Intent: concepts=%s terms=%s exclusions=%s" % (it["concepts"], it["terms"], it["exclusions"]))
    cands, info = select.propose(meta, aud, vis, segs, it, params)
    proj["analysis"] = dict(silences=aud.get("silences", []), bursts=aud.get("bursts", []), cuts=vis["cuts"], info=info)
    job.stage("thumbnails", 0.92)
    td = os.path.join(pdir, "thumbs"); os.makedirs(td, exist_ok=True)
    for c in cands:
        ingest.thumbnail(src, (c["start"] + c["end"]) / 2, os.path.join(td, c["id"] + ".jpg"))
        prepare_clip(proj, c, params)
    proj["clips"] = cands; proj["params"] = params; proj["instruction"] = instruction
    job.log("Proposed %d clip(s). Review, edit, then render." % len(cands))

def prepare_clip(proj, c, params=None):
    """Compute dead-air keep-plan, captions and auto SFX proposals for a clip (all editable afterwards)."""
    params = params or proj.get("params", {})
    an = proj.get("analysis", {}); segs = proj.get("transcript", [])
    in_segs = [s for s in segs if s["end"] > c["start"] and s["start"] < c["end"]]
    c["keep"] = trim.plan_keep(c["start"], c["end"], an.get("silences", []), params.get("deadair", "balanced"), in_segs, an.get("bursts", []))
    kws = proj.get("intent", {}).get("terms", []) + [h for h in sum([w.split(", ") for w in [x.split(": ")[-1] for x in c.get("why", []) if x.startswith("Transcript match")]], [])]
    c["keywords"] = [k.strip() for k in kws if k.strip()]
    c["cues"] = CAP.build_cues(in_segs, c["keep"], params.get("cap_chars", 24), params.get("cap_lines", 2))
    peak = None
    bs = [b for b in an.get("bursts", []) if c["start"] <= b["start"] <= c["end"]]
    if bs: peak = trim.remap(max(bs, key=lambda b: b["strength"])["start"], c["keep"])
    elif c.get("anchor") is not None: peak = trim.remap(c["anchor"], c["keep"])
    c["sfx"] = sfx.auto_place(trim.out_duration(c["keep"]), peak, bool(bs)) if params.get("auto_sfx") else []
    c["out_duration"] = round(trim.out_duration(c["keep"]), 2)
    if not c.get("hook_text") and in_segs: c["hook_text"] = in_segs[0]["text"]

def run_render(proj, pdir, clip_ids, opts, sfxdir, job, fp_fn=None):
    outdir = os.path.join(pdir, "exports"); os.makedirs(outdir, exist_ok=True)
    results = []
    for k, cid in enumerate(clip_ids):
        c = next((x for x in proj["clips"] if x["id"] == cid), None)
        if not c: continue
        label = "rendering %s (%d/%d)" % (cid, k + 1, len(clip_ids))
        job.stage(label, k / len(clip_ids))
        fn = "%s_%s_%s.mp4" % (os.path.splitext(os.path.basename(proj["source"]["path"]))[0], cid, opts.get("preset", "1080p60"))
        outp = os.path.join(outdir, fn)
        if getattr(job, "cancelled", False): break
        try:
            summary = render.build_and_run(job, proj["source"]["path"], proj["source"], c, [tuple(x) for x in c["keep"]], c["cues"], proj.get("caption_style", {}),
                                           proj.get("template", {}), c.get("sfx", []), sfxdir, dict(opts, keywords=c.get("keywords", [])), outp,
                                           progress=lambda f: job.stage(label, (k + f) / len(clip_ids)), log=job.log)
            summary["clip"] = cid; summary["ts"] = time.time(); summary["settings"] = dict(opts); summary["fp"] = fp_fn(proj, c) if fp_fn else None; summary["url"] = "/api/export/%s/%s" % (proj["id"], fn); summary["download_url"] = "/api/export/%s/%s/download" % (proj["id"], fn); results.append(summary)
            job.log("Rendered %s -> %s (%s, %s)" % (cid, fn, summary["rendered"], summary["encoder"]))
        except render.Cancelled:
            job.log("Render of %s cancelled; partial file removed." % cid); break
        except Exception as e:
            job.log("RENDER FAILED for %s: %s" % (cid, e)); results.append(dict(clip=cid, error=str(e)))
    proj["last_exports"] = results
    proj["export_history"] = (proj.get("export_history", []) + [r for r in results if "error" not in r])[-60:]
    if getattr(job, "cancelled", False): return
    if any("error" in r for r in results): raise ingest.MediaError("%d of %d renders failed - see log." % (sum("error" in r for r in results), len(results)))
