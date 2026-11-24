#!/usr/bin/env python3
"""예약 게시 — queue/*.json 중 시각(KST)이 지난 것을 게시한다 (GitHub Actions에서 10분마다).

queue 항목(맥의 publish_ig.py --at 이 만든다):
  {"slug": 글폴더, "kind": "carousel"|"reel", "at": "YYYY-MM-DD HH:MM" (KST), "caption": …,
   "images": [공개 주소…] 또는 "video": 주소, "cover": 주소}
게시하면 queue/done/으로 옮기고 결과(게시물 주소)를 적어 커밋한다. 실패하면 error를 적고 다음 실행에 다시 시도(3번까지).
"""
import datetime as dt
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
Q, DONE = ROOT / "queue", ROOT / "queue" / "done"
API = "https://graph.facebook.com/v21.0"
TOKEN, ME = os.environ["IG_TOKEN"], os.environ["IG_ID"]
KST = dt.timezone(dt.timedelta(hours=9))


def call(method, path, **p):
    p["access_token"] = TOKEN
    if method == "GET":
        req = urllib.request.Request(f"{API}{path}?" + urllib.parse.urlencode(p))
    else:
        req = urllib.request.Request(f"{API}{path}", data=urllib.parse.urlencode(p).encode(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path} → {e.code} {e.read().decode('utf-8', 'replace')[:300]}") from None


def ready(cid):
    for _ in range(60):
        st = call("GET", f"/{cid}", fields="status_code").get("status_code")
        if st == "FINISHED":
            return
        if st in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"처리 실패 {st}")
        time.sleep(5)
    raise RuntimeError("처리 시간 초과")


def post(item):
    if item["kind"] == "carousel":
        kids = [call("POST", f"/{ME}/media", image_url=u, is_carousel_item="true")["id"] for u in item["images"]]
        for k in kids:
            ready(k)
        c = call("POST", f"/{ME}/media", media_type="CAROUSEL", children=",".join(kids), caption=item["caption"])["id"]
    else:
        c = call("POST", f"/{ME}/media", media_type="REELS", video_url=item["video"], cover_url=item["cover"],
                 caption=item["caption"], share_to_feed="false")["id"]
    ready(c)
    mid = call("POST", f"/{ME}/media_publish", creation_id=c)["id"]
    return call("GET", f"/{mid}", fields="permalink,timestamp") | {"id": mid}


def main():
    now = dt.datetime.now(KST)
    changed = False
    for f in sorted(Q.glob("*.json")):
        item = json.loads(f.read_text(encoding="utf-8"))
        if dt.datetime.strptime(item["at"], "%Y-%m-%d %H:%M").replace(tzinfo=KST) > now:
            continue
        try:
            item["result"] = post(item)
            DONE.mkdir(exist_ok=True)
            (DONE / f.name).write_text(json.dumps(item, ensure_ascii=False, indent=1), encoding="utf-8")
            f.unlink()
            print("게시:", f.name, item["result"].get("permalink"))
        except RuntimeError as e:
            item["tries"] = item.get("tries", 0) + 1
            item["error"] = str(e)[:300]
            if item["tries"] >= 3:
                DONE.mkdir(exist_ok=True)
                (DONE / ("FAILED-" + f.name)).write_text(json.dumps(item, ensure_ascii=False, indent=1), encoding="utf-8")
                f.unlink()
            else:
                f.write_text(json.dumps(item, ensure_ascii=False, indent=1), encoding="utf-8")
            print("실패:", f.name, e)
        changed = True
    if changed:
        subprocess.run(["git", "config", "user.name", "haebwa-bot"], check=True)
        subprocess.run(["git", "config", "user.email", "haebwa-bot@users.noreply.github.com"], check=True)
        subprocess.run(["git", "add", "-A", "queue"], check=True)
        subprocess.run(["git", "commit", "-qm", "예약 게시 처리"], check=True)
        subprocess.run(["git", "push", "-q"], check=True)


if __name__ == "__main__":
    main()
