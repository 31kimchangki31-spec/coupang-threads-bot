# -*- coding: utf-8 -*-
"""
Toss쇼핑 쉐어링크 -> Threads 자동 게시 (카드형 이미지 합성 버전)

흐름:
1. 하루특가 상품 목록 조회
2. 상세 조회로 최신 가격/할인율/이미지/품절여부 재확인
3. 아직 안 올린 것 중 품절 아닌 첫 상품 선택
4. 쉐어링크(추적 링크) 발급
5. 상품 사진 위에 할인배지/상품명/가격/별점을 합성한 카드 이미지 생성
6. 합성 이미지를 imgbb에 업로드해서 공개 URL 확보 후 쓰레드에 게시
"""
import os
import sys
import json
from datetime import datetime, timezone, timedelta

from toss_api import get_access_token, get_today_deals, get_product_detail, issue_share_link
from caption_generator import generate_caption
from threads_api import post_to_threads
from image_compose import compose_product_card
from image_host import upload_image_get_url

POSTED_FILE = "posted.json"
COMPOSED_IMAGE_PATH = "composed_card.png"
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
    imgbb_api_key = os.environ.get("IMGBB_API_KEY")

    posted = load_posted()

    token = get_access_token(access_key, secret_key)
    print("[토스] 액세스 토큰 발급 완료")

    deals = get_today_deals(token, size=30)
    items = deals.get("items", [])
    print(f"[토스] 하루특가 후보 {len(items)}개")

    if not items:
        print("오늘 편성된 하루특가가 없습니다. 다음 실행에서 다시 시도합니다.")
        sys.exit(0)

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
            continue
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
    review_score = target.get("reviewScore")
    review_count = target.get("reviewCount")
    source_image_url = target.get("thumbnailUrl") or (target.get("mainImageUrls") or [None])[0]

    print(f"선택된 상품: {product_name} ({int(price):,}원) / 할인율 {discount_rate}")

    # 쉐어링크(추적 링크) 발급
    link_result = issue_share_link(token, taca_item_id, publisher_id)
    deeplink = link_result["shortUrl"]
    print(f"쉐어링크: {deeplink}")

    # 카드형 이미지 합성
    image_url = None
    if source_image_url:
        composed = compose_product_card(
            source_image_url, product_name, price, discount_rate,
            review_score, review_count, COMPOSED_IMAGE_PATH,
            original_price=target.get("originalPrice"),
        )
        if composed and imgbb_api_key:
            try:
                image_url = upload_image_get_url(COMPOSED_IMAGE_PATH, imgbb_api_key)
            except Exception as e:
                print(f"[이미지 호스팅] 업로드 실패, 원본 사진으로 대체: {e}")
                image_url = source_image_url
        else:
            # 합성 실패했거나 imgbb 키가 없으면, 원본 상품 사진(이미 공개 URL)으로 대체
            image_url = source_image_url

    caption = generate_caption(product_name, price, deeplink, discount_rate=discount_rate)
    print(f"게시 문구:\n{caption}")

    media_id = post_to_threads(
        threads_user_id, threads_access_token, caption,
        image_url=image_url
    )
    print(f"게시 완료. media_id={media_id}")

    posted.add(taca_item_id)
    save_posted(posted)


if __name__ == "__main__":
    main()
