# -*- coding: utf-8 -*-
"""
쓰레드 게시글 문구 생성 모듈.

동작 순서:
  1) ANTHROPIC_API_KEY가 있으면 Claude로 본문 생성 (모델 폴백 체인)
  2) 실패하면 템플릿으로 생성
어느 경로든 공시 문구와 고정 CTA는 코드에서 강제로 붙인다.
"""
import json
import os
import random

import requests

# ---------------------------------------------------------------------------
# 경제적 이해관계 표시 문구.
#
# 2024-12-01 시행 개정 심사지침은 표시 문구를 게시물 '끝부분'에 두는 방식을
# 더 이상 적절하다고 보지 않는다. 그래서 본문 첫 줄로 올리고 문장을 줄였다.
# 위치를 앞으로 옮긴 대신 길이가 짧아져 전체 글자 수는 오히려 줄어든다.
#
# 주제 태그(topic_tag)는 사용자가 직접 입력하는 '주제'일 뿐이고, Meta가 붙이는
# 유료광고 표시가 아니다. 따라서 태그만으로는 이 문구를 대체할 수 없다.
# ---------------------------------------------------------------------------
DISCLOSURE = "광고 · 쿠팡 파트너스 수수료를 받습니다"

# 고정 CTA. 사용하지 않으려면 빈 문자열로 둔다.
CTA = ""

MONEY_EMOJIS = ["💰", "💸", "🏷️"]
LINK_EMOJIS = ["🔗", "👉", "📎"]
DISCOUNT_EMOJIS = ["🔻", "⬇️", "🔥"]

# 앞에서부터 순서대로 시도한다. 마지막까지 실패하면 템플릿으로 떨어진다.
MODEL_CHAIN = [
    os.environ.get("CAPTION_MODEL") or "claude-opus-5",
    "claude-sonnet-5",
]

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"

SYSTEM_PROMPT = """당신은 쿠팡 파트너스 제휴 마케터의 쓰레드(Threads) 게시글 작성자입니다.

작성 규칙:
- 한국어, 반말 섞인 친근한 구어체
- 3~4줄, 각 줄은 짧게. 전체 200자 이내
- 첫 줄은 스크롤을 멈추게 하는 후크 (질문형 또는 의외성)
- 상품의 구체적 쓸모를 한 가지만 언급. 여러 기능 나열 금지
- 과장 광고 표현 금지: "최저가", "무조건", "역대급", "품절임박" 사용하지 말 것
- 이모지는 최대 2개
- 가격, 링크, 공시 문구, CTA는 절대 쓰지 말 것 (시스템이 따로 붙임)
- 해시태그 쓰지 말 것

출력은 게시글 본문 텍스트만. 설명이나 따옴표 없이."""


def _discount_line(discount_rate) -> str:
    if not discount_rate:
        return ""
    try:
        rate = float(discount_rate)
    except (TypeError, ValueError):
        return ""
    if rate <= 0:
        return ""
    return f"{random.choice(DISCOUNT_EMOJIS)} {rate:.0f}% 할인\n"


def _price_block(price, original_price=None, discount_rate=None,
                 coupon_required=False) -> str:
    """
    가격 표시 블록. 정가가 있으면 취소선 대신 '->' 로 대비를 준다.
    쿠폰 적용이 조건인 가격은 반드시 그 사실을 함께 적는다 (표시광고 문제 방지).
    """
    money = random.choice(MONEY_EMOJIS)
    lines = []

    rate_line = _discount_line(discount_rate).strip()
    if rate_line:
        lines.append(rate_line)

    if not price:
        return "\n".join(lines)

    if original_price and original_price > price:
        lines.append(f"{money} {int(original_price):,}원 → {int(price):,}원")
    else:
        lines.append(f"{money} {int(price):,}원")

    if coupon_required:
        lines.append("※ 쿠폰 적용 시 가격이며, 조건에 따라 달라질 수 있어요")

    return "\n".join(lines)


def _template_body(product_name: str) -> str:
    """AI 없이 쓰는 기본 본문 (상품명만)."""
    return product_name.strip()


def _call_claude(prompt: str, api_key: str, model: str) -> str:
    resp = requests.post(
        API_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        },
        data=json.dumps(
            {
                "model": model,
                "max_tokens": 400,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": prompt}],
            }
        ),
        timeout=45,
    )
    if not resp.ok:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")

    payload = resp.json()
    blocks = payload.get("content") or []
    text = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    text = text.strip()
    if not text:
        raise RuntimeError(f"빈 응답: {str(payload)[:300]}")
    return text


def _ai_body(product_name: str, price, discount_rate, category: str) -> str:
    """Claude로 본문을 생성한다. 전부 실패하면 RuntimeError."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY 미설정")

    facts = [f"상품명: {product_name}"]
    if category:
        facts.append(f"카테고리: {category}")
    if price:
        facts.append(f"판매가: {int(price):,}원")
    if discount_rate:
        try:
            facts.append(f"할인율: {float(discount_rate):.0f}%")
        except (TypeError, ValueError):
            pass
    prompt = "아래 상품으로 쓰레드 게시글 본문을 써주세요.\n\n" + "\n".join(facts)

    errors = []
    for model in MODEL_CHAIN:
        if not model:
            continue
        try:
            body = _call_claude(prompt, api_key, model)
            print(f"[캡션] AI 생성 성공 (model={model})")
            return body
        except Exception as exc:
            print(f"[캡션] {model} 실패: {exc}")
            errors.append(f"{model}: {exc}")

    raise RuntimeError("모든 모델 실패 -> " + " | ".join(errors))


def _sanitize(body: str) -> str:
    """AI가 넣지 말라는 걸 넣었을 때 대비한 후처리."""
    banned = ["최저가", "무조건", "역대급", "품절임박", "#"]
    lines = []
    for line in body.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if "coupang.com" in stripped or "link.coupang" in stripped:
            continue  # 링크는 시스템이 붙인다
        if DISCLOSURE[:8] in stripped:
            continue  # 공시 중복 방지
        for word in banned:
            stripped = stripped.replace(word, "")
        lines.append(stripped.strip())
    return "\n".join(lines[:5]).strip()


def generate_caption(
    product_name: str,
    price,
    deeplink: str,
    discount_rate=None,
    original_price=None,
    coupon_required: bool = False,
    category: str = "",
    use_ai: bool = True,
) -> str:
    """
    최종 게시글 문구를 만든다.
    본문(AI 또는 템플릿) + 가격블록 + 링크 + CTA + 공시 순서로 조립한다.
    공시와 CTA는 AI 응답과 무관하게 항상 붙는다.
    """
    body = ""
    if use_ai:
        try:
            body = _sanitize(_ai_body(product_name, price, discount_rate, category))
        except Exception as exc:
            print(f"[캡션] AI 실패, 템플릿으로 대체: {exc}")

    if not body:
        body = _template_body(product_name)

    # 표시 문구를 첫 줄에 둔다 (심사지침 권장 위치)
    parts = [DISCLOSURE, body]

    price_block = _price_block(price, original_price, discount_rate, coupon_required)
    if price_block:
        parts.append(price_block)

    link_emoji = random.choice(LINK_EMOJIS)
    parts.append(f"{link_emoji} {deeplink}")

    if CTA.strip():
        parts.append(CTA)

    return "\n\n".join(p for p in parts if p and p.strip())
