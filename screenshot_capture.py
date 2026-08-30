# -*- coding: utf-8 -*-
"""
쿠팡 골드박스 페이지에서, API가 준 후보 상품들과 화면을 매칭해서
해당 카드를 스크린샷으로 캡처하는 모듈.
(과도한 봇탐지 우회 장치는 오히려 역효과를 낼 수 있어 최소한으로 유지)
"""
import re
import math
from playwright.sync_api import sync_playwright

GOLDBOX_URL = "https://www.coupang.com/np/goldbox"

DISCOUNT_WITH_LABEL_PATTERN = re.compile(r"(\d+)\s*%\s*할인")
BARE_PERCENT_PATTERN = re.compile(r"^(\d+)\s*%$")
TWO_PRICE_PATTERN = re.compile(r"([\d,]+)\s*원[^0-9]{0,10}?([\d,]+)\s*원")
SKIP_LINE_PATTERN = re.compile(r"원|%|로켓|남음|배송|판매|쿠폰|무료")
HANGUL_PATTERN = re.compile(r"[가-힣]")


def _compute_discount_from_prices(text: str):
    m = TWO_PRICE_PATTERN.search(text)
    if not m:
        return None
    try:
        price_a = int(m.group(1).replace(",", ""))
        price_b = int(m.group(2).replace(",", ""))
    except ValueError:
        return None
    sale, original = min(price_a, price_b), max(price_a, price_b)
    if original <= sale or original <= 0:
        return None
    return math.floor((original - sale) / original * 100)


def _parse_card_text(text: str, fallback_name: str):
    """카드의 전체 텍스트에서 전체 상품명과 할인율(있으면)을 뽑아낸다."""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    full_name = fallback_name
    discount_rate = None

    for line in lines:
        if discount_rate is None:
            m = DISCOUNT_WITH_LABEL_PATTERN.search(line) or BARE_PERCENT_PATTERN.match(line)
            if m:
                discount_rate = float(m.group(1))
                continue
        if (
            not SKIP_LINE_PATTERN.search(line)
            and len(line) > 3
            and HANGUL_PATTERN.search(line)
        ):
            full_name = line
            break

    if discount_rate is None:
        computed = _compute_discount_from_prices(text)
        if computed is not None:
            discount_rate = float(computed)

    return full_name, discount_rate


def find_and_capture_first_match(candidates_to_try: list, output_path: str):
    """
    골드박스 페이지를 한 번만 열고, candidates_to_try(=[(price, name, candidate_dict), ...])를
    순서대로 시도해서 처음 매칭되는 걸 스크린샷으로 저장한다.
    반환: (matched_candidate: dict|None, full_name: str|None, discount_rate: float|None)
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            channel="chromium",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-sandbox",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=2,
            locale="ko-KR",
            timezone_id="Asia/Seoul",
        )
        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        try:
            cards = []
            for attempt in range(1, 4):
                print(f"[스크린샷] 골드박스 페이지 접속 시도 ({attempt}/3): {GOLDBOX_URL}")
                if attempt == 1:
                    page.goto(GOLDBOX_URL, timeout=60000)
                else:
                    page.reload(timeout=60000)
                page.wait_for_timeout(5000)

                page.mouse.wheel(0, 1000)
                page.wait_for_timeout(3000)

                for _ in range(8):
                    page.mouse.wheel(0, 1500)
                    page.wait_for_timeout(800)

                cards = page.query_selector_all(
                    "li.baby-product, .instant-n-item, div[class*='ProductItem']"
                )
                if not cards:
                    links = page.query_selector_all("a[href*='/vp/products/']")
                    cards = []
                    for link in links:
                        try:
                            parent = link.evaluate_handle(
                                "el => el.closest('li') || el.closest('div')"
                            ).as_element()
                            if parent and parent not in cards:
                                cards.append(parent)
                        except Exception:
                            continue

                print(f"[스크린샷] 시도 {attempt}회차: 카드 {len(cards)}개 탐색됨")
                if len(cards) >= 10:
                    break
                print(f"[스크린샷] 카드가 너무 적음({len(cards)}개), 새로고침 후 재시도")

            print(f"[디버그] 페이지 제목: {page.title()}")
            print(f"[디버그] 최종 URL: {page.url}")
            page.screenshot(path="debug_full_page.png", full_page=False)

            print(f"[스크린샷] 화면에서 카드 {len(cards)}개 탐색됨")

            # 매칭이 왜 실패하는지 원인 파악용 디버그: 텍스트 읽기 성공/실패 집계 + 샘플 출력
            readable_texts = []
            read_errors = 0
            for card in cards:
                try:
                    t = card.inner_text()
                    readable_texts.append(t)
                except Exception:
                    read_errors += 1
            print(f"[디버그] 카드 텍스트 읽기: 성공 {len(readable_texts)}개 / 실패 {read_errors}개")
            for i, t in enumerate(readable_texts[:3]):
                sample = re.sub(r"\s+", " ", t)[:100]
                print(f"[디버그] 카드#{i} 텍스트 샘플: {sample}")

            for price, name, candidate in candidates_to_try:
                price_str = f"{int(price):,}"
                name_fragment = name.strip()[:10]
                print(f"[스크린샷] 매칭 시도: {price_str}원 / '{name_fragment}'")

                for text in readable_texts:
                    # 줄바꿈/공백 무시하고 비교 (상품명이 화면에서 줄바꿈될 수 있어서)
                    normalized = re.sub(r"\s+", " ", text)
                    normalized_fragment = re.sub(r"\s+", " ", name_fragment)
                    if price_str in normalized and normalized_fragment in normalized:
                        idx = readable_texts.index(text)
                        cards[idx].screenshot(path=output_path)
                        full_name, discount_rate = _parse_card_text(text, name)
                        print(f"[스크린샷] 매칭 성공: {full_name} / 할인율 {discount_rate}")
                        return candidate, full_name, discount_rate

            print("[스크린샷] 시도한 후보 중 화면과 일치하는 카드를 하나도 찾지 못함")
            return None, None, None

        except Exception as e:
            print(f"[스크린샷] 실패: {e}")
            return None, None, None
        finally:
            browser.close()
