---
name: clipeverything-scout
description: Find a YouTube video that can legally be reused (Creative Commons Attribution) and is worth clipping, then clip it with the clipeverything skill. Use when the user says "clip a video", "find me something to clip", "find a video about <topic> to clip", or has no link yet. Searches the channel's niches (science, psychology, religion, philosophy, language, tech) or any topic the user names, and checks each video's license before suggesting it.
---

# clipeverything-scout

Finds reusable videos so the user does not have to hunt for one. The user's channel covers science, psychology,
religion, philosophy, language and tech, so any of those is a good fit unless they name a topic.

`$PY` = `$env:USERPROFILE\.clipeverything\venv\Scripts\python.exe`
`$SCOUT` = `$env:USERPROFILE\.claude\skills\clipeverything-scout\scripts\scout.py`
(It needs the `clipeverything` skill installed beside it and `setup.ps1` already run.)

## Workflow

1. **Search.** With a topic: `& $PY $SCOUT search "stoicism"`. Without one, search the niches:
   `& $PY $SCOUT search` (about a minute). Add `--max-minutes 60` for shorter videos.
   Every result is license-verified as Creative Commons Attribution by checking the video itself, not just the search filter.
   Videos already clipped before are skipped.
2. **Choose.** Show the user the top 3-5 as a short table (title, channel, minutes, views, topic). Recommend one:
   prefer 10-60 minutes, spoken content (lectures, talks, explainers, interviews), chapters present, and a
   topic that fits the channel. Skip anything that is mostly music, gameplay or slideshow with no speech.
   Unless the user wants to choose, go ahead with your top pick and say which one.
3. **Warn once, briefly.** Read `references/monetization.md` and give the user the two or three points that matter for
   this video (it is short). Do not repeat the whole file.
4. **Clip it.** Hand off to the `clipeverything` skill with the chosen URL (default 3 clips, 25-55 s). Use its normal
   workflow, including the CC BY credit in each `.txt`.
5. **If search fails** (YouTube blocks it, nothing verified, or no good match): say so and ask the user to paste a link.
   For a pasted link, run `& $PY $SCOUT check "<url>"` first and tell them whether it is CC BY. If it is not, say
   the credit file will warn them to get permission.

## Rules

- Only suggest videos that came back verified. Never claim a video is reusable from its title or channel alone.
- Another person's channel and videos stay theirs: always keep the credit text with the clip.
- Do not clip more than the user asked for, and do not clip several videos from the same channel in one go unless asked.
