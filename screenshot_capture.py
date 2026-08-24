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


def _clean_name_for_matching(name: str) -> str:
    """'[로켓프레시]' 등 대괄호 태그 제거 후 순수 상품명에서 키워드 추출"""
    clean = re.sub(r"\[.*?\]", "", name).strip()
    return clean[:8]


def _extract_product_id(url: str) -> str:
    """URL에서 /products/123456 형태의 고유 ID 추출"""
    m = re.search(r"/products/(\d+)", url) if url else None
    return m.group(1) if m else ""


def find_and_capture_first_match(candidates_to_try: list, output_path: str):
    """
    골드박스 페이지를 접속 후 5초 대기하며, Product ID 및 태그 정제 키워드로
    매칭되는 상품 카드를 찾아 스크린샷으로 저장한다.
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

            # 1. 접속 후 상품 렌더링을 위해 5초 대기
            page.wait_for_timeout(5000)

            # 2. 리뉴얼 안내 버튼이 있을 경우 클릭
            try:
                btn = page.locator("text='더욱 새로워진 골드박스 살펴보기'")
                if btn.is_visible(timeout=2000):
                    btn.click()
                    page.wait_for_timeout(2000)
            except Exception:
                pass

            print(f"[디버그] 페이지 제목: {page.title()}")
            print(f"[디버그] 최종 URL: {page.url}")

            # 3. 반복 스크롤하여 상품 로딩
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

            # 4. 각 카드로 스크롤 이동 후 텍스트/HTML 추출 (지연 로딩 방지)
            card_items = []
            for card in cards:
                try:
                    card.scroll_into_view_if_needed()
                    page.wait_for_timeout(100)
                    card_items.append((
                        card,
                        card.inner_text(),
                        card.inner_html()
                    ))
                except Exception:
                    continue

            # 5. 후보 매칭 수행
            for price, name, candidate in candidates_to_try:
                candidate_url = candidate.get("정리된 URL") or candidate.get("url") or ""
                product_id = _extract_product_id(candidate_url)
                
                price_str = f"{int(price):,}"
                clean_name_fragment = _clean_name_for_matching(name)

                print(f"[스크린샷] 매칭 시도 -> ID: {product_id} / 가격: {price_str}원 / 키워드: '{clean_name_fragment}'")

                for card, text, html in card_items:
                    is_matched = False

                    # [우선순위 1] URL의 Product ID로 매칭
                    if product_id and product_id in html:
                        is_matched = True
                        print(f"[스크린샷] ✅ Product ID({product_id}) 매칭 성공")

                    # [우선순위 2] 가격 + [로켓프레시] 제거된 키워드로 매칭
                    elif price_str in text and clean_name_fragment in text:
                        is_matched = True
                        print(f"[스크린샷] ✅ 텍스트(가격+키워드) 매칭 성공")

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
