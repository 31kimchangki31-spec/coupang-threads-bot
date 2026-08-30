# -*- coding: utf-8 -*-
"""
쿠팡파트너스 Open API 연동 모듈 (골드박스 조회 + 딥링크 변환)
"""
import os
import time
import hmac
import hashlib
import json
import requests

DOMAIN = "https://api-gateway.coupang.com"


def generate_hmac(method: str, url: str, secret_key: str, access_key: str) -> str:
    """쿠팡 Open API 인증 헤더(Authorization) 생성 (크로스플랫폼: tzset 대신 gmtime 사용)"""
    path, *query = url.split("?")
    utc_now = time.gmtime()
    datetime_str = time.strftime("%y%m%d", utc_now) + "T" + time.strftime("%H%M%S", utc_now) + "Z"
    message = datetime_str + method + path + (query[0] if query else "")
    signature = hmac.new(
        bytes(secret_key, "utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return (
        f"CEA algorithm=HmacSHA256, access-key={access_key}, "
        f"signed-date={datetime_str}, signature={signature}"
    )


def create_deeplink(product_urls, access_key: str, secret_key: str) -> list:
    """상품 URL 리스트를 파트너스 딥링크로 변환."""
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


def get_goldbox_products(access_key: str, secret_key: str, limit: int = 100) -> list:
    """쿠팡 골드박스(당일 특가) 상품 목록 조회."""
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
