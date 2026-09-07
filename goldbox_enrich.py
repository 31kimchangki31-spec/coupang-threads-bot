# -*- coding: utf-8 -*-
"""
골드박스 페이지에서 할인율 / 정가를 보강하는 선택적 모듈.

골드박스 Open API는 판매가는 주지만 할인율과 정가는 항상 주지 않는다.
카드 이미지에 할인 배지를 넣으려면 이 숫자가 필요해서, 선택한 상품 하나에
대해서만 페이지에서 숫자를 읽어온다.

원칙:
  - 상품 이미지와 카드 레이아웃은 쿠팡 화면을 캡처하지 않고 직접 렌더링한다.
    (이 모듈은 '숫자'만 보강한다)
  - 실패하면 조용히 None을 반환하고 파이프라인은 그대로 진행된다.
  - ENRICH_DISCOUNT=0 이면 아예 건너뛴다.
"""
import math
import os
import re

GOLDBOX_URL = "https://www.coupang.com/np/goldbox"

DISCOUNT_PATTERN = re.compile(r"(\d{1,2})\s*%")
TWO_PRICE_PATTERN = re.compile(r"([\d,]{3,})\s*원[^0-9]{0,12}?([\d,]{3,})\s*원")


def _discount_from_prices(text: str):
    match = TWO_PRICE_PATTERN.search(text)
    if not match:
        return None, None
    try:
        a = int(match.group(1).replace(",", ""))
        b = int(match.group(2).replace(",", ""))
    except ValueError:
        return None, None
    sale, original = min(a, b), max(a, b)
    if original <= sale:
        return None, None
    return math.floor((original - sale) / original * 100), original


def enrich(product: dict) -> dict:
    """
    선택된 상품의 discount_rate / original_price 를 채워서 반환한다.
    실패해도 원본 dict를 그대로 돌려준다.
    """
    if os.environ.get("ENRICH_DISCOUNT", "1") == "0":
        return product
    if product.get("discount_rate"):
        return product  # API가 이미 줬으면 건드리지 않는다

    name_fragment = (product.get("name") or "").strip()[:12]
    price = product.get("price")
    if not name_fragment or not price:
        return product

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[보강] playwright 미설치, 할인율 보강 건너뜀")
        return product

    price_str = f"{int(price):,}"
    print(f"[보강] 골드박스에서 '{name_fragment}' 할인 정보 탐색")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1920, "height": 1080},
                locale="ko-KR",
                timezone_id="Asia/Seoul",
            )
            page = context.new_page()
            page.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
            )
            try:
                page.goto(GOLDBOX_URL, timeout=45000)
                page.wait_for_timeout(4000)
                for _ in range(6):
                    page.mouse.wheel(0, 1500)
                    page.wait_for_timeout(600)

                body = re.sub(r"\s+", " ", page.inner_text("body"))
            finally:
                browser.close()
    except Exception as exc:
        print(f"[보강] 실패, 할인 정보 없이 진행: {exc}")
        return product

    # 상품명 주변 텍스트만 잘라서 본다
    idx = body.find(name_fragment)
    if idx < 0:
        idx = body.find(price_str)
    if idx < 0:
        print("[보강] 페이지에서 상품을 찾지 못함, 할인 정보 없이 진행")
        return product

    window = body[max(0, idx - 200) : idx + 300]

    rate, original = _discount_from_prices(window)
    if rate is None:
        match = DISCOUNT_PATTERN.search(window)
        if match:
            rate = int(match.group(1))

    enriched = dict(product)
    if rate:
        enriched["discount_rate"] = rate
    if original:
        enriched["original_price"] = original
    print(f"[보강] 결과: 할인율={enriched.get('discount_rate')} 정가={enriched.get('original_price')}")
    return enriched
