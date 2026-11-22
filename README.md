# clipeverything

Two free Claude Code skills that turn **any video** into ready-to-post vertical clips. Gaming, web development, history, civilization, podcasts, lectures, tutorials: any topic.

- **clipeverything** clips a finished video. Give it a link (YouTube, Facebook, Instagram, TikTok, X, Twitch, Kick, Vimeo, and anything else yt-dlp supports) or a video file on your PC.
- **clipeverything-live** clips a stream while it is still live.

Every clip comes out 1080x1920 with a hook title, word-by-word captions, and a `.txt` with a post caption and hashtags. The layout adapts to the video: facecam over gameplay or slides, a talking head, or a screen recording/documentary on a blurred background.

**Windows version.**

## Install

### Option A: paste this into Claude Code

```text
Install the clipeverything skills from https://github.com/eshunyhaw-del/clipeverything.
Clone the repo to a temporary folder, then copy BOTH folders inside its skills\ folder
(clipeverything and clipeverything-live) into %USERPROFILE%\.claude\skills\ so they sit side by side.
Then run: powershell -ExecutionPolicy Bypass -File "%USERPROFILE%\.claude\skills\clipeverything\scripts\setup.ps1"
Tell me what it installed and whether it says READY. Then remind me to restart Claude Code.
```

### Option B: as a plugin

```text
/plugin marketplace add eshunyhaw-del/clipeverything
/plugin install clipeverything@clipeverything
```

Then say **set up clipeverything**.

### Option C: by hand

```powershell
git clone https://github.com/eshunyhaw-del/clipeverything.git $env:TEMP\clipeverything
Copy-Item -Recurse $env:TEMP\clipeverything\skills\clipeverything, $env:TEMP\clipeverything\skills\clipeverything-live $env:USERPROFILE\.claude\skills\
powershell -ExecutionPolicy Bypass -File $env:USERPROFILE\.claude\skills\clipeverything\scripts\setup.ps1
```

Setup uses winget to install what is missing (FFmpeg, Deno, Python 3.12 if you have no Python 3.10-3.13), makes a Python environment in `%USERPROFILE%\.clipeverything\venv` (yt-dlp, faster-whisper, OpenCV) and downloads the Whisper `small` speech model (about 460 MB). Re-run it any time downloads start failing; it updates yt-dlp.

## Use it

Open Claude Code and say:

- **clip this video** `<link>`
- **find the best 5 moments in this** `<link>` **for TikTok**
- **clip this history lecture** `<file path>`
- **clip a video** (finds a reusable one for you)
- **live clip** `<link>` (for a stream that is live right now)

Clips land in `%USERPROFILE%\Clips\<date>\`. Each has an `.mp4` and a `.txt` with title, caption and hashtags.

## Find something to clip (clipeverything-scout)

Say **clip a video** or **find me a video about stoicism to clip**. The `clip-scout` agent searches YouTube's Creative Commons filter across your niches (science, psychology, religion, philosophy, language, tech) or the topic you name, then verifies each video's license (CC BY) before suggesting it, skips videos you already clipped, and recommends one. Then the normal clipeverything workflow takes over. If search is blocked or nothing fits, paste a link instead and it will tell you whether that video is CC BY.

Read `skills/clipeverything-scout/references/monetization.md` before posting reused clips: a CC BY license gives you copyright permission, but YouTube can still limit monetization on channels that mostly reuse other people's content without adding their own value.

For the agent, copy `agents\clip-scout.md` to `%USERPROFILE%\.claude\agents\` (the plugin install does this for you).

## How it works

| Step | Finished video | Live stream |
|---|---|---|
| 1. Get the video | Downloads the audio only | Records 1-minute pieces, keeps the last 20 min |
| 2. Speech to text | Whole video once (faster-whisper) | Each minute as it lands |
| 3. Find energy | Loud seconds (8 dB above the speaker's own normal) | Loud seconds per piece |
| 4. Pick the moments | Claude reads 10-minute chunks and scores them by content type (teaching, conversation, gaming, story, demo) | Claude reads the last minutes and picks 7.5+ |
| 5. Make the clip | Downloads only those minutes, detects layout, burns title and captions | Cuts from the pieces on disk |

Picking is the only AI step. The rules are in `skills/clipeverything/references/picking.md`; edit that file to change what "a good moment" means for your content.

## Instagram, Facebook and login-only videos

Public videos usually work. If a link fails, set one of these before starting Claude Code:

```powershell
$env:CLIPEVERYTHING_COOKIES_BROWSER = "firefox"     # firefox works best on Windows; chrome/edge can be locked
$env:CLIPEVERYTHING_COOKIES_FILE = "C:\path\cookies.txt"   # alternative: exported cookies.txt
```

Private videos cannot be clipped. Never commit a cookies file.

## Settings (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `CLIPEVERYTHING_OUT` | `%USERPROFILE%\Clips` | Where clips are saved |
| `CLIPEVERYTHING_MODEL` | `small` | Whisper model for finished videos (`base` faster, `medium` more accurate) |
| `CLIPEVERYTHING_LIVE_MODEL` | `base` | Whisper model for live |
| `CLIPEVERYTHING_HOME` | `%USERPROFILE%\.clipeverything` | Work folder and Python environment |

## Notes

- Only transcription, loudness and cutting run on your PC; picking uses Claude. You can point Claude Code at a local model (for example through Ollama) to run free, with rougher picks.
- Face detection is basic. If a layout looks wrong, tell Claude which one to use (`talking`, `stack`, `screen`) or where the facecam is.
- Check that you have the right to repost the source video before you publish clips of someone else's content.

## License

MIT
