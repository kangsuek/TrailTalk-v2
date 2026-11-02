"""M5-02 네이버 뉴스·블로그 검색 API 확인 스크립트. 호출은 질의당 1회씩 7회다.

키는 환경 변수 NAVER_CLIENT_ID·NAVER_CLIENT_SECRET로만 받고 파일·출력에 남기지 않는다.
사용: NAVER_CLIENT_ID=... NAVER_CLIENT_SECRET=... uv run python naver_spike.py
결과 요약은 logs/naver.json에 쓴다(키 없음).
"""

import json
import os
import re
import statistics
import time
from pathlib import Path

import httpx2 as httpx

URL = "https://openapi.naver.com/v1/search/{kind}.json"
TAG = re.compile(r"<[^>]+>")
LOGS = Path(__file__).resolve().parent / "logs"

CASES = [
    ("news", "코스피 마감 시황", "date", 10),
    ("news", "삼성전자 실적", "sim", 10),
    ("blog", "제주도 맛집 후기", "sim", 10),
    ("blog", "제주도 맛집 후기", "date", 10),
    ("blog", "아이폰 17 사용 후기", "sim", 10),
    ("blog", "서울 한강공원 피크닉 경험담", "date", 30),
    ("blog", "Nvidia earnings", "sim", 10),
]


def main() -> None:
    headers = {
        "X-Naver-Client-Id": os.environ["NAVER_CLIENT_ID"],
        "X-Naver-Client-Secret": os.environ["NAVER_CLIENT_SECRET"],
    }
    out = []
    with httpx.Client(timeout=10) as client:
        for kind, query, sort, display in CASES:
            started = time.monotonic()
            resp = client.get(
                URL.format(kind=kind),
                params={"query": query, "sort": sort, "display": display},
                headers=headers,
            )
            elapsed = round(time.monotonic() - started, 2)
            row = {"kind": kind, "query": query, "sort": sort, "display": display,
                   "status": resp.status_code, "elapsed_s": elapsed}  # fmt: skip
            if resp.status_code == 200:
                body = resp.json()
                items = body.get("items", [])
                row["total"] = body.get("total")
                row["fields"] = sorted(items[0]) if items else []
                row["hosts"] = sorted(
                    {re.sub(r"^https?://([^/]+).*", r"\1", i.get("link", "")) for i in items}
                )
                row["sample"] = [
                    {k: TAG.sub("", str(v))[:90] for k, v in i.items()} for i in items[:3]
                ]
            else:
                row["error"] = resp.text[:200]
            out.append(row)
            print(kind, query, sort, resp.status_code, elapsed, row.get("total"))
    times = [r["elapsed_s"] for r in out]
    print("지연 중앙값", statistics.median(times), "최대", max(times))
    LOGS.mkdir(exist_ok=True)
    (LOGS / "naver.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
