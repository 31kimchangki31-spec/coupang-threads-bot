# -*- coding: utf-8 -*-
"""
게시글 문구 생성 모듈.
기본은 템플릿 조합 방식(무료, 즉시 사용 가능).
ANTHROPIC_API_KEY가 설정되어 있으면 Claude API로 자연스러운 문구를 생성한다(선택사항).
"""
import os
import random
import re

MONEY_EMOJIS = ["💰", "💸", "🏷️"]
LINK_EMOJIS = ["🔗", "👉", "📎"]
DISCOUNT_EMOJIS = ["🔻", "⬇️", "🔥"]


def shorten_product_name(name: str) -> str:
    """
    상품명을 자르지 않고 원본 풀네임 그대로 반환합니다.
    (쉼표 뒤 30개, 용량 등이 자르기 당하던 현상 수정)
    """
    return name.strip()


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


def generate_caption(product_name: str, price: int, deeplink: str, discount_rate=None, original_price=None) -> str:
    # 상품명 원본 풀네임 사용
    full_name = shorten_product_name(product_name)

    # API discountRate가 없더라도 원가(original_price) 정보가 있다면 직접 할인율 계산
    calculated_rate = discount_rate
    if (not calculated_rate or float(calculated_rate) <= 0) and original_price and price:
        try:
            orig = float(original_price)
            curr = float(price)
            if orig > curr:
                calculated_rate = round(((orig - curr) / orig) * 100)
        except (TypeError, ValueError):
            pass

    use_ai = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if use_ai:
        return _generate_with_ai(full_name, price, deeplink, calculated_rate)

    money_emoji = random.choice(MONEY_EMOJIS)
    link_emoji = random.choice(LINK_EMOJIS)

    discount_line = _discount_line(calculated_rate)
    price_str = f"{money_emoji} {int(price):,}원" if price else ""
    return f"{full_name}\n{discount_line}{price_str}\n\n{link_emoji} {deeplink}"


def _generate_with_ai(product_name: str, price: int, deeplink: str, discount_rate=None) -> str:
    """Claude API로 캡션 생성 (ANTHROPIC_API_KEY 설정 시에만 사용)"""
    discount_line = _discount_line(discount_rate)
    price_str = f"💰 {int(price):,}원" if price else ""
    return f"{product_name}\n{discount_line}{price_str}\n\n🔗 {deeplink}"
