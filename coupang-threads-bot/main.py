# -*- coding: utf-8 -*-
"""
Coupang(골드박스) -> Threads 자동 게시 (화면에서 직접 상품 고르는 방식)

흐름:
1. 골드박스 페이지 위쪽(=잘 팔리는 순)부터 살펴보며, 아직 안 올린 로켓배송 상품을 하나 고름
   (쿠팡파트너스 API의 골드박스 목록 조회는 더 이상 안 씀 - 화면과 API 목록이 서로 달라서
   매칭이 계속 실패했기 때문에, 화면에 실제로 보이는 걸 그대로 신뢰하는 방식으로 변경)
2. 그 상품의 URL을 정리해서 파트너스 딥링크 생성 (API는 이 변환에만 사용)
3. 상품목록 카드의 데이터를 1번 예시 형태의 홍보 카드 이미지로 재구성
4. 생성한 이미지를 imgbb에 업로드해서 공개 URL 확보
5. 상품명+가격+링크로 캡션 작성 후, 이미지와 함께 쓰레드에 게시
"""
import os
import sys
import json
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs

from coupang_api import create_deeplink
from caption_generator import generate_caption
from threads_api import post_to_threads
from screenshot_capture import pick_top_unposted_product, extract_product_key
from image_host import upload_image_get_url
from product_card_renderer import render_product_card

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


def normalize_product_url(raw_url: str) -> str:
    """
    화면에서 뽑은 상품 링크에는 제휴 태그/추적값이 붙어있을 수 있어서,
    itemId/vendorItemId/pageKey만 뽑아 순수 상품 URL로 재조립한다.
    """
    parsed = urlparse(raw_url)
    params = parse_qs(parsed.query)

    item_id = params.get("itemId", [None])[0]
    vendor_item_id = params.get("vendorItemId", [None])[0]

    # /vp/products/{productId} 형태에서 productId 추출
    path_parts = parsed.path.strip("/").split("/")
    product_id = None
    if "products" in path_parts:
        idx = path_parts.index("products")
        if idx + 1 < len(path_parts):
            product_id = path_parts[idx + 1]
    product_id = product_id or params.get("pageKey", [None])[0] or item_id

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


def main():
    required_env = [
        "COUPANG_ACCESS_KEY",
        "COUPANG_SECRET_KEY",
        "THREADS_USER_ID",
        "THREADS_ACCESS_TOKEN",
        "IMGBB_API_KEY",
    ]
    missing = [name for name in required_env if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"필수 환경변수가 없습니다: {', '.join(missing)}")

    coupang_access_key = os.environ["COUPANG_ACCESS_KEY"]
    coupang_secret_key = os.environ["COUPANG_SECRET_KEY"]
    threads_user_id = os.environ["THREADS_USER_ID"]
    threads_access_token = os.environ["THREADS_ACCESS_TOKEN"]
    imgbb_api_key = os.environ.get("IMGBB_API_KEY")

    posted = load_posted()

    # 1. 화면 위(잘 팔리는 순)부터 살펴서 아직 안 올린 로켓배송 상품 선택
    picked = pick_top_unposted_product(posted, SCREENSHOT_PATH, require_rocket=True)
    if picked is None:
        print("게시할 새 상품을 화면에서 찾지 못했습니다. 다음 실행에서 다시 시도합니다.")
        sys.exit(0)

    raw_href = picked["href"]
    product_name = picked["name"]
    price = picked["price"]
    discount_rate = picked.get("discount_rate")
    print(f"선택된 상품: {product_name} ({int(price):,}원)")

    # 2. 딥링크 생성 (API는 이 변환에만 사용)
    clean_url = normalize_product_url(raw_href)
    try:
        deeplink_result = create_deeplink([clean_url], coupang_access_key, coupang_secret_key)
        deeplink = deeplink_result[0]["shortenUrl"]
    except Exception as e:
        raise RuntimeError(f"딥링크 변환 실패: {e}") from e
    print(f"딥링크: {deeplink}")

    # 3. 2번 상품목록 카드의 데이터를 1번 형태의 홍보 카드로 재구성
    try:
        render_product_card(picked, SCREENSHOT_PATH)
        print(f"[홍보 이미지] 카드 생성 완료: {SCREENSHOT_PATH}")
    except Exception as e:
        raise RuntimeError(f"홍보 이미지 생성 실패: {e}") from e

    # 4. imgbb 업로드
    try:
        image_url = upload_image_get_url(SCREENSHOT_PATH, imgbb_api_key)
    except Exception as e:
        raise RuntimeError(f"이미지 업로드 실패: {e}") from e

    # 5. 캡션 생성 및 게시
    caption = generate_caption(product_name, price, deeplink, discount_rate=discount_rate)
    print(f"게시 문구:\n{caption}")

    media_id = post_to_threads(
        threads_user_id, threads_access_token, caption,
        image_url=image_url, topic_tag="광고"
    )
    print(f"게시 완료. media_id={media_id}")

    # 6. Threads 게시 성공 후에만 중복 방지 기록 저장
    key = extract_product_key(raw_href)
    if key:
        posted.add(key)
        save_posted(posted)


if __name__ == "__main__":
    main()
