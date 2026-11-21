#!/usr/bin/env python3
"""Post for Me: публикация роликов и постов в свои соцсети одной командой.

Только стандартная библиотека Python 3.9+. Ничего ставить не нужно.

  python3 pfm.py check                          проверить ключ (бесплатно)
  python3 pfm.py accounts [--platform youtube]  какие соцсети подключены
  python3 pfm.py connect youtube                ссылка, чтобы подключить соцсеть (открыть в браузере)
  python3 pfm.py upload video.mp4               залить файл во временное хранилище Post for Me
  python3 pfm.py post NAME --to youtube,instagram --media video.mp4 --caption-file caption.txt \\
        [--title "Заголовок"] [--privacy public|unlisted|private] [--placement reels|stories|timeline] \\
        [--cover cover.jpg | --cover-ms 3000] [--schedule 2026-12-01T10:00:00+03:00] [--draft] \\
        [--config examples/configs/youtube.json] [--yes]
        без --yes только показывает, что будет отправлено (бесплатно и безопасно)
  python3 pfm.py status POST_ID                 статус поста и ссылки на опубликованное
  python3 pfm.py wait POST_ID [--minutes 15]    ждать, пока все соцсети ответят
  python3 pfm.py posts [--status scheduled]     последние посты
  python3 pfm.py delete POST_ID --yes           удалить запланированный пост или черновик
  python3 pfm.py feed ACCOUNT_ID [--metrics]    что уже опубликовано в аккаунте и статистика

Ключ: переменная POST_FOR_ME_API_KEY или строка POST_FOR_ME_API_KEY=... в файле .env
(текущая папка, корень набора или ~/.postforme.env). Ключ не печатается.

Пост отправляется ровно один раз: результат пишется в out/NAME.json. Повторный запуск с тем же
именем не публикует второй раз, а показывает статус уже созданного поста.
"""
import argparse, json, mimetypes, os, sys, time, urllib.error, urllib.parse, urllib.request

API = "https://api.postforme.dev"
UA = "postforme-kit/1.0"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "out")
PLATFORMS = ("youtube", "instagram", "tiktok", "tiktok_business", "facebook", "x", "linkedin",
             "threads", "pinterest", "bluesky")


def log(msg):
    print(msg, flush=True)


def load_key():
    if os.environ.get("POST_FOR_ME_API_KEY"):
        return os.environ["POST_FOR_ME_API_KEY"].strip()
    for p in (".env", os.path.join(ROOT, ".env"), os.path.expanduser("~/.postforme.env")):
        if os.path.exists(p):
            for line in open(p, encoding="utf-8"):
                line = line.strip()
                if line.startswith("export "):
                    line = line[7:]
                if line.startswith("POST_FOR_ME_API_KEY="):
                    v = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if v:
                        return v
    sys.exit("Нет ключа. Создайте файл .env со строкой POST_FOR_ME_API_KEY=pfm_live_... "
             "(ключ: app.postforme.dev → ваш проект → API Keys). Подробно: guides/registration.md")


def clean(obj):
    """Убрать из ответа токены соцсетей: их нельзя печатать и пересылать."""
    if isinstance(obj, dict):
        return {k: ("<скрыто>" if "token" in k.lower() or k.lower() in ("secret", "api_key") else clean(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean(x) for x in obj]
    return obj


def qs(params):
    pairs = []
    for k, v in params.items():
        if v is None:
            continue
        for item in (v if isinstance(v, (list, tuple)) else [v]):
            pairs.append((k, str(item)))
    return ("?" + urllib.parse.urlencode(pairs)) if pairs else ""


def http(method, path, key, body=None, query=None, timeout=120):
    url = API + path + qs(query or {})
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + key, "Content-Type": "application/json",
        "Accept": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")[:800]
        hint = {401: "ключ неверный или отозван — создайте новый в app.postforme.dev → API Keys",
                403: "нет доступа: проверьте тариф и что ключ от нужного проекта",
                404: "не найдено: проверьте ID",
                429: "слишком много запросов: подождите минуту"}.get(e.code, "")
        if "reconnect" in text.lower():
            hint = "соцсеть отключилась (истёк доступ) — переподключите: python3 scripts/pfm.py connect <платформа>"
        if e.code >= 500 and "social-account-feeds" in path:
            hint = ("лента не читается: обычно аккаунт подключали без доступа к статистике или доступ истёк — "
                    "переподключите: python3 scripts/pfm.py connect <платформа>")
        sys.exit(f"Ошибка API {e.code} {method} {path}: {text}" + (f"\nПодсказка: {hint}" if hint else ""))
    except urllib.error.URLError as e:
        sys.exit(f"Нет связи с api.postforme.dev: {e.reason}. Проверьте интернет/VPN и повторите.")


def items(resp):
    return resp.get("data", []) if isinstance(resp, dict) else (resp or [])


def account_line(a):
    return f"{a.get('id')}  {a.get('platform'):<16} {a.get('username') or '-':<28} {a.get('status')}"


# ---------- команды ----------

def cmd_check(a, key):
    resp = http("GET", "/v1/social-accounts", key, query={"limit": 100})
    accs = items(resp)
    log(f"Ключ работает. Подключено соцсетей: {len(accs)}")
    for x in accs:
        log("  " + account_line(x))
    if not accs:
        log("Пока ничего не подключено: python3 scripts/pfm.py connect youtube (или instagram, tiktok...)")


def cmd_accounts(a, key):
    q = {"limit": 100, "platform": a.platform, "status": a.status}
    accs = items(http("GET", "/v1/social-accounts", key, query=q))
    if not accs:
        log("Аккаунтов нет. Подключить: python3 scripts/pfm.py connect <платформа>")
    for x in accs:
        log(account_line(x))


def cmd_connect(a, key):
    if a.platform not in PLATFORMS:
        sys.exit("Платформа одна из: " + ", ".join(PLATFORMS))
    body = {"platform": a.platform, "permissions": ["posts", "feeds"]}  # feeds — для статистики
    if a.external_id:
        body["external_id"] = a.external_id
    if a.platform_data:
        body["platform_data"] = json.loads(a.platform_data)
    elif a.platform == "instagram":
        # API требует способ входа: instagram (вход в Instagram) или facebook (через страницу Facebook)
        body["platform_data"] = {"instagram": {"connection_type": a.via}}
    resp = http("POST", "/v1/social-accounts/auth-url", key, body=body)
    url = resp.get("url")
    if not url:
        sys.exit("API не вернул ссылку: " + json.dumps(clean(resp), ensure_ascii=False)[:500])
    log("Откройте ссылку в браузере, войдите в соцсеть и разрешите доступ:")
    log(url)
    log("Потом проверьте: python3 scripts/pfm.py accounts")


def upload_file(path, key):
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not os.path.isfile(path):
        sys.exit(f"Файл не найден: {path}")
    size = os.path.getsize(path)
    ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
    resp = http("POST", "/v1/media/create-upload-url", key)
    up, media_url = resp.get("upload_url"), resp.get("media_url")
    if not up or not media_url:
        sys.exit("API не выдал ссылку для загрузки: " + json.dumps(clean(resp), ensure_ascii=False)[:400])
    log(f"Загружаю {os.path.basename(path)} ({size / 1048576:.1f} МБ)...")
    with open(path, "rb") as f:
        req = urllib.request.Request(up, data=f, method="PUT", headers={
            "Content-Type": ctype, "Content-Length": str(size), "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=1800) as r:
                if r.status >= 300:
                    sys.exit(f"Загрузка не удалась: HTTP {r.status}")
        except urllib.error.HTTPError as e:
            sys.exit(f"Загрузка не удалась: HTTP {e.code} {e.read()[:300]!r}")
    log("Загружено. Файл живёт 24 часа или до публикации.")
    return media_url


def cmd_upload(a, key):
    log(upload_file(a.file, key))


def resolve_accounts(spec, key):
    """--to принимает ID (spc_...), названия платформ (youtube,instagram) или all."""
    accs = [x for x in items(http("GET", "/v1/social-accounts", key, query={"limit": 100}))
            if x.get("status") == "connected"]
    wanted = [s.strip() for s in spec.split(",") if s.strip()]
    chosen = []
    for w in wanted:
        if w == "all":
            chosen += accs
        elif w.startswith("spc_"):
            m = [x for x in accs if x.get("id") == w]
            if not m:
                sys.exit(f"Аккаунт {w} не найден среди подключённых. Список: python3 scripts/pfm.py accounts")
            chosen += m
        else:
            m = [x for x in accs if x.get("platform") == w]
            if not m:
                sys.exit(f"Нет подключённого аккаунта {w}. Подключить: python3 scripts/pfm.py connect {w}")
            chosen += m
    uniq = {x["id"]: x for x in chosen}
    if not uniq:
        sys.exit("Не выбрано ни одного аккаунта (--to)")
    return list(uniq.values())


def read_caption(a):
    if a.caption_file:
        return open(a.caption_file, encoding="utf-8").read().strip()
    return (a.caption or "").strip()


def cmd_post(a, key):
    os.makedirs(OUT, exist_ok=True)
    ledger = os.path.join(OUT, a.name + ".json")
    if os.path.exists(ledger):
        prev = json.load(open(ledger, encoding="utf-8"))
        log(f"Пост «{a.name}» уже создан раньше (id {prev.get('post_id')}). Второй раз не публикую.")
        log(f"Статус: python3 scripts/pfm.py status {prev.get('post_id')}")
        return
    caption = read_caption(a)
    if not caption:
        sys.exit("Нужен текст поста: --caption \"...\" или --caption-file caption.txt")
    for m in (a.media or []) + ([a.cover] if a.cover else []):
        if not m.startswith(("http://", "https://")) and not os.path.isfile(m):
            sys.exit(f"Файл не найден: {m}")
    accs = resolve_accounts(a.to, key)
    platforms = sorted({x["platform"] for x in accs})

    cfg = json.load(open(a.config, encoding="utf-8")) if a.config else {}
    if a.title:
        for p in ("youtube", "tiktok", "tiktok_business"):
            if p in platforms:
                cfg.setdefault(p, {})["title"] = a.title
    if a.privacy:
        for p in ("youtube", "tiktok", "tiktok_business"):
            if p in platforms:
                cfg.setdefault(p, {})["privacy_status"] = a.privacy
    if a.placement:
        for p in ("instagram", "facebook"):
            if p in platforms:
                cfg.setdefault(p, {})["placement"] = a.placement
    if "youtube" in platforms:
        cfg.setdefault("youtube", {}).setdefault("localizations", {})
        if not cfg["youtube"].get("title"):
            sys.exit("Для YouTube нужен заголовок: --title \"...\" (до 100 символов)")
        if len(cfg["youtube"]["title"]) > 100:
            sys.exit("Заголовок YouTube длиннее 100 символов — сократите")

    body = {"caption": caption, "social_accounts": [x["id"] for x in accs], "external_id": a.name}
    if cfg:
        body["platform_configurations"] = cfg
    if a.schedule:
        body["scheduled_at"] = a.schedule
    if a.draft:
        body["isDraft"] = True  # верхний уровень API: camelCase (у TikTok внутри настроек — is_draft)

    preview_media = []
    for m in a.media or []:
        item = {"url": m}
        if a.cover:
            item["thumbnail_url"] = a.cover
        if a.cover_ms is not None:
            item["thumbnail_timestamp_ms"] = a.cover_ms
        preview_media.append(item)
    if preview_media:
        body["media"] = preview_media

    log("Будет отправлено:")
    log("  Куда: " + "; ".join(f"{x['platform']} ({x.get('username')})" for x in accs))
    log("  Когда: " + (a.schedule or ("черновик" if a.draft else "сразу после отправки")))
    log("  Медиа: " + (", ".join(a.media) if a.media else "нет (только текст)"))
    log("  Текст (" + str(len(caption)) + " симв.): " + caption[:200] + ("…" if len(caption) > 200 else ""))
    if cfg:
        log("  Настройки платформ: " + json.dumps(cfg, ensure_ascii=False))
    if not a.yes:
        log("\nЭто проверка. Чтобы опубликовать, повторите команду с --yes (после «да» человека).")
        return

    # загрузка локальных файлов только в боевом запуске
    for item in body.get("media", []):
        item["url"] = upload_file(item["url"], key)
        if item.get("thumbnail_url"):
            item["thumbnail_url"] = upload_file(item["thumbnail_url"], key)

    resp = http("POST", "/v1/social-posts", key, body=body, timeout=300)  # ровно один раз, без повторов
    post_id = resp.get("id")
    json.dump({"post_id": post_id, "status": resp.get("status"), "accounts": body["social_accounts"],
               "created": time.strftime("%Y-%m-%d %H:%M:%S")}, open(ledger, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    log(f"Пост создан: {post_id}, статус {resp.get('status')}")
    log(f"Дальше: python3 scripts/pfm.py wait {post_id}")


def results_for(post_id, key):
    return items(http("GET", "/v1/social-post-results", key, query={"post_id": [post_id], "limit": 100}))


def print_results(res, accs_by_id):
    for r in res:
        acc = accs_by_id.get(r.get("social_account_id"), {})
        pd = r.get("platform_data") or {}
        name = f"{acc.get('platform', '?')} ({acc.get('username', r.get('social_account_id'))})"
        if r.get("success"):
            log(f"  ✅ {name}: {pd.get('url') or 'опубликовано'}")
        else:
            err = r.get("error")
            log(f"  ❌ {name}: {json.dumps(clean(err), ensure_ascii=False)[:400]}")


def cmd_status(a, key):
    post = http("GET", f"/v1/social-posts/{a.post_id}", key)
    accs = {x.get("id"): x for x in post.get("social_accounts") or []}
    log(f"Пост {a.post_id}: статус {post.get('status')}"
        + (f", запланирован на {post.get('scheduled_at')}" if post.get("status") == "scheduled" else ""))
    res = results_for(a.post_id, key)
    if res:
        print_results(res, accs)
    else:
        log("  Результатов от соцсетей пока нет (обычно 1–10 минут, YouTube бывает дольше).")
    return post, res


def cmd_wait(a, key):
    deadline = time.time() + a.minutes * 60
    while True:
        post = http("GET", f"/v1/social-posts/{a.post_id}", key)
        accs = {x.get("id"): x for x in post.get("social_accounts") or []}
        res = results_for(a.post_id, key)
        if post.get("status") == "scheduled" and not res:
            log(f"Пост запланирован на {post.get('scheduled_at')} — ждать сейчас нечего.")
            return
        if len(res) >= len(accs) and accs:
            log(f"Готово, статус {post.get('status')}:")
            print_results(res, accs)
            return
        if time.time() > deadline:
            log(f"За {a.minutes} мин ответили {len(res)} из {len(accs)}. Это нормально для YouTube; "
                f"проверьте позже: python3 scripts/pfm.py status {a.post_id}")
            print_results(res, accs)
            return
        log(time.strftime("%H:%M:%S") + f"  статус {post.get('status')}, ответили {len(res)} из {len(accs)}…")
        time.sleep(20)


def cmd_posts(a, key):
    q = {"limit": a.limit, "status": a.status, "platform": a.platform}
    for p in items(http("GET", "/v1/social-posts", key, query=q)):
        plats = ",".join(sorted({x.get("platform", "?") for x in p.get("social_accounts") or []}))
        cap = (p.get("caption") or "").replace("\n", " ")[:60]
        log(f"{p.get('id')}  {p.get('status'):<10} {p.get('scheduled_at') or p.get('created_at')}  [{plats}]  {cap}")


def cmd_delete(a, key):
    post = http("GET", f"/v1/social-posts/{a.post_id}", key)
    log(f"Пост {a.post_id}: статус {post.get('status')}, текст: {(post.get('caption') or '')[:80]}")
    if post.get("status") == "processed":
        log("Внимание: пост уже опубликован. Удаление здесь не удалит ролик из соцсети — его удаляют в самой соцсети.")
    if not a.yes:
        log("Чтобы удалить, повторите с --yes (после «да» человека).")
        return
    resp = http("DELETE", f"/v1/social-posts/{a.post_id}", key)
    log("Удалено." if resp.get("success", True) else "Ответ: " + json.dumps(clean(resp), ensure_ascii=False))


def cmd_feed(a, key):
    q = {"limit": a.limit, "expand": ["metrics"] if a.metrics else None}
    resp = http("GET", f"/v1/social-account-feeds/{a.account_id}", key, query=q)
    for p in items(resp):
        m = p.get("metrics") or {}
        brief = ", ".join(f"{k}={v}" for k, v in m.items() if isinstance(v, (int, float))) if m else ""
        cap = (p.get("caption") or "").replace("\n", " ")[:50]
        log(f"{p.get('posted_at') or ''}  {p.get('url') or p.get('platform_url') or ''}  {cap}" + (f"\n    {brief}" if brief else ""))
    if a.raw:
        log(json.dumps(clean(resp), ensure_ascii=False, indent=2)[:6000])


def main():
    ap = argparse.ArgumentParser(description="Post for Me: публикация в свои соцсети")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    s = sub.add_parser("accounts"); s.add_argument("--platform"); s.add_argument("--status")
    s = sub.add_parser("connect"); s.add_argument("platform"); s.add_argument("--external-id")
    s.add_argument("--via", choices=("instagram", "facebook"), default="instagram",
                   help="только для Instagram: вход через Instagram (по умолчанию) или через Facebook")
    s.add_argument("--platform-data", help='JSON, например {"instagram":{"connection_type":"instagram"}}')
    s = sub.add_parser("upload"); s.add_argument("file")
    s = sub.add_parser("post"); s.add_argument("name", help="короткое имя поста латиницей, защита от дублей")
    s.add_argument("--to", required=True, help="youtube,instagram | spc_... | all")
    s.add_argument("--media", action="append", help="путь к файлу или https-ссылка; можно несколько раз")
    s.add_argument("--caption"); s.add_argument("--caption-file")
    s.add_argument("--title"); s.add_argument("--privacy", choices=("public", "unlisted", "private"))
    s.add_argument("--placement", choices=("reels", "stories", "timeline"))
    s.add_argument("--cover", help="обложка: файл или ссылка"); s.add_argument("--cover-ms", type=int)
    s.add_argument("--schedule", help="ISO-время, например 2026-12-01T10:00:00+03:00")
    s.add_argument("--draft", action="store_true"); s.add_argument("--config")
    s.add_argument("--yes", action="store_true")
    s = sub.add_parser("status"); s.add_argument("post_id")
    s = sub.add_parser("wait"); s.add_argument("post_id"); s.add_argument("--minutes", type=int, default=15)
    s = sub.add_parser("posts"); s.add_argument("--limit", type=int, default=20)
    s.add_argument("--status", choices=("draft", "scheduled", "processing", "processed")); s.add_argument("--platform")
    s = sub.add_parser("delete"); s.add_argument("post_id"); s.add_argument("--yes", action="store_true")
    s = sub.add_parser("feed"); s.add_argument("account_id"); s.add_argument("--metrics", action="store_true")
    s.add_argument("--limit", type=int, default=10); s.add_argument("--raw", action="store_true")
    a = ap.parse_args()
    key = load_key()
    {"check": cmd_check, "accounts": cmd_accounts, "connect": cmd_connect, "upload": cmd_upload,
     "post": cmd_post, "status": cmd_status, "wait": cmd_wait, "posts": cmd_posts,
     "delete": cmd_delete, "feed": cmd_feed}[a.cmd](a, key)


if __name__ == "__main__":
    main()
