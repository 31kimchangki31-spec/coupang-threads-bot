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
import requests

DOMAIN = "https://api-gateway.coupang.com"


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
