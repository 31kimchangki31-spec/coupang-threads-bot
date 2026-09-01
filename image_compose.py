# -*- coding: utf-8 -*-
"""
토스쇼핑 API가 주는 순수 상품 사진 위에, 할인 배지/상품명/가격/별점을
직접 그려 넣어서 카드형 이미지를 합성하는 모듈.
(화면을 긁는 게 아니라 우리가 직접 그리는 거라 매번 100% 안정적으로 작동함)
"""
import os
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

CANVAS_SIZE = (1200, 900)
PHOTO_AREA = (60, 60, 600, 840)  # 왼쪽 사진 영역 (x1, y1, x2, y2)

# Windows(자동화 도는 PC)와 리눅스 양쪽 다 시도해볼 한글 폰트 경로 후보
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\malgunbd.ttf",   # 맑은 고딕 Bold (Windows)
    r"C:\Windows\Fonts\malgun.ttf",     # 맑은 고딕 (Windows)
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",  # 리눅스 대비
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
]


def _find_font(size: int, bold: bool = False):
    candidates = FONT_CANDIDATES if bold else FONT_CANDIDATES[1:2] + FONT_CANDIDATES[3:]
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _download_image(url: str) -> Image.Image:
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return Image.open(BytesIO(resp.content)).convert("RGBA")


def compose_product_card(
    image_url: str,
    product_name: str,
    price: int,
    discount_rate,
    review_score,
    review_count,
    output_path: str,
) -> bool:
    """상품 사진 위에 정보를 합성해서 output_path에 저장. 성공하면 True."""
    try:
        canvas = Image.new("RGB", CANVAS_SIZE, "white")
        draw = ImageDraw.Draw(canvas)

        # 1. 상품 사진 (왼쪽, 비율 유지하며 영역 안에 맞춤)
        photo = _download_image(image_url)
        area_w = PHOTO_AREA[2] - PHOTO_AREA[0]
        area_h = PHOTO_AREA[3] - PHOTO_AREA[1]
        photo.thumbnail((area_w, area_h))
        px = PHOTO_AREA[0] + (area_w - photo.width) // 2
        py = PHOTO_AREA[1] + (area_h - photo.height) // 2
        canvas.paste(photo, (px, py), photo)

        # 2. 할인 배지 (사진 좌상단, 빨간 리본)
        if discount_rate:
            badge_font = _find_font(40, bold=True)
            badge_text = f"{int(float(discount_rate))}% 할인"
            draw.rectangle([60, 60, 60 + 260, 60 + 90], fill=(230, 30, 40))
            draw.text((90, 78), badge_text, font=badge_font, fill="white")

        # 3. 오른쪽 정보 영역
        right_x = 660
        name_font = _find_font(42, bold=True)
        price_font = _find_font(64, bold=True)
        rating_font = _find_font(34, bold=False)
        brand_font = _find_font(28, bold=False)

        # 상품명 (최대 2줄, 넘치면 ... 처리)
        name_lines = _wrap_text(product_name, name_font, draw, max_width=480, max_lines=2)
        y = 100
        for line in name_lines:
            draw.text((right_x, y), line, font=name_font, fill=(30, 30, 30))
            y += 56

        # 가격
        y += 20
        draw.text((right_x, y), f"{int(price):,}원", font=price_font, fill=(20, 20, 20))
        y += 100

        # 별점 + 리뷰수
        if review_score:
            stars = "★" * round(float(review_score)) + "☆" * (5 - round(float(review_score)))
            rating_text = f"{stars}  {review_score} ({review_count:,})" if review_count else f"{stars}  {review_score}"
            draw.text((right_x, y), rating_text, font=rating_font, fill=(120, 120, 120))
            y += 60

        # 브랜드 표시
        draw.text((right_x, CANVAS_SIZE[1] - 100), "토스쇼핑", font=brand_font, fill=(0, 100, 230))

        canvas.save(output_path, "PNG")
        return True

    except Exception as e:
        print(f"[이미지 합성] 실패: {e}")
        return False


def _wrap_text(text: str, font, draw, max_width: int, max_lines: int) -> list:
    words = text.split(" ")
    lines = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), trial, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines:
        last = lines[-1]
        while draw.textbbox((0, 0), last + "…", font=font)[2] > max_width and len(last) > 1:
            last = last[:-1]
        lines[-1] = last + "…" if len(text) > sum(len(l) for l in lines) else last
    return lines
