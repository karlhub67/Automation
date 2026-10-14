"""Real FFmpeg rendering: edited timeline -> shared 9:16 composition -> overlays/captions -> audio -> encode."""
import os, re, subprocess, shutil, tempfile
import numpy as np
from . import templates, captions as CAP, fonts as FONTS
from .ingest import MediaError

PRESETS = {
    "preview": (540, 960, 24, "Preview 540x960 24fps"),
    "1080p30": (1080, 1920, 30, "1080p 30 FPS"),
    "1080p60": (1080, 1920, 60, "1080p 60 FPS"),
    "2k60": (1440, 2560, 60, "2K 60 FPS"),
    "4k60": (2160, 3840, 60, "4K 60 FPS"),
    "1080p120": (1080, 1920, 120, "1080p 120 FPS"),
}
EXPORT_PRESET_ORDER = [k for k in PRESETS if k != "preview"]   # what the Export dropdown offers, in this order
CODEC_ENC = {"h264": ["h264_nvenc", "h264_qsv", "h264_amf", "libx264"], "h265": ["hevc_nvenc", "hevc_qsv", "hevc_amf", "libx265"],
             "av1": ["av1_nvenc", "av1_qsv", "av1_amf", "libsvtav1", "libaom-av1"]}
HW_MARKERS = ("nvenc", "qsv", "amf")
_enc_list_cache = {}
_hw_probe_cache = {}

class Cancelled(Exception): pass

def is_hw(enc): return any(x in enc for x in HW_MARKERS)

def _available_encoders():
    if "t" not in _enc_list_cache:
        _enc_list_cache["t"] = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    return _enc_list_cache["t"]

def probe_hw_encoder(enc, W, H, fps):
    """Really encode a few frames at the TARGET size/fps. A hardware encoder that works at 256x256 can still reject 2160x3840
    (per-codec size/level limits, VRAM, session limits), so the old tiny-frame test proved nothing for 2K/4K."""
    key = (enc, W, H, int(fps))
    if key in _hw_probe_cache: return _hw_probe_cache[key]
    cmd = ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=%dx%d:r=%d:d=0.5" % (W, H, fps), "-frames:v", "8", "-pix_fmt", "yuv420p", "-c:v", enc, "-f", "null", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        res = (r.returncode == 0, (r.stderr or "").strip()[-400:])
    except Exception as e:
        res = (False, "%s: %s" % (type(e).__name__, e))
    _hw_probe_cache[key] = res
    return res

def encoder_chain(codec, prefer_hw=True, W=1080, H=1920, fps=30):
    """Ordered fallback list [(encoder, is_hardware)] plus human notes about candidates that were skipped.
    Hardware encoders only qualify if they can actually encode W x H @ fps; software encoders are always the last resort."""
    avail = _available_encoders(); chain, notes = [], []
    for enc in CODEC_ENC.get(codec, CODEC_ENC["h264"]):
        if enc not in avail: continue
        if is_hw(enc):
            if not prefer_hw: continue
            ok, err = probe_hw_encoder(enc, W, H, fps)
            if not ok:
                # Only worth telling the user when the encoder works at small sizes but not at this one (size/level/VRAM limit). An encoder
                # that cannot run at all (no GPU) is skipped silently.
                if probe_hw_encoder(enc, 256, 256, 30)[0]:
                    lines = [l for l in err.splitlines() if l.strip() and "Nothing was written" not in l]
                    notes.append("%s cannot encode %dx%d@%d on this machine (%s); using the next encoder." % (enc, W, H, fps, (lines or ["unsupported"])[0][:160]))
                continue
        chain.append((enc, is_hw(enc)))
    if not chain: raise MediaError("No usable %s encoder found in this FFmpeg build." % codec)
    return chain, notes

def pick_encoder(codec, prefer_hw=True, W=1080, H=1920, fps=60):
    """First usable encoder for the target size (kept for /api/system and older callers)."""
    return encoder_chain(codec, prefer_hw, W, H, fps)[0][0][0]

def track_faces(src, start, dur, src_w, src_h, progress=None, job=None, log=None):
    """Optional Haar tracking. Any OpenCV/cascade/detection failure falls back to a deterministic centre crop."""
    def fallback(reason):
        msg = "Face tracking unavailable; using center crop%s." % ((" (%s)" % reason) if reason else "")
        if log: log("WARNING: " + msg)
        return [(0.0, 0.5)]
    try:
        import cv2
        if not hasattr(cv2, "CascadeClassifier") or not hasattr(cv2, "data"):
            return fallback("OpenCV CascadeClassifier/data unavailable")
        cascade = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
        if not os.path.isfile(cascade): return fallback("Haar cascade file missing")
        det = cv2.CascadeClassifier(cascade)
        if det.empty(): return fallback("Haar cascade failed to load")
    except Exception as e:
        return fallback("OpenCV runtime error: %s" % str(e).splitlines()[0][:100])
    W = 480; H = max(2, int(src_h * W / max(src_w, 1)) // 2 * 2); fs = W * H
    try:
        p = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", "%.3f" % start, "-t", "%.3f" % dur, "-i", src, "-an",
                              "-vf", "fps=2,scale=%d:%d,format=gray" % (W, H), "-f", "rawvideo", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except Exception as e:
        return fallback("frame extraction failed: %s" % str(e).splitlines()[0][:100])
    if job is not None: job.face_proc = p
    xs, last = [], 0.5
    try:
        while True:
            if job is not None and getattr(job, "cancelled", False):
                try: p.terminate()
                except Exception: pass
                raise Cancelled()
            b = p.stdout.read(fs)
            if len(b) < fs: break
            try:
                g = np.frombuffer(b, dtype=np.uint8).reshape(H, W)
                f = det.detectMultiScale(g, 1.15, 5, minSize=(max(24, W // 20),) * 2)
                if len(f):
                    f = sorted(f, key=lambda r: -(r[2] * r[3]) + abs((r[0] + r[2] / 2) / W - last) * 500)
                    last = (f[0][0] + f[0][2] / 2) / W
            except Exception as e:
                return fallback("face detection failed: %s" % str(e).splitlines()[0][:100])
            xs.append(last)
    finally:
        try: p.wait(timeout=2)
        except Exception:
            try: p.kill()
            except Exception: pass
        if job is not None: job.face_proc = None
    if not xs: return [(0.0, 0.5)]
    a = np.array(xs); k = 5
    med = np.array([np.median(a[max(0, i - k // 2): i + k // 2 + 1]) for i in range(len(a))])
    sm, cur = [], med[0]
    for v in med:
        if abs(v - cur) > 0.04: cur = cur + 0.35 * (v - cur)
        sm.append(cur)
    pts = [(i / 2.0, float(v)) for i, v in enumerate(sm)]
    return pts[::2] if len(pts) > 24 else (pts or [(0.0, 0.5)])

def _lerp_expr(kf):
    if len(kf) == 1: return "%.4f" % kf[0][1]
    e = "%.4f" % kf[-1][1]
    for i in range(len(kf) - 2, -1, -1):
        (t0, x0), (t1, x1) = kf[i], kf[i + 1]
        e = "if(lt(t,%.3f),%.4f+(%.4f)*(t-%.3f)/%.3f,%s)" % (t1, x0, x1 - x0, t0, max(t1 - t0, 0.01), e)
    return "if(lt(t,%.3f),%.4f,%s)" % (kf[0][0], kf[0][1], e)

def _composition_graph(src_label, W, H, tpl):
    """Base 9:16 picture for the template's format (templates.FORMAT_SPECS) -> filter parts ending in [composition].

    One parameterised graph serves all formats:
      blur  background : enlarged blurred copy of the clip + sharp foreground overlaid in the video box   (Format 3 = the original universal look)
      black background : foreground padded onto a black canvas at the video box                          (Formats 1 and 2)
    The foreground is either cropped to fill the box ("cover") or fitted inside it ("contain"); never stretched.
    """
    spec = templates.format_spec(tpl)
    bx, by, bw, bh = templates.box_px(spec, W, H)
    cover = spec["fit"] == "cover"
    fg = "scale=%d:%d:force_original_aspect_ratio=%s" % (bw, bh, "increase" if cover else "decrease")
    if cover: fg += ",crop=%d:%d" % (bw, bh)
    fg += ",setsar=1"
    if spec["background"] == "blur":
        bg = tpl.get("background") or {}
        blur = max(0.0, float(bg.get("blur", 20)))
        dark = max(0.0, min(1.0, float(bg.get("darken", 0.05))))
        # Blur strength is RELATIVE to the canvas width (slider value = sigma in px on a 540-wide canvas), so the 540x960 preview and a
        # 1080p/2K/4K export look the same. The blur itself runs on a downscaled copy (4x for >=1080 wide), which is visually identical for a
        # heavy blur and keeps 4K exports fast.
        ds = 4 if W >= 1080 else 2
        sw, sh = max(2, -(-W // ds) // 2 * 2), max(2, -(-H // ds) // 2 * 2)
        sigma = blur * W / 540.0 / ds
        bgf = "[bgsrc]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d" % (sw, sh, sw, sh)
        if sigma > 0: bgf += ",gblur=sigma=%.2f:steps=2" % sigma
        bgf += ",scale=%d:%d:flags=bicubic" % (W, H)
        # Darken = black blended over the background by `darken` (0 = none, 1 = black). Linear, so the slider is directly visible.
        if dark > 0: bgf += ",drawbox=x=0:y=0:w=iw:h=ih:color=black@%.3f:t=fill" % dark
        bgf += ",setsar=1[bg]"
        parts = ["%ssplit=2[bgsrc][fgsrc]" % src_label, bgf, "[fgsrc]%s[fg]" % fg,
                 "[bg][fg]overlay=x=%d+(%d-w)/2:y=%d+(%d-h)/2:format=auto[composition]" % (bx, bw, by, bh)]
    else:
        parts = ["%s%s,pad=%d:%d:%d+(%d-iw)/2:%d+(%d-ih)/2:color=black[composition]" % (src_label, fg, W, H, bx, bw, by, bh)]
    return parts

def _enc_args(enc, codec, quality, is_prev, W, H, fps):
    big = W * H > 1920 * 1080          # 2K/4K: faster software presets keep render times practical
    if enc in ("libx264", "libx265"):
        return ["-c:v", enc, "-preset", "ultrafast" if is_prev else ("fast" if big else "medium"), "-crf", "28" if is_prev else {"high": "18", "balanced": "22", "small": "26"}[quality]]
    if enc == "libsvtav1": return ["-c:v", enc, "-crf", {"high": "26", "balanced": "32", "small": "38"}[quality], "-preset", "8"]
    if enc == "libaom-av1": return ["-c:v", enc, "-crf", "32", "-b:v", "0", "-cpu-used", "8"]
    # Hardware encoders are bitrate-driven: scale the 1080p60 base with pixel rate so 2K/4K are not starved.
    base = {"high": 20, "balanced": 12, "small": 6}[quality] * (W * H * fps) / float(1080 * 1920 * 60)
    return ["-c:v", enc, "-b:v", "%dM" % int(max(4, min(100, round(base))))] + (["-cq", "20"] if "nvenc" in enc else [])

def _run_ffmpeg(job, cmd, cwd, out_dur, progress, log):
    """Run FFmpeg; stderr is drained on its own thread (a full stderr pipe would otherwise deadlock the progress loop). Returns (returncode, stderr)."""
    import threading
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if job is not None: job.proc = p
    errbuf = []
    t = threading.Thread(target=lambda: errbuf.append(p.stderr.read()), daemon=True); t.start()
    for line in p.stdout:
        m = re.match(r"out_time_ms=(\d+)", line)
        if m and progress and out_dur: progress(min(int(m.group(1)) / 1e6 / out_dur, 1.0))
    p.wait(); t.join(timeout=5)
    if job is not None: job.proc = None
    return p.returncode, (errbuf[0] if errbuf else "")

def verify_output(path, W, H, fps, out_dur, expect_audio, full_decode=True):
    """Probe the finished file with ffprobe (core/ingest) and decode it. Returns dict(ok, checks=[(name, ok, detail)], summary)."""
    from . import ingest
    checks = []
    def add(name, ok, detail): checks.append(dict(name=name, ok=bool(ok), detail=detail))
    size = os.path.getsize(path) if os.path.isfile(path) else 0
    add("file exists and has valid size", size >= 1000, "%d bytes" % size)
    if size < 1000: return dict(ok=False, checks=checks)
    try: o = ingest.probe_output(path)
    except Exception as e:
        add("ffprobe can read the file", False, str(e)[:200]); return dict(ok=False, checks=checks)
    add("width matches", o["width"] == W, "%d (requested %d)" % (o["width"], W))
    add("height matches", o["height"] == H, "%d (requested %d)" % (o["height"], H))
    add("fps matches", abs(o["fps"] - fps) <= 0.05 and abs(o["r_fps"] - fps) <= 0.05, "avg %.3f / r %.3f (requested %d)" % (o["fps"], o["r_fps"], fps))
    if o.get("nb_frames"):
        want = out_dur * fps; add("frame count matches duration x fps", abs(o["nb_frames"] - want) <= max(3, want * 0.02), "%d frames (expected ~%d)" % (o["nb_frames"], round(want)))
    add("duration matches", abs(o["duration"] - out_dur) <= 0.3 + 1.0 / fps, "%.2fs (expected %.2fs)" % (o["duration"], out_dur))
    if expect_audio:
        ad = o.get("audio_duration")
        add("audio present and in sync", ad is not None and abs(ad - o["video_duration"]) <= 0.3, "audio %s s vs video %.2f s" % (("%.2f" % ad) if ad is not None else "missing", o["video_duration"]))
    if full_decode:
        r = subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", path, "-f", "null", "-"], capture_output=True, text=True)
        add("file decodes without errors (playable)", r.returncode == 0 and not r.stderr.strip(), (r.stderr.strip()[-200:] or "ok"))
    return dict(ok=all(c["ok"] for c in checks), checks=checks)

def build_and_run(job, src, probe, clip, keep, cues, cap_style, tpl, sfx_events, sfxdir, opts, outpath, progress=None, log=None):
    preset = PRESETS[opts.get("preset", "1080p60")]
    W, H, fps = preset[:3]
    codec = opts.get("codec", "h264")
    is_prev = bool(opts.get("preview"))
    if is_prev: codec = "h264"; opts = dict(opts, hardware=False, denoise=False, loudnorm=False, interpolate=False)
    enc_chain, enc_notes = encoder_chain(codec, opts.get("hardware", True), W, H, fps)
    cs = float(clip["start"]); dur = float(clip["end"]) - cs
    rel = [(float(a) - cs, float(b) - cs) for a, b in keep if float(b) > float(a)]
    if not rel: raise MediaError("Clip has no kept timeline intervals to render.")
    out_dur = sum(b - a for a, b in rel)
    tpl = templates.merge(tpl)
    work = tempfile.mkdtemp(prefix="cf_render_")
    try:
        sw, sh = int(probe["width"]), int(probe["height"])
        fspec = templates.format_spec(tpl)
        notes = ["%s: %s" % (fspec["name"], fspec["note"])] + enc_notes
        ovp = os.path.join(work, "overlay.png"); templates.render_overlay(ovp, W, H, tpl, "", (sw, sh))
        fonts_needed = {}
        fam, fontsdir, fnote = FONTS.stage((cap_style or {}).get("font", "Poppins"), work)
        fonts_needed[(cap_style or {}).get("font", "Poppins")] = fam
        if fnote: notes.append(fnote)
        for layer in tpl.get("top_captions", []) if tpl.get("layout_template_enabled") else []:
            req = layer.get("font", "Poppins"); lf, _, lnote = FONTS.stage(req, work); fonts_needed[req] = lf
            if lnote and lnote not in notes: notes.append(lnote)
        assp = os.path.join(work, "cap.ass")
        cstyle = dict(size=0.045, pos_y=0.80, pos_x=0.50, max_chars=24, max_lines=2); cstyle.update(cap_style or {})
        cap_stats = CAP.write_ass(assp, cues, W, H, cstyle, opts.get("keywords", []), font_family=fam)
        top_count = 0
        top_ass = os.path.join(work, "top.ass")
        if tpl.get("layout_template_enabled") and tpl.get("top_captions"):
            top_count = CAP.write_top_ass(top_ass, tpl["top_captions"], out_dur, W, H, fonts_needed)
        if top_count: notes.append("Top On-Screen Caption: %d active layer(s)." % top_count)
        if not tpl.get("layout_template_enabled"): notes.append("Layout Template OFF: template overlays hidden; video/background/transcript captions remain visible.")
        if not cap_stats.get("fade_in", True): notes.append("Caption Fade In OFF: %d cue(s) appear instantly." % cap_stats.get("instant_cues", 0))
        elif cap_stats["fallback_cues"] and cap_stats["word_cues"] + cap_stats["fallback_cues"]:
            notes.append("Captions: %d cue(s) use phrase-level fallback; %d cue(s) use word-by-word fade." % (cap_stats["fallback_cues"], cap_stats["word_cues"]))

        # Order: cut kept regions from the SOURCE -> concat -> frame rate -> composition. The heavy 9:16 composition (blur, overlay) therefore
        # runs once on kept frames only, and fps conversion/interpolation happens at source resolution instead of at 2K/4K.
        vf = []
        n = len(rel)
        if n > 1:
            vf.append("[0:v]split=%d%s" % (n, "".join("[vs%d]" % i for i in range(n))))
            for i, (a, b) in enumerate(rel): vf.append("[vs%d]trim=%.3f:%.3f,setpts=PTS-STARTPTS[v%d]" % (i, a, b, i))
            vf.append("%sconcat=n=%d:v=1:a=0[vseq]" % ("".join("[v%d]" % i for i in range(n)), n))
        else:
            vf.append("[0:v]trim=%.3f:%.3f,setpts=PTS-STARTPTS[vseq]" % (rel[0][0], rel[0][1]))
        src_fps = float(probe.get("fps", fps)) or fps
        if fps > src_fps * 1.05 and opts.get("interpolate"):
            vf.append("[vseq]minterpolate=fps=%d:mi_mode=mci:mc_mode=aobmc:vsbmc=1[vfps]" % fps); notes.append("Frame rate raised with motion-interpolation (synthesised frames)")
        else:
            vf.append("[vseq]fps=%d[vfps]" % fps)
            if fps > src_fps * 1.05: notes.append("Target %d fps is above source %.2f fps: frames are DUPLICATED (no new motion detail)" % (fps, src_fps))
            elif fps < src_fps * 0.95: notes.append("Target %d fps is below source %.2f fps: frames are dropped." % (fps, src_fps))
        vf += _composition_graph("[vfps]", W, H, tpl)
        # overlay.png is a single frame: overlay repeats its last frame, so it is decoded once instead of 60x per second.
        vf.append("[composition][1:v]overlay=0:0:format=auto[ov]"); chain = "[ov]"
        if top_count:
            vf.append("%sass=top.ass:fontsdir=fonts[topv]" % chain); chain = "[topv]"
        vf.append("%sass=cap.ass:fontsdir=fonts,format=yuv420p[vout]" % chain)

        af, inputs = [], ["-ss", "%.3f" % cs, "-t", "%.3f" % dur, "-i", src, "-i", ovp]
        have_a = bool(probe["has_audio"])
        if have_a:
            for i, (a, b) in enumerate(rel): af.append("[0:a]atrim=%.3f:%.3f,asetpts=PTS-STARTPTS[a%d]" % (a, b, i))
            af.append("%sconcat=n=%d:v=0:a=1[aseq]" % ("".join("[a%d]" % i for i in range(n)), n))
            chain_a = "[aseq]"; fx = []
            if opts.get("denoise"): fx.append("afftdn=nr=12")
            if opts.get("loudnorm"): fx.append("loudnorm=I=%s:TP=-1.5:LRA=11" % opts.get("lufs", -14))
            if fx: af.append("%s%s[aclean]" % (chain_a, ",".join(fx))); chain_a = "[aclean]"
        ev = [e for e in (sfx_events or []) if e.get("enabled", True) and e.get("t", 0) < out_dur and os.path.isfile(os.path.join(sfxdir, e.get("sound", "")))]
        if ev:
            labs = []
            for k, e in enumerate(ev):
                inputs += ["-i", os.path.join(sfxdir, e["sound"])]
                idx = 2 + k; f = "[%d:a]aformat=sample_rates=44100:channel_layouts=stereo" % idx
                if e.get("trim_start") or e.get("trim_len"):
                    f += ",atrim=start=%.3f%s,asetpts=PTS-STARTPTS" % (e.get("trim_start", 0), (":duration=%.3f" % e["trim_len"]) if e.get("trim_len") else "")
                f += ",volume=%.1fdB" % e.get("gain_db", -8)
                if e.get("fade_in"): f += ",afade=t=in:d=%.3f" % e["fade_in"]
                if e.get("fade_out"): f += ",areverse,afade=t=in:d=%.3f,areverse" % e["fade_out"]
                ms = int(float(e.get("t", 0)) * 1000); f += ",adelay=%d|%d[x%d]" % (ms, ms, k); af.append(f); labs.append("[x%d]" % k)
            af.append("%samix=inputs=%d:normalize=0[sfxbus]" % ("".join(labs), len(labs)))
            if have_a:
                if any(e.get("duck", True) for e in ev):
                    af.append("%sasplit[sp1][sp2]" % chain_a); af.append("[sfxbus][sp2]sidechaincompress=threshold=0.04:ratio=8:attack=5:release=250[sfxd]"); af.append("[sp1][sfxd]amix=inputs=2:normalize=0,alimiter=limit=0.95[aout]")
                else: af.append("%s[sfxbus]amix=inputs=2:normalize=0,alimiter=limit=0.95[aout]" % chain_a)
            else: af.append("[sfxbus]anull[aout]")
        elif have_a: af.append("%sanull[aout]" % chain_a)
        fc = ";".join(vf + af)
        q = opts.get("quality", "high")
        expect_audio = bool(have_a or ev)
        from .ingest import probe as _probe

        # Try each encoder in the chain (hardware first when allowed). A failed encode OR a failed output verification moves on to the next
        # encoder; only when every candidate fails do we raise, carrying FFmpeg's real error text. Nothing is reported as success unless verified.
        failures, used = [], None
        for ci, (enc, hw) in enumerate(enc_chain):
            cmd = ["ffmpeg", "-v", "error", "-y", "-progress", "pipe:1", "-nostats"] + inputs + ["-filter_complex", fc, "-map", "[vout]"]
            if expect_audio: cmd += ["-map", "[aout]", "-c:a", "aac", "-b:a", "96k" if is_prev else "192k"]
            cmd += _enc_args(enc, codec, q, is_prev, W, H, fps) + ["-pix_fmt", "yuv420p", "-r", str(fps)]
            if codec == "h265": cmd += ["-tag:v", "hvc1"]
            cmd += ["-movflags", "+faststart", "-t", "%.3f" % out_dur, outpath]
            if log: log("ffmpeg [%s %dx%d@%d]: %s ... (filter graph %d chars)" % (enc, W, H, fps, " ".join(cmd[:14]), len(fc)))
            if getattr(job, "cancelled", False): raise Cancelled()
            rc, err = _run_ffmpeg(job, cmd, work, out_dur, progress, log)
            if getattr(job, "cancelled", False):
                try: os.remove(outpath)
                except OSError: pass
                raise Cancelled()
            problem = None
            if rc != 0 or not os.path.isfile(outpath) or os.path.getsize(outpath) < 1000:
                problem = "%s failed (exit %s): %s" % (enc, rc, err.strip()[-2000:] or "no error text from FFmpeg")
                verification = None
            else:
                verification = verify_output(outpath, W, H, fps, out_dur, expect_audio, full_decode=not is_prev)
                if not verification["ok"]:
                    problem = "%s produced a file that failed verification: %s" % (enc, "; ".join("%s [%s]" % (c["name"], c["detail"]) for c in verification["checks"] if not c["ok"]))
            if problem is None: used = (enc, hw); break
            failures.append(problem)
            if log: log("ENCODER PROBLEM: " + problem)
            try: os.remove(outpath)
            except OSError: pass
            if ci + 1 < len(enc_chain): notes.append("%s failed; fell back to %s. Reason: %s" % (enc, enc_chain[ci + 1][0], problem.splitlines()[0][:240]))
        if used is None: raise MediaError("FFmpeg render failed with every available encoder:\n" + "\n---\n".join(failures))
        enc, hw = used
    finally:
        shutil.rmtree(work, ignore_errors=True) if not opts.get("keep_intermediates") else None
    from .ingest import probe as _probe
    o = _probe(outpath)
    _, _, bw, bh = templates.box_px(fspec, W, H)   # the sharp foreground is scaled into the format's video box
    fit_f = max if fspec["fit"] == "cover" else min
    factor = fit_f(bw / float(max(sw, 1)), bh / float(max(sh, 1)))
    up_res = factor > 1.001
    return dict(file=outpath, source="%dx%d @ %.2f fps" % (sw, sh, probe["fps"]), requested=preset[3], rendered="%dx%d @ %.2f fps" % (o["width"], o["height"], o["fps"]),
                encoder=enc + (" (hardware)" if hw else " (software)"), verification=verification, requested_fps=fps, requested_size="%dx%d" % (W, H), duration=round(o["duration"], 2), upscaled=bool(up_res), upscale_factor=round(factor, 3),
                format=templates.normalize_format(tpl.get("format")), format_name=fspec["name"], captions=cap_stats, font=fam, interpolated=bool(opts.get("interpolate") and fps > probe["fps"] * 1.05),
                notes=notes + (["Sharp foreground is UPSCALED from the source (%.2fx)." % factor] if up_res else ["Sharp foreground is rendered at or below native source resolution (no upscaling)."]))
