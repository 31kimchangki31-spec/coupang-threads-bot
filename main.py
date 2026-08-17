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
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs

from coupang_api import get_goldbox_products, get_best_products_pool, create_deeplink, get_full_product_title
from caption_generator import generate_caption
from threads_api import post_to_threads

POSTED_FILE = "posted.json"
DAILY_COUNT_FILE = "daily_count.json"

KST = timezone(timedelta(hours=9))
WINDOW_START_HOUR = 7    # 활성 구간 시작: 오전 7시(KST)
WINDOW_LENGTH_HOURS = 23  # 오전 7시 ~ 다음날 오전 6시
SLOT_MINUTES = 15         # 워크플로가 대략 이 간격으로 돎 (실제 실행은 GitHub 사정에 따라 들쭉날쭉)
DAILY_TARGET_POSTS = 30


def get_window_info(now_kst: datetime):
    """지금이 속한 활성 구간(07:00~다음날 06:00)의 날짜 라벨과 끝나는 시각을 계산"""
    if now_kst.hour < WINDOW_START_HOUR:
        window_date = (now_kst - timedelta(days=1)).date()
    else:
        window_date = now_kst.date()
    start = datetime(window_date.year, window_date.month, window_date.day, WINDOW_START_HOUR, tzinfo=KST)
    end = start + timedelta(hours=WINDOW_LENGTH_HOURS)
    return window_date, start, end


def load_daily_count(window_date) -> tuple:
    data = {}
    if os.path.exists(DAILY_COUNT_FILE):
        with open(DAILY_COUNT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    return data.get(str(window_date), 0), data


def save_daily_count(window_date, count: int, data: dict):
    data[str(window_date)] = count
    # 오래된 날짜 기록은 최근 3일치만 남기고 정리
    for old_key in sorted(data.keys())[:-3]:
        data.pop(old_key, None)
    with open(DAILY_COUNT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def decide_should_post():
    """
    오늘 목표(30개) 대비 지금까지 게시한 개수와, 활성 구간 마감까지 남은 시간을 보고
    이번 회차에 게시할지 확률적으로 결정한다.
    실행이 중간에 몇 번 씹혀도(GitHub 스케줄 특성), 마감이 다가올수록 확률이 자동으로
    올라가서 하루 목표치에 최대한 맞춰진다.
    """
    now = datetime.now(KST)
    window_date, start, end = get_window_info(now)

    if now < start or now > end:
        print(f"활성 시간대(07:00~다음날 06:00) 밖입니다. 지금: {now.strftime('%H:%M')}")
        return False, window_date, 0, {}

    already_posted, data = load_daily_count(window_date)
    remaining_target = DAILY_TARGET_POSTS - already_posted

    if remaining_target <= 0:
        print(f"오늘({window_date}) 목표({DAILY_TARGET_POSTS}개) 이미 달성. 스킵.")
        return False, window_date, already_posted, data

    remaining_minutes = max(1, (end - now).total_seconds() / 60)
    remaining_slots = max(1, remaining_minutes / SLOT_MINUTES)
    probability = min(1.0, remaining_target / remaining_slots)

    roll = random.random()
    should_post = roll < probability
    print(
        f"[스케줄] {window_date} 기준 {already_posted}/{DAILY_TARGET_POSTS}개 게시됨, "
        f"마감까지 약 {remaining_minutes:.0f}분 남음, 이번 확률 {probability:.0%} -> "
        f"{'게시' if should_post else '스킵'}"
    )
    return should_post, window_date, already_posted, data


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


def filter_rocket_only(candidates: list) -> list:
    """로켓배송 상품만 남기고 나머지는 제외"""
    return [c for c in candidates if c.get("isRocket")]


def save_posted(posted_urls):
    with open(POSTED_FILE, "w", encoding="utf-8") as f:
        json.dump(list(posted_urls), f, ensure_ascii=False, indent=2)


def main():
    should_post, window_date, already_posted, daily_data = decide_should_post()
    if not should_post:
        sys.exit(0)

    coupang_access_key = os.environ["COUPANG_ACCESS_KEY"]
    coupang_secret_key = os.environ["COUPANG_SECRET_KEY"]
    threads_user_id = os.environ["THREADS_USER_ID"]
    threads_access_token = os.environ["THREADS_ACCESS_TOKEN"]

    posted = load_posted()

    # 1. 골드박스 특가 상품 조회 (최대치로), 로켓배송만 남기고 할인율/로켓배송 기준 정렬
    candidates = sort_by_attractiveness(
        filter_rocket_only(
            get_goldbox_products(coupang_access_key, coupang_secret_key, limit=100)
        )
    )

    # 2~3. 아직 안 올린 상품 중, 딥링크 변환까지 성공하는 상품을 찾을 때까지 순서대로 시도.
    # 골드박스에서 다 소진되면(전부 게시했거나 변환 실패) 베스트 카테고리 풀을 추가로 불러와서 이어서 시도.
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
            # 베스트 카테고리까지 다 시도했는데도 없으면 포기
            break

        # 골드박스 소진 -> 베스트 카테고리 풀로 확장 (역시 로켓배송만)
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

    product_name = get_full_product_title(target_clean_url, target["productName"])
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
    save_daily_count(window_date, already_posted + 1, daily_data)


if __name__ == "__main__":
    main()
