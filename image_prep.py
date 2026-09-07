# -*- coding: utf-8 -*-
"""
캡처한 카드 이미지를 Threads(Meta)가 받아주는 형태로 변환한다.

Meta 요구사항:
  - 형식: JPEG 권장 (PNG는 거부되는 사례가 잦음)
  - 가로세로 비율: 4:5 ~ 1.91:1 범위
  - 용량: 8MiB 미만

쿠팡 카드를 잘라내면 대체로 2:1 이상이라 그대로 올리면 비율 초과로 거부된다.
그래서 흰 여백을 넣어 1:1 정사각형으로 맞춘다.
"""
import os

TARGET_RATIO = 1.0        # 정사각형 (4:5 ~ 1.91:1 범위 한가운데)
MAX_SIDE = 1440
JPEG_QUALITY = 92


def prepare_for_threads(src_path: str, out_path: str = "post_image.jpg") -> str:
    """
    이미지를 흰 배경 정사각형 JPEG으로 변환한다.
    Pillow가 없거나 실패하면 원본 경로를 그대로 반환한다.
    """
    try:
        from PIL import Image
    except ImportError:
        print("[이미지] Pillow 미설치, 변환 없이 원본 사용")
        return src_path

    try:
        with Image.open(src_path) as img:
            img = img.convert("RGB")
            width, height = img.size

            side = max(width, height)
            side = min(side, MAX_SIDE)

            # 원본이 캔버스보다 크면 비율 유지하며 축소
            scale = min(side / width, side / height, 1.0)
            new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
            if new_size != (width, height):
                img = img.resize(new_size, Image.LANCZOS)

            canvas = Image.new("RGB", (side, side), (255, 255, 255))
            offset = ((side - img.size[0]) // 2, (side - img.size[1]) // 2)
            canvas.paste(img, offset)
            canvas.save(out_path, "JPEG", quality=JPEG_QUALITY, optimize=True)

        size_mb = os.path.getsize(out_path) / (1024 * 1024)
        print(f"[이미지] JPEG 변환 완료: {out_path} ({side}x{side}, {size_mb:.2f}MB)")
        return out_path
    except Exception as exc:
        print(f"[이미지] 변환 실패, 원본 사용: {exc}")
        return src_path
