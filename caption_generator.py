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
# 특정 카테고리(식품/생활용품 등)에 치우치지 않고 어떤 상품에도 어울리게 범용으로 구성
HOOK_TEMPLATES = [
    "특가 떠서 가져왔어요 👀",
    "혼자 알기 아까운 가격이라 공유해요",
    "가격 보고 놀라서 공유합니다",
    "지나가다 발견한 특가예요",
    "필요하신 분 있을까 해서 올려봐요",
    "타이밍 맞으면 이득인 특가",
    "이 가격이면 한번 볼 만함",
    "지금 이 가격 흔치 않아요",
    "할인 중이길래 가져와봤어요",
    "특가로 나온 상품이에요",
    "핫딜 찾다가 이거 발견함",
    "지금 가격 괜찮아서 가져옴",
    "살까 말까 고민될 가격",
    "이거 지금 가격 괜찮은데? 👀",
]

MONEY_EMOJIS = ["💰", "💸", "🏷️"]
LINK_EMOJIS = ["🔗", "👉", "📎"]
DISCOUNT_EMOJIS = ["🔻", "⬇️", "🔥"]


def shorten_product_name(name: str) -> str:
    """
    상품명을 자르거나 변형하지 않고 전체 그대로 반환한다.
    쉼표(,), 하이픈(-), 수량, 용량, 괄호 등 모든 내용을 유지한다.
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


def generate_caption(product_name: str, price: int, deeplink: str, discount_rate=None) -> str:
    short_name = shorten_product_name(product_name)

    use_ai = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if use_ai:
        return _generate_with_ai(short_name, price, deeplink, discount_rate)

    hook = random.choice(HOOK_TEMPLATES)
    money_emoji = random.choice(MONEY_EMOJIS)
    link_emoji = random.choice(LINK_EMOJIS)

    discount_line = _discount_line(discount_rate)
    price_str = f"{money_emoji} {int(price):,}원" if price else ""
    body = f"{hook}\n\n{short_name}\n{discount_line}{price_str}\n\n{link_emoji} {deeplink}"
    return body + DISCLOSURE


def _generate_with_ai(product_name: str, price: int, deeplink: str, discount_rate=None) -> str:
    """Claude API로 캡션 생성 (ANTHROPIC_API_KEY 설정 시에만 사용)"""
    import anthropic

    discount_line = _discount_line(discount_rate)
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
    return f"{hook}\n\n{product_name}\n{discount_line}{price_str}\n\n🔗 {deeplink}{DISCLOSURE}"
