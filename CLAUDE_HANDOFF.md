# ClipForge handoff

## Completed
- **OpenCV / face-tracking robustness:** `track_faces()` treats missing/broken `cv2`, missing `CascadeClassifier`, missing Haar data/cascade, frame-extraction failure, or detection failure as non-fatal and falls back to deterministic center crop with a clear warning.
- **Universal 9:16 composition:** all renders use the same shared 9:16 graph: blurred enlarged background + sharp aspect-ratio-preserving foreground.
- **Platform unification:** TikTok / YouTube / Facebook / Instagram share the same base composition; platform selection changes safe-area guidance only.
- **Layout Template master ON/OFF:** OFF hides profile/logo/top-text template overlays while leaving video, background and transcript captions visible.
- **Top On-Screen Caption editor:** add/select/edit/remove, enable/disable, normalized X/Y, font, size, color, bold, alignment, outline, shadow, plus up/down ordering.
- **Caption Draft -> Apply / Cancel:** transcript-caption style changes stay local until Apply; Cancel restores saved values; Reset restores safe defaults without rendering.
- **9:16 caption positioning canvas:** draggable caption, X/Y controls and platform safe-area guides.
- **Caption cue editor:** add/edit/delete/start/end controls. Same-word-count manual edits proportionally retime word timings; structurally different edits are marked stale and fall back to cue-level animation.
- **Font picker:** dynamic internal family names, visual sample grid, and browser `@font-face` loading for app-local uploaded fonts where available. FFmpeg still stages the selected family for the actual render.
- **Word-by-word fade:** preserved using actual word timings with cue-level fallback when timings are stale/unavailable.
- **True edited Live Preview:** real FFmpeg-rendered preview, fingerprint cache, generation/stale-request guard, cancellation, last-valid preview retention, native playback events and seek.
- **Preview timeline:** lightweight timeline markers for caption cues and kept regions under the seek control.
- **Project saving / reopening:** projects now have persistent names, save timestamps, searchable Previous Projects, explicit Save Project, atomic JSON persistence, project-local media storage when Save is requested, project file tracking, and one-click reopening without selecting the source again when a stored project copy is available.
- **Source recovery behavior:** older projects resolve a stored project copy first when the original source path is unavailable. Missing sources are surfaced instead of producing a low-level traceback.
- **Assets:** project-local avatar/logo files remain inside the project directory and are tracked by the project file list.
- **Migration safety:** older project templates are merged/migrated on load with safe defaults.
- **Export correctness/cancellation/history:** existing upscaling detection, checkpoint freshness, cancellation, export history and stale-preview behavior remain intact.

## Partially completed
- Full browser UI automation was not executed in this sandbox because Flask is not installed in the active Python runtime.
- Windows/macOS end-to-end rendering was not executed here.
- Real face-containing subject-tracking verification after the fallback changes was not executed here; broken-OpenCV fallback was tested.

## Not completed
- Optional LAN PIN/token protection.

## Tests actually run
- `python3 -m py_compile app.py core/*.py` -> OK.
- `node --check static/app.js` -> OK.
- Caption proportional retime unit check -> OK.
- Synthetic 1280x720@30 source -> real FFmpeg preview completed at **540x960 @ 24 fps**, with dead-air removal, top text, and word-level caption fade.
- Synthetic 720x1280 portrait source -> real FFmpeg preview completed at **540x960 @ 24 fps** using the same shared composition.
- Layout Template OFF -> real FFmpeg render completed with video/background/transcript-caption behavior retained.
- SFX smoke test -> real FFmpeg preview completed with H.264 video and AAC audio streams.
- Broken OpenCV fallback simulation -> non-fatal center-crop fallback completed.
- Legacy hook migration unit check -> completed.
- **Project-save HTTP integration / browser UI:** not run because Flask is not installed in the validation sandbox.

## Known issues / risks
- Explicit Save Project stores an externally referenced source into `workspace/projects/<id>/media/` when possible. This may consume substantial disk space for a large local source; uploaded sources on the same filesystem use a hard link when supported.
- If a user chooses not to preserve an external source (or the copy cannot be made), reopening the project still loads its edits, but the source must remain at the original path.
- The sharp foreground intentionally preserves aspect ratio rather than cropping to fill the 9:16 canvas.
- Poppins may fall back to another available family on machines where it is not installed.

## Exact next steps
1. Install `requirements.txt` and run the Flask app in the target environment.
2. Test creating a project, saving it, closing/restarting ClipForge, searching Previous Projects, loading it, and confirming the source/avatars/logo/edit state are restored.
3. Exercise custom uploaded fonts in a browser and verify their samples match the selected family.
4. Validate Windows/macOS paths and a real face-containing clip if legacy tracking is needed.

## Video Format selector
- Change a format's look by editing numbers in `core/templates.py: FORMAT_SPECS` only (box x/y/w/h, fit, background, logo_cy/profile_cy, caption_zone). UI cards, preview, export and upscale detection all read it.
- Format 1 follows the reference image literally: a full-width, centred band (y 28.8%-71.2%), cover-cropped. If a taller "full-height" look is wanted instead, change `format1.box` (e.g. y=0, h=1.0).
- Format 2's reference box is ~1.42:1, so the true 16:9 clip is fitted inside it (width-limited, 76.6% of canvas width) rather than stretched.
- Transcript captions keep their own saved position (default y=0.80) and can overlap the logo slot (y~0.794) in Formats 1/2 when a logo is on; the caption canvas now shows the format's video area and caption zone to help place them.
- Background blur/darken only affect Format 3; values are kept when switching.
