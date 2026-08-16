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
import random
from urllib.parse import urlparse, parse_qs

from coupang_api import get_goldbox_products, get_best_products_pool, create_deeplink, get_full_product_title
from caption_generator import generate_caption
from threads_api import post_to_threads

POSTED_FILE = "posted.json"

# 하루 23시간(오전 7시~다음날 오전 6시) 동안 30분 간격으로 워크플로가 46번 실행됨.
# 그중 평균 30번만 실제로 게시되도록 확률을 걸어서 간격을 불규칙하게 만든다.
DAILY_ACTIVE_SLOTS = 46   # 23시간 / 30분
DAILY_TARGET_POSTS = 30
POST_PROBABILITY = DAILY_TARGET_POSTS / DAILY_ACTIVE_SLOTS


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
        # 뽑을 정보가 없으면 원본 URL 그대로 시도 (마지막 수단)
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
    """
    클릭 잘 받을 만한 상품을 우선 노출하기 위한 점수.
    할인율이 높을수록, 로켓배송이면 가점.
    (쿠팡 API 응답에 discountRate가 없는 카테고리도 있어서 없으면 0으로 처리)
    """
    score = 0.0
    discount_rate = candidate.get("discountRate")
    if discount_rate:
        try:
            score += float(discount_rate)
        except (TypeError, ValueError):
            pass
    if candidate.get("isRocket"):
        score += 5  # 로켓배송 가점
    return score


def sort_by_attractiveness(candidates: list) -> list:
    return sorted(candidates, key=attractiveness_score, reverse=True)


def save_posted(posted_urls):
    with open(POSTED_FILE, "w", encoding="utf-8") as f:
        json.dump(list(posted_urls), f, ensure_ascii=False, indent=2)


def main():
    # 불규칙 게시: 이번 실행에서 실제로 올릴지 말지 확률로 결정.
    # 평균적으로 하루 30개 정도만 올라가고, 간격은 매번 달라짐.
    if random.random() > POST_PROBABILITY:
        print(f"이번 회차는 스킵 (확률 {POST_PROBABILITY:.0%}) - 불규칙 게시를 위한 정상 동작입니다.")
        sys.exit(0)

    coupang_access_key = os.environ["COUPANG_ACCESS_KEY"]
    coupang_secret_key = os.environ["COUPANG_SECRET_KEY"]
    threads_user_id = os.environ["THREADS_USER_ID"]
    threads_access_token = os.environ["THREADS_ACCESS_TOKEN"]

    posted = load_posted()

    # 1. 골드박스 특가 상품 조회 (최대치로), 할인율/로켓배송 기준 정렬
    candidates = sort_by_attractiveness(
        get_goldbox_products(coupang_access_key, coupang_secret_key, limit=100)
    )

    # 2~3. 아직 안 올린 상품 중, 딥링크 변환까지 성공하는 상품을 찾을 때까지 순서대로 시도.
    # 골드박스에서 다 소진되면(전부 게시했거나 변환 실패) 베스트 카테고리 풀을 추가로 불러와서 이어서 시도.
    target = None
    deeplink = None
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
                break
            except RuntimeError as e:
                print(f"딥링크 변환 실패, 다음 상품으로 넘어감: {candidate['productName']} ({e})")
                continue

        if target is not None:
            break

        if tried_fallback:
            # 베스트 카테고리까지 다 시도했는데도 없으면 포기
            break

        # 골드박스 소진 -> 베스트 카테고리 풀로 확장
        print("골드박스 물량 소진. 베스트 카테고리 상품으로 보충합니다.")
        candidates = sort_by_attractiveness(
            get_best_products_pool(
                coupang_access_key, coupang_secret_key, limit_per_category=20
            )
        )
        source_label = "베스트카테고리"
        tried_fallback = True

    if target is None:
        print("딥링크 변환 가능한 상품을 찾지 못했습니다. 다음 실행에서 다시 시도합니다.")
        sys.exit(0)

    product_name = get_full_product_title(target["productUrl"], target["productName"])
    price = target.get("productPrice", 0)
    print(f"선택된 상품: {product_name} ({int(price):,}원)")
    print(f"딥링크: {deeplink}")

    # 4. 캡션 생성
    caption = generate_caption(
        product_name, price, deeplink, discount_rate=target.get("discountRate")
    )
    print(f"게시 문구:\n{caption}")

    # 5. 쓰레드 게시
    # 이미지를 직접 첨부하지 않고 TEXT로 게시 -> 쓰레드가 링크를 스캔해서
    # 사진+상품명+가격이 담긴 미리보기 카드를 자동으로 붙여줌 ("광고" 라벨도 이때 같이 붙음)
    media_id = post_to_threads(
        threads_user_id, threads_access_token, caption
    )
    print(f"게시 완료. media_id={media_id}")

    # 6. 기록 저장
    posted.add(target["productUrl"])
    save_posted(posted)


if __name__ == "__main__":
    main()
