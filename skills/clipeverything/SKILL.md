---
name: clipeverything
description: Turn any finished video (YouTube, Facebook, Instagram, TikTok, X, Twitch, Kick, Vimeo, or a file on this PC) into ready-to-post vertical clips (1080x1920) with a hook title, word-by-word captions and a post caption with hashtags. Works for any topic - gaming, web development, history, civilization, podcasts, lectures, interviews, tutorials. Use when the user says "clip this", "find the best moments", "make shorts/reels/tiktoks from this video", or gives a video link and wants clips. For streams that are live right now, use clipeverything-live instead.
---

# clipeverything

Finds the best moments in a video and renders them as vertical clips. Windows.

Python runs from the venv that `setup.ps1` made. In every command below, `$PY` means
`$env:USERPROFILE\.clipeverything\venv\Scripts\python.exe` and `$CLIP` means
`$env:USERPROFILE\.claude\skills\clipeverything\scripts\clip.py`.
(If the skill was installed as a plugin, `$CLIP` is `scripts\clip.py` inside the plugin folder; find it with Glob.)

## First run

Run `& $PY $CLIP doctor`. If it does not say READY, run
`powershell -ExecutionPolicy Bypass -File <skill folder>\scripts\setup.ps1` and then doctor again.
If `$PY` does not exist, setup has never been run.

## Workflow

1. **Understand the ask.** Get the link or file path. Note anything the user said about the
   topic, how many clips, how long, or the platform. Defaults: 3 clips, 25-55 seconds each.
   If the user gives a topic instead of a link, search:
   `& $PY -m yt_dlp "ytsearch8:<topic>" --flat-playlist --print "%(webpage_url)s | %(title)s | %(view_count)s views | %(duration_string)s"`
   and let them choose.
2. **Prepare.** `& $PY $CLIP prepare "<link or path>"`
   This downloads audio only, transcribes it with Whisper, finds loud moments and writes
   transcript chunks. It prints JSON with `workdir` and `chunks`. It can take several minutes for long videos; run it
   in the background if the video is over an hour and tell the user.
   If it says the video is LIVE, switch to the clipeverything-live skill.
3. **Pick the moments.** Read `references/picking.md` first. Then read every chunk file in order
   and choose moments the way that file describes. Read the video title, chapters and `hype.json`
   too: they are strong hints. Do not skip chunks.
4. **Render each clip.**
   ```
   & $PY $CLIP cut "<workdir>" --start 12:34 --end 13:10 --title "HOOK TITLE" --caption "post caption" --hashtags "#a #b #c"
   ```
   Only that part of the video is downloaded. Start and end snap to sentence boundaries.
   Use `--layout talking|stack|screen|fill` only if the automatic layout looks wrong
   (see `references/layouts.md`).
5. **Check at least one clip** by pulling a frame:
   `ffmpeg -y -ss 3 -i "<clip.mp4>" -frames:v 1 "<workdir>\check.png"` and looking at it.
   Fix layout problems before reporting.
6. **Report.** For each clip: file path, time range in the source, the title and why you picked it. Clips are in
   `%USERPROFILE%\Clips\<date>\` with a `.txt` next to each (title, caption, hashtags, source link).

## Rules

- Never invent what was said. Titles and captions come from the transcript.
- Titles: max ~8 words, a hook or a question, no clickbait that the clip does not deliver.
- Captions: one or two short sentences in the speaker's language, then 3-6 hashtags that fit the *topic*
  (not generic spam).
- If the download fails on Instagram or Facebook, the post is probably login-only. Tell the user to set
  `CLIPEVERYTHING_COOKIES_BROWSER` (e.g. `firefox`) or `CLIPEVERYTHING_COOKIES_FILE` as described in the README. Private videos cannot be clipped.
- The user is responsible for having the right to repost the source video. Mention it once if the source is
  someone else's content and the user is posting publicly; do not lecture.
