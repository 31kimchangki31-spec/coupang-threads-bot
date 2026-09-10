# -*- coding: utf-8 -*-
"""
쿠팡 골드박스 -> 쓰레드 자동 게시.

흐름:
  1. 골드박스 Open API로 당일 특가 상품 목록 조회 (상품ID/링크 확보)
  2. 골드박스 페이지를 한 번 열어 모든 카드의 정확한 정보 수집 + 카드 캡처
     (API는 정가를 판매가로 주고 할인율을 주지 않으며 상품명도 잘려서 옴)
  3. 두 데이터를 병합해 상품 하나 선정 (picks.txt 우선, 없으면 필터+점수)
  4. 제휴 링크 확보 (골드박스 링크는 이미 제휴 링크라 변환 생략)
  5. 캡처한 카드를 Meta 요구 규격(JPEG, 4:5~1.91:1)으로 변환
  6. GitHub raw -> imgbb 순으로 공개 URL 확보
  7. 캡션 생성 (Claude -> 실패 시 템플릿) 후 쓰레드 게시
  8. posted.json에 기록 (상품ID + 상품명 기준 중복 제외, KST 06시 초기화)

DRY_RUN=1 이면 게시 직전까지만 수행한다.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from caption_generator import generate_caption
from coupang_api import deeplink_for, get_goldbox_products
from image_prep import prepare_for_threads
from product_selector import normalize_name, select_product
from threads_api import post_to_threads

POSTED_FILE = "posted.json"
KST = timezone(timedelta(hours=9))

# 게시 기록을 초기화하는 시각(KST). 기본 06시.
# 게시 스케줄이 07:05~05:35 이므로, 자정이 아니라 06시를 하루 경계로 삼는다.
RESET_HOUR = int(os.environ.get("RESET_HOUR", "6"))


def cycle_label() -> str:
    """
    현재 게시 주기의 이름. RESET_HOUR 를 하루 경계로 쓴다.
    예) RESET_HOUR=6 이면 09-09 05:30 은 아직 '09-08' 주기에 속한다.
    """
    now = datetime.now(KST)
    if now.hour < RESET_HOUR:
        now -= timedelta(days=1)
    return now.strftime("%Y-%m-%d")


def load_posted() -> tuple:
    """
    현재 주기의 게시 기록을 (상품ID 집합, 상품명키 집합) 으로 돌려준다.
    주기가 바뀌었으면 빈 집합을 반환해 자동으로 초기화된다.
    """
    empty = (set(), set())
    if not os.path.exists(POSTED_FILE):
        return empty
    try:
        with open(POSTED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return empty
    if not isinstance(data, dict):
        return empty

    # 이전 버전은 "date"/"ids" 형식이었으므로 둘 다 인정한다
    label = data.get("cycle") or data.get("date")
    if label != cycle_label():
        print(f"[기록] 주기 변경({label} -> {cycle_label()}), 게시 기록 초기화")
        return empty

    ids = {str(i) for i in data.get("ids", [])}
    names = {str(n) for n in data.get("names", [])}
    return ids, names


def save_posted(posted_ids: set, posted_names: set) -> None:
    with open(POSTED_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "cycle": cycle_label(),
                "reset_hour": RESET_HOUR,
                "ids": sorted(posted_ids),
                "names": sorted(posted_names),
            },
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
    게시용 이미지를 준비한다.

    쿠팡 페이지에서 캡처한 실제 카드만 사용한다.
    카드를 직접 그려서 만드는 경로는 없다. 캡처가 없으면 None을 반환하고,
    호출부에서 게시하지 않고 종료한다.
    """
    captured = target.get("card_image")
    if not captured or not os.path.exists(captured):
        print("[이미지] 캡처된 카드가 없습니다.")
        return None

    print(f"[이미지] 캡처한 골드박스 카드 사용: {captured}")
    return prepare_for_threads(captured)


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
    posted_ids, posted_names = load_posted()
    print(f"[기록] 주기 {cycle_label()} / 게시됨 {len(posted_ids)}건")
    target = select_product(products, posted_ids, page_data, posted_names)
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
            "  캡처도 없으므로 이 상품은 게시되지 않습니다.\n"
            + "!" * 60
        )


    # 4. 제휴 링크
    deeplink = deeplink_for(target["product_url"], access_key, secret_key, sub_id)
    print(f"링크: {deeplink}")

    # 5~6. 이미지 준비 + 공개 URL
    image_url = None
    local_image = resolve_image(target)
    if not local_image:
        print(
            "\n캡처 이미지가 없어 게시하지 않고 종료합니다.\n"
            "  이 봇은 쿠팡 페이지에서 캡처한 카드만 사용합니다.\n"
            "  페이지 수집이 실패한 경우이니 위의 [페이지] 로그를 확인하세요."
        )
        sys.exit(0)

    if dry_run:
        print(f"[DRY_RUN] 이미지 준비 완료(업로드 생략): {local_image}")
    else:
        from image_host import publish

        image_url = publish(local_image)
        if not image_url:
            print(
                "\n이미지 공개 URL 확보에 실패해 게시하지 않고 종료합니다.\n"
                "  이미지 없이 올리면 링크 미리보기만 붙은 글이 됩니다.\n"
                "  다음 실행에서 재시도합니다."
            )
            sys.exit(0)

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

    posted_ids.add(target["id"])
    posted_names.add(normalize_name(target["name"]))
    save_posted(posted_ids, posted_names)


if __name__ == "__main__":
    main()
