# -*- coding: utf-8 -*-

"""
Coupang -> Threads 자동 게시

게시 시간:
    KST 기준 07:00 ~ 다음날 05:30
    30분 단위

예:
    07:00
    07:30
    08:00
    08:30
    ...
    05:00
    05:30

GitHub Actions가 정시에 실행되지 않을 수 있기 때문에
실제 게시 시간은 해당 슬롯에서 약간 랜덤하게 처리합니다.

예:
    07:00 슬롯
    -> 07:03 게시
    -> 07:08 게시
    -> 07:10 게시

단, GitHub Actions가 늦게 시작한 경우에는
불필요하게 추가로 기다리지 않고 바로 게시합니다.

추가로 posted_slots.json을 이용해
같은 30분 슬롯에서 중복 게시하는 것을 방지합니다.
"""

import os
import sys
import json
import random
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlparse, parse_qs

from coupang_api import (
    get_goldbox_products,
    get_best_products_pool,
    create_deeplink,
    get_full_product_title,
)

from caption_generator import generate_caption
from threads_api import post_to_threads


POSTED_FILE = "posted.json"
POSTED_SLOTS_FILE = "posted_slots.json"

KST = ZoneInfo("Asia/Seoul")


# ============================================================
# 시간 관리
# ============================================================

def get_now_kst():
    """현재 한국시간을 반환합니다."""
    return datetime.now(KST)


def get_current_slot(now=None):
    """
    현재 시간을 30분 단위 슬롯으로 변환합니다.

    예:
        07:03 -> 07:00
        07:18 -> 07:00
        07:29 -> 07:00
        07:30 -> 07:30
        07:58 -> 07:30
        08:01 -> 08:00
    """
    if now is None:
        now = get_now_kst()

    minute = 0 if now.minute < 30 else 30

    return now.replace(
        minute=minute,
        second=0,
        microsecond=0
    )


def is_posting_time(now=None):
    """
    KST 기준 게시 가능 시간인지 확인합니다.

    07:00 ~ 다음날 05:59:59
    06:00부터는 게시하지 않습니다.
    """
    if now is None:
        now = get_now_kst()

    current_minutes = now.hour * 60 + now.minute

    # 07:00 ~ 23:59
    if 7 * 60 <= current_minutes <= 23 * 60 + 59:
        return True

    # 00:00 ~ 05:59
    if current_minutes < 6 * 60:
        return True

    return False


def wait_for_random_post_time(slot):
    """
    해당 30분 슬롯 안에서 0~10분 사이의 랜덤 게시시간을 만듭니다.

    예:
        슬롯 08:30
        랜덤 목표시간 08:36

    GitHub Actions가 목표시간보다 일찍 시작했다면 기다립니다.

    반대로 GitHub Actions가 이미 늦게 시작했다면
    추가 대기 없이 바로 진행합니다.
    """

    now = get_now_kst()

    random_seconds = random.randint(0, 600)

    target_time = slot + timedelta(seconds=random_seconds)

    print("")
    print("========================================")
    print("[예약 시간]")
    print(f"슬롯        : {slot.strftime('%Y-%m-%d %H:%M:%S')}")
    print(
        f"랜덤 목표시간: "
        f"{target_time.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    print(
        f"현재시간    : "
        f"{now.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    print("========================================")
    print("")

    if now >= target_time:
        print("[시간 처리] 이미 목표 시간이 지났습니다.")
        print("[시간 처리] 추가 대기 없이 바로 게시합니다.")
        return

    wait_seconds = int((target_time - now).total_seconds())

    print(
        f"[시간 처리] {wait_seconds}초 "
        f"({wait_seconds // 60}분 {wait_seconds % 60}초) "
        f"대기 후 게시합니다."
    )

    time.sleep(wait_seconds)

    print(
        f"[시간 처리] 대기 완료. "
        f"현재 KST: {get_now_kst().strftime('%Y-%m-%d %H:%M:%S')}"
    )


# ============================================================
# 게시 슬롯 기록
# ============================================================

def load_posted_slots():
    """
    이미 처리한 게시 슬롯을 불러옵니다.
    """

    if not os.path.exists(POSTED_SLOTS_FILE):
        return set()

    try:
        with open(
            POSTED_SLOTS_FILE,
            "r",
            encoding="utf-8"
        ) as f:
            data = json.load(f)

        if isinstance(data, list):
            return set(data)

        return set()

    except Exception as e:
        print(f"[경고] posted_slots.json 읽기 실패: {e}")
        return set()


def save_posted_slots(posted_slots):
    """
    게시 완료 슬롯을 저장합니다.
    """

    with open(
        POSTED_SLOTS_FILE,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            sorted(posted_slots),
            f,
            ensure_ascii=False,
            indent=2
        )


def slot_key(slot):
    """
    슬롯을 문자열로 변환합니다.

    예:
        2026-08-19 08:30
        ->
        2026-08-19T08:30
    """

    return slot.strftime("%Y-%m-%dT%H:%M")


# ============================================================
# 상품 URL
# ============================================================

def normalize_product_url(raw_url: str) -> str:
    """
    골드박스 API가 주는 URL에서
    상품 ID / itemId / vendorItemId를 추출하여
    순수 쿠팡 상품 URL로 재조립합니다.
    """

    parsed = urlparse(raw_url)
    params = parse_qs(parsed.query)

    item_id = params.get("itemId", [None])[0]
    vendor_item_id = params.get("vendorItemId", [None])[0]
    product_id = params.get("pageKey", [None])[0] or item_id

    if not product_id:
        return raw_url

    clean_url = (
        f"https://www.coupang.com/vp/products/{product_id}"
    )

    query_parts = []

    if item_id:
        query_parts.append(
            f"itemId={item_id}"
        )

    if vendor_item_id:
        query_parts.append(
            f"vendorItemId={vendor_item_id}"
        )

    if query_parts:
        clean_url += "?" + "&".join(query_parts)

    return clean_url


# ============================================================
# 기존 게시 기록
# ============================================================

def load_posted():
    """
    이미 게시된 상품 URL 기록을 불러옵니다.
    """

    if not os.path.exists(POSTED_FILE):
        return set()

    try:
        with open(
            POSTED_FILE,
            "r",
            encoding="utf-8"
        ) as f:
            data = json.load(f)

        if isinstance(data, list):
            return set(data)

        return set()

    except Exception as e:
        print(f"[경고] posted.json 읽기 실패: {e}")
        return set()


def save_posted(posted_urls):
    """
    게시된 상품 URL을 저장합니다.
    """

    with open(
        POSTED_FILE,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            sorted(posted_urls),
            f,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# 상품 선정
# ============================================================

def attractiveness_score(candidate: dict) -> float:
    """
    할인율 + 로켓배송 여부를 기준으로
    상품 매력도를 계산합니다.
    """

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
    return sorted(
        candidates,
        key=attractiveness_score,
        reverse=True
    )


def filter_rocket_only(candidates: list) -> list:
    return [
        c
        for c in candidates
        if c.get("isRocket")
    ]


# ============================================================
# 메인
# ============================================================

def main():

    # --------------------------------------------------------
    # 0. 현재 한국시간 확인
    # --------------------------------------------------------

    now = get_now_kst()

    print("")
    print("========================================")
    print("       Coupang -> Threads 자동 게시")
    print("========================================")
    print(
        f"현재 KST: "
        f"{now.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    print("")

    # --------------------------------------------------------
    # 1. 게시 가능 시간 확인
    # --------------------------------------------------------

    if not is_posting_time(now):
        print("[시간 종료]")
        print("현재는 게시 가능 시간이 아닙니다.")
        print("게시 시간: 07:00 ~ 다음날 05:59")
        sys.exit(0)

    # --------------------------------------------------------
    # 2. 현재 30분 슬롯 계산
    # --------------------------------------------------------

    slot = get_current_slot(now)
    current_slot_key = slot_key(slot)

    print(
        f"[게시 슬롯] "
        f"{slot.strftime('%Y-%m-%d %H:%M')}"
    )

    # --------------------------------------------------------
    # 3. 같은 슬롯 중복 게시 방지
    # --------------------------------------------------------

    posted_slots = load_posted_slots()

    if current_slot_key in posted_slots:
        print("")
        print("[중복 방지]")
        print(
            f"현재 슬롯 {current_slot_key}은 "
            f"이미 게시가 완료되었습니다."
        )
        print("이번 실행은 종료합니다.")
        sys.exit(0)

    # --------------------------------------------------------
    # 4. 슬롯 랜덤 시간 처리
    # --------------------------------------------------------

    wait_for_random_post_time(slot)

    # --------------------------------------------------------
    # 5. 환경변수
    # --------------------------------------------------------

    coupang_access_key = os.environ["COUPANG_ACCESS_KEY"]
    coupang_secret_key = os.environ["COUPANG_SECRET_KEY"]

    threads_user_id = os.environ["THREADS_USER_ID"]
    threads_access_token = os.environ["THREADS_ACCESS_TOKEN"]

    # --------------------------------------------------------
    # 6. 기존 상품 게시 기록
    # --------------------------------------------------------

    posted = load_posted()

    # --------------------------------------------------------
    # 7. 골드박스 우선 조회
    # --------------------------------------------------------

    print("")
    print("[소싱] 오늘의 골드박스 상품을 조회합니다.")

    try:

        raw_goldbox = get_goldbox_products(
            coupang_access_key,
            coupang_secret_key,
            limit=100
        )

        candidates = sort_by_attractiveness(
            filter_rocket_only(raw_goldbox)
        )

        source_label = "골드박스"

        print(
            f"[소싱] 골드박스 후보 "
            f"{len(candidates)}개"
        )

    except Exception as e:

        print(
            f"[소싱 경고] "
            f"골드박스 조회 실패: {e}"
        )

        candidates = []
        source_label = "베스트카테고리(대체)"

    target = None
    deeplink = None
    target_clean_url = None

    tried_fallback = False

    # --------------------------------------------------------
    # 8. 상품 선정
    # --------------------------------------------------------

    while True:

        for candidate in candidates:

            product_url = candidate.get(
                "productUrl"
            )

            if not product_url:
                continue

            if product_url in posted:
                print(
                    f"[중복 상품] "
                    f"{candidate.get('productName')}"
                )
                continue

            clean_url = normalize_product_url(
                product_url
            )

            print("")
            print(
                f"[{source_label}] 시도: "
                f"{candidate.get('productName')}"
            )

            print(
                f"[URL] {clean_url}"
            )

            try:

                deeplink_result = create_deeplink(
                    [clean_url],
                    coupang_access_key,
                    coupang_secret_key
                )

                deeplink = deeplink_result[0][
                    "shortenUrl"
                ]

                target = candidate
                target_clean_url = clean_url

                print(
                    "[상품 선정] "
                    f"{candidate.get('productName')}"
                )

                break

            except RuntimeError as e:

                print(
                    "[딥링크 변환 실패] "
                    f"{candidate.get('productName')} "
                    f"({e})"
                )

                continue

        if target is not None:
            break

        # ----------------------------------------------------
        # 골드박스 소진 -> 베스트 카테고리
        # ----------------------------------------------------

        if not tried_fallback:

            print("")
            print(
                "[소싱 전환] "
                "골드박스 내 미게시 상품이 없습니다."
            )

            try:

                raw_best = get_best_products_pool(
                    coupang_access_key,
                    coupang_secret_key,
                    limit_per_category=20
                )

                candidates = sort_by_attractiveness(
                    filter_rocket_only(raw_best)
                )

                source_label = "베스트카테고리"

                print(
                    f"[소싱] 베스트카테고리 후보 "
                    f"{len(candidates)}개"
                )

            except Exception as e:

                print(
                    f"[소싱 경고] "
                    f"베스트 카테고리 조회 실패: {e}"
                )

                candidates = []

            tried_fallback = True

        else:
            break

    # --------------------------------------------------------
    # 9. 게시 가능한 상품이 없는 경우
    # --------------------------------------------------------

    if target is None:

        print("")
        print(
            "게시 가능한 새로운 상품을 찾지 못했습니다."
        )
        print(
            "현재 슬롯은 게시 처리하지 않습니다."
        )

        sys.exit(0)

    # --------------------------------------------------------
    # 10. 상품 정보
    # --------------------------------------------------------

    print("")
    print("========================================")
    print("[선택된 상품]")
    print("========================================")

    print(
        json.dumps(
            target,
            ensure_ascii=False,
            indent=2
        )
    )

    product_name = get_full_product_title(
        target_clean_url,
        target.get("productName")
    )

    price = target.get(
        "productPrice",
        0
    )

    image_url = target.get(
        "productImage"
    )

    original_product_url = target.get(
        "productUrl"
    )

    print("")
    print(
        f"상품명: {product_name}"
    )

    try:
        print(
            f"가격: {int(price):,}원"
        )
    except Exception:
        print(
            f"가격: {price}"
        )

    print(
        f"이미지: {image_url}"
    )

    print(
        f"딥링크: {deeplink}"
    )

    # --------------------------------------------------------
    # 11. 캡션 생성
    # --------------------------------------------------------

    caption = generate_caption(
        product_name,
        price,
        deeplink,
        discount_rate=target.get(
            "discountRate"
        ),
        original_price=target.get(
            "productOriginalPrice"
        )
    )

    print("")
    print("========================================")
    print("[게시 문구]")
    print("========================================")
    print(caption)
    print("")

    # --------------------------------------------------------
    # 12. Threads 게시
    # --------------------------------------------------------

    try:

        media_id = post_to_threads(
            user_id=threads_user_id,
            access_token=threads_access_token,
            text=caption,
            image_url=image_url,
            topic_tag="광고"
        )

        print("")
        print("========================================")
        print("[게시 성공]")
        print("========================================")
        print(
            f"media_id = {media_id}"
        )

    except Exception as e:

        print("")
        print("========================================")
        print("[게시 실패]")
        print("========================================")
        print(e)

        # 게시 실패 시 슬롯 기록을 남기지 않습니다.
        # 다음 GitHub Actions 실행에서 재시도할 수 있습니다.
        raise

    # --------------------------------------------------------
    # 13. 상품 중복 방지 기록
    # --------------------------------------------------------

    if original_product_url:

        posted.add(
            original_product_url
        )

        save_posted(posted)

        print(
            "[기록] 상품 URL 저장 완료"
        )

    # --------------------------------------------------------
    # 14. 슬롯 중복 방지 기록
    # --------------------------------------------------------

    posted_slots.add(
        current_slot_key
    )

    save_posted_slots(
        posted_slots
    )

    print(
        f"[기록] 게시 슬롯 저장 완료: "
        f"{current_slot_key}"
    )

    print("")
    print("========================================")
    print("자동 게시 작업 완료")
    print("========================================")


if __name__ == "__main__":
    main()
