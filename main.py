# -*- coding: utf-8 -*-
"""
Coupang(골드박스) -> Threads 자동 게시 (화면에서 직접 상품 고르는 방식)
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
    parsed = urlparse(raw_url)
    params = parse_qs(parsed.query)

    item_id = params.get("itemId", [None])[0]
    vendor_item_id = params.get("vendorItemId", [None])[0]

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
    coupang_access_key = os.environ["COUPANG_ACCESS_KEY"]
    coupang_secret_key = os.environ["COUPANG_SECRET_KEY"]
    threads_user_id = os.environ["THREADS_USER_ID"]
    threads_access_token = os.environ["THREADS_ACCESS_TOKEN"]
    imgbb_api_key = os.environ.get("IMGBB_API_KEY")

    posted = load_posted()

    picked = pick_top_unposted_product(posted, SCREENSHOT_PATH, require_rocket=True)
    if picked is None:
        print("게시할 새 상품을 화면에서 찾지 못했습니다. 다음 실행에서 다시 시도합니다.")
        sys.exit(0)

    raw_href, product_name, price, discount_rate = picked
    print(f"선택된 상품: {product_name} ({int(price):,}원)")

    clean_url = normalize_product_url(raw_href)
    try:
        deeplink_result = create_deeplink([clean_url], coupang_access_key, coupang_secret_key)
        deeplink = deeplink_result[0]["shortenUrl"]
    except RuntimeError as e:
        print(f"딥링크 변환 실패 - 이번 회차는 게시하지 않고 스킵합니다: {e}")
        sys.exit(0)
    print(f"딥링크: {deeplink}")

    if not imgbb_api_key:
        print("IMGBB_API_KEY가 설정되지 않아 이미지를 올릴 수 없습니다 - 스킵합니다.")
        sys.exit(0)
    try:
        image_url = upload_image_get_url(SCREENSHOT_PATH, imgbb_api_key)
    except Exception as e:
        print(f"이미지 업로드 실패 - 이번 회차는 게시하지 않고 스킵합니다: {e}")
        sys.exit(0)

    caption = generate_caption(product_name, price, deeplink, discount_rate=discount_rate)
    print(f"게시 문구:\n{caption}")

    media_id = post_to_threads(
        threads_user_id, threads_access_token, caption,
        image_url=image_url, topic_tag="광고"
    )
    print(f"게시 완료. media_id={media_id}")

    key = extract_product_key(raw_href)
    if key:
        posted.add(key)
        save_posted(posted)


if __name__ == "__main__":
    main()
