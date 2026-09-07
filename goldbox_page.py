# -*- coding: utf-8 -*-
"""
골드박스 페이지를 한 번만 열어서 모든 카드의 정확한 정보를 수집하고,
각 카드를 개별 이미지로 캡처하는 모듈.

왜 필요한가:
  골드박스 Open API의 productPrice는 쿠폰 적용 전 '정가'를 주는 경우가 있고
  (예: 정가 14,780원 / 실제 3,780원), 상품명도 짧게 잘려서 온다.
  할인율은 아예 오지 않는다. 정확한 숫자와 전체 상품명은 페이지에만 있다.

수집 항목 (productId 기준):
  full_name, sale_price, original_price, discount_rate,
  remaining_time, coupon_required, card_image
"""
import math
import os
import re

GOLDBOX_URL = "https://www.coupang.com/np/goldbox"
CARD_DIR = "cards"

PRICE_PATTERN = re.compile(r"([\d,]{3,})\s*원")
PERCENT_ONLY_PATTERN = re.compile(r"^(\d{1,2})\s*%$")
TIMER_PATTERN = re.compile(r"(\d{1,2}:\d{2}:\d{2})\s*남음")

# 조건부 가격이라 '판매가'로 쓰면 안 되는 줄
CONDITIONAL_LINE = re.compile(r"가입\s*쿠폰가|WOW|와우|첫구매|신규")
# 가격이 아닌 숫자가 섞인 줄
NOISE_LINE = re.compile(r"판매됨|배송|도착|남음|리뷰")
# 단위당 가격, 리뷰 수 등은 괄호 안에 있으므로 통째로 제거한다
PAREN_PATTERN = re.compile(r"\([^)]*\)")
# 상품명 줄에서 배제할 패턴
NOT_A_NAME = re.compile(r"원|%|로켓|남음|판매|쿠폰|무료|배송|도착|\(\d")


def _parse_card(text: str) -> dict:
    """카드 전체 텍스트에서 상품명, 가격, 할인율, 남은시간을 뽑는다."""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    result = {
        "full_name": None,
        "sale_price": None,
        "original_price": None,
        "discount_rate": None,
        "remaining_time": None,
        "coupon_required": False,
    }

    prices = []          # (금액, 쿠폰조건여부)
    for line in lines:
        timer = TIMER_PATTERN.search(line)
        if timer and not result["remaining_time"]:
            result["remaining_time"] = timer.group(1)
            continue

        percent = PERCENT_ONLY_PATTERN.match(line)
        if percent and result["discount_rate"] is None:
            result["discount_rate"] = float(percent.group(1))
            continue

        # 상품명: 가격/배지/배송 정보가 없는 첫 줄
        if (
            result["full_name"] is None
            and len(line) > 5
            and not NOT_A_NAME.search(line)
        ):
            result["full_name"] = line
            continue

        # 가격 수집. 조건부 가격 줄과 노이즈 줄은 제외
        if CONDITIONAL_LINE.search(line) or NOISE_LINE.search(line):
            continue
        # 괄호 안 단위당 가격/리뷰수를 걷어내고 첫 번째 금액만 본다
        cleaned = PAREN_PATTERN.sub(" ", line)
        match = PRICE_PATTERN.search(cleaned)
        if match:
            try:
                amount = int(match.group(1).replace(",", ""))
            except ValueError:
                continue
            if amount > 0:
                prices.append((amount, "쿠폰" in cleaned))

    if prices:
        amounts = [p[0] for p in prices]
        result["sale_price"] = min(amounts)
        if len(amounts) > 1 and max(amounts) > min(amounts):
            result["original_price"] = max(amounts)
        # 최저가 줄에 '쿠폰'이 있으면 쿠폰 적용 조건부 가격
        for amount, is_coupon in prices:
            if amount == result["sale_price"] and is_coupon:
                result["coupon_required"] = True

    # 할인율 배지를 못 읽었으면 두 가격으로 계산
    if (
        result["discount_rate"] is None
        and result["sale_price"]
        and result["original_price"]
    ):
        sale, original = result["sale_price"], result["original_price"]
        result["discount_rate"] = float(
            math.floor((original - sale) / original * 100)
        )

    return result


def scrape_all(max_cards: int = 60) -> dict:
    """
    골드박스 페이지를 한 번 열어 모든 카드를 파싱하고 개별 캡처한다.
    반환: {productId(str): {수집 항목...}}
    실패하면 빈 dict.
    """
    if os.environ.get("SCRAPE_GOLDBOX", "1") == "0":
        print("[페이지] SCRAPE_GOLDBOX=0, 페이지 수집 건너뜀")
        return {}

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[페이지] playwright 미설치, 페이지 수집 건너뜀")
        return {}

    os.makedirs(CARD_DIR, exist_ok=True)
    collected = {}

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
                viewport={"width": 1600, "height": 1200},
                device_scale_factor=2,
                locale="ko-KR",
                timezone_id="Asia/Seoul",
            )
            page = context.new_page()
            page.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
            )
            try:
                page.goto(GOLDBOX_URL, timeout=60000)
                page.wait_for_timeout(5000)
                for _ in range(10):
                    page.mouse.wheel(0, 1600)
                    page.wait_for_timeout(700)
                page.mouse.wheel(0, -20000)
                page.wait_for_timeout(1500)

                # 상품 링크를 기준으로 카드를 찾는다.
                # 클래스명은 배포마다 바뀌지만 /vp/products/ 링크 구조는 안정적이다.
                links = page.query_selector_all("a[href*='/vp/products/']")
                print(f"[페이지] 상품 링크 {len(links)}개 발견")

                seen = set()
                for link in links[: max_cards * 3]:
                    if len(collected) >= max_cards:
                        break
                    try:
                        href = link.get_attribute("href") or ""
                        id_match = re.search(r"/vp/products/(\d+)", href)
                        if not id_match:
                            continue
                        product_id = id_match.group(1)
                        if product_id in seen:
                            continue
                        seen.add(product_id)

                        card = link.evaluate_handle(
                            "el => el.closest('li') || el.parentElement"
                        ).as_element()
                        if card is None:
                            continue

                        text = card.inner_text()
                        if not text or len(text.strip()) < 10:
                            continue

                        parsed = _parse_card(text)
                        if not parsed["sale_price"]:
                            continue

                        image_path = os.path.join(CARD_DIR, f"{product_id}.png")
                        try:
                            card.scroll_into_view_if_needed(timeout=5000)
                            page.wait_for_timeout(250)
                            card.screenshot(path=image_path)
                            parsed["card_image"] = image_path
                        except Exception:
                            parsed["card_image"] = None

                        collected[product_id] = parsed
                    except Exception:
                        continue
            finally:
                browser.close()
    except Exception as exc:
        print(f"[페이지] 수집 실패, API 데이터만 사용: {exc}")
        return {}

    print(f"[페이지] 카드 {len(collected)}개 수집 완료")
    return collected


def merge(api_item: dict, page_data: dict) -> dict:
    """API 항목에 페이지에서 읽은 정확한 값을 덮어쓴다. 페이지 값이 우선."""
    found = page_data.get(api_item["id"])
    if not found:
        return api_item

    merged = dict(api_item)
    if found.get("full_name"):
        merged["name"] = found["full_name"]
    if found.get("sale_price"):
        merged["price"] = found["sale_price"]
    if found.get("original_price"):
        merged["original_price"] = found["original_price"]
    if found.get("discount_rate"):
        merged["discount_rate"] = found["discount_rate"]
    merged["remaining_time"] = found.get("remaining_time")
    merged["coupon_required"] = found.get("coupon_required", False)
    merged["card_image"] = found.get("card_image")
    merged["from_page"] = True
    return merged
