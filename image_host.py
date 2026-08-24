# -*- coding: utf-8 -*-
"""
로컬 스크린샷 파일을 무료 이미지 호스팅(imgbb)에 업로드해서
공개 URL을 받아오는 모듈.
쓰레드 API는 로컬 파일이 아니라 URL만 받을 수 있어서 이 단계가 필요하다.
무료 API 키 발급: https://api.imgbb.com/ (가입만 하면 무료, 무제한)
"""
import os
import base64
import requests

IMGBB_UPLOAD_URL = "https://api.imgbb.com/1/upload"


def upload_image_get_url(image_path: str, api_key: str) -> str:
    """
    이미지 파일을 imgbb에 업로드하고 공개 URL을 반환한다. 실패하면 예외 발생.
    """
    # 1. API 키 검증
    if not api_key or not str(api_key).strip():
        raise ValueError("[이미지 호스팅] ImgBB API Key가 비어있거나 올바르지 않습니다.")

    # 2. 파일 존재 여부 및 용량 검증 (0바이트 파일 업로드 방지)
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"[이미지 호스팅] 파일이 존재하지 않습니다: {image_path}")

    if os.path.getsize(image_path) == 0:
        raise ValueError(f"[이미지 호스팅] 캡처된 이미지 용량이 0바이트입니다: {image_path}")

    # 3. Base64 인코딩 후 utf-8 문자열로 변환 (.decode('utf-8') 필수)
    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")

    # 4. ImgBB API 호출
    resp = requests.post(
        IMGBB_UPLOAD_URL,
        data={"key": api_key, "image": image_data},
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()

    if not result.get("success"):
        raise RuntimeError(f"imgbb 업로드 실패: {result}")

    url = result["data"]["url"]
    print(f"[이미지 호스팅] 업로드 성공: {url}")
    return url
