# -*- coding: utf-8 -*-
"""
Toss쇼핑 쉐어링크 -> Threads 자동 게시

흐름:
1. 하루특가 상품 목록 조회
2. 상세 조회로 최신 가격/할인율/이미지/품절여부 재확인
3. 아직 안 올린 것 중 품절 아닌 첫 상품 선택
4. 쉐어링크(추적 링크) 발급
5. 캡션 생성 후, API가 준 이미지 URL 그대로 써서 쓰레드에 게시
   (스크린샷/이미지 업로드 단계가 필요 없음 - 이미지가 이미 공개 URL로 옴)
"""
import os
import sys
import json
from datetime import datetime, timezone, timedelta

from toss_api import get_access_token, get_today_deals, get_product_detail, issue_share_link
from caption_generator import generate_caption
from threads_api import post_to_threads

POSTED_FILE = "posted.json"
KST = timezone(timedelta(hours=9))


def today_label() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def load_posted() -> set:
    if os.path.exists(POSTED_FILE):
        with open(POSTED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("date") == today_label():
            return set(data.get("ids", []))
    return set()


def save_posted(posted_ids: set):
    data = {"date": today_label(), "ids": list(posted_ids)}
    with open(POSTED_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    access_key = os.environ["TOSS_ACCESS_KEY"]
    secret_key = os.environ["TOSS_SECRET_KEY"]
    publisher_id = os.environ["TOSS_PUBLISHER_ID"]
    threads_user_id = os.environ["THREADS_USER_ID"]
    threads_access_token = os.environ["THREADS_ACCESS_TOKEN"]

    posted = load_posted()

    token = get_access_token(access_key, secret_key)
    print("[토스] 액세스 토큰 발급 완료")

    deals = get_today_deals(token, size=30)
    items = deals.get("items", [])
    print(f"[토스] 하루특가 후보 {len(items)}개")

    if not items:
        print("오늘 편성된 하루특가가 없습니다. 다음 실행에서 다시 시도합니다.")
        sys.exit(0)

    # 아직 안 올린 상품들의 tacaItemId만 추려서, 상세조회로 최신 정보 재확인 (최대 30개)
    candidate_ids = [it["tacaItemId"] for it in items if it["tacaItemId"] not in posted]
    if not candidate_ids:
        print("오늘 특가 상품을 이미 다 게시했습니다. 다음 실행에서 다시 시도합니다.")
        sys.exit(0)

    detail_result = get_product_detail(token, candidate_ids[:30])
    detail_map = {d["tacaItemId"]: d for d in detail_result.get("items", [])}

    target = None
    for taca_item_id in candidate_ids:
        detail = detail_map.get(taca_item_id)
        if detail is None:
            continue  # notFoundIds에 있는 경우 (판매종료/페널티 등) -> 건너뜀
        if detail.get("isSoldOut"):
            continue
        target = detail
        break

    if target is None:
        print("게시 가능한(품절 아닌) 상품을 찾지 못했습니다. 다음 실행에서 다시 시도합니다.")
        sys.exit(0)

    taca_item_id = target["tacaItemId"]
    product_name = target["displayName"]
    price = target["displayPrice"]
    discount_rate = target.get("discountRate")
    image_url = target.get("thumbnailUrl") or (target.get("mainImageUrls") or [None])[0]

    print(f"선택된 상품: {product_name} ({int(price):,}원) / 할인율 {discount_rate}")

    # 쉐어링크(추적 링크) 발급
    link_result = issue_share_link(token, taca_item_id, publisher_id)
    deeplink = link_result["shortUrl"]
    print(f"쉐어링크: {deeplink}")

    caption = generate_caption(product_name, price, deeplink, discount_rate=discount_rate)
    print(f"게시 문구:\n{caption}")

    media_id = post_to_threads(
        threads_user_id, threads_access_token, caption,
        image_url=image_url, topic_tag="광고"
    )
    print(f"게시 완료. media_id={media_id}")

    posted.add(taca_item_id)
    save_posted(posted)


if __name__ == "__main__":
    main()
