# How to pick clip moments

You are reading a transcript with timestamps, one line per spoken segment: `[H:MM:SS] [LOUD] text`.
`[LOUD]` means the audio was well above the speaker's normal volume (a shout, laugh or emphasis).
It is a hint, not a verdict: a loud segment of nothing is still nothing.

## Step 1: decide the content type

Decide from the title, description, chapters and the first chunk. Ask the user only if it is truly unclear.
The type changes what "good" means.

| Type | Examples | What makes a moment |
|---|---|---|
| **Teaching** | web development, coding, history, civilization, science, finance, language, lectures | One complete idea that makes sense alone: a surprising fact, a clear explanation of a hard thing, a myth being busted, a rule of thumb, a story with a payoff |
| **Conversation** | podcast, interview, debate, panel | A strong opinion, a disagreement, a confession, a funny exchange, a quotable line, a question and its best answer |
| **Reaction / gaming / stream** | gameplay, live streams, challenges | A big reaction (LOUD), a win or fail, a funny line, chat-worthy chaos. Here `[LOUD]` is a strong signal |
| **Story / documentary** | narrated history, vlogs | A scene with tension and a reveal; the sentence that makes you want to hear the next one |
| **Demo / tutorial** | screen recordings, how-tos | A before/after, a "this one trick" moment, a bug found and fixed, a result appearing |

## Step 2: score each candidate 1-10

Score, then keep only 7 and up. A video may honestly have zero clips; say so instead of padding.

Add points for:
- **Hook in the first 3 seconds**: starts with a claim, question, number or surprise. (+2)
- **Self-contained**: a stranger understands it with no context. (+2)
- **Payoff**: it ends on the answer, punchline or conclusion, not mid-thought. (+2)
- **Emotion or surprise**: laughter, shock, strong opinion, "wait, what?". (+1-2)
- **Quotable / shareable**: someone would send it to a friend. (+1)
- **Energy match**: `[LOUD]` on a reaction-type video. (+1)

Subtract for:
- Needs earlier context ("as I said before", "this one", "like I showed") (-2)
- Starts or ends mid-sentence, or on filler ("um", "so yeah") (-2)
- Pure setup with no payoff, housekeeping, sponsor reads, "like and subscribe", intros and outros (-3)
- Long silence or dead air (-2)

## Step 3: set the boundaries

- Length 25-55 seconds is ideal. Teaching content may run to 75 if the idea needs it. Never over 90.
- **Start** at the first word of the hook sentence, never in the middle of one. If the best line only works with
  one earlier sentence, include that sentence.
- **End** just after the payoff lands. Cut the "so..." that follows.
- Give timestamps as `H:MM:SS` copied from the transcript lines. The tool snaps to sentence edges, so
  being within a couple of seconds is fine.
- Do not pick overlapping moments. Spread picks across the video unless one section is clearly better.

## Step 4: write the title, caption and hashtags

- **Title** (shown on screen for 6 seconds): 4-8 words, in the clip's language. A question, a bold claim or the
  surprising fact. It must be true to the clip. Examples: "Rome fell for a boring reason", "Never use this CSS
  mistake again", "He did NOT expect that".
- **Caption**: one or two short sentences that would work as the post text. No fake claims.
- **Hashtags**: 3-6, specific to the topic (#romanempire #history, #webdev #css #frontend), plus one broad one at most.

## Output format while working

Keep a short list while you read: `start-end | score | one-line reason`. After the last chunk, pick the top N
(the user's number, default 3), best first, then render them.
