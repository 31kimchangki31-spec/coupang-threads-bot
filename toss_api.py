# -*- coding: utf-8 -*-
"""
토스쇼핑 쉐어링크 Open API 연동 모듈.
- 액세스 토큰 발급
- 하루특가 상품 목록 조회
- 상품 상세 조회 (정가/할인율/이미지 등 최신 정보)
- 쉐어링크(추적 링크) 발급
"""
import requests

BASE_URL = "https://sharelink.toss.im"
TOKEN_URL = "https://oauth2.cert.toss.im/token"


def get_access_token(access_key: str, secret_key: str) -> str:
    """Access Key/Secret Key로 OAuth2 client_credentials 방식으로 액세스 토큰을 발급받는다."""
    resp = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "client_credentials",
            "client_id": access_key,
            "client_secret": secret_key,
            "scope": "sharelink:read sharelink:write",
        },
    )
    resp.raise_for_status()
    result = resp.json()

    token = result.get("access_token")
    if not token:
        raise RuntimeError(f"토큰 발급 응답에서 access_token을 찾지 못함: {result}")
    return token


def _get(token: str, path: str, params: dict = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(f"{BASE_URL}{path}", headers=headers, params=params or {})
    resp.raise_for_status()
    result = resp.json()
    if result.get("resultType") != "SUCCESS":
        raise RuntimeError(f"API 호출 실패 ({path}): {result}")
    return result["success"]


def get_today_deals(token: str, cursor: str = None, size: int = 30) -> dict:
    """그날 하루만 판매하는 특가 상품 목록 조회."""
    params = {"size": size}
    if cursor:
        params["cursor"] = cursor
    return _get(token, "/openapi/products/today-deals", params)


def get_product_detail(token: str, taca_item_ids: list) -> dict:
    """상품 옵션 ID로 상세 정보(정가/할인율/이미지/품절여부) 최대 30건 조회."""
    ids_str = ",".join(str(i) for i in taca_item_ids)
    return _get(token, "/openapi/products/detail", {"tacaItemIds": ids_str})


def issue_share_link(token: str, taca_item_id: int, publisher_id: str) -> dict:
    """상품 옵션 ID로 쉐어링크(추적 링크)를 발급받는다."""
    url = f"{BASE_URL}/openapi/links"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"tacaItemId": taca_item_id, "publisherId": publisher_id}
    resp = requests.post(url, headers=headers, json=body)
    resp.raise_for_status()
    result = resp.json()
    if result.get("resultType") != "SUCCESS":
        raise RuntimeError(f"쉐어링크 발급 실패: {result}")
    return result["success"]
