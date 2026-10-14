"""Shared 9:16 composition and editable non-transcript template overlays."""
import os
from PIL import Image, ImageDraw, ImageFont, ImageOps

FONT_DIRS = [
    "/usr/share/fonts/truetype/google-fonts", "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/liberation", "C:/Windows/Fonts",
    "/System/Library/Fonts", "/System/Library/Fonts/Supplemental",
]

def font(names, size):
    for d in FONT_DIRS:
        for n in names:
            p = os.path.join(d, n)
            if os.path.isfile(p):
                try: return ImageFont.truetype(p, size)
                except OSError: pass
    return ImageFont.load_default()

MED = ["Poppins-Medium.ttf", "Arial.ttf", "LiberationSans-Regular.ttf", "DejaVuSans.ttf"]
BOLD = ["Poppins-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf", "LiberationSans-Bold.ttf", "DejaVuSans-Bold.ttf"]
REG = ["Poppins-Regular.ttf", "Arial.ttf", "LiberationSans-Regular.ttf", "DejaVuSans.ttf"]

# Kept for compatibility with existing /api/system consumers; universal composition no longer uses these values to define the base video.
LAYOUT = dict(hook_top=0.11, video_center=0.50, video_w=0.90, profile_center=0.745, logo_center=0.805, avatar_d=0.175)

# Approximate platform UI safe areas for placement guidance only.
SAFE = {
    "tiktok": dict(top=0.10, bottom=0.20, right=0.14),
    "instagram": dict(top=0.10, bottom=0.18, right=0.12),
    "youtube": dict(top=0.10, bottom=0.22, right=0.14),
    "facebook": dict(top=0.09, bottom=0.18, right=0.12),
}

# ---------------------------------------------------------------------------------------------------------------------
# Video formats (template["format"]). One spec per format drives BOTH the FFmpeg composition (core/render.py) and the
# overlay slots below (render_overlay), and is served to the UI via /api/system so the selector cards never drift.
#
# All geometry is normalised to the output canvas (0-1), so the same spec serves 540x960 previews and 1080p-4K exports.
# Numbers were measured from the reference images (1080x1920): caption box y 251-514 / x 105-975, logo slot centre y~1524.
#   background : "black" | "blur" (enlarged blurred copy of the same clip; uses template.background blur/darken)
#   fit        : "cover"   = scale up + centre-crop to fill `box`  (the app's existing crop/fill behaviour)
#                "contain" = scale down to fit inside `box`, aspect ratio preserved (never stretched)
#   box        : video area  (x, y, w, h)
# To change how a format looks, edit its numbers here - nothing else needs touching.
# ---------------------------------------------------------------------------------------------------------------------
DEFAULT_FORMAT = "format3"   # identical to the pre-format "universal" composition, so projects without a format render exactly as before
_CAPTION_ZONE = dict(x=0.097, y=0.131, w=0.806, h=0.137)   # same zone in all three reference images
FORMAT_SPECS = {
    "format1": dict(
        name="Format 1 — Full Vertical", short="Full Vertical", platforms="TikTok / YouTube Shorts / Facebook Reels",
        description="The clip fills the full width of the vertical canvas, cropped to fill (never stretched).",
        layout="9:16 · full-width clip band · black above & below",
        image="/static/formats/format1.png",
        note="clip fills a full-width band (cropped to fill, not stretched) on a black 9:16 canvas.",
        background="black", fit="cover", box=dict(x=0.0, y=0.288, w=1.0, h=0.424),
        caption_zone=_CAPTION_ZONE, caption_y=0.255, logo_cy=0.794, profile_cy=0.794, profile_cy_with_logo=0.885),
    "format2": dict(
        name="Format 2 — Instagram", short="Instagram", platforms="Instagram",
        description="The original 16:9 clip stays uncropped, centred inside the 9:16 canvas.",
        layout="9:16 · centred 16:9 clip · black above & below",
        image="/static/formats/format2.png",
        note="original 16:9 clip kept intact and centred on a black 9:16 canvas.",
        background="black", fit="contain", box=dict(x=0.117, y=0.348, w=0.766, h=0.304),
        caption_zone=_CAPTION_ZONE, caption_y=0.255, logo_cy=0.794, profile_cy=0.794, profile_cy_with_logo=0.885),
    "format3": dict(
        name="Format 3 — Blurred Background", short="Blurred Background", platforms="TikTok / Facebook Reels / YouTube Shorts",
        description="Sharp 16:9 clip centred over an enlarged, blurred copy of the same clip.",
        layout="9:16 · sharp centred 16:9 clip · blurred full-frame background",
        image="/static/formats/format3.png",
        note="blurred full-frame background + sharp proportional foreground.",
        background="blur", fit="contain", box=dict(x=0.0, y=0.0, w=1.0, h=1.0),
        caption_zone=_CAPTION_ZONE, caption_y=0.255, logo_cy=0.805, profile_cy=0.745, profile_cy_with_logo=0.745),
}

def normalize_format(v):
    return v if isinstance(v, str) and v in FORMAT_SPECS else DEFAULT_FORMAT

def format_spec(tpl):
    """Spec for a template; a missing/unknown format (older projects) falls back to DEFAULT_FORMAT."""
    return FORMAT_SPECS[normalize_format((tpl or {}).get("format"))]

def format_catalog():
    return {k: dict(v, key=k) for k, v in FORMAT_SPECS.items()}

def box_px(spec, W, H):
    """Video area in pixels (even numbers, as yuv420p requires)."""
    b = spec["box"]
    return (int(round(b["x"] * W)) // 2 * 2, int(round(b["y"] * H)) // 2 * 2,
            max(2, int(round(b["w"] * W)) // 2 * 2), max(2, int(round(b["h"] * H)) // 2 * 2))

DEFAULT_TOP_CAPTION = dict(id="top1", enabled=True, text="", x=0.50, y=0.11, font="Poppins",
                           size=0.040, color="#FFFFFF", bold=True, align="center",
                           outline=0.002, outline_color="#000000", shadow=0.002)

DEFAULT_SPEC = dict(
    mode="universal",
    layout_template_enabled=True,
    background=dict(blur=20, darken=0.05, tint=""),
    hook=dict(on=True, text="", size=0.034, color="#FFFFFF", align="left"),
    top_captions=[],
    profile=dict(on=True, name="Account Name", handle="@account", verified=True, avatar="", ring="#7A2A5A"),
    logo=dict(on=False, path="", text="", scale=0.30),
    crop_fill_tracking=True,
)

def merge(spec):
    """Merge project/template state and migrate legacy hook into top caption layer 1."""
    out = {}
    for k, v in DEFAULT_SPEC.items(): out[k] = dict(v) if isinstance(v, dict) else (list(v) if isinstance(v, list) else v)
    for k, v in (spec or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict): out[k].update(v)
        else: out[k] = v
    out["layout_template_enabled"] = out.get("layout_template_enabled", True) is not False
    # Only validate when present: projects saved before formats existed have no key and simply use DEFAULT_FORMAT
    # (see format_spec), so opening/listing them never rewrites their files.
    if "format" in out: out["format"] = normalize_format(out["format"])
    layers = []
    for i, layer in enumerate(out.get("top_captions") or []):
        d = dict(DEFAULT_TOP_CAPTION); d.update(layer or {}); d["id"] = d.get("id") or "top%d" % (i + 1); layers.append(d)
    legacy = out.get("hook") or {}
    legacy_text = (legacy.get("text") or "").strip()
    if not layers and legacy_text:
        d = dict(DEFAULT_TOP_CAPTION)
        d.update(text=legacy_text, size=legacy.get("size", 0.034), color=legacy.get("color", "#FFFFFF"),
                 align=legacy.get("align", "left"), x=0.08 if legacy.get("align", "left") == "left" else 0.50, y=0.11)
        layers = [d]
    out["top_captions"] = layers
    out["hook"] = dict(out.get("hook") or {}, text=legacy_text)
    return out

def video_rect(W, H, src_w, src_h, spec):
    """Legacy helper retained for clients; universal composition itself is built in core/render.py."""
    spec = merge(spec)
    if spec.get("mode") != "letterbox": return 0, 0, W, H
    rw = int(W * 0.77) // 2 * 2
    rh = int(rw * src_h / src_w) // 2 * 2
    if rh > H * 0.5:
        rh = int(H * 0.5) // 2 * 2; rw = int(rh * src_w / src_h) // 2 * 2
    return (W - rw) // 2, int(H * 0.50 - rh / 2) // 2 * 2, rw, rh

def _hex(c):
    c = (c or "#FFFFFF").lstrip("#")
    if len(c) != 6: c = "FFFFFF"
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))

def _avatar(d, path, ring, initial):
    S = 4; D = d * S
    if path and os.path.isfile(path): im = ImageOps.fit(Image.open(path).convert("RGB"), (D, D))
    else:
        im = Image.new("RGB", (D, D), (70, 60, 110)); dr = ImageDraw.Draw(im)
        dr.text((D / 2, D / 2), initial, font=font(BOLD, int(D * 0.5)), fill=(255, 255, 255), anchor="mm")
    ringw = max(2, D // 28); pad = ringw * 2
    out = Image.new("RGBA", (D, D), (0, 0, 0, 0)); dr = ImageDraw.Draw(out)
    dr.ellipse((0, 0, D - 1, D - 1), fill=_hex(ring) + (255,))
    inner = D - 2 * pad
    m = Image.new("L", (D, D), 0); ImageDraw.Draw(m).ellipse((pad, pad, D - pad - 1, D - pad - 1), fill=255)
    out.paste(ImageOps.fit(im, (inner, inner)), (pad, pad), m.crop((pad, pad, D - pad, D - pad)))
    return out.resize((d, d), Image.LANCZOS)

def _badge(d):
    S = 4; im = Image.new("RGBA", (d * S, d * S), (0, 0, 0, 0)); dr = ImageDraw.Draw(im)
    dr.ellipse((0, 0, d * S - 1, d * S - 1), fill=(29, 155, 240, 255))
    pts = [(0.27, 0.52), (0.44, 0.68), (0.74, 0.34)]
    dr.line([(x * d * S, y * d * S) for x, y in pts], fill=(255, 255, 255, 255), width=int(d * S * 0.12), joint="curve")
    return im.resize((d, d), Image.LANCZOS)

def render_overlay(path, W, H, spec, hook_fallback="", src_size=(1920, 1080)):
    """Transparent PNG of template profile/logo overlays. Top captions are rendered in ASS for font fidelity."""
    spec = merge(spec)
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); dr = ImageDraw.Draw(im)
    if not spec["layout_template_enabled"]:
        im.save(path); return path
    fs = format_spec(spec)   # per-format profile/logo slots (Format 3 keeps the original 0.745 / 0.805 positions)
    pf, lg = spec["profile"], spec["logo"]
    has_logo = bool(lg["on"] and ((lg["path"] and os.path.isfile(lg["path"])) or lg["text"]))
    if pf["on"]:
        d = int(H * 0.0608); cy = int(H * (fs["profile_cy_with_logo"] if has_logo else fs["profile_cy"])); x0 = int(W * 0.155)
        im.alpha_composite(_avatar(d, pf["avatar"], pf["ring"], (pf["name"] or "A")[:1].upper()), (x0, cy - d // 2))
        fn, fh = font(BOLD, int(H * 0.0175)), font(REG, int(H * 0.0115))
        tx = x0 + d + int(W * 0.035)
        dr.text((tx, cy - int(H * 0.0085)), pf["name"], font=fn, fill=(255, 255, 255, 255), anchor="ls")
        if pf["verified"]:
            bd = int(H * 0.0125); nw = dr.textlength(pf["name"], font=fn)
            im.alpha_composite(_badge(bd), (int(tx + nw + W * 0.015), cy - int(H * 0.0085) - bd + int(bd * 0.1)))
        dr.text((tx, cy + int(H * 0.0135)), pf["handle"], font=fh, fill=(150, 156, 165, 255), anchor="ls")
    if lg["on"]:
        cy = int(H * fs["logo_cy"])
        if lg["path"] and os.path.isfile(lg["path"]):
            L = Image.open(lg["path"]).convert("RGBA"); w = max(1, int(W * lg["scale"])); L = L.resize((w, int(L.height * w / L.width)), Image.LANCZOS)
            im.alpha_composite(L, ((W - L.width) // 2, cy - L.height // 2))
        elif lg["text"]:
            f = font(BOLD, int(H * 0.026)); dr.text((W / 2, cy), lg["text"], font=f, fill=(255, 255, 255, 255), anchor="mm")
    im.save(path)
    return path
