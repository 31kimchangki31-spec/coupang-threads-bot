# -*- coding: utf-8 -*-
"""
게시글 문구 생성 모듈.
기본은 템플릿 조합 방식(무료, 즉시 사용 가능).
ANTHROPIC_API_KEY가 설정되어 있으면 Claude API로 자연스러운 문구를 생성한다(선택사항).
"""
import os
import random
import re

MAX_CORE_NAME_LEN = 20  # 핵심 상품명(수량 제외) 최대 길이
QUANTITY_PATTERN = re.compile(r"\d[\d,.]*\s*(g|kg|ml|l|개|매|팩|box|봉|입|정|포|캡슐|장|병|세트)", re.IGNORECASE)

MONEY_EMOJIS = ["💰", "💸", "🏷️"]
LINK_EMOJIS = ["🔗", "👉", "📎"]
DISCOUNT_EMOJIS = ["🔻", "⬇️", "🔥"]


def shorten_product_name(name: str) -> str:
    """
    부가설명(- 뒤에 붙는 카테고리성 문구)만 제거하고, 핵심 상품명과 수량/용량 정보는
    자르지 않고 전체 그대로 보여준다.
    """
    parts = [p.strip() for p in re.split(r"[,\-]", name) if p.strip()]
    if not parts:
        return name

    core = parts[0]
    quantity_parts = [p for p in parts[1:] if QUANTITY_PATTERN.search(p)]

    if quantity_parts:
        return core + ", " + ", ".join(quantity_parts)
    return core


def _discount_line(discount_rate) -> str:
    """할인율이 있으면 가격 줄 위에 넣을 한 줄을 만든다. 없으면 빈 문자열."""
    if not discount_rate:
        return ""
    try:
        rate = float(discount_rate)
    except (TypeError, ValueError):
        return ""
    if rate <= 0:
        return ""
    emoji = random.choice(DISCOUNT_EMOJIS)
    return f"{emoji} {rate:.0f}% 할인\n"


def generate_caption(product_name: str, price: int, deeplink: str, discount_rate=None) -> str:
    # 후킹 문구, 대가성 문구 없이 상품 정보만 표기
    use_ai = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if use_ai:
        return _generate_with_ai(product_name, price, deeplink, discount_rate)

    money_emoji = random.choice(MONEY_EMOJIS)
    link_emoji = random.choice(LINK_EMOJIS)

    discount_line = _discount_line(discount_rate)
    price_str = f"{money_emoji} {int(price):,}원" if price else ""
    return f"{product_name}\n{discount_line}{price_str}\n\n{link_emoji} {deeplink}"


def _generate_with_ai(product_name: str, price: int, deeplink: str, discount_rate=None) -> str:
    """Claude API로 캡션 생성 (ANTHROPIC_API_KEY 설정 시에만 사용)"""
    discount_line = _discount_line(discount_rate)
    price_str = f"💰 {int(price):,}원" if price else ""
    return f"{product_name}\n{discount_line}{price_str}\n\n🔗 {deeplink}"
