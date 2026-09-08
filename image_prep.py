# -*- coding: utf-8 -*-
"""
캡처한 카드 이미지를 Threads(Meta)가 받아주는 형태로 변환한다.

Meta 요구사항:
  - 형식: JPEG 권장 (PNG는 거부되는 사례가 잦음)
  - 가로세로 비율: 4:5(0.8) ~ 1.91:1 범위
  - 용량: 8MiB 미만

처리 순서:
  1) 캡처 주변의 흰 여백을 잘라낸다
  2) 비율이 허용 범위를 벗어날 때만, 벗어난 만큼만 여백을 넣는다
     (범위 안이면 여백을 전혀 넣지 않는다)
  3) JPEG로 저장
"""
import os

MIN_RATIO = 0.80          # 4:5
MAX_RATIO = 1.91          # 1.91:1
SAFE_MIN = 0.85           # 경계에 딱 붙지 않도록 약간 안쪽으로
SAFE_MAX = 1.85
MAX_SIDE = 1600
JPEG_QUALITY = 92

WHITE_THRESHOLD = 247     # 이 값보다 밝으면 여백으로 본다
EDGE_MARGIN = 6           # 잘라낸 뒤 남겨둘 최소 여백(px)


def _trim_white_border(img):
    """이미지 주변의 흰 여백을 잘라낸다. 실패하면 원본 그대로."""
    from PIL import Image, ImageChops

    try:
        # 흰 배경과의 차이를 구해 내용이 있는 영역을 찾는다
        background = Image.new("RGB", img.size, (255, 255, 255))
        diff = ImageChops.difference(img, background).convert("L")
        mask = diff.point(lambda v: 255 if v > (255 - WHITE_THRESHOLD) else 0)
        bbox = mask.getbbox()
        if not bbox:
            return img

        left, top, right, bottom = bbox
        left = max(0, left - EDGE_MARGIN)
        top = max(0, top - EDGE_MARGIN)
        right = min(img.width, right + EDGE_MARGIN)
        bottom = min(img.height, bottom + EDGE_MARGIN)

        if right - left < 50 or bottom - top < 50:
            return img
        return img.crop((left, top, right, bottom))
    except Exception:
        return img


def _fit_ratio(img):
    """
    비율이 허용 범위를 벗어날 때만 흰 여백을 넣어 범위 안으로 들인다.
    범위 안이면 아무것도 하지 않는다.
    """
    from PIL import Image

    width, height = img.size
    ratio = width / height

    if MIN_RATIO <= ratio <= MAX_RATIO:
        return img, ratio, False

    if ratio > MAX_RATIO:
        # 너무 넓다 -> 위아래로만 최소한의 여백
        new_height = int(round(width / SAFE_MAX))
        new_width = width
    else:
        # 너무 길다 -> 좌우로만 최소한의 여백
        new_width = int(round(height * SAFE_MIN))
        new_height = height

    canvas = Image.new("RGB", (new_width, new_height), (255, 255, 255))
    canvas.paste(img, ((new_width - width) // 2, (new_height - height) // 2))
    return canvas, new_width / new_height, True


def prepare_for_threads(src_path: str, out_path: str = "post_image.jpg") -> str:
    """
    이미지를 Meta 규격 JPEG으로 변환한다.
    Pillow가 없거나 실패하면 원본 경로를 그대로 반환한다.
    """
    try:
        from PIL import Image
    except ImportError:
        print("[이미지] Pillow 미설치, 변환 없이 원본 사용")
        return src_path

    try:
        with Image.open(src_path) as opened:
            img = opened.convert("RGB")
            before = img.size

            img = _trim_white_border(img)
            trimmed = img.size

            # 너무 크면 비율 유지하며 축소
            if max(img.size) > MAX_SIDE:
                scale = MAX_SIDE / max(img.size)
                img = img.resize(
                    (max(1, int(img.width * scale)), max(1, int(img.height * scale))),
                    Image.LANCZOS,
                )

            img, ratio, padded = _fit_ratio(img)
            img.save(out_path, "JPEG", quality=JPEG_QUALITY, optimize=True)

        size_mb = os.path.getsize(out_path) / (1024 * 1024)
        print(
            f"[이미지] {before[0]}x{before[1]} -> 여백제거 {trimmed[0]}x{trimmed[1]} "
            f"-> 최종 {img.size[0]}x{img.size[1]} (비율 {ratio:.2f}, "
            f"{'여백 추가' if padded else '여백 없음'}, {size_mb:.2f}MB)"
        )
        return out_path
    except Exception as exc:
        print(f"[이미지] 변환 실패, 원본 사용: {exc}")
        return src_path
