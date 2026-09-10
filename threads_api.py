# -*- coding: utf-8 -*-
"""
Threads API 연동 모듈
- 게시물 컨테이너 생성 -> 발행 2단계로 동작
- 텍스트 전용 / 이미지 포함 둘 다 지원
"""
import os
import time

import requests

BASE_URL = "https://graph.threads.net/v1.0"


def post_to_threads(user_id: str, access_token: str, text: str, image_url: str = None, topic_tag: str = None) -> str:
    """
    쓰레드에 게시글을 올린다.
    image_url을 주면 이미지 포함 게시물, 없으면 텍스트만.
    topic_tag를 주면 해당 주제 태그가 게시물에 붙는다 (1~50자, 마침표/앰퍼샌드 불가).
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
    if topic_tag:
        params["topic_tag"] = topic_tag

    resp = requests.post(create_url, params=params)
    if not resp.ok:
        print(f"[Threads 컨테이너 생성 실패] status={resp.status_code} body={resp.text}")
        # 이미지 게시가 실패했을 때 텍스트만으로 올릴지 여부.
        #
        # 기본값은 '올리지 않음'이다. 이미지 없이 올리면 Threads 가 링크 미리보기를
        # 대신 붙여버려서 원하는 카드 이미지 게시물이 나오지 않는다.
        # 그럴 바에는 건너뛰고 다음 슬롯에 제대로 올리는 편이 낫다.
        allow_text_fallback = os.environ.get("ALLOW_TEXT_FALLBACK", "0") == "1"
        if image_url and allow_text_fallback:
            print("[Threads] 이미지 없이 텍스트 전용으로 재시도합니다.")
            retry_params = {
                "text": text,
                "access_token": access_token,
                "media_type": "TEXT",
            }
            if topic_tag:
                retry_params["topic_tag"] = topic_tag
            resp = requests.post(create_url, params=retry_params)
            if not resp.ok:
                print(f"[Threads 텍스트 재시도도 실패] body={resp.text}")
        elif image_url:
            print(
                "[Threads] 이미지 게시에 실패했습니다. 텍스트만 올리면 링크 미리보기가\n"
                "          붙어버리므로 게시하지 않고 종료합니다.\n"
                "          (텍스트 전용 게시를 허용하려면 ALLOW_TEXT_FALLBACK=1)"
            )
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
    if not publish_resp.ok:
        print(f"[Threads 발행 실패] status={publish_resp.status_code} body={publish_resp.text}")
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
