# -*- coding: utf-8 -*-
"""
Threads API 연동 모듈
- 게시물 컨테이너 생성 -> 발행 2단계로 동작
- 텍스트 전용 / 이미지 포함 둘 다 지원
"""
import time
import requests

BASE_URL = "https://graph.threads.net/v1.0"


def post_to_threads(user_id: str, access_token: str, text: str, image_url: str = None) -> str:
    """
    쓰레드에 게시글을 올린다.
    image_url을 주면 이미지 포함 게시물, 없으면 텍스트만.
    반환: 게시된 미디어 id
    """
    # 1. 컨테이너 생성
    create_url = f"{BASE_URL}/{user_id}/threads"
    params = {
        "text": text,
        "access_token": access_token,
    }
    if image_url:
        params["media_type"] = "IMAGE"
        params["image_url"] = image_url
    else:
        params["media_type"] = "TEXT"

    resp = requests.post(create_url, params=params)
    resp.raise_for_status()
    creation_id = resp.json()["id"]

    # 컨테이너가 서버에서 처리될 시간을 잠깐 대기 (메타 권장)
    time.sleep(5)

    # 2. 발행
    publish_url = f"{BASE_URL}/{user_id}/threads_publish"
    publish_resp = requests.post(
        publish_url,
        params={"creation_id": creation_id, "access_token": access_token},
    )
    publish_resp.raise_for_status()
    return publish_resp.json()["id"]


def refresh_long_lived_token(access_token: str, app_secret: str = None) -> dict:
    """
    60일짜리 장기 토큰을 갱신한다 (만료 전, 매번 새 토큰으로 교체해서 저장해야 함).
    """
    url = f"{BASE_URL}/refresh_access_token"
    params = {
        "grant_type": "th_refresh_token",
        "access_token": access_token,
    }
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    return resp.json()  # {"access_token": "...", "expires_in": 5184000}
