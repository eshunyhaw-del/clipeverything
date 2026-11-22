#!/usr/bin/env python3
"""clipeverything-live - clip a stream while it is still live.

  start URL        begin recording in the background (1-minute pieces, last 20 min kept)
  status           is it running, how far along, latest words
  transcript       print what was said (use --last 5 for the last 5 minutes)
  clip             cut a moment (--start/--end in recording time, or --back/--length)
  stop             stop recording

Recording time = seconds since `start`; the transcript shows it as [H:MM:SS].
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "clipeverything" / "scripts"))
import clip as C  # noqa: E402

SEG_SECONDS = 60
KEEP_MINUTES = 20
LIVE = C.BASE / "live"
STATE = LIVE / "state.json"


def load_state():
    if not STATE.exists():
        return None
    return json.loads(STATE.read_text(encoding="utf-8"))


def save_state(s):
    LIVE.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=1), encoding="utf-8")


def pid_alive(pid):
    if not pid:
        return False
    r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True)
    return str(pid) in r.stdout


def kill_tree(pid):
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)


# ------------------------------------------------------------------ start

def cmd_start(a):
    st = load_state()
    if st and pid_alive(st.get("daemon_pid")):
        C.die("already recording " + st["url"] + " - run `stop` first")
    url = a.url
    r = subprocess.run(C.ytdlp_base() + ["-g", "-f", "best[height<=720]/best", url],
                       capture_output=True, text=True, encoding="utf-8")
    stream = r.stdout.strip().splitlines()
    if r.returncode != 0 or not stream:
        C.die("could not open that stream: " + (r.stderr or "").strip()[-500:])
    info = subprocess.run(C.ytdlp_base() + ["--dump-single-json", "--skip-download", url],
                          capture_output=True, text=True, encoding="utf-8")
    title = url
    try:
        title = json.loads(info.stdout).get("title") or url
    except Exception:
        pass

    wd = LIVE / time.strftime("%Y%m%d-%H%M%S")
    (wd / "segs").mkdir(parents=True)
    state = {"url": url, "title": title, "workdir": str(wd), "started": time.time(),
             "model": a.model, "language": a.language}
    save_state(state)
    log = open(wd / "daemon.log", "w", encoding="utf-8")
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    p = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "_daemon"],
                         stdout=log, stderr=log, stdin=subprocess.DEVNULL, creationflags=flags)
    state["daemon_pid"] = p.pid
    save_state(state)
    print(json.dumps({"ok": True, "recording": title, "workdir": str(wd),
                      "note": "first transcript lines appear after ~2 minutes"}, indent=1))


# ------------------------------------------------------------------ daemon

def cmd_daemon(_a):
    st = load_state()
    wd = Path(st["workdir"])
    segs = wd / "segs"
    r = subprocess.run(C.ytdlp_base() + ["-g", "-f", "best[height<=720]/best", st["url"]],
                       capture_output=True, text=True, encoding="utf-8")
    stream = r.stdout.strip().splitlines()[0]
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-i", stream, "-c", "copy", "-f", "segment",
         "-segment_time", str(SEG_SECONDS), "-reset_timestamps", "1", "-segment_format", "mpegts",
         str(segs / "seg_%06d.ts")],
        stdin=subprocess.DEVNULL)
    st["ffmpeg_pid"] = ff.pid
    save_state(st)

    index_p = wd / "index.json"      # [{name, start, dur}]
    tr_p = wd / "transcript.jsonl"
    index = []
    done = set()
    clock = 0.0
    while True:
        files = sorted(segs.glob("seg_*.ts"))
        finished = files[:-1] if ff.poll() is None else files
        for f in finished:
            if f.name in done:
                continue
            try:
                _, _, d = C.probe(f)
            except Exception:
                continue
            if d <= 0:
                done.add(f.name)
                continue
            wav = wd / "tmp.wav"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(f), "-vn", "-ac", "1", "-ar", "16000",
                            str(wav)])
            seg_start = clock
            try:
                tr = C.transcribe(wav, st["model"], st.get("language"), offset=seg_start, progress=False)
                db = C.loudness_db(wav)
            except Exception as e:
                print("transcribe failed:", e, flush=True)
                tr, db = {"segments": []}, []
            loud = round(max(db) - (sum(db) / len(db)), 1) if db else 0
            with open(tr_p, "a", encoding="utf-8") as fh:
                for sg in tr["segments"]:
                    sg["loud_db_over_avg"] = loud
                    fh.write(json.dumps(sg, ensure_ascii=False) + "\n")
            index.append({"name": f.name, "start": seg_start, "dur": d})
            index_p.write_text(json.dumps(index), encoding="utf-8")
            clock += d
            done.add(f.name)
            wav.unlink(missing_ok=True)
        # keep only the last KEEP_MINUTES of video
        keep = KEEP_MINUTES * 60 // SEG_SECONDS
        for ent in index[:-keep]:
            (segs / ent["name"]).unlink(missing_ok=True)
        if ff.poll() is not None and all(f.name in done for f in files):
            print("stream ended", flush=True)
            break
        time.sleep(8)


# ------------------------------------------------------------------ read

def read_transcript(wd):
    p = wd / "transcript.jsonl"
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def cmd_status(_a):
    st = load_state()
    if not st:
        C.die("nothing is recording")
    wd = Path(st["workdir"])
    idx = json.loads((wd / "index.json").read_text(encoding="utf-8")) if (wd / "index.json").exists() else []
    covered = idx[-1]["start"] + idx[-1]["dur"] if idx else 0
    print(json.dumps({"recording": pid_alive(st.get("daemon_pid")), "title": st["title"],
                      "elapsed": C.fmt_ts(time.time() - st["started"]),
                      "transcribed_up_to": C.fmt_ts(covered)}, indent=1))


def cmd_transcript(a):
    st = load_state()
    if not st:
        C.die("nothing is recording")
    segs = read_transcript(Path(st["workdir"]))
    if a.last and segs:
        cut = segs[-1]["end"] - a.last * 60
        segs = [s for s in segs if s["end"] >= cut]
    for s in segs:
        tag = " [LOUD]" if s.get("loud_db_over_avg", 0) >= a.loud_db else ""
        print(f"[{C.fmt_ts(s['start'])}]{tag} {s['text']}")


# ------------------------------------------------------------------ clip

def cmd_clip(a):
    st = load_state()
    if not st:
        C.die("nothing is recording")
    wd = Path(st["workdir"])
    index = json.loads((wd / "index.json").read_text(encoding="utf-8"))
    if not index:
        C.die("nothing recorded yet")
    covered = index[-1]["start"] + index[-1]["dur"]
    if a.back is not None:
        end = covered - a.back
        start = end - a.length
    else:
        start, end = C.parse_ts(a.start), C.parse_ts(a.end)
    segs = read_transcript(wd)
    if not a.no_snap:
        start, end = C.snap(segs, start, end)
    start = max(start - 0.15, index[0]["start"])
    end = min(end + 0.35, covered)
    if end <= start:
        C.die("that moment is outside the recorded window (only the last "
              f"{KEEP_MINUTES} min are kept; recorded range is {C.fmt_ts(index[0]['start'])}"
              f"-{C.fmt_ts(covered)})")
    need = [e for e in index if e["start"] + e["dur"] > start and e["start"] < end]
    if not need:
        C.die("those minutes are no longer on disk")
    lst = wd / "concat.txt"
    lst.write_text("".join(f"file 'segs/{e['name']}'\n" for e in need), encoding="utf-8")
    src = wd / "joined.mp4"
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-c", "copy", str(src)], cwd=str(wd))
    if r.returncode != 0:
        C.die("could not join the recorded pieces")
    t0 = need[0]["start"]
    words = [w for s in segs for w in s["words"]]
    day = C.OUT_ROOT / time.strftime("%Y-%m-%d")
    name = a.name or C.slugify(a.title)
    out, n = day / f"{name}.mp4", 2
    while out.exists():
        out = day / f"{name}-{n}.mp4"
        n += 1
    layout = C.render_clip(src, start - t0, end - start, words, start, a.title, out, wd,
                           a.layout if a.layout != "auto" else None, a.facecam, tag=out.stem[:40])
    C.write_post_text(out.with_suffix(".txt"), a.title, a.caption, a.hashtags, st["url"], start, end,
                      {"title": st["title"], "webpage_url": st["url"], "source": st["url"], "license": None})
    print(json.dumps({"ok": True, "clip": str(out), "post_text": str(out.with_suffix(".txt")),
                      "layout": layout, "length_seconds": round(end - start, 1)}, indent=1))


def cmd_stop(_a):
    st = load_state()
    if not st:
        C.die("nothing is recording")
    for k in ("ffmpeg_pid", "daemon_pid"):
        if st.get(k):
            kill_tree(st[k])
    print(json.dumps({"ok": True, "stopped": st["title"], "recordings_kept_in": st["workdir"]}))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("url")
    s.add_argument("--model", default=os.environ.get("CLIPEVERYTHING_LIVE_MODEL", "base"))
    s.add_argument("--language", default=None)
    s.set_defaults(fn=cmd_start)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    t = sub.add_parser("transcript")
    t.add_argument("--last", type=float, default=0, help="only the last N minutes")
    t.add_argument("--loud-db", type=float, default=10.0)
    t.set_defaults(fn=cmd_transcript)
    c = sub.add_parser("clip")
    c.add_argument("--start")
    c.add_argument("--end")
    c.add_argument("--back", type=float, help="seconds before 'now' that the clip ENDS")
    c.add_argument("--length", type=float, default=45)
    c.add_argument("--title", required=True)
    c.add_argument("--caption", default="")
    c.add_argument("--hashtags", default="")
    c.add_argument("--name", default=None)
    c.add_argument("--layout", default="auto", choices=["auto", "stack", "talking", "screen", "fill"])
    c.add_argument("--facecam", default=None)
    c.add_argument("--no-snap", action="store_true")
    c.set_defaults(fn=cmd_clip)
    sub.add_parser("stop").set_defaults(fn=cmd_stop)
    sub.add_parser("_daemon").set_defaults(fn=cmd_daemon)
    args = ap.parse_args()
    if args.cmd == "clip" and args.back is None and not (args.start and args.end):
        ap.error("clip needs --start and --end, or --back")
    args.fn(args)


if __name__ == "__main__":
    main()
