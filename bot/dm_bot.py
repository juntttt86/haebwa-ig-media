#!/usr/bin/env python3
"""댓글 키워드 → 쿠팡 링크 카드 DM (GitHub Actions에서 10분마다, 기록 파일 없이).

- 각 글 폴더의 dm.json(공개 정보만: 키워드·블로그 주소·제품 이름·가격·쿠팡 파트너스 링크)을 읽는다.
- 게시물 캡션 속 블로그 주소로 글을 찾고, 키워드 댓글에 비공개 답장(제품 카드+버튼)을 보낸 뒤 공개 답글을 단다.
- 이미 처리했는지는 '내 계정의 공개 답글이 그 댓글에 달려 있는지'로 판단한다(기록 파일 불필요).
- 비공개 답장은 댓글당 1통, 댓글 후 7일 안(Meta 규칙). 내 댓글·ManyChat 담당 게시물(manychat_media)은 건너뜀.
환경변수: IG_TOKEN, IG_ID (GitHub Secrets)
"""
import datetime as dt
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "https://graph.facebook.com/v21.0"
PAGES = "https://juntttt86.github.io/haebwa-ig-media"
TOKEN, ME = os.environ["IG_TOKEN"], os.environ["IG_ID"]
EXTRA_KEYWORDS = ["링크"]
REPLIES = ["DM으로 보내드렸어요 📩", "링크 DM 드렸어요! 확인해 보세요 🙌", "보내드렸어요~ DM함 봐주세요 😊"]
MAX_PER_RUN = 30


def call(method, path, **params):
    if method == "GET":
        req = urllib.request.Request(f"{API}{path}?" + urllib.parse.urlencode({**params, "access_token": TOKEN}))
    else:
        req = urllib.request.Request(f"{API}{path}?access_token={urllib.parse.quote(TOKEN)}",
                                     data=json.dumps(params).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path} → {e.code} {e.read().decode('utf-8', 'replace')[:300]}") from None


def card(slug, d):
    note = "[광고] 쿠팡 파트너스 활동으로 수수료를 받아요"   # 잘려도 대가성 문구가 남게 맨 앞
    els = [{"title": f"{p['tag']} {p['brand']} {p['price']}"[:80],
            "subtitle": (f"{note} · {d['dm_note']}" if d.get("dm_note") else f"{note} · {p['for']}")[:80],
            "image_url": f"{PAGES}/{urllib.parse.quote(slug)}/product-{p['tag']}.jpg",
            "buttons": [{"type": "web_url", "url": p["link"], "title": "쿠팡에서 보기"},
                        {"type": "web_url", "url": d["blog_url"], "title": "전체 비교 글"}]}
           for p in d["products"]]
    return {"attachment": {"type": "template", "payload": {"template_type": "generic", "elements": els}}}


def main():
    posts = {}
    for f in ROOT.glob("*/dm.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        if not str(d.get("blog_url") or "").startswith("http"):   # 블로그 발행 전({BLOG_URL}) — 빈 값이 모든 캡션에 걸리지 않게
            continue
        posts[d["blog_url"]] = (f.parent.name, d)
    now = dt.datetime.now(dt.timezone.utc)
    sent = 0
    for m in call("GET", f"/{ME}/media", fields="id,caption", limit=25).get("data", []):
        hit = next((v for u, v in posts.items() if u in (m.get("caption") or "")), None)
        if not hit or m["id"] in hit[1].get("manychat_media", []):
            continue
        slug, d = hit
        kws = [d["dm_keyword"], *EXTRA_KEYWORDS]
        cs = call("GET", f"/{m['id']}/comments", fields="id,text,timestamp,from,replies{from}", limit=50).get("data", [])
        for c in cs:
            if (c.get("from") or {}).get("id") == ME:
                continue
            t = (c.get("text") or "").replace(" ", "").lower()
            if not any(k.lower() in t for k in kws):
                continue
            if now - dt.datetime.strptime(c["timestamp"], "%Y-%m-%dT%H:%M:%S%z") > dt.timedelta(days=7):
                continue
            if any((r.get("from") or {}).get("id") == ME for r in (c.get("replies") or {}).get("data", [])):
                continue   # 이미 공개 답글을 달았음 = 처리 끝
            if sent >= MAX_PER_RUN:
                print("이번 실행 한도 도달"); break
            try:
                call("POST", f"/{ME}/messages", recipient={"comment_id": c["id"]}, message=card(slug, d))
            except RuntimeError as e:
                print(f"[{slug}] {c['id']} DM 실패:", e)
                if "already" not in str(e).lower():
                    continue
            try:
                call("POST", f"/{c['id']}/replies", message=random.choice(REPLIES))
            except RuntimeError as e:
                print(f"[{slug}] {c['id']} 공개 답글 실패:", e)
            sent += 1
            print(f"[{slug}] {c['id']} → DM")
            time.sleep(1.5)
    print(f"{now:%Y-%m-%d %H:%M}Z 보냄 {sent}건")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        print("오류:", e); sys.exit(1)
