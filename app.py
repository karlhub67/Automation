#!/usr/bin/env python3
"""ClipForge - local-first AI auto-clipping app. Run:  python app.py   then open http://127.0.0.1:5173"""
import os, sys, json, time, uuid, threading, shutil, traceback, copy, hashlib
from flask import Flask, request, jsonify, send_file, send_from_directory, abort
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import pipeline, ingest, sfx, templates, transcript, render, captions as CAP, trim, fonts as FONTS

ROOT = os.path.dirname(os.path.abspath(__file__))
WS = os.environ.get("CLIPFORGE_WORKSPACE", os.path.join(ROOT, "workspace"))
SFXDIR = os.path.join(WS, "sfx")
for d in (WS, os.path.join(WS, "projects"), SFXDIR, os.path.join(WS, "uploads"), os.path.join(WS, "fonts")): os.makedirs(d, exist_ok=True)
FONTS.USER_DIRS.append(os.path.join(WS, "fonts"))
app = Flask(__name__, static_folder=os.path.join(ROOT, "static"), static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 40 << 30
JOBS, LOCK = {}, threading.RLock()

class Job:
    def __init__(s, kind):
        s.id = uuid.uuid4().hex[:8]; s.kind = kind; s.status = "running"; s.stage_name = "queued"; s.progress = 0.0
        s.logs = []; s.error = None; s.t0 = time.time(); s.cancelled = False; s.proc = None; s.face_proc = None; s.key = None
    def stage(s, name, p): s.stage_name, s.progress = name, round(float(p), 3)
    def log(s, m): s.logs.append("[%5.1fs] %s" % (time.time() - s.t0, m)); print(m, flush=True)
    def cancel(s):
        s.cancelled = True
        for p in (s.proc, s.face_proc):
            if p is not None:
                try: p.terminate()
                except Exception: pass
    def public(s): return dict(id=s.id, kind=s.kind, status=s.status, stage=s.stage_name, progress=s.progress, logs=s.logs[-200:], error=s.error, human=getattr(s, "human", None), result=getattr(s, "result", None))

PROJECT_VERSION = 2
def pdir(pid): return os.path.join(WS, "projects", pid)
def project_media_dir(pid):
    d = os.path.join(pdir(pid), "media"); os.makedirs(d, exist_ok=True); return d
def _safe_basename(path, fallback="source.mp4"):
    name = os.path.basename(path or "").strip().replace(" ", "_")
    return name or fallback
def _resolve_project_source(proj):
    src = proj.get("source") or {}
    candidates = [src.get("path"), src.get("stored_path"), os.path.join(project_media_dir(proj["id"]), _safe_basename(src.get("original_path") or src.get("path")))]
    for c in candidates:
        if c and os.path.isfile(c):
            return os.path.abspath(c)
    return src.get("path") or src.get("original_path")
def load(pid, touch=True):
    p = os.path.join(pdir(pid), "project.json")
    if not os.path.isfile(p): abort(404)
    proj = json.load(open(p, encoding="utf-8"))
    changed = False
    proj.setdefault("version", PROJECT_VERSION)
    proj.setdefault("name", _safe_basename((proj.get("source") or {}).get("path"), "Untitled Project").rsplit(".", 1)[0])
    proj.setdefault("created", os.path.getmtime(p))
    if touch: proj["last_opened_at"] = time.time()
    src = proj.setdefault("source", {})
    resolved = _resolve_project_source(proj)
    if resolved and src.get("path") != resolved:
        src["path"] = resolved; changed = True
    before = json.dumps(proj.get("template"), sort_keys=True, default=str)
    proj["template"] = templates.merge(proj.get("template") or {})
    if json.dumps(proj["template"], sort_keys=True, default=str) != before: changed = True
    if changed:
        try: save(proj)
        except Exception: pass
    elif touch:
        try: _touch_project_index(proj)
        except Exception: pass
    return proj
def _touch_project_index(proj):
    # Keep project metadata in one tiny index file so listing/search remains fast even with many projects.
    idx = os.path.join(WS, "projects", "index.json")
    data = {}
    try: data = json.load(open(idx, encoding="utf-8"))
    except Exception: pass
    data[str(proj["id"])] = {"id": proj["id"], "name": proj.get("name"), "created": proj.get("created"), "saved_at": proj.get("saved_at", proj.get("created")), "last_opened_at": proj.get("last_opened_at", 0), "source_name": os.path.basename((proj.get("source") or {}).get("path", ""))}
    tmp = idx + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(data, f, indent=1)
    os.replace(tmp, idx)
def save(proj):  # atomic project save
    os.makedirs(pdir(proj["id"]), exist_ok=True)
    proj.setdefault("version", PROJECT_VERSION); proj["saved_at"] = time.time()
    p = os.path.join(pdir(proj["id"]), "project.json")
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(proj, f, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    os.replace(tmp, p)
    try: _touch_project_index(proj)
    except Exception: pass
def snapshot(proj):
    s = {k: proj.get(k) for k in ("clips", "template", "caption_style")}
    proj.setdefault("undo", []).append(copy.deepcopy(s)); proj["undo"] = proj["undo"][-40:]; proj["redo"] = []
def public(proj):
    out = {k: v for k, v in proj.items() if k not in ("undo", "redo")} | dict(can_undo=bool(proj.get("undo")), can_redo=bool(proj.get("redo")))
    src = out.setdefault("source", {})
    src["exists"] = bool(src.get("path") and os.path.isfile(src.get("path")))
    src["stored_in_project"] = bool(src.get("stored_path") and os.path.isfile(src.get("stored_path")))
    out["project_path"] = pdir(proj["id"])
    return out

def spawn(kind, fn, *a):
    j = Job(kind); JOBS[j.id] = j
    def runner():
        try:
            fn(*a, j)
            if j.cancelled: j.status = "cancelled"; j.stage("cancelled", j.progress)
            else: j.status = "done"; j.stage("done", 1.0)
        except render.Cancelled: j.status = "cancelled"; j.stage("cancelled", j.progress); j.log("Cancelled by user.")
        except Exception as e:
            j.status = "error"; j.human = "Failed during '%s': %s" % (j.stage_name, str(e).strip().splitlines()[0][:200] if str(e).strip() else type(e).__name__); j.error = "%s: %s" % (type(e).__name__, e); j.log("ERROR " + j.error); j.logs.append(traceback.format_exc()[-1200:])
    threading.Thread(target=runner, daemon=True).start()
    return j

@app.route("/")
def index(): return send_from_directory(os.path.join(ROOT, "static"), "index.html")

@app.route("/api/system")
def system():
    try: ingest.check_tools(); ff = True
    except Exception: ff = False
    hw = {}
    if ff:
        for c in ("h264", "h265", "av1"):
            try: hw[c] = render.pick_encoder(c, True)
            except Exception as ex: hw[c] = None
    try:
        import cv2
        cv = {"available": bool(hasattr(cv2, "CascadeClassifier") and hasattr(cv2, "data")),
              "module": getattr(cv2, "__file__", None), "version": getattr(cv2, "__version__", None),
              "cascade": os.path.isfile(os.path.join(getattr(cv2.data, "haarcascades", ""), "haarcascade_frontalface_default.xml")) if hasattr(cv2, "data") else False}
    except Exception as ex:
        cv = {"available": False, "module": None, "version": None, "cascade": False, "error": str(ex).splitlines()[0][:200]}
    return jsonify(ffmpeg=ff, asr=transcript.backends(), encoders=hw, presets={k: v[3] for k, v in render.PRESETS.items()}, export_presets=[dict(key=k, label=render.PRESETS[k][3], width=render.PRESETS[k][0], height=render.PRESETS[k][1], fps=render.PRESETS[k][2]) for k in render.EXPORT_PRESET_ORDER], safe=templates.SAFE, layout=templates.LAYOUT, face_tracking=cv, formats=templates.format_catalog(), default_format=templates.DEFAULT_FORMAT)

@app.route("/api/project", methods=["POST"])
def new_project():
    d = request.get_json(force=True); path = d.get("path", "").strip().strip('"')
    try: meta = ingest.probe(path)
    except ingest.MediaError as e: return jsonify(error=str(e)), 400
    pid = uuid.uuid4().hex[:8]; os.makedirs(pdir(pid), exist_ok=True); project_media_dir(pid)
    original = os.path.abspath(path); stored = None
    # Uploaded sources live inside the ClipForge workspace, so preserve a project-local copy for one-click reopening.
    if os.path.isfile(original):
        target = os.path.join(project_media_dir(pid), _safe_basename(original))
        try:
            os.link(original, target)
            stored = target
        except OSError:
            # Avoid silently spending huge amounts of disk for arbitrary local files; leave the original path as the fallback.
            stored = None
    meta = dict(meta); meta["original_path"] = original; meta["stored_path"] = stored
    if stored: meta["path"] = stored
    proj = dict(id=pid, version=PROJECT_VERSION, name=(d.get("name") or os.path.splitext(os.path.basename(original))[0]), created=time.time(), saved_at=None, last_opened_at=time.time(), source=meta, platform=d.get("platform", "instagram"), clips=[], transcript=None,
                template=templates.merge({"format": templates.DEFAULT_FORMAT}), caption_style={}, export_history=[], undo=[], redo=[], project_files=[])
    save(proj); return jsonify(public(proj))

@app.route("/api/upload", methods=["POST"])
def upload():
    f = request.files.get("file")
    if not f: return jsonify(error="No file"), 400
    name = uuid.uuid4().hex[:6] + "_" + os.path.basename(f.filename).replace(" ", "_")
    p = os.path.join(WS, "uploads", name); f.save(p); return jsonify(path=p)

@app.route("/api/projects")
def projects():
    q = (request.args.get("q") or "").strip().lower()
    out = []
    root = os.path.join(WS, "projects")
    for pid in sorted(os.listdir(root)):
        pth = os.path.join(root, pid, "project.json")
        if not os.path.isfile(pth): continue
        try:
            p = load(pid, touch=False); src = p.get("source") or {}; name = p.get("name") or os.path.basename(src.get("path", ""))
            rec = dict(id=pid, name=name, source_name=os.path.basename(src.get("path", src.get("original_path", ""))), clips=len(p.get("clips", [])), created=p.get("created"), saved_at=p.get("saved_at"), last_opened_at=p.get("last_opened_at"), source_exists=bool(src.get("path") and os.path.isfile(src.get("path"))), stored_in_project=bool(src.get("stored_path") and os.path.isfile(src.get("stored_path"))))
            hay = " ".join(str(rec[k]) for k in ("name", "source_name", "id")).lower()
            if not q or q in hay: out.append(rec)
        except Exception: pass
    out.sort(key=lambda r: (r.get("last_opened_at") or 0, r.get("saved_at") or 0), reverse=True)
    return jsonify(out)

@app.route("/api/project/<pid>/save", methods=["POST"])
def save_project(pid):
    proj = load(pid); d = request.get_json(silent=True) or {}
    if str(d.get("name", "")).strip(): proj["name"] = str(d["name"]).strip()[:120]
    src = proj.get("source") or {}
    # Explicit Save can archive an externally referenced source into the project for true one-click reopening.
    if d.get("store_source", True) and not (src.get("stored_path") and os.path.isfile(src.get("stored_path"))):
        original = src.get("path") or src.get("original_path")
        if original and os.path.isfile(original):
            target = os.path.join(project_media_dir(pid), _safe_basename(original))
            try:
                if os.path.abspath(original) != os.path.abspath(target):
                    try: os.link(original, target)
                    except OSError: shutil.copy2(original, target)
                    src["original_path"] = src.get("original_path") or os.path.abspath(original)
                    src["stored_path"] = target; src["path"] = target
                    proj["source"] = src
            except OSError: pass
    # Re-scan project-local assets so a reopened project knows which files belong to it.
    files = []
    for base, _, names in os.walk(pdir(pid)):
        for n in names:
            if n == "project.json" or n.endswith(".tmp"): continue
            full = os.path.join(base, n)
            try: files.append(os.path.relpath(full, pdir(pid)))
            except ValueError: pass
    proj["project_files"] = sorted(set(files))
    save(proj); return jsonify(public(proj))

@app.route("/api/project/<pid>/files")
def project_files(pid):
    proj = load(pid); rows=[]
    for rel in proj.get("project_files", []):
        full=os.path.join(pdir(pid), rel)
        if os.path.isfile(full): rows.append(dict(path=rel, size=os.path.getsize(full), url="/api/project/%s/file/%s" % (pid, rel.replace(os.sep, "/"))))
    return jsonify(rows)

@app.route("/api/project/<pid>/file/<path:rel>")
def project_file(pid, rel):
    full=os.path.abspath(os.path.join(pdir(pid), rel))
    if not full.startswith(os.path.abspath(pdir(pid)) + os.sep) or not os.path.isfile(full): abort(404)
    return send_file(full, conditional=True)

@app.route("/api/project/<pid>")
def get_project(pid): return jsonify(public(load(pid)))

@app.route("/api/project/<pid>/source")
def stream_source(pid):
    proj = load(pid); src = proj.get("source") or {}; path = src.get("path") or src.get("stored_path")
    if not path or not os.path.isfile(path): return jsonify(error="Source file is missing. Re-link the original video or restore the project media file."), 404
    return send_file(path, conditional=True)  # range requests -> big files stream

@app.route("/api/project/<pid>/thumb/<cid>")
def thumb(pid, cid):
    p = os.path.join(pdir(pid), "thumbs", cid + ".jpg")
    return send_file(p) if os.path.isfile(p) else abort(404)

@app.route("/api/export/<pid>/<fn>")
def export_file(pid, fn):
    """Stream an exported MP4 for inline playback/preview."""
    export_dir = os.path.abspath(os.path.join(pdir(pid), "exports"))
    return send_from_directory(export_dir, fn, conditional=True, mimetype="video/mp4")

@app.route("/api/export/<pid>/<fn>/download")
def export_download(pid, fn):
    """Force the finished MP4 to download instead of relying on the browser's download attribute."""
    export_dir = os.path.abspath(os.path.join(pdir(pid), "exports"))
    full = os.path.abspath(os.path.join(export_dir, fn))
    if not full.startswith(export_dir + os.sep) or not os.path.isfile(full):
        abort(404)
    return send_file(full, mimetype="video/mp4", as_attachment=True,
                     download_name=os.path.basename(full), conditional=True)

@app.route("/api/project/<pid>/analyze", methods=["POST"])
def analyze(pid):
    d = request.get_json(force=True); proj = load(pid)
    def work(job):
        pr = load(pid); snapshot(pr)
        pipeline.run_analysis(pr, pdir(pid), d.get("instruction", ""), d.get("params", {}), job); save(pr)
    j = spawn("analyze", work); return jsonify(j.public())

@app.route("/api/project/<pid>/render", methods=["POST"])
def render_clips(pid):
    d = request.get_json(force=True); opts = d.get("options", {}) or {}
    if opts.get("preset", "1080p60") not in render.PRESETS: return jsonify(error="Unknown export preset: %r" % (opts.get("preset"),)), 400
    if opts.get("codec", "h264") not in render.CODEC_ENC: return jsonify(error="Unknown codec: %r" % (opts.get("codec"),)), 400
    if not d.get("clips"): return jsonify(error="No clips selected to render."), 400
    def work(job):
        pr = load(pid)
        try: pipeline.run_render(pr, pdir(pid), d["clips"], opts, SFXDIR, job, fp_fn=edit_fingerprint)
        finally:
            # Always persist the results (including FAILURES), otherwise the UI would keep showing the previous successful export.
            # Re-load first so edits the user made while the export ran are not overwritten by this job's stale copy.
            fresh = load(pid, touch=False)
            for k in ("last_exports", "export_history"):
                if k in pr: fresh[k] = pr[k]
            save(fresh)
    return jsonify(spawn("render", work).public())

@app.route("/api/jobs/<jid>")
def job(jid): return jsonify(JOBS[jid].public()) if jid in JOBS else abort(404)

@app.route("/api/project/<pid>/edit", methods=["POST"])
def edit(pid):
    """Apply a user edit. Every edit is snapshotted for undo/redo and autosaved."""
    d = request.get_json(force=True); proj = load(pid); snapshot(proj)
    op = d["op"]; clips = {c["id"]: c for c in proj["clips"]}
    if op == "clip":  # patch fields of a clip: status, start, end, hook_text, locked, cues, sfx, keep
        c = clips[d["id"]]
        old_cues = copy.deepcopy(c.get("cues") or [])
        for k, v in d["patch"].items():
            if c.get("locked") and k in ("start", "end", "keep") and not d.get("force"): continue
            c[k] = v
        if "cues" in d["patch"]:
            c["cues"] = CAP.retime_edited_cues(old_cues, c.get("cues") or [])
        if "start" in d["patch"] or "end" in d["patch"]:
            c["start"], c["end"] = float(c["start"]), float(c["end"])
            if not c.get("locked_cues"):
                keep_sfx = c.get("sfx", []); pipeline.prepare_clip(proj, c); c["sfx"] = keep_sfx
    elif op == "reprepare":
        c = clips[d["id"]]; pipeline.prepare_clip(proj, c, dict(proj.get("params", {}), **d.get("params", {})))
    elif op == "bulk": [c.update(status=d["status"]) for c in proj["clips"] if not c.get("locked")]
    elif op == "merge":
        a, b = sorted([clips[d["ids"][0]], clips[d["ids"][1]]], key=lambda c: c["start"])
        a["end"] = max(a["end"], b["end"]); a["why"] = a["why"] + ["Merged with %s" % b["id"]]
        proj["clips"] = [c for c in proj["clips"] if c["id"] != b["id"]]; pipeline.prepare_clip(proj, a)
    elif op == "template":
        new = templates.merge(d["template"])
        # A client that does not know about formats must not silently reset the project's format.
        if "format" not in new and "format" in (proj.get("template") or {}): new["format"] = proj["template"]["format"]
        proj["template"] = new
    elif op == "format":  # video format (Format 1/2/3): patches ONLY template.format, leaving every other template setting untouched
        if d.get("format") not in templates.FORMAT_SPECS: return jsonify(error="Unknown video format: %r" % (d.get("format"),)), 400
        tpl = templates.merge(proj.get("template") or {}); tpl["format"] = d["format"]; proj["template"] = tpl
    elif op == "caption_style": proj["caption_style"] = d["style"]
    elif op == "platform": proj["platform"] = d["platform"]  # platform changes safe-area guidance only; base composition remains shared 9:16
    elif op == "transcript": proj["transcript"] = d["segments"]
    save(proj); return jsonify(public(proj))

@app.route("/api/project/<pid>/undo", methods=["POST"])
@app.route("/api/project/<pid>/redo", methods=["POST"])
def undo_redo(pid):
    proj = load(pid); undo = request.path.endswith("undo"); a, b = ("undo", "redo") if undo else ("redo", "undo")
    if not proj.get(a): return jsonify(public(proj))
    cur = {k: proj.get(k) for k in ("clips", "template", "caption_style")}
    prev = proj[a].pop(); proj.setdefault(b, []).append(copy.deepcopy(cur)); proj.update(prev); save(proj); return jsonify(public(proj))

@app.route("/api/project/<pid>/subtitles", methods=["POST"])
def subtitles(pid):
    f = request.files.get("file")
    if not f: return jsonify(error="No file"), 400
    segs = transcript.parse_subs(f.read().decode("utf-8", errors="replace"))
    proj = load(pid); snapshot(proj); proj["transcript"] = segs; save(proj); return jsonify(count=len(segs))

@app.route("/api/project/<pid>/asset", methods=["POST"])
def asset(pid):  # avatar / logo upload
    f = request.files.get("file"); kind = request.form.get("kind", "avatar")
    p = os.path.join(pdir(pid), "%s_%s" % (kind, os.path.basename(f.filename))); f.save(p); return jsonify(path=p)

@app.route("/api/sfx")
def sfx_list(): return jsonify(sfx.list_library(SFXDIR))
@app.route("/api/sfx/file/<name>")
def sfx_file(name): return send_from_directory(SFXDIR, name)
@app.route("/api/sfx/import", methods=["POST"])
def sfx_import():
    f = request.files.get("file"); n = os.path.basename(f.filename); f.save(os.path.join(SFXDIR, n)); return jsonify(id=n)
@app.route("/api/sfx/new", methods=["POST"])
def sfx_new(): d = request.get_json(force=True); return jsonify(sfx.new_event(d["sound"], d.get("t", 0), d.get("gain_db", -8)))

@app.route("/api/overlay_preview", methods=["POST"])
def overlay_preview():
    d = request.get_json(force=True); proj = load(d["pid"]); W, H = 540, 960
    from PIL import Image; import io
    tpl = templates.merge(d.get("template") or proj["template"]); s = proj["source"]
    x, y, w, h = templates.video_rect(W, H, s["width"], s["height"], tpl)
    tmp = os.path.join(pdir(d["pid"]), "_ov_%s.png" % uuid.uuid4().hex[:6]); templates.render_overlay(tmp, W, H, tpl, d.get("hook", ""), (s["width"], s["height"]))
    bg = Image.new("RGB", (W, H), tuple(int(tpl["background"][i:i + 2], 16) for i in (1, 3, 5))); bg.paste((52, 58, 76), (x, y, x + w, y + h))
    ov = Image.open(tmp); bg.paste(ov, (0, 0), ov); buf = io.BytesIO(); bg.save(buf, "PNG"); os.remove(tmp); buf.seek(0); return send_file(buf, mimetype="image/png")

def edit_fingerprint(proj, c):
    """Hash of everything that changes the rendered picture/sound of one clip (the single source of truth for preview + export staleness)."""
    s = proj["source"]
    tpl = proj.get("template")
    if isinstance(tpl, dict) and templates.normalize_format(tpl.get("format")) == templates.DEFAULT_FORMAT:
        tpl = {k: v for k, v in tpl.items() if k != "format"}  # default format == the pre-format composition: keep old preview cache / export freshness valid
    state = dict(src=[s.get("path"), s.get("size_bytes"), s.get("duration")], clip={k: c.get(k) for k in ("start", "end", "keep", "cues", "sfx", "hook_text", "keywords")},
                 template=tpl, caption_style=proj.get("caption_style"), v=4)
    return hashlib.sha1(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()[:12]

PREVIEW_JOBS = {}
@app.route("/api/project/<pid>/preview", methods=["POST"])
def preview_clip(pid):
    """Return a playable low-res render of the EDITED clip (same render graph as export). Cached by edit fingerprint."""
    d = request.get_json(force=True); proj = load(pid); c = next((x for x in proj["clips"] if x["id"] == d.get("clip")), None)
    if not c: return jsonify(error="Unknown clip"), 404
    # Optional "format": render the preview as if this format were applied, WITHOUT saving it. The format selector uses this to
    # prove the new format renders before committing it, so a failure leaves the project (and its last good preview) untouched.
    fmt_override = d.get("format")
    if fmt_override is not None:
        if fmt_override not in templates.FORMAT_SPECS: return jsonify(error="Unknown video format: %r" % (fmt_override,)), 400
        proj["template"] = dict(proj.get("template") or {}, format=fmt_override)
    fp = edit_fingerprint(proj, c); pd = os.path.join(pdir(pid), "previews"); os.makedirs(pd, exist_ok=True)
    fn = "%s_%s.mp4" % (c["id"], fp); outp = os.path.join(pd, fn); url = "/api/preview/%s/%s" % (pid, fn)
    if os.path.isfile(outp): return jsonify(state="ready", fp=fp, url=url)
    key = (pid, c["id"], fp)
    with LOCK:
        j = PREVIEW_JOBS.get(key)
        if j and j.status == "running": return jsonify(state="rendering", fp=fp, job=j.id)
        def work(job):
            pr = load(pid); cc = next(x for x in pr["clips"] if x["id"] == c["id"]); tmp = outp + ".part.mp4"
            if fmt_override is not None: pr["template"] = dict(pr.get("template") or {}, format=fmt_override)
            job.stage("rendering preview", 0.01)
            try:
                summary = render.build_and_run(job, pr["source"]["path"], pr["source"], cc, [tuple(x) for x in cc["keep"]], cc["cues"], pr.get("caption_style", {}), pr.get("template", {}),
                                               cc.get("sfx", []), SFXDIR, dict(preset="preview", preview=True, keywords=cc.get("keywords", [])), tmp,
                                               progress=lambda f: job.stage("rendering preview", f), log=job.log)
                job.result = {k: summary[k] for k in ("rendered", "duration", "notes", "font", "captions")}
                if job.cancelled: raise render.Cancelled()
                os.replace(tmp, outp)
            finally:
                if os.path.isfile(tmp): os.remove(tmp)
            olds = sorted([f for f in os.listdir(pd) if f.startswith(c["id"] + "_") and f.endswith(".mp4")], key=lambda f: os.path.getmtime(os.path.join(pd, f)))[:-3]
            for f in olds:
                try: os.remove(os.path.join(pd, f))
                except OSError: pass
        j = spawn("preview", work); j.key = key; PREVIEW_JOBS[key] = j
    return jsonify(state="rendering", fp=fp, job=j.id)

@app.route("/api/preview/<pid>/<fn>")
def preview_file(pid, fn): return send_from_directory(os.path.join(pdir(pid), "previews"), fn, conditional=True)

@app.route("/api/jobs/<jid>/cancel", methods=["POST"])
def job_cancel(jid):
    if jid not in JOBS: abort(404)
    JOBS[jid].cancel(); return jsonify(JOBS[jid].public())

@app.route("/api/fonts")
def fonts_list(): return jsonify(FONTS.list_names())

@app.route("/api/fonts/files")
def fonts_files():
    out = []
    for family, entries in FONTS.families().items():
        for e in entries:
            path = e.get("path")
            try:
                in_user = any(os.path.commonpath([os.path.abspath(path), os.path.abspath(d)]) == os.path.abspath(d) for d in FONTS.USER_DIRS)
            except ValueError: in_user = False
            if in_user and os.path.isfile(path): out.append(dict(family=family, style=e.get("style"), file=os.path.basename(path), url="/api/fonts/file/" + os.path.basename(path)))
    return jsonify(out)

@app.route("/api/fonts/file/<name>")
def fonts_file(name):
    for d in FONTS.USER_DIRS:
        p = os.path.join(d, os.path.basename(name))
        if os.path.isfile(p): return send_file(p, conditional=True)
    abort(404)

@app.route("/api/fonts/upload", methods=["POST"])
def fonts_upload():
    f = request.files.get("file")
    if not f or not f.filename.lower().endswith((".ttf", ".otf")): return jsonify(error="Choose a .ttf or .otf file"), 400
    f.save(os.path.join(WS, "fonts", os.path.basename(f.filename))); FONTS.families(refresh=True); return jsonify(FONTS.list_names())

@app.route("/api/project/<pid>/export_state")
def export_state(pid):
    proj = load(pid); out = {}
    for c in proj["clips"]:
        h = [e for e in proj.get("export_history", []) if e.get("clip") == c["id"] and "error" not in e]
        out[c["id"]] = dict(fp=edit_fingerprint(proj, c), last_export_fp=h[-1].get("fp") if h else None)
    return jsonify(out)

if __name__ == "__main__":
    sfx.ensure_library(SFXDIR)
    import socket
    port = int(os.environ.get("PORT", 5173))
    lan = "--lan" in sys.argv or os.environ.get("HOST") == "0.0.0.0"
    host = "0.0.0.0" if lan else "127.0.0.1"
    print("ClipForge on this computer: http://127.0.0.1:%d" % port)
    if lan:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]; s.close()
        except Exception: ip = "YOUR-PC-IP"
        print("\nPHONE MODE - open this in Chrome on your phone (same Wi-Fi):  http://%s:%d" % (ip, port))
        print("WARNING: anyone on this network can open it. Use only on a trusted Wi-Fi.\n")
    app.run(host=host, port=port, threaded=True)
