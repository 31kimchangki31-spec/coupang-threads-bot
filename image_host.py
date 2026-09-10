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

# 하루 46회 게시하면 이미지가 빠르게 쌓인다. 최근 N개만 남기고 정리한다.
KEEP_IMAGES = int(os.environ.get("KEEP_CARD_IMAGES", "30"))


def _run(cmd: list) -> tuple:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def wait_until_reachable(url: str, attempts: int = 8, interval: int = 4) -> bool:
    """
    이미지 URL이 실제로 공개 접근 가능한지 확인한다.

    Meta 는 자체 크롤러로 이미지를 내려받는다. 푸시 직후에는 raw CDN 반영이
    덜 되어 404가 나는 경우가 있는데, 그 상태로 게시하면 Meta 가 이미지를
    못 가져와 링크 미리보기만 붙은 글이 올라간다. 그래서 미리 확인한다.
    """
    import requests

    for attempt in range(1, attempts + 1):
        try:
            resp = requests.get(url, timeout=15, stream=True)
            content_type = resp.headers.get("content-type", "")
            if resp.ok and content_type.startswith("image/"):
                print(f"[이미지] URL 접근 확인 ({attempt}회차, {content_type})")
                return True
            print(
                f"[이미지] URL 확인 {attempt}/{attempts}: "
                f"status={resp.status_code} type={content_type or '없음'}"
            )
        except Exception as exc:
            print(f"[이미지] URL 확인 {attempt}/{attempts} 실패: {exc}")

        if attempt < attempts:
            time.sleep(interval)
    return False


def _prune_old_images() -> None:
    """오래된 카드 이미지를 지운다 (파일명이 타임스탬프라 이름순 = 시간순)."""
    try:
        if not os.path.isdir(PUBLIC_DIR):
            return
        files = sorted(
            f for f in os.listdir(PUBLIC_DIR)
            if os.path.isfile(os.path.join(PUBLIC_DIR, f))
        )
        excess = files[:-KEEP_IMAGES] if len(files) > KEEP_IMAGES else []
        for name in excess:
            _run(["git", "rm", "-f", "--ignore-unmatch", os.path.join(PUBLIC_DIR, name)])
        if excess:
            print(f"[이미지] 오래된 카드 이미지 {len(excess)}개 정리")
    except Exception as exc:
        print(f"[이미지] 이미지 정리 건너뜀: {exc}")


def push_with_rebase(branch: str, label: str = "기록", attempts: int = 3) -> bool:
    """
    원격이 앞서 있을 수 있으므로 rebase 후 푸시한다.

    러너가 체크아웃한 뒤에 저장소가 갱신되면(웹에서 파일 수정 등)
    푸시가 non-fast-forward 로 거부된다. 그때마다 원격을 당겨와 다시 시도한다.
    """
    for attempt in range(1, attempts + 1):
        code, out = _run(["git", "push", "origin", f"HEAD:{branch}"])
        if code == 0:
            return True

        if attempt == attempts:
            print(f"[{label}] git push 최종 실패: {out}")
            return False

        print(f"[{label}] push 거부({attempt}/{attempts}), 원격 변경을 가져와 재시도")
        _run(["git", "fetch", "origin", branch])
        rc, ro = _run(
            ["git", "pull", "--rebase", "--autostash", "origin", branch]
        )
        if rc != 0:
            print(f"[{label}] rebase 실패: {ro}")
            # rebase 가 꼬였으면 중단하고 원격 위에 다시 올린다
            _run(["git", "rebase", "--abort"])
            return False
    return False


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

    _prune_old_images()

    code, out = _run(["git", "commit", "-m", f"chore: 카드 이미지 {filename}"])
    if code != 0 and "nothing to commit" not in out:
        print(f"[이미지] git commit 실패: {out}")
        return None

    if not push_with_rebase(branch, label="이미지"):
        return None

    url = f"https://raw.githubusercontent.com/{repo}/{branch}/{PUBLIC_DIR}/{filename}"
    if not wait_until_reachable(url):
        print("[이미지] GitHub raw 반영 확인 실패")
        return None
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
            candidate = upload_image_get_url(image_path, imgbb_key)
            if wait_until_reachable(candidate, attempts=3, interval=2):
                return candidate
            print("[이미지] imgbb URL 접근 확인 실패")
        except Exception as exc:
            print(f"[이미지] imgbb 업로드 실패: {exc}")

    print("[이미지] 공개 URL 확보 실패")
    return None
