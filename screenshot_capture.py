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


def _deep_extract_ids(obj) -> list:
    """candidate 객체 내의 모든 8~12자리 고유 숫자(Product ID, Item ID 등) 교차 추출"""
    text_repr = str(obj)
    digits = re.findall(r"\d{8,12}", text_repr)
    return list(set(digits))


def _clean_keywords(name: str) -> list:
    """상품명에서 [태그] 제거 후 검색용 주요 키워드 추출"""
    clean = re.sub(r"\[.*?\]", " ", str(name))
    clean = re.sub(r"[^\w\s]", " ", clean)
    words = [w.strip() for w in clean.split() if len(w.strip()) >= 2]
    return words[:4]


def find_and_capture_first_match(candidates_to_try: list, output_path: str):
    """
    골드박스 페이지 접속 후 모든 Product/Item ID 및 outerHTML 스캔 방식으로
    매칭되는 상품 카드를 찾아 스크린샷 저장.
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

            # 리뉴얼 배너 클릭 처리
            try:
                btn = page.locator("text='더욱 새로워진 골드박스 살펴보기'")
                if btn.is_visible(timeout=2000):
                    btn.click()
                    page.wait_for_timeout(2000)
            except Exception:
                pass

            print(f"[디버그] 페이지 제목: {page.title()}")
            print(f"[디버그] 최종 URL: {page.url}")

            # 페이지 전체를 천천히 스크롤하여 지연 로딩(Lazy Loading) 요소 동적 활성화
            for _ in range(12):
                page.evaluate("window.scrollBy(0, 800)")
                page.wait_for_timeout(600)

            # 모든 상품 관련 링크 요소 탐색 (/vp/, products, itemId, productId 포함)
            product_links = page.query_selector_all(
                "a[href*='/vp/'], a[href*='products'], a[href*='itemId'], a[href*='productId']"
            )

            cards = []
            for link in product_links:
                try:
                    # 링크를 포함하는 가장 상위의 카드 컨테이너 엘리먼트 추출
                    card_parent = link.evaluate_handle("""
                        el => {
                            let p = el;
                            for (let i = 0; i < 6; i++) {
                                if (!p.parentElement) break;
                                p = p.parentElement;
                                const cls = (p.className && typeof p.className === 'string') ? p.className : '';
                                const tag = p.tagName;
                                if (tag === 'LI' || cls.includes('Product') || cls.includes('card') || cls.includes('item') || cls.includes('unit') || cls.includes('grid')) {
                                    return p;
                                }
                            }
                            return el;
                        }
                    """).as_element()
                    if card_parent and card_parent not in cards:
                        cards.append(card_parent)
                except Exception:
                    continue

            # Fallback: 개별 카드를 찾지 못한 경우 일반 리스트/디브 탐색
            if not cards:
                cards = page.query_selector_all("li, div[class*='Product'], div[class*='card'], div[class*='item']")

            print(f"[스크린샷] 화면에서 상품 카드 {len(cards)}개 탐색됨")

            # 각 카드의 innerText 및 outerHTML(속성, URL, alt 텍스트 전체) 데이터 수집
            card_items = []
            for card in cards:
                try:
                    outer_html = card.evaluate("el => el.outerHTML")
                    inner_text = card.inner_text()
                    card_items.append((card, inner_text, outer_html))
                except Exception:
                    continue

            # 후보 매칭 수행
            for price, name, candidate in candidates_to_try:
                target_ids = _deep_extract_ids((price, name, candidate))
                keywords = _clean_keywords(name)
                price_num_str = str(int(price))
                price_formatted = f"{int(price):,}"

                print(f"[스크린샷] 매칭 시도 -> ID 후보군: {target_ids} / 가격: {price_formatted}원 / 키워드: {keywords}")

                for card, text, html in card_items:
                    is_matched = False

                    # [우선순위 1] ID 매칭 (Product ID / Item ID / VendorItem ID 중 하나라도 html에 포함)
                    if target_ids:
                        for tid in target_ids:
                            if tid in html:
                                is_matched = True
                                print(f"[스크린샷] ✅ 고유 ID({tid}) outerHTML 매칭 성공!")
                                break

                    # [우선순위 2] 가격 + 핵심 키워드 매칭
                    if not is_matched and (price_num_str in html or price_formatted in text):
                        matched_kws = [kw for kw in keywords if kw in html or kw in text]
                        if len(matched_kws) >= 1:
                            is_matched = True
                            print(f"[스크린샷] ✅ 가격({price_formatted}) + 키워드({matched_kws}) 매칭 성공!")

                    # [우선순위 3] 주요 키워드 조합 매칭 (2개 이상 일치)
                    if not is_matched and len(keywords) >= 2:
                        matched_kws = [kw for kw in keywords if kw in html or kw in text]
                        if len(matched_kws) >= 2:
                            is_matched = True
                            print(f"[스크린샷] ✅ 키워드 조합({matched_kws}) 매칭 성공!")

                    if is_matched:
                        card.scroll_into_view_if_needed()
                        page.wait_for_timeout(500)
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
