# -*- coding: utf-8 -*-
"""
전체 자동화 파이프라인 (골드박스 자동 소싱 버전):
1. 쿠팡 골드박스(당일 특가) 상품 목록 조회
2. 아직 안 올린 상품 중 하나 선택
3. 파트너스 딥링크 생성
4. 상품명+가격+이미지로 게시글 문구 구성
5. 쓰레드에 이미지 포함 게시 (media_type: IMAGE)
6. posted.json에 사용 기록 남김 (중복 게시 방지)
"""
import os
import sys
import json
from urllib.parse import urlparse, parse_qs

from coupang_api import get_goldbox_products, get_best_products_pool, create_deeplink, get_full_product_title
from caption_generator import generate_caption
from threads_api import post_to_threads

POSTED_FILE = "posted.json"


def normalize_product_url(raw_url: str) -> str:
    """
    골드박스 API가 주는 URL은 이미 다른 제휴 태그(lptag)가 찍힌
    link.coupang.com 링크라 딥링크 재변환이 거부된다.
    쿼리스트링의 itemId/vendorItemId/pageKey를 뽑아 순수 상품 URL로 재조립한다.
    """
    parsed = urlparse(raw_url)
    params = parse_qs(parsed.query)

    item_id = params.get("itemId", [None])[0]
    vendor_item_id = params.get("vendorItemId", [None])[0]
    product_id = params.get("pageKey", [None])[0] or item_id

    if not product_id:
        return raw_url

    clean_url = f"https://www.coupang.com/vp/products/{product_id}"
    query_parts = []
    if item_id:
        query_parts.append(f"itemId={item_id}")
    if vendor_item_id:
        query_parts.append(f"vendorItemId={vendor_item_id}")
    if query_parts:
        clean_url += "?" + "&".join(query_parts)

    return clean_url


def load_posted():
    if os.path.exists(POSTED_FILE):
        with open(POSTED_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def attractiveness_score(candidate: dict) -> float:
    score = 0.0
    discount_rate = candidate.get("discountRate")
    if discount_rate:
        try:
            score += float(discount_rate)
        except (TypeError, ValueError):
            pass
    if candidate.get("isRocket"):
        score += 5
    return score


def sort_by_attractiveness(candidates: list) -> list:
    return sorted(candidates, key=attractiveness_score, reverse=True)


def filter_rocket_only(candidates: list) -> list:
    return [c for c in candidates if c.get("isRocket")]


def save_posted(posted_urls):
    with open(POSTED_FILE, "w", encoding="utf-8") as f:
        json.dump(list(posted_urls), f, ensure_ascii=False, indent=2)


def main():
    coupang_access_key = os.environ["COUPANG_ACCESS_KEY"]
    coupang_secret_key = os.environ["COUPANG_SECRET_KEY"]
    threads_user_id = os.environ["THREADS_USER_ID"]
    threads_access_token = os.environ["THREADS_ACCESS_TOKEN"]

    posted = load_posted()

    candidates = sort_by_attractiveness(
        filter_rocket_only(
            get_goldbox_products(coupang_access_key, coupang_secret_key, limit=100)
        )
    )

    target = None
    deeplink = None
    target_clean_url = None
    source_label = "골드박스"
    tried_fallback = False

    while True:
        for candidate in candidates:
            if candidate["productUrl"] in posted:
                continue
            clean_url = normalize_product_url(candidate["productUrl"])
            print(f"[{source_label}] 시도: {candidate['productName']} / 정리된 URL: {clean_url}")
            try:
                deeplink_result = create_deeplink(
                    [clean_url], coupang_access_key, coupang_secret_key
                )
                deeplink = deeplink_result[0]["shortenUrl"]
                target = candidate
                target_clean_url = clean_url
                break
            except RuntimeError as e:
                print(f"딥링크 변환 실패, 다음 상품으로 넘어감: {candidate['productName']} ({e})")
                continue

        if target is not None:
            break

        if tried_fallback:
            break

        print("골드박스 물량 소진. 베스트 카테고리 상품으로 보충합니다.")
        candidates = sort_by_attractiveness(
            filter_rocket_only(
                get_best_products_pool(
                    coupang_access_key, coupang_secret_key, limit_per_category=20
                )
            )
        )
        source_label = "베스트카테고리"
        tried_fallback = True

    if target is None:
        print("딥링크 변환 가능한 상품을 찾지 못했습니다. 다음 실행에서 다시 시도합니다.")
        sys.exit(0)

    print(f"[디버그] API 원본 데이터 전체: {json.dumps(target, ensure_ascii=False, indent=2)}")

    product_name = get_full_product_title(target_clean_url, target["productName"])
    price = target.get("productPrice", 0)
    image_url = target.get("productImage")  # 쿠팡 대표 이미지 추출

    print(f"선택된 상품: {product_name} ({int(price):,}원)")
    print(f"이미지 URL: {image_url}")
    print(f"딥링크: {deeplink}")

    # 4. 캡션 생성 (원가/할인율 정보 포함)
    caption = generate_caption(
        product_name,
        price,
        deeplink,
        discount_rate=target.get("discountRate"),
        original_price=target.get("productOriginalPrice")
    )
    print(f"게시 문구:\n{caption}")

    # 5. 쓰레드 게시 (image_url을 전달하여 이미지 포함 게시글로 등록)
    media_id = post_to_threads(
        user_id=threads_user_id,
        access_token=threads_access_token,
        text=caption,
        image_url=image_url,
        topic_tag="광고"
    )
    print(f"게시 완료. media_id={media_id}")

    # 6. 기록 저장
    posted.add(target["productUrl"])
    save_posted(posted)


if __name__ == "__main__":
    main()
