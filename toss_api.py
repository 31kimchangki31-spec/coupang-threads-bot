# -*- coding: utf-8 -*-
"""
토스쇼핑 쉐어링크 Open API 연동 모듈.
- 액세스 토큰 발급
- 하루특가 상품 목록 조회
- 상품 상세 조회 (정가/할인율/이미지 등 최신 정보)
- 쉐어링크(추적 링크) 발급

주의: 토큰 발급 엔드포인트(get_access_token)는 공식 문서(/guide/open-api/auth)를
직접 확인 못하고 일반적인 방식으로 추정해서 작성함. 실제 요청/응답 형식이 다르면
이 함수만 고치면 됨.
"""
import requests

BASE_URL = "https://sharelink.toss.im"


def get_access_token(access_key: str, secret_key: str) -> str:
    """Access Key/Secret Key로 액세스 토큰을 발급받는다. (엔드포인트는 추정, 확인 필요)"""
    url = f"{BASE_URL}/openapi/auth/token"
    resp = requests.post(url, json={"accessKey": access_key, "secretKey": secret_key})
    resp.raise_for_status()
    result = resp.json()

    if result.get("resultType") != "SUCCESS":
        raise RuntimeError(f"토큰 발급 실패: {result}")

    success = result.get("success", {})
    token = success.get("accessToken") or success.get("token")
    if not token:
        raise RuntimeError(f"토큰 발급 응답에서 accessToken을 찾지 못함: {result}")
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
