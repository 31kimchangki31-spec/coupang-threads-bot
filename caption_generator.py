# -*- coding: utf-8 -*-
"""
게시글 문구 생성 모듈.
"""
import random

MONEY_EMOJIS = ["💰", "💸", "🏷️"]
LINK_EMOJIS = ["🔗", "👉", "📎"]
DISCOUNT_EMOJIS = ["🔻", "⬇️", "🔥"]

# 토스 공식 문서(경제적 이해관계 표시 가이드)에서 권장하는 문구.
# "광고" 라벨이 자동으로 붙어도 이 문구는 별개로 필요함 (공정위 표시광고 심사지침 요구사항).
DISCLOSURE = "\n\n(이 포스팅은 토스쇼핑 쉐어링크 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.)"


def _discount_line(discount_rate) -> str:
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
    money_emoji = random.choice(MONEY_EMOJIS)
    link_emoji = random.choice(LINK_EMOJIS)

    discount_line = _discount_line(discount_rate)
    price_str = f"{money_emoji} {int(price):,}원" if price else ""
    body = f"{product_name}\n{discount_line}{price_str}\n\n{link_emoji} {deeplink}"
    return body + DISCLOSURE
