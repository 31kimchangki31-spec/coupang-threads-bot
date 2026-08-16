# -*- coding: utf-8 -*-
"""
게시글 문구 생성 모듈.
기본은 템플릿 조합 방식(무료, 즉시 사용 가능).
ANTHROPIC_API_KEY가 설정되어 있으면 Claude API로 자연스러운 문구를 생성한다(선택사항).
"""
import os
import random

# 스크린샷 스타일: 상품명 -> 가격 -> (빈줄) -> 링크 순서
DISCLOSURE = "\n\n(이 게시물은 쿠팡파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.)"


def generate_caption(product_name: str, price: int, deeplink: str) -> str:
    use_ai = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if use_ai:
        return _generate_with_ai(product_name, price, deeplink)

    price_str = f"{int(price):,}원" if price else ""
    body = f"{product_name}\n{price_str}\n\n{deeplink}"
    return body + DISCLOSURE


def _generate_with_ai(product_name: str, price: int, deeplink: str) -> str:
    """Claude API로 캡션 생성 (ANTHROPIC_API_KEY 설정 시에만 사용)"""
    import anthropic

    price_str = f"{int(price):,}원" if price else ""
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
    return f"{hook}\n\n{product_name}\n{price_str}\n\n{deeplink}{DISCLOSURE}"
