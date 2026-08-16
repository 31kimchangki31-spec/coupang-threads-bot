# -*- coding: utf-8 -*-
"""
쿠팡파트너스 Open API 연동 모듈
- 상품 URL -> 파트너스 딥링크(단축 URL) 변환
- HMAC 인증 방식은 쿠팡 공식 가이드를 따름
"""
import os
import time
import hmac
import hashlib
import json
import re
import requests

DOMAIN = "https://api-gateway.coupang.com"


def get_full_product_title(product_url: str, fallback_name: str) -> str:
    """
    API의 productName은 짧게 잘려있는 경우가 많아서(수량/용량 누락),
    실제 상품 페이지의 <title> 태그(쓰레드 링크카드가 쓰는 것과 동일한 정보)를 가져와
    본문에도 수량/용량까지 표시되게 한다. 실패하면 API의 짧은 이름으로 대체.
    """
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            )
        }
        resp = requests.get(product_url, headers=headers, timeout=5)
        if not resp.ok:
            print(f"[전체제목 조회 실패] status={resp.status_code} url={product_url} -> API 이름으로 대체: {fallback_name}")
            return fallback_name
        match = re.search(r"<title>(.*?)</title>", resp.text, re.DOTALL)
        if not match:
            print(f"[전체제목 조회 실패] title 태그 없음 url={product_url} -> API 이름으로 대체: {fallback_name}")
            return fallback_name
        title = match.group(1).strip()
        # "상품명, 500ml, 40개 - 국산생수 | 쿠팡" 형태에서 " | 쿠팡" 꼬리표만 제거
        title = re.sub(r"\s*\|\s*쿠팡\s*$", "", title).strip()
        if not title:
            print(f"[전체제목 조회 실패] title 비어있음 url={product_url} -> API 이름으로 대체: {fallback_name}")
            return fallback_name
        print(f"[전체제목 조회 성공] {title}")
        return title
    except requests.RequestException:
        return fallback_name


def generate_hmac(method: str, url: str, secret_key: str, access_key: str) -> str:
    """쿠팡 Open API 인증 헤더(Authorization) 생성"""
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
    """
    상품 URL 리스트를 파트너스 딥링크로 변환.
    product_urls: ["https://www.coupang.com/vp/products/12345", ...]
    반환: [{"originalUrl": ..., "shortenUrl": ...}, ...]
    """
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


def search_products(keyword: str, access_key: str, secret_key: str, limit: int = 10) -> list:
    """
    키워드로 쿠팡 상품 검색 (자동으로 올릴 상품을 고를 때 사용, 시간당 10회 제한)
    """
    method = "GET"
    path = (
        f"/v2/providers/affiliate_open_api/apis/openapi/products/search"
        f"?keyword={requests.utils.quote(keyword)}&limit={limit}"
    )
    authorization = generate_hmac(method, path, secret_key, access_key)
    headers = {"Authorization": authorization}

    resp = requests.get(DOMAIN + path, headers=headers)
    resp.raise_for_status()
    result = resp.json()

    if result.get("rCode") != "0":
        raise RuntimeError(f"상품 검색 실패: {result.get('rMessage')}")

    return result["data"]["productData"]


def get_goldbox_products(access_key: str, secret_key: str, limit: int = 20) -> list:
    """
    쿠팡 골드박스(당일 특가) 상품 목록 조회.
    반환 항목에 productName, productPrice, productImage, productUrl 등이 들어있음.
    """
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
    """
    카테고리별 베스트(인기) 상품 목록 조회.
    category_id 예시: 1001(여성패션), 1010(뷰티), 1012(주방용품), 1024(생활용품) 등.
    """
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


# 자주 쓰는 생활/인기 카테고리 (필요하면 자유롭게 추가/삭제하세요)
DEFAULT_CATEGORY_IDS = [
    "1024",  # 생활용품
    "1012",  # 주방용품
    "1010",  # 뷰티
    "1013",  # 식품
]


def get_best_products_pool(
    access_key: str, secret_key: str, category_ids=None, limit_per_category: int = 20
) -> list:
    """
    여러 카테고리의 베스트 상품을 한번에 모아서 보조 상품 풀로 사용.
    골드박스 물량이 소진됐을 때 이걸로 채운다.
    """
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
