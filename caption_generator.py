# -*- coding: utf-8 -*-
"""
게시글 문구 생성 모듈.
기본은 템플릿 조합 방식(무료, 즉시 사용 가능).
ANTHROPIC_API_KEY가 설정되어 있으면 Claude API로 자연스러운 문구를 생성한다(선택사항).
"""
import os
import random
import re

# 스크린샷 스타일: 상품명 -> 가격 -> (빈줄) -> 링크 순서
DISCLOSURE = "\n\n(이 게시물은 쿠팡파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.)"

MAX_CORE_NAME_LEN = 20  # 핵심 상품명(수량 제외) 최대 길이
QUANTITY_PATTERN = re.compile(r"\d[\d,.]*\s*(g|kg|ml|l|개|매|팩|box|봉|입|정|포|캡슐|장|병|세트)", re.IGNORECASE)

# 매번 무작위로 하나씩 골라 쓰는 도입 문구 (봇 느낌 줄이기용)
HOOK_TEMPLATES = [
    "오늘의 특가 떴어요 👀",
    "이거 재구매각인데 지금 싸네요",
    "장바구니 담아두고 나중에 후회하지 마세요",
    "혼자 알기 아까운 가격이라 공유해요",
    "요즘 이거 잘 쓰고 있어요",
    "지금 이 가격이면 사야 함",
    "눈여겨보던 상품인데 할인 중이네요",
]

MONEY_EMOJIS = ["💰", "💸", "🏷️"]
LINK_EMOJIS = ["🔗", "👉", "📎"]


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


def generate_caption(product_name: str, price: int, deeplink: str) -> str:
    short_name = shorten_product_name(product_name)

    use_ai = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if use_ai:
        return _generate_with_ai(short_name, price, deeplink)

    hook = random.choice(HOOK_TEMPLATES)
    money_emoji = random.choice(MONEY_EMOJIS)
    link_emoji = random.choice(LINK_EMOJIS)

    price_str = f"{money_emoji} {int(price):,}원" if price else ""
    body = f"{hook}\n\n{short_name}\n{price_str}\n\n{link_emoji} {deeplink}"
    return body + DISCLOSURE


def _generate_with_ai(product_name: str, price: int, deeplink: str) -> str:
    """Claude API로 캡션 생성 (ANTHROPIC_API_KEY 설정 시에만 사용)"""
    import anthropic

    price_str = f"💰 {int(price):,}원" if price else ""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[
            {
                "role": "user",
                "content": (
                    f"'{product_name}' ({price_str}) 상품을 소개하는 짧은 한 줄 문구를 "
                    "친근한 톤으로 하나만 작성해줘. 이모지 0~1개, 과장광고 문구 금지, "
                    "해시태그 없이, 상품명은 반복하지 말고."
                ),
            }
        ],
    )
    hook = message.content[0].text.strip()
    return f"{hook}\n\n{product_name}\n{price_str}\n\n🔗 {deeplink}{DISCLOSURE}"
