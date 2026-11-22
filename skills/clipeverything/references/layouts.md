# Layouts

Every clip is 1080x1920. The tool picks a layout by sampling frames and looking for a face.

| Layout | When it is chosen | What you get |
|---|---|---|
| `stack` | A small face near an edge or corner (a facecam over gameplay, slides or a screen recording) | Facecam enlarged on top, the main picture below |
| `talking` | A large or centered face (podcast, interview, talking head, lecture) | 9:16 crop that follows the speaker's position |
| `screen` | No face found (screen recordings, code, maps, documentaries, b-roll) | The full picture, sharp, in the middle over a blurred copy of itself |
| `fill` | The source is already vertical | Scaled to fill |

## When the automatic choice is wrong

- Check a frame of the result (see SKILL.md step 5).
- Face detection is basic (OpenCV). It misses faces that are tiny, turned away, or covered by a game overlay.
- Force a layout with `--layout screen|talking|stack|fill`.
- For `stack` when the facecam was missed, give its box as fractions of the frame:
  `--facecam 0.74,0.03,0.24,0.30` means x, y, width, height (0-1). Look at a full frame first to measure it.
- Wide two-person podcast shots in `talking` may crop one person out. Use `--layout screen` to keep both in frame.
