# -*- coding: utf-8 -*-
"""
Threads API 연동 모듈
- 게시물 컨테이너 생성 -> 발행 2단계로 동작
- 텍스트 전용 / 이미지 포함 둘 다 지원
"""
import time
import requests

BASE_URL = "https://graph.threads.net/v1.0"
REQUEST_TIMEOUT = 30


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

    resp = requests.post(create_url, params=params, timeout=REQUEST_TIMEOUT)
    if not resp.ok:
        print(f"[Threads 컨테이너 생성 실패] status={resp.status_code} body={resp.text}")
    resp.raise_for_status()
    creation_id = resp.json()["id"]

    # 이미지 컨테이너는 고정 5초보다 처리 시간이 길어질 수 있으므로 상태를 확인한다.
    wait_for_container(creation_id, access_token)

    # 2. 발행
    publish_url = f"{BASE_URL}/{user_id}/threads_publish"
    publish_resp = requests.post(
        publish_url,
        params={"creation_id": creation_id, "access_token": access_token},
        timeout=REQUEST_TIMEOUT,
    )
    if not publish_resp.ok:
        print(f"[Threads 발행 실패] status={publish_resp.status_code} body={publish_resp.text}")
    publish_resp.raise_for_status()
    return publish_resp.json()["id"]


def wait_for_container(
    creation_id: str,
    access_token: str,
    max_wait_seconds: int = 90,
    interval_seconds: int = 3,
) -> None:
    """미디어 컨테이너가 FINISHED 상태가 될 때까지 기다린다."""
    status_url = f"{BASE_URL}/{creation_id}"
    deadline = time.monotonic() + max_wait_seconds

    while time.monotonic() < deadline:
        resp = requests.get(
            status_url,
            params={
                "fields": "status,error_message",
                "access_token": access_token,
            },
            timeout=REQUEST_TIMEOUT,
        )
        if not resp.ok:
            print(f"[Threads 컨테이너 상태 조회 실패] status={resp.status_code} body={resp.text}")
        resp.raise_for_status()

        result = resp.json()
        status = result.get("status")
        if status == "FINISHED":
            return
        if status in {"ERROR", "EXPIRED"}:
            message = result.get("error_message") or "컨테이너 처리 실패"
            raise RuntimeError(f"Threads 컨테이너 상태={status}: {message}")

        print(f"[Threads 컨테이너] status={status}, {interval_seconds}초 후 재확인")
        time.sleep(interval_seconds)

    raise TimeoutError(
        f"Threads 컨테이너가 {max_wait_seconds}초 안에 FINISHED 상태가 되지 않았습니다."
    )


def refresh_long_lived_token(access_token: str, app_secret: str = None) -> dict:
    """
    60일짜리 장기 토큰을 갱신한다 (만료 전, 매번 새 토큰으로 교체해서 저장해야 함).
    """
    url = f"{BASE_URL}/refresh_access_token"
    params = {
        "grant_type": "th_refresh_token",
        "access_token": access_token,
    }
    resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    result = resp.json()
    if not result.get("access_token"):
        raise RuntimeError(f"Threads 토큰 갱신 응답에 access_token이 없습니다: {result}")
    return result  # {"access_token": "...", "expires_in": 5184000}
