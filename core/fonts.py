"""Portable font discovery + per-render font staging so libass finds the selected font on Windows/macOS/Linux."""
import os, sys, shutil, glob
EXTS = (".ttf", ".otf", ".ttc")
_cache = {"t": 0, "fams": None}
USER_DIRS = []  # app-local font folders (workspace/fonts, project fonts); set by app.py

def system_dirs():
    h = os.path.expanduser("~")
    if sys.platform.startswith("win"):
        wd = os.environ.get("WINDIR", r"C:\Windows")
        return [os.path.join(wd, "Fonts"), os.path.join(os.environ.get("LOCALAPPDATA", h), "Microsoft", "Windows", "Fonts")]
    if sys.platform == "darwin":
        return ["/System/Library/Fonts", "/Library/Fonts", os.path.join(h, "Library", "Fonts")]
    return ["/usr/share/fonts", "/usr/local/share/fonts", os.path.join(h, ".fonts"), os.path.join(h, ".local", "share", "fonts")]

def _scan_dir(d, out):
    if not os.path.isdir(d): return
    for root, _, files in os.walk(d):
        for f in files:
            if f.lower().endswith(EXTS):
                p = os.path.join(root, f)
                try:
                    from PIL import ImageFont
                    fam, style = ImageFont.truetype(p, 12).getname()
                except Exception: continue
                out.setdefault(fam, []).append(dict(path=p, style=style))

def families(refresh=False):
    """{family name -> [{path, style}]}, family = the name libass matches against (the font's internal family, not the file name)."""
    import time
    if _cache["fams"] is not None and not refresh and time.time() - _cache["t"] < 300: return _cache["fams"]
    out = {}
    for d in USER_DIRS + system_dirs(): _scan_dir(d, out)
    _cache["fams"], _cache["t"] = out, time.time(); return out

def list_names():
    fams = families(); local = {d for d in USER_DIRS}
    return sorted(fams, key=str.lower)

def stage(font, workdir):
    """Copy the files of the requested family into workdir/fonts. Returns (family_to_use, fontsdir_relative, note_or_None)."""
    fams = families(); fd = os.path.join(workdir, "fonts"); os.makedirs(fd, exist_ok=True)
    key = next((k for k in fams if k.lower() == (font or "").lower()), None)
    note = None
    if key is None:  # allow the user to give a file-like name ("Poppins-Bold") -> match on file stem
        for k, fl in fams.items():
            if any(os.path.splitext(os.path.basename(f["path"]))[0].lower() == (font or "").lower() for f in fl): key = k; break
    if key is None:
        for fb in ("Poppins", "DejaVu Sans", "Liberation Sans", "Arial", "Helvetica", "Segoe UI"):
            key = next((k for k in fams if k.lower() == fb.lower()), None)
            if key: break
        if key is None and fams: key = sorted(fams)[0]
        note = "Font '%s' was not found on this computer; used '%s' instead." % (font, key)
    if key:
        for f in fams[key]:
            try: shutil.copy(f["path"], os.path.join(fd, os.path.basename(f["path"])))
            except OSError: pass
    return (key or font or "Sans"), "fonts", note
