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
RSS = "https://rss.blog.naver.com/juntttt.xml"
PH = "{BLOG_URL}"   # 블로그 글이 아직 예약 상태일 때 캡션·dm.json에 넣는 자리(2026-11-26 PS5부터)


def blog_url_for(key):
    """네이버 블로그 RSS에서 제목에 key(예: '3종비교 #17')가 든 발행 글 주소를 찾는다. 없으면 None."""
    import re
    import xml.etree.ElementTree as ET
    try:
        with urllib.request.urlopen(urllib.request.Request(RSS, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as r:
            root = ET.fromstring(r.read())
    except Exception as e:
        print("RSS 실패:", str(e)[:120])
        return None
    for it in root.iter("item"):
        if key in (it.findtext("title") or ""):
            m = re.search(r"blog\.naver\.com/juntttt/(\d+)", it.findtext("link") or it.findtext("guid") or "")
            if m:
                return f"https://blog.naver.com/juntttt/{m.group(1)}"
    return None


def fill_blog_url(f, item):
    """캡션에 PH가 있으면 발행된 블로그 주소로 바꾸고 dm.json도 고친다. 아직 발행 전이면 False(다음 실행에 다시)."""
    if PH not in item["caption"]:
        return True
    url = blog_url_for(item.get("blog_title_key") or "")
    if not item.get("blog_title_key") or not url:
        print("블로그 글 발행 대기:", f.name, item.get("blog_title_key"))
        return False
    item["caption"] = item["caption"].replace(PH, url)
    f.write_text(json.dumps(item, ensure_ascii=False, indent=1), encoding="utf-8")
    dmj = ROOT / item["slug"] / "dm.json"
    if dmj.exists():
        d = json.loads(dmj.read_text(encoding="utf-8"))
        if d.get("blog_url") in (PH, "", None):
            d["blog_url"] = url
            dmj.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    for g in Q.glob(f"*{item['slug']}.json"):   # 같은 글의 다른 예약(캐러셀 등)도 같이
        o = json.loads(g.read_text(encoding="utf-8"))
        if PH in o["caption"]:
            o["caption"] = o["caption"].replace(PH, url)
            g.write_text(json.dumps(o, ensure_ascii=False, indent=1), encoding="utf-8")
    print("블로그 주소 채움:", url)
    return True


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
        args = dict(media_type="REELS", video_url=item["video"], cover_url=item["cover"],
                    caption=item["caption"], share_to_feed="false")
        if item.get("ai_audio"):          # AI 음성 → Meta 'AI 정보' 표시
            try:
                c = call("POST", f"/{ME}/media", **args, is_ai_generated="true")["id"]
            except RuntimeError as e:     # 이 계정·버전에서 지원 안 되면 표시 없이(캡션에 AI 음성 안내가 있음)
                print("AI 표시 실패 → 표시 없이 진행:", str(e)[:200])
                c = call("POST", f"/{ME}/media", **args)["id"]
        else:
            c = call("POST", f"/{ME}/media", **args)["id"]
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
        if not fill_blog_url(f, item):
            continue
        changed = True
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
        subprocess.run(["git", "add", "-A", "queue", "*/dm.json"], check=True)
        subprocess.run(["git", "commit", "-qm", "예약 게시 처리"], check=True)
        subprocess.run(["git", "push", "-q"], check=True)


if __name__ == "__main__":
    main()
