# -*- coding: utf-8 -*-
"""
카드 이미지를 Meta가 가져갈 수 있는 공개 URL로 만드는 모듈.

Meta는 자체 크롤러(facebookexternalhit)로 이미지를 내려받는다.
브라우저에서 열린다고 되는 게 아니라, 크롤러가 접근 가능해야 한다.
imgbb 같은 무료 호스팅은 크롤러가 막히는 경우가 있어 실패하기 쉽다.

그래서 우선순위:
  1) GitHub raw  - 저장소에 커밋해서 raw URL 사용 (크롤러 차단 없음, 가장 안정적)
  2) imgbb       - GitHub를 못 쓸 때 대비
"""
import base64
import os
import shutil
import subprocess
import time

IMGBB_UPLOAD_URL = "https://api.imgbb.com/1/upload"
PUBLIC_DIR = "docs/cards"


def _run(cmd: list) -> tuple:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def upload_via_github(image_path: str) -> str:
    """
    이미지를 저장소에 커밋/푸시하고 raw.githubusercontent.com URL을 반환한다.
    GitHub Actions 안에서만 동작한다. 실패하면 None.
    """
    repo = os.environ.get("GITHUB_REPOSITORY")
    branch = os.environ.get("GITHUB_REF_NAME") or "main"
    if not repo:
        return None

    os.makedirs(PUBLIC_DIR, exist_ok=True)
    filename = f"{int(time.time())}{os.path.splitext(image_path)[1]}"
    dest = os.path.join(PUBLIC_DIR, filename)
    shutil.copy(image_path, dest)

    _run(["git", "config", "user.name", "auto-post-bot"])
    _run(["git", "config", "user.email", "actions@github.com"])

    code, out = _run(["git", "add", "-f", dest])
    if code != 0:
        print(f"[이미지] git add 실패: {out}")
        return None

    code, out = _run(["git", "commit", "-m", f"chore: 카드 이미지 {filename}"])
    if code != 0 and "nothing to commit" not in out:
        print(f"[이미지] git commit 실패: {out}")
        return None

    code, out = _run(["git", "push", "origin", f"HEAD:{branch}"])
    if code != 0:
        print(f"[이미지] git push 실패: {out}")
        return None

    url = f"https://raw.githubusercontent.com/{repo}/{branch}/{PUBLIC_DIR}/{filename}"
    # 푸시 직후 raw CDN에 반영될 시간을 준다
    time.sleep(5)
    print(f"[이미지] GitHub 호스팅 성공: {url}")
    return url


def upload_image_get_url(image_path: str, api_key: str) -> str:
    """이미지를 imgbb에 업로드하고 공개 URL을 반환한다. 실패하면 예외."""
    import requests

    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read())

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
    print(f"[이미지] imgbb 업로드 성공: {url}")
    return url


def publish(image_path: str) -> str:
    """
    사용 가능한 방법을 순서대로 시도해 공개 URL을 반환한다.
    전부 실패하면 None (호출부에서 텍스트 전용 게시로 넘어감).
    """
    url = None
    try:
        url = upload_via_github(image_path)
    except Exception as exc:
        print(f"[이미지] GitHub 호스팅 실패: {exc}")

    if url:
        return url

    imgbb_key = os.environ.get("IMGBB_API_KEY")
    if imgbb_key:
        try:
            return upload_image_get_url(image_path, imgbb_key)
        except Exception as exc:
            print(f"[이미지] imgbb 업로드 실패: {exc}")

    print("[이미지] 공개 URL 확보 실패 -> 텍스트 전용 게시로 진행")
    return None
