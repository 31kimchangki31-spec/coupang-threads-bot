# -*- coding: utf-8 -*-
"""
쿠팡 골드박스 페이지에서 특정 상품 카드를 실제 브라우저로 열어
화면 그대로 스크린샷으로 캡처하는 모듈.
이미지에도 정보가 다 담기지만, 게시글 본문 텍스트에도 쓸 수 있게
카드 텍스트에서 전체 상품명/할인율도 같이 파싱해서 반환한다.
"""
import re
import math
from playwright.sync_api import sync_playwright

GOLDBOX_URL = "https://www.coupang.com/np/goldbox"

# "몇 % 판매됨"(판매 진행률)과 "몇 % 할인"(진짜 할인율)을 구분하기 위해
# "할인"이라는 단어가 붙어있거나, 혹은 그 줄에 숫자%만 단독으로 있는 경우만 할인율로 인정
# ("99% 판매됨"처럼 다른 글자가 붙은 줄은 제외됨)
DISCOUNT_WITH_LABEL_PATTERN = re.compile(r"(\d+)\s*%\s*할인")
BARE_PERCENT_PATTERN = re.compile(r"^(\d+)\s*%$")

# 배지 텍스트(%) 파싱이 상품마다 레이아웃이 달라 실패할 수 있어서,
# "판매가원 정가원"처럼 가격이 두 개 붙어있으면 직접 할인율을 계산하는 폴백
TWO_PRICE_PATTERN = re.compile(r"([\d,]+)\s*원[^0-9]{0,10}?([\d,]+)\s*원")

# 이름이 아닌 정보성 줄(가격/배송/판매율 등)은 상품명 후보에서 제외
SKIP_LINE_PATTERN = re.compile(r"원|%|로켓|남음|배송|판매|쿠폰|무료")


def _compute_discount_from_prices(text: str):
    """'16,500원 27,900원'처럼 가격이 두 개 붙어있으면 할인율을 직접 계산."""
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


HANGUL_PATTERN = re.compile(r"[가-힣]")


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
        # 브랜드 로고 줄(예: "LA BRUKET")은 한글이 없어서 걸러짐 -> 실제 상품명만 남음
        if (
            not SKIP_LINE_PATTERN.search(line)
            and len(line) > 3
            and HANGUL_PATTERN.search(line)
        ):
            full_name = line
            break

    # 배지 텍스트로 못 찾았으면, 가격 두 개로 직접 계산 시도
    if discount_rate is None:
        computed = _compute_discount_from_prices(text)
        if computed is not None:
            discount_rate = float(computed)

    return full_name, discount_rate


def find_and_capture_first_match(candidates_to_try: list, output_path: str):
    """
    골드박스 페이지를 한 번만 열고, candidates_to_try(=[(price, name, candidate_dict), ...])를
    순서대로 시도해서 처음 매칭되는 걸 스크린샷으로 저장한다.
    이미 상품마다 브라우저를 새로 여는 것보다 훨씬 빠르고, 실패해도 자동으로 다음 후보로 넘어간다.
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
            print(f"[스크린샷] 골드박스 페이지 접속 시도: {GOLDBOX_URL}")
            page.goto(GOLDBOX_URL, timeout=60000)
            page.wait_for_timeout(5000)

            page.mouse.wheel(0, 800)
            page.wait_for_timeout(3000)

            # 카드가 어느정도(5개 이상) 로딩된 뒤, 개수가 더 안 늘어날 때까지 반복 스크롤.
            # (초반엔 0개인 게 정상이라, 0개인 상태에서 "안정됐다"고 착각해 일찍 멈추는 걸 방지)
            prev_count = -1
            stable_rounds = 0
            for _ in range(25):
                page.mouse.wheel(0, 900)
                page.wait_for_timeout(1500)
                current_count = len(page.query_selector_all("a[href*='/vp/products/']"))
                if current_count >= 5 and current_count == prev_count:
                    stable_rounds += 1
                    if stable_rounds >= 3:
                        break
                else:
                    stable_rounds = 0
                prev_count = current_count

            # 스크롤을 다 내린 "이후" 시점 화면을 디버그용으로 저장 (실제 보이는 상태 확인용)
            print(f"[디버그] 페이지 제목: {page.title()}")
            print(f"[디버그] 최종 URL: {page.url}")
            page.screenshot(path="debug_full_page.png", full_page=False)

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

            print(f"[스크린샷] 화면에서 카드 {len(cards)}개 탐색됨")

            # 카드 텍스트를 미리 한 번씩만 읽어서 캐싱 (여러 후보와 반복 비교할 때 효율적)
            card_texts = []
            for card in cards:
                try:
                    card_texts.append((card, card.inner_text()))
                except Exception:
                    continue

            for price, name, candidate in candidates_to_try:
                price_str = f"{int(price):,}"
                name_fragment = name.strip()[:10]
                print(f"[스크린샷] 매칭 시도: {price_str}원 / '{name_fragment}'")
                for card, text in card_texts:
                    if price_str in text and name_fragment in text:
                        card.screenshot(path=output_path)
                        full_name, discount_rate = _parse_card_text(text, name)
                        print(f"[스크린샷] 매칭 성공: {full_name} / 할인율: {discount_rate}")
                        return candidate, full_name, discount_rate

            print("[스크린샷] 시도한 후보 중 화면과 일치하는 카드를 하나도 찾지 못함")
            return None, None, None

        except Exception as e:
            print(f"[스크린샷] 실패: {e}")
            return None, None, None
        finally:
            browser.close()


def capture_goldbox_card_screenshot(target_price: int, target_name: str, output_path: str):
    """(구버전 호환용) 단일 후보만 시도하는 래퍼."""
    matched, full_name, discount_rate = find_and_capture_first_match(
        [(target_price, target_name, None)], output_path
    )
    return matched is not None, full_name or target_name, discount_rate
