# -*- coding: utf-8 -*-
"""
전체 자동화 파이프라인 (골드박스 우선 소싱 및 중복 방지 버전):
1. 쿠팡 골드박스(당일 특가) 상품 목록을 최우선 조회
2. posted.json과 대조하여 아직 게시하지 않은 골드박스 상품 선택
3. 골드박스 물량이 모두 소진되었거나 이미 다 올렸을 경우에만 베스트 카테고리 상품으로 보충
4. 파트너스 딥링크 생성 및 풀 상품명 수집
5. 이미지와 가격이 포함된 문구로 Threads에 게시
6. posted.json에 기록 저장 (중복 게시 완벽 방지)
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
    골드박스 API가 주는 URL은 제휴 태그가 포함된 링크이므로
    itemId/vendorItemId/pageKey를 추출하여 순수 상품 URL로 재조립합니다.
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
    """이미 게시된 상품 URL 기록을 불러옵니다."""
    if os.path.exists(POSTED_FILE):
        with open(POSTED_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_posted(posted_urls):
    """게시 기록을 JSON 파일로 저장합니다."""
    with open(POSTED_FILE, "w", encoding="utf-8") as f:
        json.dump(list(posted_urls), f, ensure_ascii=False, indent=2)


def attractiveness_score(candidate: dict) -> float:
    """할인율과 로켓배송 여부를 기준으로 상품 매력도 점수를 계산합니다."""
    score = 0.0
    discount_rate = candidate.get("discountRate")
    if discount_rate:
        try:
            score += float(discount_rate)
        except (TypeError, ValueError):
            pass
    if candidate.get("isRocket"):
        score += 5.0
    return score


def sort_by_attractiveness(candidates: list) -> list:
    return sorted(candidates, key=attractiveness_score, reverse=True)


def filter_rocket_only(candidates: list) -> list:
    return [c for c in candidates if c.get("isRocket")]


def main():
    coupang_access_key = os.environ["COUPANG_ACCESS_KEY"]
    coupang_secret_key = os.environ["COUPANG_SECRET_KEY"]
    threads_user_id = os.environ["THREADS_USER_ID"]
    threads_access_token = os.environ["THREADS_ACCESS_TOKEN"]

    # 1. 중복 게시 방지를 위해 기존 기록 로드
    posted = load_posted()

    # 2. 1순위: 골드박스(당일 특가) 상품 목록 조회 및 정렬
    print("[소싱] 오늘의 골드박스 상품 목록을 조회합니다.")
    try:
        raw_goldbox = get_goldbox_products(coupang_access_key, coupang_secret_key, limit=100)
        candidates = sort_by_attractiveness(filter_rocket_only(raw_goldbox))
        source_label = "골드박스"
    except Exception as e:
        print(f"[소싱 경고] 골드박스 조회 실패: {e}")
        candidates = []
        source_label = "베스트카테고리(대체)"

    target = None
    deeplink = None
    target_clean_url = None
    tried_fallback = False

    while True:
        # 후보군에서 아직 게시되지 않은 상품 탐색
        for candidate in candidates:
            product_url = candidate.get("productUrl")
            if not product_url or product_url in posted:
                continue
            
            clean_url = normalize_product_url(product_url)
            print(f"[{source_label}] 시도: {candidate.get('productName')} / 정리된 URL: {clean_url}")
            try:
                deeplink_result = create_deeplink(
                    [clean_url], coupang_access_key, coupang_secret_key
                )
                deeplink = deeplink_result[0]["shortenUrl"]
                target = candidate
                target_clean_url = clean_url
                break
            except RuntimeError as e:
                print(f"딥링크 변환 실패, 다음 상품으로 넘어감: {candidate.get('productName')} ({e})")
                continue

        if target is not None:
            break

        # 골드박스 소스에서 안 올린 상품을 못 찾았거나 품절된 경우 -> 2순위 베스트 카테고리로 전환
        if not tried_fallback:
            print("[소싱 전환] 골드박스 내 미게시 상품 소진. 베스트 카테고리 상품으로 보충합니다.")
            try:
                raw_best = get_best_products_pool(coupang_access_key, coupang_secret_key, limit_per_category=20)
                candidates = sort_by_attractiveness(filter_rocket_only(raw_best))
                source_label = "베스트카테고리"
            except Exception as e:
                print(f"[소싱 경고] 베스트 카테고리 조회 실패: {e}")
                candidates = []
            tried_fallback = True
        else:
            break

    if target is None:
        print("게시 가능한 새로운 상품을 찾지 못했습니다. 다음 실행에서 다시 시도합니다.")
        sys.exit(0)

    print(f"[디버그] 선택된 API 원본 데이터: {json.dumps(target, ensure_ascii=False, indent=2)}")

    # 3. 풀 상품명 수집 및 가격/이미지 추출
    product_name = get_full_product_title(target_clean_url, target.get("productName"))
    price = target.get("productPrice", 0)
    image_url = target.get("productImage")
    original_product_url = target.get("productUrl")

    print(f"선택된 상품: {product_name} ({int(price):,}원)")
    print(f"이미지 URL: {image_url}")
    print(f"딥링크: {deeplink}")

    # 4. 캡션 생성 (할인율 및 원가 정보 반영)
    caption = generate_caption(
        product_name,
        price,
        deeplink,
        discount_rate=target.get("discountRate"),
        original_price=target.get("productOriginalPrice")
    )
    print(f"게시 문구:\n{caption}")

    # 5. Threads에 이미지 포함 게시
    media_id = post_to_threads(
        user_id=threads_user_id,
        access_token=threads_access_token,
        text=caption,
        image_url=image_url,
        topic_tag="광고"
    )
    print(f"게시 완료. media_id={media_id}")

    # 6. 중복 게시 방지를 위해 원본 상품 URL을 기록에 추가 후 저장
    if original_product_url:
        posted.add(original_product_url)
        save_posted(posted)


if __name__ == "__main__":
    main()
