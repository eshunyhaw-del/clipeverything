#!/usr/bin/env python3
"""clipeverything - turn any video into ready-to-post vertical clips.

Commands
  doctor                 check that everything is installed
  prepare SOURCE         download audio, transcribe, find loud moments, write
                         transcript chunks for Claude to read
  cut WORKDIR            render one 1080x1920 clip (layout, hook title,
                         word-by-word captions, post text)

SOURCE is a URL (YouTube, Facebook, Instagram, TikTok, X, Twitch, Kick, Vimeo...
anything yt-dlp supports) or a path to a video file on this PC.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import wave
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HOME = Path.home()
BASE = Path(os.environ.get("CLIPEVERYTHING_HOME", HOME / ".clipeverything"))
WORK_ROOT = BASE / "work"
OUT_ROOT = Path(os.environ.get("CLIPEVERYTHING_OUT", HOME / "Clips"))
W, H = 1080, 1920
VIDEO_FMT = "bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b"


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def die(msg, code=1):
    print(json.dumps({"ok": False, "error": msg}), flush=True)
    log("ERROR:", msg)
    sys.exit(code)


def run(cmd, **kw):
    cmd = [str(c) for c in cmd]
    log("$", " ".join(cmd)[:400])
    if "stdout" not in kw and "capture_output" not in kw:
        kw["stdout"] = sys.stderr  # keep stdout clean: it carries the JSON result
    return subprocess.run(cmd, **kw)


def is_url(s: str) -> bool:
    return bool(re.match(r"^https?://", s.strip(), re.I))


def ytdlp_base():
    cmd = [sys.executable, "-m", "yt_dlp", "--no-warnings", "--no-playlist"]
    cookie_file = os.environ.get("CLIPEVERYTHING_COOKIES_FILE")
    browser = os.environ.get("CLIPEVERYTHING_COOKIES_BROWSER")
    if cookie_file:
        cmd += ["--cookies", cookie_file]
    elif browser:
        cmd += ["--cookies-from-browser", browser]
    return cmd


def work_id(source: str) -> str:
    key = source if is_url(source) else str(Path(source).expanduser().resolve())
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def fmt_ts(sec: float) -> str:
    sec = max(0, int(sec))
    return f"{sec // 3600}:{(sec // 60) % 60:02d}:{sec % 60:02d}"


def parse_ts(v) -> float:
    s = str(v).strip()
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return float(s)
    parts = [float(p) for p in s.split(":")]
    out = 0.0
    for p in parts:
        out = out * 60 + p
    return out


def slugify(s: str, n: int = 60) -> str:
    s = re.sub(r"[^\w\s-]", "", s, flags=re.U).strip().lower()
    s = re.sub(r"[\s_-]+", "-", s)
    return (s[:n].strip("-")) or "clip"


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height:format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True).stdout
    j = json.loads(out)
    s = j["streams"][0]
    return int(s["width"]), int(s["height"]), float(j["format"].get("duration") or 0)


# --------------------------------------------------------------------------
# transcription (shared with live.py)
# --------------------------------------------------------------------------

_MODEL_CACHE = {}


def load_model(name="small"):
    if name in _MODEL_CACHE:
        return _MODEL_CACHE[name]
    from faster_whisper import WhisperModel
    device, ctype = "cpu", "int8"
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            device, ctype = "cuda", "float16"
    except Exception:
        pass
    log(f"loading Whisper model '{name}' on {device}")
    m = WhisperModel(name, device=device, compute_type=ctype)
    _MODEL_CACHE[name] = m
    return m


def transcribe(wav, model_name="small", language=None, offset=0.0, progress=True):
    """Return {'language', 'segments':[{start,end,text,words:[{w,s,e}]}]}."""
    model = load_model(model_name)
    segs, info = model.transcribe(
        str(wav), language=language, word_timestamps=True,
        vad_filter=True, beam_size=1, condition_on_previous_text=False)
    out, next_report = [], 60
    for sg in segs:
        words = [{"w": w.word.strip(), "s": round(w.start + offset, 2), "e": round(w.end + offset, 2)}
                 for w in (sg.words or []) if w.word.strip()]
        out.append({"start": round(sg.start + offset, 2), "end": round(sg.end + offset, 2),
                    "text": sg.text.strip(), "words": words})
        if progress and sg.end >= next_report:
            log(f"  transcribed {fmt_ts(sg.end)}")
            next_report = sg.end + 300
    return {"language": info.language, "segments": out}


def loudness_db(wav):
    """dB level of every second of a 16 kHz mono wav."""
    import numpy as np
    vals = []
    with wave.open(str(wav), "rb") as wf:
        sr = wf.getframerate()
        while True:
            raw = wf.readframes(sr * 60)
            if not raw:
                break
            x = np.frombuffer(raw, dtype=np.int16).astype("float32") / 32768.0
            n = len(x) // sr
            if n:
                sec = x[: n * sr].reshape(n, sr)
                rms = np.sqrt((sec ** 2).mean(axis=1))
                vals.extend((20 * np.log10(rms + 1e-9)).tolist())
            rest = x[n * sr:]
            if len(rest) > sr // 2:
                vals.append(float(20 * np.log10(np.sqrt((rest ** 2).mean()) + 1e-9)))
    return vals


def find_loud(db, margin):
    import numpy as np
    arr = np.array(db)
    voiced = arr[arr > -55]
    base = float(np.median(voiced)) if len(voiced) else -30.0
    loud = [i for i, v in enumerate(db) if v >= base + margin]
    return base, loud


def peaks_from_loud(db, loud_set, base, top=40, win=6):
    """Group loud seconds into windows and rank them."""
    if not loud_set:
        return []
    secs = sorted(loud_set)
    groups, cur = [], [secs[0]]
    for s in secs[1:]:
        if s - cur[-1] <= win:
            cur.append(s)
        else:
            groups.append(cur)
            cur = [s]
    groups.append(cur)
    ranked = []
    for g in groups:
        peak = max(db[s] for s in g)
        ranked.append({"start": g[0], "end": g[-1] + 1, "seconds_loud": len(g),
                       "peak_db_over_normal": round(peak - base, 1)})
    ranked.sort(key=lambda r: (r["seconds_loud"] * r["peak_db_over_normal"]), reverse=True)
    return ranked[:top]


# --------------------------------------------------------------------------
# prepare
# --------------------------------------------------------------------------

def cmd_prepare(a):
    src = a.source.strip().strip('"')
    wd = WORK_ROOT / work_id(src)
    wd.mkdir(parents=True, exist_ok=True)
    meta_path, wav, tr_path = wd / "meta.json", wd / "audio.wav", wd / "transcript.json"
    local = not is_url(src)

    if not meta_path.exists() or not wav.exists():
        if local:
            media = Path(src).expanduser().resolve()
            if not media.exists():
                die(f"file not found: {media}")
            _, _, dur = probe(media)
            meta = {"title": media.stem, "source": str(media), "local": True, "duration": dur}
        else:
            log("reading video info...")
            r = run(ytdlp_base() + ["--dump-single-json", "--skip-download", src],
                    capture_output=True, text=True, encoding="utf-8")
            if r.returncode != 0:
                die("could not read that link: " + (r.stderr or "").strip()[-600:] +
                    "  (Instagram/Facebook may need login cookies - see README)")
            info = json.loads(r.stdout)
            if info.get("is_live"):
                die("this is a LIVE stream - use the clipeverything-live skill instead")
            meta = {k: info.get(k) for k in (
                "id", "title", "uploader", "channel", "duration", "webpage_url",
                "upload_date", "tags", "categories", "chapters", "license")}
            meta["description"] = (info.get("description") or "")[:800]
            meta["source"] = src
            meta["local"] = False
            log("downloading audio...")
            for f in wd.glob("dl.*"):
                f.unlink()
            r = run(ytdlp_base() + ["-f", "bestaudio/best", "-o", str(wd / "dl.%(ext)s"), src])
            media = next((f for f in wd.glob("dl.*") if f.suffix != ".json"), None)
            if r.returncode != 0 or not media:
                die("audio download failed (private video, or login needed?)")
        log("converting audio...")
        r = run(["ffmpeg", "-y", "-v", "error", "-i", str(media), "-vn", "-ac", "1", "-ar", "16000",
                 str(wav)])
        if r.returncode != 0:
            die("ffmpeg could not read the audio")
        if not local:
            media.unlink(missing_ok=True)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if not local and "license" not in meta:  # work folder made by an older version: add the license
        r = run(ytdlp_base() + ["--dump-single-json", "--skip-download", src],
                capture_output=True, text=True, encoding="utf-8")
        try:
            meta["license"] = json.loads(r.stdout).get("license")
        except Exception:
            meta["license"] = None
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    if not tr_path.exists():
        log("transcribing (this is the slow part; ~1 min per 10 min of video on a normal PC)...")
        tr = transcribe(wav, a.model, a.language)
        tr_path.write_text(json.dumps(tr, ensure_ascii=False), encoding="utf-8")
    tr = json.loads(tr_path.read_text(encoding="utf-8"))

    log("measuring loud moments...")
    db = loudness_db(wav)
    base, loud = find_loud(db, a.loud_db)
    loud_set = set(loud)
    peaks = peaks_from_loud(db, loud_set, base)
    (wd / "hype.json").write_text(json.dumps(
        {"normal_db": round(base, 1), "loud_margin_db": a.loud_db, "peaks": peaks}, indent=1),
        encoding="utf-8")

    # chunk files for Claude to read
    cdir = wd / "chunks"
    if cdir.exists():
        shutil.rmtree(cdir)
    cdir.mkdir()
    span = a.chunk_minutes * 60
    chunks, cur, cur_idx = [], [], 0
    for sg in tr["segments"]:
        idx = int(sg["start"] // span)
        if idx != cur_idx and cur:
            chunks.append((cur_idx, cur))
            cur = []
        cur_idx = idx
        cur.append(sg)
    if cur:
        chunks.append((cur_idx, cur))
    files = []
    for n, (_, segs) in enumerate(chunks, 1):
        lines = [f"# chunk {n}: {fmt_ts(segs[0]['start'])} - {fmt_ts(segs[-1]['end'])}"]
        for sg in segs:
            s0, s1 = int(sg["start"]), int(sg["end"]) + 1
            tag = " [LOUD]" if any(i in loud_set for i in range(s0, s1)) else ""
            lines.append(f"[{fmt_ts(sg['start'])}]{tag} {sg['text']}")
        p = cdir / f"chunk_{n:02d}.txt"
        p.write_text("\n".join(lines), encoding="utf-8")
        files.append(str(p))

    print(json.dumps({
        "ok": True, "workdir": str(wd), "title": meta.get("title"),
        "uploader": meta.get("uploader") or meta.get("channel"),
        "duration": fmt_ts(meta.get("duration") or 0), "language": tr["language"],
        "chapters": [{"start": fmt_ts(c["start_time"]), "title": c["title"]}
                     for c in (meta.get("chapters") or [])],
        "chunks": files, "loud_peaks": len(peaks), "hype_file": str(wd / "hype.json"),
    }, ensure_ascii=False, indent=1))


# --------------------------------------------------------------------------
# layout detection
# --------------------------------------------------------------------------

def even(v):
    v = int(round(v))
    return v - (v % 2)


def detect_layout(src, ss, dur, sw, sh, forced=None, facecam=None):
    """Decide how to turn the source frame into a 9:16 picture."""
    if sw < sh:
        return {"layout": "fill"}
    if forced in ("screen", "fill"):
        return {"layout": forced}

    face = None
    if facecam:  # user-supplied "x,y,w,h" as fractions of the frame
        x, y, w, h = [float(v) for v in facecam.split(",")]
        face = (x + w / 2, y + h / 2, w, h)
    else:
        try:
            import cv2
            cap = cv2.VideoCapture(str(src))
            cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
            found = []
            n = 8
            for i in range(n):
                cap.set(cv2.CAP_PROP_POS_MSEC, (ss + dur * (i + 0.5) / n) * 1000)
                ok, fr = cap.read()
                if not ok:
                    continue
                if fr.shape[1] > 960:
                    k = 960 / fr.shape[1]
                    fr = cv2.resize(fr, None, fx=k, fy=k)
                g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
                gh, gw = g.shape
                f = cascade.detectMultiScale(g, 1.1, 6, minSize=(int(gw * 0.03),) * 2)
                if len(f):
                    x, y, w, h = max(f, key=lambda r: r[2] * r[3])
                    found.append(((x + w / 2) / gw, (y + h / 2) / gh, w / gw, h / gh))
            cap.release()
            if len(found) >= 3:
                found.sort()
                mid = found[len(found) // 2]
                cx = sorted(f[0] for f in found)[len(found) // 2]
                cy = sorted(f[1] for f in found)[len(found) // 2]
                fw = sorted(f[2] for f in found)[len(found) // 2]
                fh = sorted(f[3] for f in found)[len(found) // 2]
                face = (cx, cy, fw, fh)
        except Exception as e:  # opencv missing or video unreadable
            log("face detection skipped:", e)

    if face is None:
        if forced == "talking":
            face = (0.5, 0.4, 0.2, 0.3)
        elif forced == "stack":
            face = (0.85, 0.15, 0.2, 0.28)  # guess: top-right corner webcam
        else:
            return {"layout": "screen"}
    cx, cy, fw, fh = face
    # a webcam overlay sits in a corner of the frame; a talking head is central or fills the shot
    in_corner = (cx < 0.3 or cx > 0.7) and (cy < 0.35 or cy > 0.65) and fw < 0.35
    use_stack = forced == "stack" or (forced is None and (in_corner or facecam))
    if forced == "talking" or not use_stack:
        crop_w = even(sh * 9 / 16)
        x = min(max(cx * sw - crop_w / 2, 0), sw - crop_w)
        return {"layout": "talking", "crop": (crop_w, even(sh), even(x), 0)}

    # small face near an edge = facecam overlay on top of gameplay / slides / screen
    top_h = 700
    cw = min(max(fw * sw * 3.0, sw * 0.16), sw * 0.5)
    chh = cw * top_h / W
    if chh > sh:
        chh, cw = sh, sh * W / top_h
    fx = min(max(cx * sw - cw / 2, 0), sw - cw)
    fy = min(max(cy * sh - chh * 0.45, 0), sh - chh)
    bot_h = H - top_h
    gw = sh * W / bot_h
    if gw > sw:
        return {"layout": "screen"}
    gx = (sw - gw) / 2
    return {"layout": "stack", "cam": (even(cw), even(chh), even(fx), even(fy)),
            "game": (even(gw), even(sh), even(gx), 0), "top_h": top_h}


def build_filter(info, sw, sh, ass_name):
    lay = info["layout"]
    tail = f"ass={ass_name},format=yuv420p[v]"
    if lay == "stack":
        cw, chh, fx, fy = info["cam"]
        gw, gh, gx, gy = info["game"]
        th = info["top_h"]
        return (f"[0:v]split=2[a][b];"
                f"[a]crop={cw}:{chh}:{fx}:{fy},scale={W}:{th}:flags=lanczos[top];"
                f"[b]crop={gw}:{gh}:{gx}:{gy},scale={W}:{H - th}:flags=lanczos[bot];"
                f"[top][bot]vstack=inputs=2,{tail}")
    if lay == "talking":
        cw, ch, x, y = info["crop"]
        return f"[0:v]crop={cw}:{ch}:{x}:{y},scale={W}:{H}:flags=lanczos,{tail}"
    if lay == "fill":
        return f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},{tail}"
    # screen: sharp picture in the middle over a blurred copy of itself
    return (f"[0:v]split=2[a][b];"
            f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=28:6[bg];"
            f"[b]scale={W}:-2:flags=lanczos[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,{tail}")


# --------------------------------------------------------------------------
# captions (ASS) + render
# --------------------------------------------------------------------------

def ass_time(t):
    cs = max(0, int(round(t * 100)))
    return f"{cs // 360000}:{(cs // 6000) % 60:02d}:{(cs // 100) % 60:02d}.{cs % 100:02d}"


def _clean(t):
    return t.replace("\\", "").replace("{", "").replace("}", "")


def build_ass(path, words, abs_start, dur, title, layout):
    """words: [{'w','s','e'}] in source time; abs_start: source time of clip start."""
    ws = [{"w": _clean(w["w"]), "s": w["s"] - abs_start, "e": w["e"] - abs_start}
          for w in words if w["e"] > abs_start and w["s"] < abs_start + dur]
    for w in ws:
        w["s"] = max(0.0, w["s"])
        w["e"] = min(dur, w["e"])
    groups, cur = [], []
    for w in ws:
        if cur and (len(cur) >= 3 or w["s"] - cur[-1]["e"] > 0.8 or re.search(r"[.?!]$", cur[-1]["w"])):
            groups.append(cur)
            cur = []
        cur.append(w)
    if cur:
        groups.append(cur)

    cap_y = 1230 if layout == "stack" else 1280
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
        "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Cap,Arial,86,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,8,2,5,60,60,0,1",
        "Style: Title,Arial,62,&H00000000,&H000000FF,&H00FFFFFF,&H00000000,-1,0,0,0,100,100,0,0,3,16,0,8,70,70,0,1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    if title:
        wrapped = textwrap.wrap(title.upper(), 22)[:3]
        lines.append(f"Dialogue: 1,{ass_time(0)},{ass_time(min(6.0, dur))},Title,,0,0,0,,"
                     f"{{\\an8\\pos(540,110)\\fad(150,300)}}" + "\\N".join(wrapped))
    for gi, grp in enumerate(groups):
        nxt = groups[gi + 1][0]["s"] if gi + 1 < len(groups) else dur
        for wi, w in enumerate(grp):
            s = w["s"]
            e = grp[wi + 1]["s"] if wi + 1 < len(grp) else min(max(w["e"], s + 0.25) + 0.15, nxt)
            if e <= s:
                continue
            txt = " ".join(
                ("{\\c&H00D7FF&}" + g["w"].upper() + "{\\c&HFFFFFF&}") if k == wi else g["w"].upper()
                for k, g in enumerate(grp))
            lines.append(f"Dialogue: 0,{ass_time(s)},{ass_time(e)},Cap,,0,0,0,,"
                         f"{{\\an5\\pos(540,{cap_y})}}{txt}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def render_clip(src, ss, dur, words, abs_start, title, out_mp4, workdir,
                layout=None, facecam=None, tag="clip"):
    """Cut src[ss:ss+dur] into a 1080x1920 mp4 with title + captions.
    words are in the source's timeline; abs_start is the source time at which the clip begins."""
    src = Path(src).resolve()
    workdir = Path(workdir).resolve()
    out_mp4 = Path(out_mp4).resolve()
    sw, sh, _ = probe(src)
    info = detect_layout(src, ss, dur, sw, sh, layout, facecam)
    log("layout:", info["layout"])
    ass_name = f"{tag}.ass"
    build_ass(workdir / ass_name, words, abs_start, dur, title, info["layout"])
    fc = build_filter(info, sw, sh, ass_name)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{ss:.3f}", "-t", f"{dur:.3f}", "-i", str(src),
           "-filter_complex", fc, "-map", "[v]", "-map", "0:a?",
           "-c:v", "libx264", "-preset", "medium", "-crf", "22", "-pix_fmt", "yuv420p",
           "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k",
           "-movflags", "+faststart", str(out_mp4)]
    r = run(cmd, cwd=str(workdir))
    if r.returncode != 0 or not out_mp4.exists():
        die("ffmpeg render failed (see messages above)")
    return info["layout"]


def credit_block(meta):
    """Credit text for the post, based on the source's license (read from yt-dlp)."""
    if not meta:
        return ""
    if meta.get("local"):
        return "CREDIT: local file - make sure you own it or have permission to post it."
    lic = (meta.get("license") or "").strip()
    who = meta.get("uploader") or meta.get("channel") or "the creator"
    url = meta.get("webpage_url") or meta.get("source") or ""
    title = meta.get("title") or ""
    if "creative commons" in lic.lower():
        return ("CREDIT (the license requires this - paste it into your post):\n\n"
                "### Content Attribution\n\n"
                f"**Original Title:** {title}\n\n"
                f"**Creator:** {who}\n\n"
                f"**Source:** {url}\n\n"
                "**Licence:** Creative Commons Attribution (CC BY).\n\n"
                "This material is used under the Creative Commons Attribution licence. "
                "Modifications have been made where applicable.")
    return ("CREDIT - NO REUSE LICENSE DETECTED: this is probably standard copyright. Get the creator's "
            "permission before posting publicly.\n"
            f'If you have permission, credit it like: "Clip from "{title}" by {who}, {url}, used with permission."')


def write_post_text(path, title, caption, hashtags, source, start, end, meta=None):
    tags = hashtags.strip()
    if tags and not tags.startswith("#"):
        tags = " ".join("#" + t.lstrip("#") for t in re.split(r"[,\s]+", tags) if t)
    credit = credit_block(meta)
    Path(path).write_text(
        f"TITLE: {title}\n\nCAPTION:\n{caption}\n\n{tags}\n\n"
        + (credit + "\n\n" if credit else "")
        + f"SOURCE: {source}\nTIME: {fmt_ts(start)} - {fmt_ts(end)}\n", encoding="utf-8")


# --------------------------------------------------------------------------
# cut
# --------------------------------------------------------------------------

def get_source_video(wd, meta, start, end):
    """Return (video_path, time_in_original_that_the_file_starts_at)."""
    if meta.get("local"):
        return Path(meta["source"]), 0.0
    full = next(iter(wd.glob("full.*")), None)
    if full:
        return full, 0.0
    url = meta["source"]
    sec = wd / f"seg_{int(start)}_{int(end)}.mp4"
    if not sec.exists():
        log("downloading just this part of the video...")
        run(ytdlp_base() + ["-f", VIDEO_FMT, "--download-sections", f"*{start:.2f}-{end:.2f}",
                            "--force-keyframes-at-cuts", "--merge-output-format", "mp4",
                            "-o", str(sec), url])
    if sec.exists():
        try:
            _, _, d = probe(sec)
            if abs(d - (end - start)) <= 6:
                return sec, start
        except Exception:
            pass
        sec.unlink(missing_ok=True)
    log("partial download not possible for this site - downloading the whole video...")
    r = run(ytdlp_base() + ["-f", VIDEO_FMT, "--merge-output-format", "mp4",
                            "-o", str(wd / "full.%(ext)s"), url])
    full = next(iter(wd.glob("full.*")), None)
    if r.returncode != 0 or not full:
        die("video download failed (private video, or login needed?)")
    return full, 0.0


def snap(segs, start, end, reach=4.0):
    for sg in segs:
        if sg["start"] <= start < sg["end"] and start - sg["start"] <= reach:
            start = sg["start"]
            break
    for sg in segs:
        if sg["start"] < end <= sg["end"] + 0.01 and sg["end"] - end <= reach:
            end = sg["end"]
            break
    return start, end


def cmd_cut(a):
    wd = Path(a.workdir)
    if not (wd / "meta.json").exists():
        die(f"{wd} is not a prepared work folder (run prepare first)")
    meta = json.loads((wd / "meta.json").read_text(encoding="utf-8"))
    tr = json.loads((wd / "transcript.json").read_text(encoding="utf-8"))
    start, end = parse_ts(a.start), parse_ts(a.end)
    if end <= start:
        die("end must be after start")
    if not a.no_snap:
        start, end = snap(tr["segments"], start, end)
    if end - start > a.max_len:
        end = start + a.max_len
    start = max(0.0, start - 0.15)
    end = end + 0.35
    dur = end - start

    video, t0 = get_source_video(wd, meta, start, end)
    words = [] if a.no_captions else [w for sg in tr["segments"] for w in sg["words"]]
    day = OUT_ROOT / dt.date.today().isoformat()
    name = a.name or slugify(a.title)
    out = day / f"{name}.mp4"
    n = 2
    while out.exists() and not a.overwrite:
        out = day / f"{name}-{n}.mp4"
        n += 1
    layout = render_clip(video, start - t0, dur, words, start, a.title, out, wd,
                         a.layout if a.layout != "auto" else None, a.facecam, tag=out.stem[:40])
    write_post_text(out.with_suffix(".txt"), a.title, a.caption or "", a.hashtags or "",
                    meta.get("webpage_url") or meta.get("source"), start, end, meta)
    print(json.dumps({"ok": True, "clip": str(out), "post_text": str(out.with_suffix(".txt")),
                      "layout": layout, "length_seconds": round(dur, 1),
                      "from": fmt_ts(start), "to": fmt_ts(end)}, indent=1))


# --------------------------------------------------------------------------
# doctor
# --------------------------------------------------------------------------

def cmd_doctor(_a):
    ok = True

    def check(name, good, fix=""):
        nonlocal ok
        print(f"  [{'ok' if good else 'MISSING'}] {name}" + ("" if good else f"  -> {fix}"))
        ok = ok and good

    print("clipeverything check")
    check("ffmpeg", bool(shutil.which("ffmpeg")), "winget install Gyan.FFmpeg")
    check("ffprobe", bool(shutil.which("ffprobe")), "winget install Gyan.FFmpeg")
    for mod, pip in (("yt_dlp", "yt-dlp"), ("faster_whisper", "faster-whisper"),
                     ("cv2", "\"opencv-python-headless<5\""), ("numpy", "numpy")):
        try:
            m = __import__(mod)
            good = hasattr(m, "CascadeClassifier") if mod == "cv2" else True
        except Exception:
            good = False
        check(mod, good, f"pip install {pip}")
    if not shutil.which("deno") and not shutil.which("node"):
        print("  [warn] no Deno/Node found - YouTube may fail. Fix: winget install DenoLand.Deno")
    print("READY" if ok else "NOT READY - run scripts/setup.ps1 again")
    sys.exit(0 if ok else 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor").set_defaults(fn=cmd_doctor)

    p = sub.add_parser("prepare")
    p.add_argument("source")
    p.add_argument("--model", default=os.environ.get("CLIPEVERYTHING_MODEL", "small"))
    p.add_argument("--language", default=None, help="e.g. en (default: auto-detect)")
    p.add_argument("--chunk-minutes", type=int, default=10)
    p.add_argument("--loud-db", type=float, default=8.0, help="dB above the speaker's normal that counts as loud")
    p.set_defaults(fn=cmd_prepare)

    c = sub.add_parser("cut")
    c.add_argument("workdir")
    c.add_argument("--start", required=True)
    c.add_argument("--end", required=True)
    c.add_argument("--title", required=True, help="on-screen hook title")
    c.add_argument("--caption", default="")
    c.add_argument("--hashtags", default="")
    c.add_argument("--name", default=None)
    c.add_argument("--layout", default="auto", choices=["auto", "stack", "talking", "screen", "fill"])
    c.add_argument("--facecam", default=None, help="x,y,w,h as 0-1 fractions, if auto-detect gets it wrong")
    c.add_argument("--max-len", type=float, default=90.0)
    c.add_argument("--no-snap", action="store_true")
    c.add_argument("--no-captions", action="store_true",
                   help="skip our captions (use when the source already has subtitles burned in)")
    c.add_argument("--overwrite", action="store_true")
    c.set_defaults(fn=cmd_cut)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
