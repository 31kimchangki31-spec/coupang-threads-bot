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

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\malgunbd.ttf",
    r"C:\Windows\Fonts\malgun.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
]


def _find_font(size: int, bold: bool = False):
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


def _fit_name_lines(text: str, draw, max_width: int, max_height: int, start_size: int = 42):
    """
    상품명이 잘리지 않도록, 폰트 크기를 줄여가며 3줄 안에 전체 텍스트가 들어갈 때까지 시도.
    (말줄임표로 자르지 않고 전체 다 보여주는 방식)
    """
    size = start_size
    while size >= 22:
        font = _find_font(size, bold=True)
        words = text.split(" ")
        lines, current = [], ""
        for word in words:
            trial = f"{current} {word}".strip()
            if draw.textbbox((0, 0), trial, font=font)[2] <= max_width:
                current = trial
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)

        line_height = size + 14
        if len(lines) * line_height <= max_height:
            return lines, font, line_height
        size -= 2
    # 최소 크기에서도 안 들어가면 그 상태로 반환 (그래도 전체 텍스트는 유지)
    return lines, font, line_height


def compose_product_card(
    image_url: str,
    product_name: str,
    price: int,
    discount_rate,
    review_score,
    review_count,
    output_path: str,
    original_price=None,
) -> bool:
    """상품 사진 위에 정보를 합성해서 output_path에 저장. 성공하면 True."""
    try:
        canvas = Image.new("RGB", CANVAS_SIZE, "white")
        draw = ImageDraw.Draw(canvas)

        # 1. 상품 사진
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
        right_w = CANVAS_SIZE[0] - right_x - 60

        # 상품명 - 잘리지 않게 폰트 크기를 자동으로 줄여서 전체 표시
        name_lines, name_font, line_height = _fit_name_lines(
            product_name, draw, max_width=right_w, max_height=170
        )
        y = 90
        for line in name_lines:
            draw.text((right_x, y), line, font=name_font, fill=(30, 30, 30))
            y += line_height

        # 가격
        y += 30
        price_font = _find_font(64, bold=True)
        draw.text((right_x, y), f"{int(price):,}원", font=price_font, fill=(20, 20, 20))
        y += 90

        # 정가(취소선) + 할인 금액 - 예전에 비어있던 자리를 채움
        if original_price and float(original_price) > float(price):
            orig = int(float(original_price))
            saved = orig - int(price)
            small_font = _find_font(30, bold=False)
            orig_text = f"{orig:,}원"
            bbox = draw.textbbox((right_x, y), orig_text, font=small_font)
            draw.text((right_x, y), orig_text, font=small_font, fill=(160, 160, 160))
            mid_y = (bbox[1] + bbox[3]) // 2
            draw.line([bbox[0], mid_y, bbox[2], mid_y], fill=(160, 160, 160), width=2)
            y += 50
            save_font = _find_font(36, bold=True)
            draw.text((right_x, y), f"{saved:,}원 절약", font=save_font, fill=(230, 30, 40))
            y += 60

        # 별점 + 리뷰수
        if review_score:
            y += 20
            rating_font = _find_font(34, bold=False)
            stars = "★" * round(float(review_score)) + "☆" * (5 - round(float(review_score)))
            rating_text = f"{stars}  {review_score} ({review_count:,})" if review_count else f"{stars}  {review_score}"
            draw.text((right_x, y), rating_text, font=rating_font, fill=(120, 120, 120))

        canvas.save(output_path, "PNG")
        return True

    except Exception as e:
        print(f"[이미지 합성] 실패: {e}")
        return False
