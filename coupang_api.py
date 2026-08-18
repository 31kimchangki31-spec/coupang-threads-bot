# -*- coding: utf-8 -*-
"""
쿠팡파트너스 Open API 연동 모듈
- 상품 URL -> 파트너스 딥링크(단축 URL) 변환
- Playwright를 사용한 쿠팡 차단 우회 및 풀 상품명 수집
"""
import os
import time
import hmac
import hashlib
import json
import re
import html
import requests
from playwright.sync_api import sync_playwright

DOMAIN = "https://api-gateway.coupang.com"


def get_full_product_title(product_url: str, fallback_name: str) -> str:
    """
    Playwright headless 브라우저를 사용하여 쿠팡의 봇 차단(403)을 우회하고
    전체 상품명을 가져옵니다.
    """
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/128.0.0.0 Safari/537.36"
                ),
                locale="ko-KR"
            )
            page = context.new_page()
            page.goto(product_url, wait_until="domcontentloaded", timeout=15000)
            
            raw_title = page.title()
            browser.close()

            if raw_title:
                title = re.sub(r"\s*[\|-]\s*쿠팡\s*$", "", raw_title, flags=re.IGNORECASE).strip()
                title = html.unescape(title)
                if title and title != "쿠팡!":
                    print(f"[Playwright 전체제목 조회 성공] {title}")
                    return title
    except Exception as e:
        print(f"[Playwright 전체제목 조회 실패] 예외 발생: {e}")

    print(f"-> API 이름으로 대체: {fallback_name}")
    return fallback_name


def generate_hmac(method: str, url: str, secret_key: str, access_key: str) -> str:
    path, *query = url.split("?")
    os.environ["TZ"] = "GMT+0"
    time.tzset()
    datetime_str = time.strftime("%y%m%d") + "T" + time.strftime("%H%M%S") + "Z"
    message = datetime_str + method + path + (query[0] if query else "")
    signature = hmac.new(
        bytes(secret_key, "utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return (
        f"CEA algorithm=HmacSHA256, access-key={access_key}, "
        f"signed-date={datetime_str}, signature={signature}"
    )


def create_deeplink(product_urls, access_key: str, secret_key: str) -> list:
    method = "POST"
    path = "/v2/providers/affiliate_open_api/apis/openapi/v1/deeplink"
    authorization = generate_hmac(method, path, secret_key, access_key)

    headers = {
        "Authorization": authorization,
        "Content-Type": "application/json;charset=UTF-8",
    }
    body = {"coupangUrls": product_urls}

    resp = requests.post(DOMAIN + path, headers=headers, data=json.dumps(body))
    resp.raise_for_status()
    result = resp.json()

    if result.get("rCode") != "0":
        raise RuntimeError(f"딥링크 생성 실패: {result.get('rMessage')}")

    return result["data"]


def get_goldbox_products(access_key: str, secret_key: str, limit: int = 20) -> list:
    method = "GET"
    path = f"/v2/providers/affiliate_open_api/apis/openapi/products/goldbox?limit={limit}"
    authorization = generate_hmac(method, path, secret_key, access_key)
    headers = {"Authorization": authorization}

    resp = requests.get(DOMAIN + path, headers=headers)
    resp.raise_for_status()
    result = resp.json()

    if result.get("rCode") != "0":
        raise RuntimeError(f"골드박스 조회 실패: {result.get('rMessage')}")

    return result["data"]


def get_best_category_products(
    category_id: str, access_key: str, secret_key: str, limit: int = 20
) -> list:
    method = "GET"
    path = (
        f"/v2/providers/affiliate_open_api/apis/openapi/products/bestcategories/"
        f"{category_id}?limit={limit}"
    )
    authorization = generate_hmac(method, path, secret_key, access_key)
    headers = {"Authorization": authorization}

    resp = requests.get(DOMAIN + path, headers=headers)
    resp.raise_for_status()
    result = resp.json()

    if result.get("rCode") != "0":
        raise RuntimeError(f"베스트 카테고리 조회 실패: {result.get('rMessage')}")

    return result["data"]


DEFAULT_CATEGORY_IDS = ["1024", "1012", "1010", "1013"]


def get_best_products_pool(
    access_key: str, secret_key: str, category_ids=None, limit_per_category: int = 20
) -> list:
    if category_ids is None:
        category_ids = DEFAULT_CATEGORY_IDS

    pool = []
    for cid in category_ids:
        try:
            items = get_best_category_products(
                cid, access_key, secret_key, limit=limit_per_category
            )
            pool.extend(items)
        except RuntimeError as e:
            print(f"카테고리 {cid} 베스트 조회 실패, 건너뜀: {e}")
            continue
    return pool
