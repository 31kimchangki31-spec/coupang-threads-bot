# -*- coding: utf-8 -*-
"""
쿠팡 골드박스 -> 쓰레드 자동 게시.

흐름:
  1. 골드박스 Open API로 당일 특가 상품 목록 조회 (상품ID/링크 확보)
  2. 골드박스 페이지를 한 번 열어 모든 카드의 정확한 정보 수집 + 카드 캡처
     (API는 정가를 판매가로 주고 할인율을 주지 않으며 상품명도 잘려서 옴)
  3. 두 데이터를 병합해 상품 하나 선정 (picks.txt 우선, 없으면 필터+점수)
  4. 제휴 링크 확보 (골드박스 링크는 이미 제휴 링크라 변환 생략)
  5. 카드 이미지를 Meta 요구 규격(JPEG, 4:5~1.91:1)으로 변환
  6. GitHub raw -> imgbb 순으로 공개 URL 확보
  7. 캡션 생성 (Claude -> 실패 시 템플릿) 후 쓰레드 게시
  8. posted.json에 기록

DRY_RUN=1 이면 게시 직전까지만 수행한다.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from caption_generator import generate_caption
from coupang_api import deeplink_for, get_goldbox_products
from image_prep import prepare_for_threads
from product_selector import select_product
from threads_api import post_to_threads

POSTED_FILE = "posted.json"
FALLBACK_CARD = "composed_card.png"
KST = timezone(timedelta(hours=9))


def today_label() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def load_posted() -> set:
    """당일 게시 기록만 유지한다 (골드박스는 매일 갱신되므로)."""
    if not os.path.exists(POSTED_FILE):
        return set()
    try:
        with open(POSTED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return set()
    if isinstance(data, dict) and data.get("date") == today_label():
        return {str(i) for i in data.get("ids", [])}
    return set()


def save_posted(posted_ids: set) -> None:
    with open(POSTED_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"date": today_label(), "ids": sorted(posted_ids)},
            f, ensure_ascii=False, indent=2,
        )


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"[오류] 환경변수 {name} 가 설정되지 않았습니다.")
        sys.exit(1)
    return value


def resolve_image(target: dict) -> str:
    """
    게시용 이미지 경로를 만든다.
    1순위: 페이지에서 캡처한 실제 골드박스 카드
    2순위: 상품 정보로 직접 렌더링한 카드
    """
    captured = target.get("card_image")
    if captured and os.path.exists(captured):
        print(f"[이미지] 캡처한 골드박스 카드 사용: {captured}")
        return prepare_for_threads(captured)

    print("[이미지] 캡처 없음 -> 카드 직접 렌더링")
    try:
        from product_card_renderer import render_product_card

        render_product_card(target, FALLBACK_CARD)
        return prepare_for_threads(FALLBACK_CARD)
    except Exception as exc:
        print(f"[이미지] 렌더링도 실패: {exc}")
        return None


def main() -> None:
    dry_run = os.environ.get("DRY_RUN") == "1"

    access_key = require_env("COUPANG_ACCESS_KEY")
    secret_key = require_env("COUPANG_SECRET_KEY")
    sub_id = os.environ.get("COUPANG_SUB_ID")

    if not dry_run:
        threads_user_id = require_env("THREADS_USER_ID")
        threads_token = require_env("THREADS_ACCESS_TOKEN")

    # 1. 골드박스 API 목록
    try:
        products = get_goldbox_products(access_key, secret_key, limit=100)
    except Exception as exc:
        print(f"[오류] 골드박스 조회 실패: {exc}")
        sys.exit(1)

    if not products:
        print("골드박스 목록이 비어 있습니다. 다음 실행에서 재시도합니다.")
        sys.exit(0)

    # 2. 페이지에서 정확한 정보 수집 (실패해도 계속)
    page_data = {}
    try:
        from goldbox_page import scrape_all

        page_data = scrape_all(max_cards=60)
    except Exception as exc:
        print(f"[페이지] 수집 건너뜀: {exc}")

    # 3. 선정
    posted = load_posted()
    target = select_product(products, posted, page_data)
    if target is None:
        print("게시 가능한 상품이 없습니다. 다음 실행에서 재시도합니다.")
        sys.exit(0)

    origin = target.get("original_price")
    price_desc = (
        f"{int(origin):,}원 -> {int(target['price']):,}원"
        if origin and origin > target["price"]
        else f"{int(target['price']):,}원"
    )
    rate = target.get("discount_rate")
    print(
        f"\n선정: [{target['id']}] {target['name']}\n"
        f"      {price_desc}"
        + (f" ({float(rate):.0f}% 할인)" if rate else "")
        + (" [쿠폰 조건부]" if target.get("coupon_required") else "")
    )
    if not target.get("from_page"):
        print(
            "\n" + "!" * 60 + "\n"
            "  경고: 페이지 데이터 없음 -> API 값으로 게시합니다.\n"
            "  API 가격은 '정가'일 수 있어 특가로 잘못 광고될 위험이 있습니다.\n"
            "  상품명도 잘리고 할인율도 표시되지 않습니다.\n"
            "  REQUIRE_PAGE_DATA=1 로 두면 이런 경우 게시하지 않고 건너뜁니다.\n"
            + "!" * 60
        )
        if os.environ.get("REQUIRE_PAGE_DATA") == "1":
            print("REQUIRE_PAGE_DATA=1 이므로 게시하지 않고 종료합니다.")
            sys.exit(0)

    # 4. 제휴 링크
    deeplink = deeplink_for(target["product_url"], access_key, secret_key, sub_id)
    print(f"링크: {deeplink}")

    # 5~6. 이미지 준비 + 공개 URL
    image_url = None
    local_image = resolve_image(target)
    if local_image:
        if dry_run:
            print(f"[DRY_RUN] 이미지 준비 완료(업로드 생략): {local_image}")
        else:
            from image_host import publish

            image_url = publish(local_image)

    # 7. 캡션
    caption = generate_caption(
        target["name"],
        target["price"],
        deeplink,
        discount_rate=target.get("discount_rate"),
        original_price=target.get("original_price"),
        coupon_required=target.get("coupon_required", False),
        category=target.get("category", ""),
    )
    print(f"\n--- 게시 문구 ---\n{caption}\n-----------------")

    if dry_run:
        print("\n[DRY_RUN] 게시하지 않고 종료합니다.")
        return

    # 8. 게시
    # 주제 태그. 기본 "광고". POST_TOPIC_TAG 로 변경하거나 빈 값으로 끌 수 있다.
    topic_tag = os.environ.get("POST_TOPIC_TAG", "광고").strip() or None
    if topic_tag:
        print(f"주제 태그: {topic_tag}")

    media_id = post_to_threads(
        threads_user_id, threads_token, caption,
        image_url=image_url, topic_tag=topic_tag,
    )
    print(f"게시 완료. media_id={media_id}")

    posted.add(target["id"])
    save_posted(posted)


if __name__ == "__main__":
    main()
