# -*- coding: utf-8 -*-
"""
쿠팡 골드박스 페이지에서 특정 상품 카드를 실제 브라우저로 열어
화면 그대로 스크린샷으로 캡처하는 모듈.
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


def _extract_product_id(candidate_obj) -> str:
    """candidate 객체(dict 또는 str)의 모든 텍스트를 탐색하여 Product ID(숫자) 추출"""
    targets = []
    if isinstance(candidate_obj, dict):
        for v in candidate_obj.values():
            if isinstance(v, str):
                targets.append(v)
    elif isinstance(candidate_obj, str):
        targets.append(candidate_obj)

    for target in targets:
        m = re.search(r"/products/(\d+)", target) or re.search(r"productId=(\d+)", target)
        if m:
            return m.group(1)
    return ""


def _normalize_text(s: str) -> str:
    """공백, 줄바꿈, 쉼표, 원, 특수문자, 대괄호 태그를 모두 제거한 순수 비교용 문자열 생성"""
    if not s:
        return ""
    cleaned = re.sub(r"\[.*?\]", "", str(s))  # [로켓프레시] 태그 제거
    cleaned = re.sub(r"[\s,\n\r\t원%\[\]\(\)\-\_]", "", cleaned)  # 서식/특수문자 제거
    return cleaned.lower()


def find_and_capture_first_match(candidates_to_try: list, output_path: str):
    """
    골드박스 페이지 접속 후 Product ID 및 정규화된 텍스트 비교로
    정확히 일치하는 카드를 찾아 스크린샷으로 저장한다.
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

            # 1. 페이지 로딩 대기 (5초)
            page.wait_for_timeout(5000)

            # 2. 리뉴얼 안내 버튼 클릭 처리
            try:
                btn = page.locator("text='더욱 새로워진 골드박스 살펴보기'")
                if btn.is_visible(timeout=2000):
                    btn.click()
                    page.wait_for_timeout(2000)
            except Exception:
                pass

            print(f"[디버그] 페이지 제목: {page.title()}")
            print(f"[디버그] 최종 URL: {page.url}")

            # 3. 스크롤 내리며 카드 로딩
            prev_count = -1
            stable_rounds = 0
            for _ in range(20):
                page.mouse.wheel(0, 1200)
                page.wait_for_timeout(1000)
                current_count = len(page.query_selector_all("a[href*='/vp/products/']"))
                if current_count == prev_count and current_count > 0:
                    stable_rounds += 1
                    if stable_rounds >= 2:
                        break
                else:
                    stable_rounds = 0
                prev_count = current_count

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

            # 4. 카드 요소 데이터 추출 및 스크롤 렌더링
            card_items = []
            for card in cards:
                try:
                    card.scroll_into_view_if_needed()
                    page.wait_for_timeout(100)
                    card_items.append((
                        card,
                        card.inner_text(),
                        card.inner_html(),
                        _normalize_text(card.inner_text())  # 비교용 정규화 텍스트
                    ))
                except Exception:
                    continue

            # 5. 후보 매칭 수행
            for price, name, candidate in candidates_to_try:
                product_id = _extract_product_id(candidate)
                
                # 비교 데이터 정규화
                norm_price = _normalize_text(int(price))
                norm_name = _normalize_text(name)[:6]  # 상품명 앞 6글자(공백/태그 제외)

                print(f"[스크린샷] 매칭 시도 -> ID: '{product_id}' / 가격: '{norm_price}' / 키워드: '{norm_name}'")

                for card, text, html, norm_text in card_items:
                    is_matched = False

                    # [방법 1] Product ID 매칭 (가장 정확)
                    if product_id and product_id in html:
                        is_matched = True
                        print(f"[스크린샷] ✅ Product ID({product_id}) 매칭 성공")

                    # [방법 2] 정규화 텍스트 매칭 (가격 번호 + 상품명 핵심어)
                    elif norm_price in norm_text and norm_name in norm_text:
                        is_matched = True
                        print(f"[스크린샷] ✅ 정규화 텍스트(가격+키워드) 매칭 성공")

                    # [방법 3] 가격 변동 대비 (상품명 키워드만으로 2차 검증)
                    elif len(norm_name) >= 4 and norm_name in norm_text:
                        is_matched = True
                        print(f"[스크린샷] ✅ 키워드 단독 매칭 성공")

                    if is_matched:
                        card.scroll_into_view_if_needed()
                        page.wait_for_timeout(300)
                        card.screenshot(path=output_path)
                        full_name, discount_rate = _parse_card_text(text, name)
                        print(f"[스크린샷] 캡처 완료: {full_name} / 할인율: {discount_rate}")
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
