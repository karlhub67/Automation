"""Media ingest: real FFprobe metadata + validation."""
import json, os, subprocess, shutil

class MediaError(Exception):
    pass

def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)

def check_tools():
    missing = [t for t in ("ffmpeg", "ffprobe") if not shutil.which(t)]
    if missing:
        raise MediaError("Missing required tool(s): %s. Install FFmpeg and make sure it is on PATH." % ", ".join(missing))

def _fps(s):
    try:
        a, b = s.split("/")
        return float(a) / float(b) if float(b) else 0.0
    except Exception:
        try: return float(s)
        except Exception: return 0.0

def probe(path):
    check_tools()
    if not os.path.isfile(path):
        raise MediaError("File not found: %s" % path)
    if not os.access(path, os.R_OK):
        raise MediaError("No read permission for: %s" % path)
    r = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path])
    if r.returncode != 0:
        raise MediaError("FFprobe could not read this file (corrupt or unsupported): %s" % r.stderr.strip()[:300])
    j = json.loads(r.stdout)
    v = next((s for s in j.get("streams", []) if s["codec_type"] == "video"), None)
    a = next((s for s in j.get("streams", []) if s["codec_type"] == "audio"), None)
    if not v:
        raise MediaError("No video stream found in this file.")
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd: rot = int(sd["rotation"])
    rot = int(v.get("tags", {}).get("rotate", rot) or rot)
    w, h = int(v["width"]), int(v["height"])
    if abs(rot) % 180 == 90: w, h = h, w
    avg, rfr = _fps(v.get("avg_frame_rate", "0/1")), _fps(v.get("r_frame_rate", "0/1"))
    dur = float(j["format"].get("duration") or v.get("duration") or 0)
    return dict(path=os.path.abspath(path), duration=dur, width=w, height=h, fps=round(avg or rfr, 3),
                vfr=bool(avg and rfr and abs(avg - rfr) / rfr > 0.01), vcodec=v.get("codec_name"),
                pix_fmt=v.get("pix_fmt"), color_space=v.get("color_space"), rotation=rot,
                has_audio=a is not None, acodec=a.get("codec_name") if a else None,
                size_bytes=int(j["format"].get("size") or 0))

def check_disk(dir_path, need_bytes):
    free = shutil.disk_usage(dir_path).free
    if free < need_bytes:
        raise MediaError("Not enough free disk space in %s (need ~%d MB, have %d MB)." % (dir_path, need_bytes >> 20, free >> 20))

def thumbnail(src, t, out, width=240):
    run(["ffmpeg", "-v", "error", "-y", "-ss", "%.2f" % t, "-i", src, "-frames:v", "1", "-vf", "scale=%d:-2" % width, out])
    return out

def probe_output(path):
    """ffprobe facts about a RENDERED file (used to verify exports): size, fps (avg + r), frame count, per-stream durations."""
    r = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path])
    if r.returncode != 0: raise MediaError("FFprobe could not read the rendered file: %s" % r.stderr.strip()[:300])
    j = json.loads(r.stdout)
    v = next((x for x in j.get("streams", []) if x["codec_type"] == "video"), None)
    a = next((x for x in j.get("streams", []) if x["codec_type"] == "audio"), None)
    if not v: raise MediaError("Rendered file has no video stream.")
    def f(x):
        try: return float(x)
        except Exception: return None
    fdur = float(j["format"].get("duration") or 0)
    return dict(width=int(v["width"]), height=int(v["height"]), fps=_fps(v.get("avg_frame_rate", "0/1")), r_fps=_fps(v.get("r_frame_rate", "0/1")),
                nb_frames=int(v["nb_frames"]) if str(v.get("nb_frames", "")).isdigit() else None, vcodec=v.get("codec_name"), pix_fmt=v.get("pix_fmt"),
                duration=fdur, video_duration=f(v.get("duration")) or fdur, audio_duration=(f(a.get("duration")) or fdur) if a else None, has_audio=a is not None)
