#!/usr/bin/env python3
"""Нарезка вертикальных Shorts / Reels из длинного горизонтального видео.

Только стандартная библиотека Python 3.9+ и ffmpeg (ffprobe) в PATH.

  python3 shorts.py words SRC -o words.json      слова с таймингами из timeline.json / .srt / .vtt / JSON распознавания
  python3 shorts.py sentences words.json         фразы с таймингами — по ним агент выбирает моменты
  python3 shorts.py render VIDEO --words words.json --start 296 --end 349.6 \\
        --title "Какую модель Claude выбрать" --out out/s1.mp4 [--mode fit|crop] [--zoom 1.0] [--cx 0.5] \\
        [--cta "Полный урок — по ссылке ниже"] [--font путь.ttf] [--dry-run]
  python3 shorts.py plan plan.json               собрать сразу несколько клипов по плану (см. SKILL.md)
  python3 shorts.py sheet clip.mp4 [--step 0.5]  лист кадров каждые 0,5 с с подписью времени — для проверки глазами

Режимы кадра:
  fit  — горизонтальное видео целиком по центру, сверху заголовок, снизу призыв, фон — размытый тот же кадр.
         Для уроков с графикой и вшитыми субтитрами (ничего не обрезается). По умолчанию.
  crop — вырезать вертикальный кусок (лицо во весь экран). Для «говорящей головы» без вшитых субтитров.
Границы клипа всегда подтягиваются к началу/концу слов, чтобы не резать на полуслове.
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile

W, H = 1080, 1920
CTA_DEFAULT = "Полный урок — по ссылке ниже"
FONT_CANDIDATES = [
    "/opt/video-skills/fonts-ttf/Montserrat-900-cyrlat.ttf",  # VPS Павла
    "/Library/Fonts/Montserrat-ExtraBold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
]


def die(msg):
    sys.exit("Ошибка: " + msg)


def need(tool):
    if not shutil.which(tool):
        die(f"нет {tool}. Установите ffmpeg: macOS `brew install ffmpeg`, Windows `winget install Gyan.FFmpeg`, "
            "Linux `sudo apt install ffmpeg`")


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        die(f"{cmd[0]} завершился с ошибкой:\n{p.stderr[-1500:]}")
    return p.stdout


def duration(path):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]).strip())


# ---------- слова ----------

def _ts(s):
    s = s.strip().replace(",", ".")
    parts = s.split(":")
    sec = 0.0
    for p in parts:
        sec = sec * 60 + float(p)
    return sec


def words_from_youtube_vtt(text):
    """Авто-субтитры YouTube: у каждого слова свой тег <00:00:01.234><c> слово</c>; строки без тегов — повторы."""
    out = []
    for b in re.split(r"\n\s*\n", text.replace("\r", "")):
        m = re.search(r"(\d[\d:.]+)\s*-->\s*(\d[\d:.]+)", b)
        if not m or "<c>" not in b:
            continue
        body_lines = [ln for ln in b[m.end():].split("\n") if "<c>" in ln or re.search(r"<\d\d:", ln)]
        for ln in body_lines:
            first = re.split(r"<\d\d:\d\d:\d\d\.\d+>", ln)[0]
            first = re.sub(r"<[^>]+>", "", first).strip()
            stamps = re.findall(r"<(\d\d:\d\d:\d\d\.\d+)><c>(.*?)</c>", ln)
            t0 = _ts(m.group(1))
            seq = ([(t0, first)] if first else []) + [(_ts(t), w.strip()) for t, w in stamps]
            for i, (t, w) in enumerate(seq):
                if not w:
                    continue
                end = seq[i + 1][0] if i + 1 < len(seq) else t + 0.4
                out.append({"w": w, "s": round(t, 3), "e": round(max(end, t + 0.08), 3)})
    out.sort(key=lambda x: x["s"])
    return out


def words_from_subs(text):
    """SRT/VTT → слова с равномерно распределённым временем внутри реплики (приближение)."""
    if "<c>" in text and re.search(r"<\d\d:\d\d:\d\d\.\d+><c>", text):
        return words_from_youtube_vtt(text)
    out = []
    blocks = re.split(r"\n\s*\n", text.replace("\r", ""))
    for b in blocks:
        m = re.search(r"(\d[\d:.,]+)\s*-->\s*(\d[\d:.,]+)", b)
        if not m:
            continue
        s, e = _ts(m.group(1)), _ts(m.group(2).split()[0])
        body = b[m.end():].strip()
        body = re.sub(r"<[^>]+>", "", body)
        ws = body.split()
        if not ws or e <= s:
            continue
        step = (e - s) / len(ws)
        for i, w in enumerate(ws):
            out.append({"w": w, "s": round(s + i * step, 3), "e": round(s + (i + 1) * step, 3)})
    # авто-субтитры YouTube повторяют строки — убрать дубли подряд
    dedup = []
    for w in out:
        if dedup and dedup[-1]["w"] == w["w"] and abs(dedup[-1]["s"] - w["s"]) < 1.5:
            continue
        dedup.append(w)
    return dedup


def words_from_json(d):
    """timeline.json студии (words: t/s/e), ElevenLabs/Vibi (words: text/start/end), Whisper (segments[].words)."""
    if isinstance(d, dict) and "result" in d and isinstance(d["result"], dict):
        d = d["result"]
    raw = []
    if isinstance(d, dict):
        if isinstance(d.get("words"), list):
            raw = d["words"]
        elif isinstance(d.get("segments"), list):
            for seg in d["segments"]:
                raw += seg.get("words") or [{"word": seg.get("text", ""), "start": seg.get("start"), "end": seg.get("end")}]
    elif isinstance(d, list):
        raw = d
    out = []
    for w in raw:
        t = w.get("t") or w.get("w") or w.get("text") or w.get("word") or ""
        s = w.get("s", w.get("start"))
        e = w.get("e", w.get("end"))
        if w.get("type") in ("spacing", "audio_event") or s is None or e is None or not str(t).strip():
            continue
        out.append({"w": str(t).strip(), "s": float(s), "e": float(e)})
    return out


def cmd_words(a):
    src = a.src
    if src.lower().endswith((".srt", ".vtt")):
        ws = words_from_subs(open(src, encoding="utf-8").read())
    else:
        ws = words_from_json(json.load(open(src, encoding="utf-8")))
    if not ws:
        die("не нашёл слов с таймингами в " + src)
    json.dump(ws, open(a.out, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"Слов: {len(ws)}, от {ws[0]['s']:.1f} до {ws[-1]['e']:.1f} с → {a.out}")


def load_words(path):
    return json.load(open(path, encoding="utf-8"))


def sentences(ws):
    out, cur = [], []
    for w in ws:
        cur.append(w)
        if re.search(r"[.!?…]$|[.!?…][»\"')]$", w["w"]):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return [{"s": c[0]["s"], "e": c[-1]["e"], "text": " ".join(x["w"] for x in c)} for c in out]


def fmt(t):
    return f"{int(t) // 60}:{t % 60:05.2f}"


def cmd_sentences(a):
    ss = sentences(load_words(a.words))
    if a.json:
        print(json.dumps(ss, ensure_ascii=False, indent=1))
        return
    for i, s in enumerate(ss):
        print(f"[{i}] {fmt(s['s'])}–{fmt(s['e'])} ({s['s']:.2f}–{s['e']:.2f})  {s['text']}")


def snap(ws, start, end):
    """Подтянуть границы к словам: начало — к началу первого слова, конец — к концу последнего."""
    # слово внутри, если его середина попадает в окно (короткие слова «У», «А» не теряются на краю)
    inside = [w for w in ws if start - 0.2 <= (w["s"] + w["e"]) / 2 <= end + 0.2]
    if not inside:
        die(f"между {start} и {end} нет слов — проверьте время")
    s = max(0.0, inside[0]["s"] - 0.12)
    e = inside[-1]["e"] + 0.30
    return s, e, " ".join(w["w"] for w in inside)


# ---------- рендер ----------

def pick_font(path):
    if path:
        if not os.path.exists(path):
            die("шрифт не найден: " + path)
        return path
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    die("не нашёл шрифт с кириллицей. Укажите --font путь/к/шрифту.ttf")


def wrap(text, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + (1 if cur else 0) > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines


def ff_path(p):
    # путь для фильтров ffmpeg: прямые слеши, экранировать двоеточие (Windows C:)
    return p.replace("\\", "/").replace(":", r"\:")


def text_filters(lines, y0, size, color, font, tmpdir, tag):
    """Каждая строка отдельно по центру; текст через textfile, чтобы не экранировать кавычки и двоеточия."""
    flt = []
    for i, line in enumerate(lines):
        tf = os.path.join(tmpdir, f"{tag}{i}.txt")
        open(tf, "w", encoding="utf-8").write(line)
        y = y0 + int(i * size * 1.22)
        flt.append(f"drawtext=fontfile='{ff_path(font)}':textfile='{ff_path(tf)}':fontsize={size}:fontcolor={color}:"
                   f"x=(w-text_w)/2:y={y}:borderw=4:bordercolor=black@0.85:shadowx=0:shadowy=3:shadowcolor=black@0.6")
    return flt


def build_filter(a, font, tmpdir, src_w, src_h):
    title_lines = wrap(a.title, 20)[:3] if a.title else []
    cta_lines = wrap(a.cta, 30)[:2] if a.cta else []
    if a.mode == "crop":
        cw = int(src_h * 9 / 16)
        cx = int((src_w - cw) * a.cx)
        base = f"[0:v]crop={cw}:{src_h}:{cx}:0,scale={W}:{H},setsar=1[v0]"
        chain = []
        if title_lines:
            chain += text_filters(title_lines, 300, 74, "white", font, tmpdir, "t")
        if cta_lines:
            chain += text_filters(cta_lines, 1460, 48, "0xFFC21A", font, tmpdir, "c")
        return base + (";[v0]" + ",".join(chain) + "[v]" if chain else ";[v0]null[v]")
    # fit: размытый фон + видео по центру
    fg_w = int(W * a.zoom)
    fg_h = int(round(fg_w * src_h / src_w / 2) * 2)
    fg_y = (H - min(fg_h, H)) // 2 + 40
    parts = [
        f"[0:v]scale=-2:{H},crop={W}:{H},boxblur=40:3,eq=brightness=-0.38:saturation=0.7,setsar=1[bg]",
        f"[0:v]scale={fg_w}:{fg_h},crop={min(fg_w, W)}:{fg_h},setsar=1[fg]",
        f"[bg][fg]overlay=(W-w)/2:{fg_y}[v0]",
    ]
    chain = []
    if title_lines:
        n = len(title_lines)
        size = 76 if n <= 2 else 66
        y0 = max(250, fg_y - 60 - int(n * size * 1.22))
        chain += text_filters(title_lines, y0, size, "white", font, tmpdir, "t")
    if cta_lines:
        chain += text_filters(cta_lines, fg_y + fg_h + 70, 50, "0xFFC21A", font, tmpdir, "c")
    parts.append("[v0]" + (",".join(chain) if chain else "null") + "[v]")
    return ";".join(parts)


def probe_wh(path):
    out = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
               "-of", "csv=p=0:s=x", path]).strip()
    w, h = out.split("x")[:2]
    return int(w), int(h)


def render_one(a):
    need("ffmpeg"); need("ffprobe")
    if not os.path.isfile(a.video):
        die("нет видео " + a.video)
    if a.words:
        s, e, said = snap(load_words(a.words), a.start, a.end)
    else:
        s, e, said = a.start, a.end, ""
    dur = e - s
    if dur > 180:
        die(f"клип {dur:.1f} с — YouTube Shorts не длиннее 3 минут, Reels лучше до 90 с")
    font = pick_font(a.font)
    src_w, src_h = probe_wh(a.video)
    print(f"Клип {a.out}: {fmt(s)}–{fmt(e)} ({dur:.1f} с), режим {a.mode}")
    if said:
        print("  Речь: " + (said[:220] + ("…" if len(said) > 220 else "")))
    if a.dry_run:
        return
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        flt = build_filter(a, font, tmp, src_w, src_h)
        fade_out = max(0.0, dur - 0.25)
        cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{s:.3f}", "-i", a.video, "-t", f"{dur:.3f}",
               "-filter_complex", flt + f";[v]fade=t=out:st={fade_out:.2f}:d=0.25[vo]",
               "-map", "[vo]", "-map", "0:a?", "-r", "30",
               "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
               "-af", f"loudnorm=I=-14:TP=-1.5:LRA=11,afade=t=out:st={fade_out:.2f}:d=0.25",
               "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart", a.out]
        run(cmd)
    print(f"  Готово: {a.out} ({duration(a.out):.1f} с, {W}x{H})")


def cmd_render(a):
    render_one(a)


def cmd_plan(a):
    plan = json.load(open(a.plan, encoding="utf-8"))
    base = os.path.dirname(os.path.abspath(a.plan))
    for c in plan["clips"]:
        ns = argparse.Namespace(
            video=plan["video"], words=plan.get("words"), start=float(c["start"]), end=float(c["end"]),
            title=c.get("title", ""), cta=c.get("cta", plan.get("cta", CTA_DEFAULT)),
            out=os.path.join(base, plan.get("out_dir", "out"), c["name"] + ".mp4"),
            mode=c.get("mode", plan.get("mode", "fit")), zoom=float(c.get("zoom", plan.get("zoom", 1.0))),
            cx=float(c.get("cx", 0.5)), font=plan.get("font"), dry_run=a.dry_run)
        render_one(ns)


def cmd_sheet(a):
    need("ffmpeg")
    dur = duration(a.clip)
    n = int(dur / a.step) + 1
    cols = 6
    rows = (n + cols - 1) // cols
    out = a.out or os.path.splitext(a.clip)[0] + "_sheet.jpg"
    font = pick_font(a.font)
    vf = (f"fps=1/{a.step},scale=270:-2,drawtext=fontfile='{ff_path(font)}':text='%{{pts\\:hms}}':"
          f"x=8:y=8:fontsize=22:fontcolor=yellow:box=1:boxcolor=black@0.6,tile={cols}x{rows}")
    run(["ffmpeg", "-v", "error", "-y", "-i", a.clip, "-vf", vf, "-frames:v", "1", "-q:v", "3", out])
    print(f"Лист: {out} ({n} кадров с шагом {a.step} с)")


def main():
    ap = argparse.ArgumentParser(description="Shorts/Reels из длинного видео")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("words"); s.add_argument("src"); s.add_argument("-o", "--out", default="words.json")
    s = sub.add_parser("sentences"); s.add_argument("words"); s.add_argument("--json", action="store_true")
    s = sub.add_parser("render")
    s.add_argument("video"); s.add_argument("--words"); s.add_argument("--start", type=float, required=True)
    s.add_argument("--end", type=float, required=True); s.add_argument("--title", default="")
    s.add_argument("--cta", default=CTA_DEFAULT); s.add_argument("--out", required=True)
    s.add_argument("--mode", choices=("fit", "crop"), default="fit"); s.add_argument("--zoom", type=float, default=1.0)
    s.add_argument("--cx", type=float, default=0.5); s.add_argument("--font"); s.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("plan"); s.add_argument("plan"); s.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("sheet"); s.add_argument("clip"); s.add_argument("--step", type=float, default=0.5)
    s.add_argument("-o", "--out"); s.add_argument("--font")
    a = ap.parse_args()
    {"words": cmd_words, "sentences": cmd_sentences, "render": cmd_render, "plan": cmd_plan, "sheet": cmd_sheet}[a.cmd](a)


if __name__ == "__main__":
    main()
