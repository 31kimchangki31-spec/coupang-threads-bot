# -*- coding: utf-8 -*-
"""
게시글 문구 생성 모듈.
스크린샷 이미지 안에 정가/할인율/전체 상품명이 다 담기므로,
본문 텍스트는 상품명+가격+링크 정도로 짧게만 구성한다.
"""
import os
import random

MONEY_EMOJIS = ["💰", "💸", "🏷️"]
LINK_EMOJIS = ["🔗", "👉", "📎"]
DISCOUNT_EMOJIS = ["🔻", "⬇️", "🔥"]


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
    return f"{product_name}\n{discount_line}{price_str}\n\n{link_emoji} {deeplink}"
