# -*- coding: utf-8 -*-
"""
Coupang(골드박스) -> Threads 자동 게시 (스크린샷 방식)

흐름:
1. 골드박스 API로 상품 후보 조회 (로켓배송만, 할인율 높은 순)
2. 아직 안 올린 상품 중 하나를 골라 파트너스 딥링크 생성
3. 실제 골드박스 페이지에서 그 상품 카드를 스크린샷으로 캡처
   (정가/할인율/전체 상품명이 이미지 안에 다 담겨있어서 텍스트 파싱 불필요)
4. 스크린샷을 imgbb에 업로드해서 공개 URL 확보
5. 상품명+가격+딥링크로 짧은 캡션 작성 후, 이미지와 함께 쓰레드에 게시
6. 스크린샷 실패 시 이미지 없이 텍스트만으로라도 게시 (완전히 스킵하지 않음)
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
    """골드박스가 매일 오전 7시(KST)에 갱신되므로, 그날그날 구분용 날짜 라벨."""
    return datetime.now(KST).strftime("%Y-%m-%d")


def load_posted() -> set:
    """
    게시 기록을 불러온다. 저장된 날짜가 오늘과 다르면(=골드박스가 갱신된 새 날이면)
    자동으로 빈 목록으로 새로 시작해서, 오늘 하루 안에서만 중복을 막는다.
    """
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


def product_key(raw_url: str) -> str:
    """
    productUrl 원본에는 매 API 호출마다 바뀌는 traceid가 포함돼 있어서
    URL 전체를 그대로 중복 판단 키로 쓰면 안 된다 (같은 상품도 매번 다른 문자열이 됨).
    itemId/vendorItemId(상품 고유값)만 뽑아서 안정적인 키로 사용한다.
    """
    parsed = urlparse(raw_url)
    params = parse_qs(parsed.query)
    item_id = params.get("itemId", [None])[0]
    vendor_item_id = params.get("vendorItemId", [None])[0]
    if item_id or vendor_item_id:
        return f"{item_id}:{vendor_item_id}"
    return raw_url  # 뽑을 게 없으면 마지막 수단으로 원본 URL 사용


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
    imgbb_api_key = os.environ.get("IMGBB_API_KEY")  # 없으면 이미지 없이 텍스트만 게시

    posted = load_posted()

    # 1. 골드박스 조회 (로켓배송만, 할인율/로켓배송 우선순위 정렬)
    candidates = sort_by_attractiveness(
        filter_rocket_only(
            get_goldbox_products(coupang_access_key, coupang_secret_key, limit=100)
        )
    )
    print(f"[골드박스] 후보 {len(candidates)}개")

    # 2. 아직 안 올린 상품들 중, 딥링크 변환에 성공한 것들을 최대 8개까지 모아서
    #    스크린샷 매칭 후보 목록으로 준비 (하나가 매칭 실패해도 자동으로 다음 걸 시도하기 위함)
    ready_candidates = []  # [(price, name, candidate_dict, deeplink), ...]
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
            price = candidate.get("productPrice", 0)
            ready_candidates.append((price, candidate["productName"], candidate, deeplink))
        except RuntimeError as e:
            print(f"딥링크 변환 실패, 다음 상품으로 넘어감: {candidate['productName']} ({e})")
            continue

    if not ready_candidates:
        print("오늘 골드박스에서 게시 가능한 새 상품을 찾지 못했습니다. 다음 실행에서 재시도합니다.")
        sys.exit(0)

    # 3. 골드박스 페이지를 한 번만 열고, 준비된 후보들을 순서대로 매칭 시도
    matched_candidate, full_name, parsed_discount_rate = find_and_capture_first_match(
        [(price, name, cand) for price, name, cand, _ in ready_candidates],
        SCREENSHOT_PATH,
    )

    if matched_candidate is None:
        print("시도한 후보 중 스크린샷 매칭에 성공한 게 없습니다 - 이번 회차는 게시하지 않고 스킵합니다.")
        sys.exit(0)

    # 매칭된 후보에 해당하는 딥링크 찾기
    target = matched_candidate
    deeplink = next(dl for _, _, cand, dl in ready_candidates if cand is matched_candidate)
    price = target.get("productPrice", 0)
    print(f"선택된 상품: {full_name} ({int(price):,}원)")
    print(f"딥링크: {deeplink}")

    if not imgbb_api_key:
        print("IMGBB_API_KEY가 설정되지 않아 이미지를 올릴 수 없습니다 - 스킵합니다.")
        sys.exit(0)

    try:
        image_url = upload_image_get_url(SCREENSHOT_PATH, imgbb_api_key)
    except Exception as e:
        print(f"이미지 업로드 실패 - 이번 회차는 게시하지 않고 스킵합니다: {e}")
        sys.exit(0)

    # 4. 최종 할인율: 카드에서 파싱된 값이 있으면 그걸 우선 사용, 없으면 API 값 사용
    discount_rate = parsed_discount_rate or target.get("discountRate")

    # 5. 캡션 생성 (전체 상품명 + 할인율 반영)
    caption = generate_caption(full_name, price, deeplink, discount_rate=discount_rate)
    print(f"게시 문구:\n{caption}")

    # 6. 쓰레드 게시
    media_id = post_to_threads(
        threads_user_id, threads_access_token, caption,
        image_url=image_url, topic_tag="광고"
    )
    print(f"게시 완료. media_id={media_id} (이미지 포함: {bool(image_url)})")

    # 7. 기록 저장
    posted.add(product_key(target["productUrl"]))
    save_posted(posted)


if __name__ == "__main__":
    main()
