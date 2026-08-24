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


def _extract_product_id(*args) -> str:
    """인자로 전달된 모든 객체를 문자열로 변환하여 Product ID(숫자) 100% 추출"""
    text = " ".join(str(a) for a in args if a is not None)
    m = re.search(r"/products/(\d+)", text) or re.search(r"productId=(\d+)", text)
    return m.group(1) if m else ""


def _normalize_text(s: str) -> str:
    """공백, 줄바꿈, 쉼표, 특수문자를 제거한 비교용 정규화 텍스트 생성"""
    if not s:
        return ""
    cleaned = re.sub(r"\[.*?\]", "", str(s))
    cleaned = re.sub(r"[\s,\n\r\t원%\[\]\(\)\-\_]", "", cleaned)
    return cleaned.lower()


def find_and_capture_first_match(candidates_to_try: list, output_path: str):
    """
    골드박스 페이지 접속 후 Product ID 및 링크 URL 추적 방식으로
    정확히 일치하는 상품 카드를 찾아 스크린샷으로 저장한다.
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

            # 1. 초기 렌더링을 위해 5초 대기
            page.wait_for_timeout(5000)

            # 2. 리뉴얼 안내 버튼 클릭
            try:
                btn = page.locator("text='더욱 새로워진 골드박스 살펴보기'")
                if btn.is_visible(timeout=2000):
                    btn.click()
                    page.wait_for_timeout(2000)
            except Exception:
                pass

            print(f"[디버그] 페이지 제목: {page.title()}")
            print(f"[디버그] 최종 URL: {page.url}")

            # 3. 스크롤을 내리며 상품 목록 동적 로딩
            prev_count = -1
            stable_rounds = 0
            for _ in range(20):
                page.mouse.wheel(0, 1200)
                page.wait_for_timeout(1000)
                current_count = len(page.query_selector_all("a[href*='/products/']"))
                if current_count == prev_count and current_count > 0:
                    stable_rounds += 1
                    if stable_rounds >= 2:
                        break
                else:
                    stable_rounds = 0
                prev_count = current_count

            # 4. 화면상의 모든 상품 링크 요소 수집
            product_links = page.query_selector_all("a[href*='/products/'], a[href*='productId']")
            print(f"[스크린샷] 화면에서 상품 링크 {len(product_links)}개 탐색됨")

            # 링크 및 카드 컨테이너 매핑 정보 수집
            link_items = []
            for link in product_links:
                try:
                    href = link.get_attribute("href") or ""
                    # <a> 태그 상위의 전체 카드 블록 탐색
                    card_element = link.evaluate_handle("""
                        el => {
                            let curr = el;
                            for (let i = 0; i < 6; i++) {
                                if (!curr.parentElement) break;
                                curr = curr.parentElement;
                                if (curr.tagName === 'LI' || (curr.className && typeof curr.className === 'string' && (curr.className.includes('Product') || curr.className.includes('card') || curr.className.includes('item')))) {
                                    return curr;
                                }
                            }
                            return el.parentElement ? el.parentElement.parentElement : el;
                        }
                    """).as_element()
                    
                    if card_element:
                        card_element.scroll_into_view_if_needed()
                        page.wait_for_timeout(100)
                        text = card_element.inner_text()
                        link_items.append((card_element, href, text, _normalize_text(text)))
                except Exception:
                    continue

            # 5. 후보 매칭 수행
            for price, name, candidate in candidates_to_try:
                # price, name, candidate 전체에서 Product ID 추적
                product_id = _extract_product_id(price, name, candidate)
                
                norm_price = _normalize_text(int(price))
                norm_name = _normalize_text(name)[:6]

                print(f"[스크린샷] 매칭 시도 -> ID: '{product_id}' / 가격: '{norm_price}' / 키워드: '{norm_name}'")

                for card, href, text, norm_text in link_items:
                    is_matched = False

                    # [우선순위 1] URL의 Product ID로 100% 매칭
                    if product_id and product_id in href:
                        is_matched = True
                        print(f"[스크린샷] ✅ Product ID({product_id}) 매칭 성공!")

                    # [우선순위 2] 정규화 텍스트 매칭
                    elif norm_price in norm_text and norm_name in norm_text:
                        is_matched = True
                        print(f"[스크린샷] ✅ 정규화 텍스트 매칭 성공!")

                    # [우선순위 3] 상품명 단독 매칭
                    elif len(norm_name) >= 4 and norm_name in norm_text:
                        is_matched = True
                        print(f"[스크린샷] ✅ 키워드 단독 매칭 성공!")

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
