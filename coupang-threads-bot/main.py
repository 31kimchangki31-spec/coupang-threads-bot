# -*- coding: utf-8 -*-
"""
전체 자동화 파이프라인 (골드박스 자동 소싱 버전):
1. 쿠팡 골드박스(당일 특가) 상품 목록 조회
2. 아직 안 올린 상품 중 하나 선택
3. 파트너스 딥링크 생성
4. 상품명+가격+이미지로 게시글 문구 구성
5. 쓰레드에 이미지 포함 게시
6. posted.json에 사용 기록 남김 (중복 게시 방지)
"""
import os
import sys
import json

from coupang_api import get_goldbox_products, create_deeplink
from caption_generator import generate_caption
from threads_api import post_to_threads

POSTED_FILE = "posted.json"


def load_posted():
    if os.path.exists(POSTED_FILE):
        with open(POSTED_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_posted(posted_urls):
    with open(POSTED_FILE, "w", encoding="utf-8") as f:
        json.dump(list(posted_urls), f, ensure_ascii=False, indent=2)


def main():
    coupang_access_key = os.environ["COUPANG_ACCESS_KEY"]
    coupang_secret_key = os.environ["COUPANG_SECRET_KEY"]
    threads_user_id = os.environ["THREADS_USER_ID"]
    threads_access_token = os.environ["THREADS_ACCESS_TOKEN"]

    posted = load_posted()

    # 1. 골드박스 특가 상품 조회
    candidates = get_goldbox_products(
        coupang_access_key, coupang_secret_key, limit=20
    )

    # 2. 아직 안 올린 상품 선택
    target = next(
        (p for p in candidates if p["productUrl"] not in posted), None
    )
    if target is None:
        print("오늘 골드박스 상품을 모두 게시했습니다. 나중에 다시 시도해주세요.")
        sys.exit(0)

    product_name = target["productName"]
    price = target.get("productPrice", 0)
    image_url = target.get("productImage")
    print(f"선택된 상품: {product_name} ({price:,}원)")

    # 3. 딥링크 생성
    deeplink_result = create_deeplink(
        [target["productUrl"]], coupang_access_key, coupang_secret_key
    )
    deeplink = deeplink_result[0]["shortenUrl"]
    print(f"딥링크: {deeplink}")

    # 4. 캡션 생성
    caption = generate_caption(product_name, price, deeplink)
    print(f"게시 문구:\n{caption}")

    # 5. 쓰레드 게시 (상품 이미지 포함)
    media_id = post_to_threads(
        threads_user_id, threads_access_token, caption, image_url=image_url
    )
    print(f"게시 완료. media_id={media_id}")

    # 6. 기록 저장
    posted.add(target["productUrl"])
    save_posted(posted)


if __name__ == "__main__":
    main()
