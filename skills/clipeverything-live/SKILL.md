---
name: clipeverything-live
description: Clip a stream while it is still live (YouTube Live, Twitch, Kick, Facebook Live and other sites yt-dlp can open) into ready-to-post vertical clips with hook title and word-by-word captions. A clip is ready a few minutes after the moment happens. Use when the user says "live clip", "clip this stream", "clip it as it happens", and the link is a stream that is live right now. For finished videos use clipeverything.
---

# clipeverything-live

Records the stream in the background in 1-minute pieces (keeps the last 20 minutes), transcribes each piece as it lands,
and cuts clips from what is already on disk. Windows. Needs the `clipeverything` skill installed next to this one (it shares
its code) and `setup.ps1` already run.

`$PY` = `$env:USERPROFILE\.clipeverything\venv\Scripts\python.exe`
`$LIVE` = `$env:USERPROFILE\.claude\skills\clipeverything-live\scripts\live.py`
(Plugin install: find `live.py` with Glob.)

## Workflow

1. **Start.** `& $PY $LIVE start "<stream link>"`. If it says the link cannot be opened, the stream may be offline,
   private or login-only (see the cookies note in the README).
2. **Wait about 2 minutes**, then read what is happening: `& $PY $LIVE transcript --last 5`.
   `& $PY $LIVE status` shows how far transcription has got.
3. **Look for a moment** worth clipping using `../clipeverything/references/picking.md` (same rules; scores 7.5+ only, because
   live you cannot see what comes next - wait until the payoff has landed and a few seconds have passed).
   Check the transcript again every few minutes. Do not poll in a tight loop: use a wait of 2-5 minutes between checks.
4. **Cut it.** Times are recording time (the `[H:MM:SS]` in the transcript):
   `& $PY $LIVE clip --start 0:14:20 --end 0:14:58 --title "HOOK" --caption "..." --hashtags "#a #b"`
   or, for "the last bit": `--back 20 --length 40` (a clip of 40 seconds ending 20 seconds ago).
5. **Check a frame** of the clip (see the clipeverything skill), then tell the user the path.
6. **Stop** when the user says so or the stream ends: `& $PY $LIVE stop`.

## Limits to tell the user

- Only the last 20 minutes are kept, so a moment must be cut within 20 minutes.
- Live transcription uses the smaller `base` Whisper model so it keeps up; captions can have small mistakes.
  Set `CLIPEVERYTHING_LIVE_MODEL=small` for better accuracy on a fast PC.
- Live chat speed is not used (Windows version reads audio only).
- Clips go to `%USERPROFILE%\Clips\<date>\` like the normal skill.
