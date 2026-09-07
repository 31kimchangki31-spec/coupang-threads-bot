# -*- coding: utf-8 -*-
"""
쿠팡파트너스 Open API 연동 모듈.

제공 기능:
  - get_goldbox_products : 골드박스(당일 특가) 상품 목록 조회
  - create_deeplink      : 상품 URL -> 파트너스 추적 딥링크 변환
  - search_products      : 키워드 상품 검색 (골드박스가 비었을 때 대체용)

HMAC-SHA256 서명 규칙 (쿠팡 CEA):
  message = signed-date + METHOD + path + query
  signed-date = UTC 기준 "yymmddTHHMMSSZ"
"""
import hashlib
import hmac
import json
import time
from urllib.parse import quote

import requests

DOMAIN = "https://api-gateway.coupang.com"
BASE = "/v2/providers/affiliate_open_api/apis/openapi"

# 엔드포인트 경로. 골드박스/딥링크는 /v1/ 세그먼트가 반드시 들어간다.
PATH_GOLDBOX = f"{BASE}/v1/products/goldbox"
PATH_DEEPLINK = f"{BASE}/v1/deeplink"
PATH_SEARCH = f"{BASE}/v1/products/search"

TIMEOUT = 20


def generate_hmac(method: str, url: str, secret_key: str, access_key: str) -> str:
    """쿠팡 Open API Authorization 헤더를 만든다 (UTC gmtime 사용, 크로스플랫폼)."""
    path, *query = url.split("?")
    utc_now = time.gmtime()
    datetime_str = time.strftime("%y%m%d", utc_now) + "T" + time.strftime("%H%M%S", utc_now) + "Z"
    message = datetime_str + method + path + (query[0] if query else "")
    signature = hmac.new(
        secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return (
        f"CEA algorithm=HmacSHA256, access-key={access_key}, "
        f"signed-date={datetime_str}, signature={signature}"
    )


def _unwrap(resp: requests.Response, label: str):
    """쿠팡 응답을 검증하고 data를 꺼낸다. 실패 원인을 그대로 노출한다."""
    if not resp.ok:
        raise RuntimeError(
            f"{label} HTTP {resp.status_code}: {resp.text[:400]}"
        )
    try:
        result = resp.json()
    except ValueError:
        raise RuntimeError(f"{label} 응답이 JSON이 아님: {resp.text[:400]}")

    r_code = str(result.get("rCode", ""))
    if r_code not in ("0", "200", ""):
        raise RuntimeError(f"{label} 실패 (rCode={r_code}): {result.get('rMessage')}")

    data = result.get("data")
    if data is None:
        raise RuntimeError(f"{label} 응답에 data가 없음: {str(result)[:400]}")
    return data


def get_goldbox_products(access_key: str, secret_key: str, limit: int = 100) -> list:
    """
    골드박스 상품 목록을 조회한다.

    반환 항목의 주요 필드:
      productId, productName, productPrice, productImage,
      productUrl, categoryName, isRocket, isFreeShipping
    """
    url = f"{PATH_GOLDBOX}?limit={int(limit)}"
    headers = {"Authorization": generate_hmac("GET", url, secret_key, access_key)}
    resp = requests.get(DOMAIN + url, headers=headers, timeout=TIMEOUT)
    data = _unwrap(resp, "골드박스 조회")
    return data if isinstance(data, list) else []


def search_products(
    access_key: str, secret_key: str, keyword: str, limit: int = 20
) -> list:
    """키워드로 상품을 검색한다. 골드박스가 비었을 때의 대체 경로."""
    url = f"{PATH_SEARCH}?keyword={quote(keyword)}&limit={int(limit)}"
    headers = {"Authorization": generate_hmac("GET", url, secret_key, access_key)}
    resp = requests.get(DOMAIN + url, headers=headers, timeout=TIMEOUT)
    data = _unwrap(resp, "상품 검색")
    if isinstance(data, dict):
        return data.get("productData") or []
    return data if isinstance(data, list) else []


def create_deeplink(
    product_urls, access_key: str, secret_key: str, sub_id: str = None
) -> list:
    """
    쿠팡 상품 URL 리스트를 파트너스 딥링크로 변환한다.

    반환: [{"originalUrl": ..., "shortenUrl": ..., "landingUrl": ...}, ...]
    """
    if isinstance(product_urls, str):
        product_urls = [product_urls]

    headers = {
        "Authorization": generate_hmac("POST", PATH_DEEPLINK, secret_key, access_key),
        "Content-Type": "application/json;charset=UTF-8",
    }
    body = {"coupangUrls": list(product_urls)}
    if sub_id:
        body["subId"] = sub_id

    resp = requests.post(
        DOMAIN + PATH_DEEPLINK,
        headers=headers,
        data=json.dumps(body),
        timeout=TIMEOUT,
    )
    data = _unwrap(resp, "딥링크 생성")
    return data if isinstance(data, list) else []


def deeplink_for(
    product_url: str, access_key: str, secret_key: str, sub_id: str = None
) -> str:
    """단일 상품 URL의 추적 링크를 문자열로 반환한다. 실패 시 원본 URL로 폴백."""
    try:
        results = create_deeplink([product_url], access_key, secret_key, sub_id)
        if results:
            item = results[0]
            return item.get("shortenUrl") or item.get("landingUrl") or product_url
    except Exception as exc:
        print(f"[쿠팡] 딥링크 발급 실패, 원본 URL 사용: {exc}")
    return product_url
