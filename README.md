# ClipForge - local-first AI auto-clipping

Takes a long video + a plain-English request ("choose happy moments"), analyses the real media,
proposes clips you can inspect and edit, then renders captioned, reframed, social-ready vertical video.

## Run
    pip install -r requirements.txt          # needs FFmpeg + FFprobe on PATH
    pip install faster-whisper               # recommended: real transcription (first run downloads the model)
    python app.py                            # open http://127.0.0.1:5173

Windows/macOS/Linux. Everything runs locally; nothing is uploaded to an external service.

## Use from a phone (Chrome)
    python app.py --lan        # prints  http://<your-pc-ip>:5173
Open that address in Chrome on the phone (same Wi-Fi). Tap "browse" to pick a video from the phone; it uploads to the PC,
which does all the processing. Allow Python through the firewall if asked. Trusted networks only (no password).

## Workflow
1. Open the **Auto Clips** tab (default; the header has two tabs: Auto Clips | Editing - Editing is a "Coming Soon" placeholder), then open a video (path or drop).
2. Type your request, set clip count / durations / dead-air level, **Analyze**.
3. Review candidate cards: thumbnail, times, score, **Why this clip?** (measured evidence). Accept / reject / trim / merge / lock.
4. Pick a **Format** (button above Play in Live Preview): Format 1 Full Vertical, Format 2 Instagram, or Format 3 Blurred Background. Okay renders the new preview first and only then saves it, so a failure never changes your project.
5. Edit the layout, top on-screen text layers, captions (text/timing/style) and SFX events. Caption styling uses **Apply / Cancel** so drafts do not trigger renders.
6. Press **Save Project** to persist the project name, edits and project-local files. Use **Previous projects** to search and reopen a saved project without selecting the source again when the project contains a stored source copy.
7. **Quick preview** renders the real thing at 540x960; **Render accepted clips** exports at the chosen preset (1080p 30/60 FPS, 2K 60 FPS, 4K 60 FPS).
   The export card reports source vs requested vs actual resolution/FPS, encoder, and whether upscaling or frame duplication/interpolation happened.

## Architecture
    app.py            Flask server, project store (JSON, autosave, undo/redo), background jobs
    core/ingest.py    FFprobe metadata, validation, thumbnails
    core/analysis.py  streamed audio (energy, silences, noise-burst laughter/applause proxy) + visual (motion, cuts)
    core/transcript.py faster-whisper / openai-whisper / .srt/.vtt import, word timings
    core/intent.py    request -> concepts, topic terms, exclusions, durations (negation/sarcasm aware)
    core/select.py    candidate generation, multi-signal scoring, sentence/pause snapping, duplicate suppression
    core/trim.py      Off/Light/Balanced/Aggressive dead-air removal that preserves comic/question pauses
    core/captions.py  cues -> ASS (fade in/out, keyword emphasis), burned in by FFmpeg
    core/sfx.py       generated licence-free SFX + imports; events are data, mixed only at render (ducked under speech)
    core/templates.py FORMAT_SPECS (the 3 video formats: geometry, fit, background, logo/profile slots, UI card text) + template overlay defaults
    core/render.py    FFmpeg graph: cut -> dead-air concat -> universal 9:16 blurred background + sharp foreground -> overlay -> captions -> audio/SFX -> encode
    core/pipeline.py  stages + checkpoints (ck_*.json in the project folder let a re-run resume)
    static/           single-page UI (no build step)

Data lives in `workspace/projects/<id>/` (project.json, checkpoints, thumbs, previews, exports, media and project-local assets). Source media is never modified. Explicit Save Project can preserve an externally referenced source inside the project for one-click reopening.

## Honest limitations
- Laughter/cheer detection is an audio heuristic (loud + noise-like bursts), not a trained classifier.
- Subject tracking uses OpenCV Haar faces (frontal faces only); "active speaker" = largest/most stable face, not lip-motion.
- Intent parsing is lexicon + rules, not an LLM. Swap `core/intent.py`/`core/select.py` scoring for an LLM if you want deeper semantics.
- Without a speech model or .srt, selection falls back to audio/visual evidence only (the UI and log say so).
- Frame rates above the source are duplicated unless "motion-interpolate" is ticked (slow, can artifact; labelled in the report).
- Software 1080p60+ encoding is slow on weak CPUs; NVENC/QSV/AMF are used automatically when they work.
- Not packaged as Tauri/Electron: it is a local web app (see STATUS.md).

## Export pipeline (reliability notes)
- Presets: 1080p30 / 1080p60 (1080x1920), 2K60 (1440x2560), 4K60 (2160x3840) (+1080p120). Output is verified after every render with ffprobe + a full decode:
  width, height, fps, frame count, duration, audio presence/sync and playability. A render is only reported successful if all checks pass; the checklist is shown in the result card.
- Hardware encoders are probed at the TARGET resolution/fps (not a tiny test frame). If one still fails (or its output fails verification) the render automatically
  falls back to the next encoder, ending in software (libx264 / libx265 / libsvtav1 / libaom). FFmpeg's real error text is kept in the log and in the failure message.
- Graph order: cut kept regions from the source -> concat -> fps/interpolation (source resolution) -> 9:16 composition -> overlay -> captions.
- Format 3 blur is relative to canvas width (slider = sigma in px on a 540-wide canvas), so Live Preview and any export size look the same. Darken blends black over the background (0-0.8).
- Caption Fade In ON/OFF (`caption_style.fade_in_on`, default ON). OFF writes no `\t`/`\alpha`/`\fad` tags: captions appear instantly at cue start.
