# -*- coding: utf-8 -*-
"""
쿠팡 골드박스 -> 쓰레드 자동 게시.

흐름:
  1. 골드박스 Open API로 당일 특가 상품 목록 조회
  2. picks.txt(수동 지정) 또는 필터+점수로 상품 하나 선정
  3. 파트너스 딥링크 발급
  4. 할인율/정가 보강 (선택, 실패해도 계속)
  5. 상품 이미지 + 정보를 홍보 카드 이미지로 렌더링
  6. imgbb에 업로드해 공개 URL 확보
  7. 캡션 생성 (Claude -> 실패 시 템플릿) 후 쓰레드 게시
  8. posted.json에 기록

DRY_RUN=1 로 실행하면 게시 직전까지만 수행하고 결과를 출력한다.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from caption_generator import generate_caption
from coupang_api import deeplink_for, get_goldbox_products
from image_host import upload_image_get_url
from product_card_renderer import render_product_card
from product_selector import select_product
from threads_api import post_to_threads

POSTED_FILE = "posted.json"
CARD_PATH = "composed_card.png"
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
            f,
            ensure_ascii=False,
            indent=2,
        )


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"[오류] 환경변수 {name} 가 설정되지 않았습니다.")
        sys.exit(1)
    return value


def main() -> None:
    dry_run = os.environ.get("DRY_RUN") == "1"

    access_key = require_env("COUPANG_ACCESS_KEY")
    secret_key = require_env("COUPANG_SECRET_KEY")
    sub_id = os.environ.get("COUPANG_SUB_ID")
    imgbb_key = os.environ.get("IMGBB_API_KEY")

    if not dry_run:
        threads_user_id = require_env("THREADS_USER_ID")
        threads_token = require_env("THREADS_ACCESS_TOKEN")

    # 1. 골드박스 목록
    try:
        products = get_goldbox_products(access_key, secret_key, limit=100)
    except Exception as exc:
        print(f"[오류] 골드박스 조회 실패: {exc}")
        sys.exit(1)

    if not products:
        print("골드박스 목록이 비어 있습니다. 다음 실행에서 재시도합니다.")
        sys.exit(0)

    # 2. 상품 선정
    posted = load_posted()
    target = select_product(products, posted)
    if target is None:
        print("게시 가능한 상품이 없습니다. 다음 실행에서 재시도합니다.")
        sys.exit(0)

    print(
        f"\n선정: [{target['id']}] {target['name']} / "
        f"{int(target['price']):,}원 / {target['category']}"
    )

    # 3. 딥링크
    deeplink = deeplink_for(target["product_url"], access_key, secret_key, sub_id)
    print(f"딥링크: {deeplink}")

    # 4. 할인율 보강 (실패 허용)
    try:
        from goldbox_enrich import enrich

        target = enrich(target)
    except Exception as exc:
        print(f"[보강] 건너뜀: {exc}")

    # 5. 카드 이미지 렌더링
    image_url = target.get("image_url")
    try:
        render_product_card(target, CARD_PATH)
        print(f"카드 이미지 생성: {CARD_PATH}")
        if imgbb_key:
            image_url = upload_image_get_url(CARD_PATH, imgbb_key)
        else:
            print("[이미지] IMGBB_API_KEY 없음 -> 원본 상품 이미지로 게시")
    except Exception as exc:
        print(f"[이미지] 카드 생성/업로드 실패, 원본 이미지로 대체: {exc}")

    # 6. 캡션
    caption = generate_caption(
        target["name"],
        target["price"],
        deeplink,
        discount_rate=target.get("discount_rate"),
        category=target.get("category", ""),
    )
    print(f"\n--- 게시 문구 ---\n{caption}\n-----------------")

    if dry_run:
        print(f"\n[DRY_RUN] 게시하지 않고 종료. 이미지 URL: {image_url}")
        return

    # 7. 게시
    media_id = post_to_threads(
        threads_user_id, threads_token, caption, image_url=image_url
    )
    print(f"게시 완료. media_id={media_id}")

    # 8. 기록
    posted.add(target["id"])
    save_posted(posted)


if __name__ == "__main__":
    main()
