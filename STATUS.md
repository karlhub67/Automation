# STATUS

## Current build
ClipForge remains a local-first Flask + FFmpeg single-page editor. The current build includes the requested shared 9:16 composition, editable caption/template workflow, real rendered Live Preview, and a persistent project saving/reopening system.

### Implemented
- Shared 9:16 blurred-background + sharp proportional foreground for all four platforms.
- Platform selection changes safe-area guidance only.
- Non-fatal OpenCV face-tracking fallback.
- Real FFmpeg edited Live Preview with cache/generation guards, native playback, seeking and cancellation.
- Word-by-word caption fade with stale-timing fallback.
- Dynamic portable font discovery, visual picker and browser loading for app-local fonts.
- Layout Template master ON/OFF.
- Top On-Screen Caption layers with add/select/edit/remove/reorder and normalized positioning.
- Caption Draft -> Apply / Cancel / Reset.
- 9:16 caption positioning canvas.
- Caption cue add/edit/delete and proportional word-timing retime when structurally reliable.
- Preview timeline markers for caption cues and kept regions.
- Project names, explicit Save Project, atomic JSON saves, searchable Previous Projects, project-local source archiving, project file tracking, and one-click reopening.
- Export upscaling correctness, checkpoint freshness, cancellation and export history retained.

### Validation completed in this build
- Python compilation: OK.
- JavaScript syntax: OK.
- Caption retiming unit check: OK.
- Real FFmpeg landscape preview: 540x960@24.
- Real FFmpeg portrait preview: 540x960@24.
- Layout Template OFF render: completed.
- SFX audio render: completed with AAC.
- Broken-cv2 fallback: completed and non-fatal.
- Legacy hook migration: completed.

### Not validated here
- Flask HTTP/browser UI integration because Flask is not installed in the current validation environment.
- Windows/macOS end-to-end rendering.
- Real face-containing clip tracking after the latest robustness changes.
- Optional LAN PIN/token protection.

## Video Format selector (added)
- `template.format` = `format1` | `format2` | `format3`. Missing => `format3`, which is pixel-identical to the previous universal composition (verified frame-by-frame), so older projects are untouched and their files are not rewritten on open.
- Spec lives in `core/templates.py: FORMAT_SPECS` (box, fit cover/contain, black/blur background, logo & profile slots, caption zone, card text). `/api/system` serves it to the UI.
- `core/render.py: _composition_graph` is the single parameterised graph; upscale detection uses the format's video box.
- `app.py`: edit op `format` (patches only template.format; undo/redo + autosave via existing snapshot), preview endpoint accepts an unsaved `format` override, fingerprint omits the default format so old preview/export freshness stays valid.
- UI: Format button above Play, centred dialog (radio cards, Esc/Enter/arrow keys, focus trap), in-preview "Applying Format N..." overlay with Cancel. Okay pre-renders the preview with the new format and commits only on success.
- Tested: 43 API checks, 41 real-browser (Chromium) checks, legacy/Format 3 frame-hash identity on landscape + portrait sources, 1080p60 exports of all three formats.
- Not tested: Windows/macOS, hardware encoders, real face-containing footage, real H.264 playback in a browser (the headless test browser lacks H.264).

## Change set: exports, navigation, Format 3, caption fade, font dropdown
- Done: 1080p30 preset; encoder chain with target-size hardware probing, runtime fallback and post-render verification; failures now saved to the project (UI no longer shows the previous success); request validation on /render.
- Done: header = Auto Clips | Editing (Coming Soon). Platform buttons removed from the UI (backend `platform` field kept; safe-area guide is now the union of all platforms).
- Done: Format 3 blur relative to canvas size + real darken; trim-before-compose graph order; single-frame overlay input.
- Done: Caption Fade In toggle (saved in caption_style.fade_in_on); font grid removed, dropdown only (saved font stays selectable even if not installed).
- Tested here (CPU-only sandbox): real renders at all four presets + H.265/AV1, 3 formats, blur/darken pixel checks, preview-vs-export parity, fade ON/OFF (ASS + pixels), fonts, Flask API flow, Chromium UI checks, simulated hardware-encoder failure.
- NOT tested: real NVENC/QSV/AMF hardware (none here), Windows/macOS, playback of H.264 in a real browser, very long clips at 4K60.
