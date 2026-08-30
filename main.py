# -*- coding: utf-8 -*-
"""
Coupang(골드박스) -> Threads 자동 게시 (API 후보 + 화면 매칭 혼합 방식)

흐름:
1. 골드박스 API로 상품 후보 조회 (로켓배송만, 할인율 높은 순)
2. 아직 안 올린 상품 중 딥링크 변환까지 성공하는 후보를 최대 8개 준비
3. 골드박스 페이지를 한 번 열어서, 8개를 순서대로 화면과 매칭 시도 (실패하면 다음 후보로)
4. 매칭된 카드를 스크린샷 -> imgbb 업로드 -> 쓰레드에 게시
"""
import os
import sys
import json
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs

from coupang_api import get_goldbox_products, create_deeplink
from caption_generator import generate_caption
from threads_api import post_to_threads
from screenshot_capture import find_and_capture_first_match
from image_host import upload_image_get_url

POSTED_FILE = "posted.json"
SCREENSHOT_PATH = "goldbox_item.png"

KST = timezone(timedelta(hours=9))


def today_label() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def load_posted() -> set:
    if os.path.exists(POSTED_FILE):
        with open(POSTED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("date") == today_label():
            return set(data.get("urls", []))
    return set()


def save_posted(posted_urls: set):
    data = {"date": today_label(), "urls": list(posted_urls)}
    with open(POSTED_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def normalize_product_url(raw_url: str) -> str:
    """골드박스 API의 productUrl은 매번 바뀌는 traceid가 붙어있어서, 순수 상품 URL로 재조립."""
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


def product_key(raw_url: str) -> str:
    """traceid가 매번 바뀌는 원본 URL 대신, itemId+vendorItemId(고유값)로 중복 판단."""
    parsed = urlparse(raw_url)
    params = parse_qs(parsed.query)
    item_id = params.get("itemId", [None])[0]
    vendor_item_id = params.get("vendorItemId", [None])[0]
    if item_id or vendor_item_id:
        return f"{item_id}:{vendor_item_id}"
    return raw_url


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


def main():
    coupang_access_key = os.environ["COUPANG_ACCESS_KEY"]
    coupang_secret_key = os.environ["COUPANG_SECRET_KEY"]
    threads_user_id = os.environ["THREADS_USER_ID"]
    threads_access_token = os.environ["THREADS_ACCESS_TOKEN"]
    imgbb_api_key = os.environ.get("IMGBB_API_KEY")

    posted = load_posted()

    # 1. 골드박스 조회 (로켓배송만, 할인율/로켓배송 우선순위 정렬)
    candidates = sort_by_attractiveness(
        filter_rocket_only(
            get_goldbox_products(coupang_access_key, coupang_secret_key, limit=100)
        )
    )
    print(f"[골드박스] 후보 {len(candidates)}개")

    # 2. 아직 안 올린 상품 중, 딥링크 변환 성공하는 것들을 최대 8개까지 준비
    ready_candidates = []
    for candidate in candidates:
        if len(ready_candidates) >= 8:
            break
        if product_key(candidate["productUrl"]) in posted:
            continue
        clean_url = normalize_product_url(candidate["productUrl"])
        print(f"[골드박스] 시도: {candidate['productName']} / 정리된 URL: {clean_url}")
        try:
            deeplink_result = create_deeplink([clean_url], coupang_access_key, coupang_secret_key)
            deeplink = deeplink_result[0]["shortenUrl"]
            candidate["_deeplink"] = deeplink
            price = candidate.get("productPrice", 0)
            name = candidate.get("productName", "")
            ready_candidates.append((price, name, candidate))
        except RuntimeError as e:
            print(f"딥링크 변환 실패, 다음 상품으로 넘어감: {candidate['productName']} ({e})")
            continue

    if not ready_candidates:
        print("딥링크 변환 가능한 상품을 찾지 못했습니다. 다음 실행에서 다시 시도합니다.")
        sys.exit(0)

    # 3. 골드박스 페이지 한 번 열어서, 준비된 후보들을 순서대로 화면과 매칭
    matched_candidate, full_name, discount_rate = find_and_capture_first_match(
        ready_candidates, SCREENSHOT_PATH
    )

    if matched_candidate is None:
        print("시도한 후보 중 스크린샷 매칭에 성공한 게 없습니다 - 이번 회차는 게시하지 않고 스킵합니다.")
        sys.exit(0)

    price = matched_candidate.get("productPrice", 0)
    deeplink = matched_candidate["_deeplink"]
    # 화면에서 못 뽑았으면 API 할인율로 대체
    if discount_rate is None:
        discount_rate = matched_candidate.get("discountRate")

    print(f"선택된 상품: {full_name} ({int(price):,}원)")
    print(f"딥링크: {deeplink}")

    # 4. imgbb 업로드
    if not imgbb_api_key:
        print("IMGBB_API_KEY가 설정되지 않아 이미지를 올릴 수 없습니다 - 스킵합니다.")
        sys.exit(0)
    try:
        image_url = upload_image_get_url(SCREENSHOT_PATH, imgbb_api_key)
    except Exception as e:
        print(f"이미지 업로드 실패 - 이번 회차는 게시하지 않고 스킵합니다: {e}")
        sys.exit(0)

    # 5. 캡션 생성 및 게시
    caption = generate_caption(full_name, price, deeplink, discount_rate=discount_rate)
    print(f"게시 문구:\n{caption}")

    media_id = post_to_threads(
        threads_user_id, threads_access_token, caption,
        image_url=image_url, topic_tag="광고"
    )
    print(f"게시 완료. media_id={media_id}")

    # 6. 기록 저장
    posted.add(product_key(matched_candidate["productUrl"]))
    save_posted(posted)


if __name__ == "__main__":
    main()
