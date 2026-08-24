# -*- coding: utf-8 -*-
"""
쿠팡 골드박스 페이지에서 특정 상품 카드를 실제 브라우저로 열어
화면 그대로 스크린샷으로 캡처하는 모듈 (개선 완성본).
"""

import re
import math
import time
from playwright.sync_api import sync_playwright

# 쿠팡 최신 골드박스 기획전 Direct URL 및 Fallback URL
GOLDBOX_URL = "https://pages.coupang.com/p/121237?sourceType=oms_goldbox"
FALLBACK_GOLDBOX_URL = "https://www.coupang.com/np/goldbox"

DISCOUNT_WITH_LABEL_PATTERN = re.compile(r"(\d+)\s*%\s*할인")
BARE_PERCENT_PATTERN = re.compile(r"^(\d+)\s*%$")
TWO_PRICE_PATTERN = re.compile(r"([\d,]+)\s*원[^0-9]{0,10}?([\d,]+)\s*원")
SKIP_LINE_PATTERN = re.compile(r"원|%|로켓|남음|배송|판매|쿠폰|무료")
HANGUL_PATTERN = re.compile(r"[가-힣]")


def _normalize_text(text: str) -> str:
    """공백 및 특수문자를 제거하여 비교용 텍스트로 정규화"""
    if not text:
        return ""
    return re.sub(r"[^\w\d가-힣]", "", text)


def _compute_discount_from_prices(text: str):
    """두 가격(원) 패턴을 찾아 할인율을 계산"""
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
    """카드 텍스트에서 상품명과 할인율을 파싱"""
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


def extract_product_id(url: str) -> str:
    """URL에서 쿠팡 상품 고유 ID(ProductID) 추출"""
    if not url:
        return ""
    m = re.search(r"products/(\d+)", url)
    if m:
        return m.group(1)
    return ""


def find_and_capture_first_match(candidates_to_try: list, output_path: str):
    """
    candidates_to_try = [(price, name, candidate_dict), ...]
    candidate_dict 내 'url' 키가 있으면 상품 ID 매칭에 활용함.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            channel="chromium",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
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
            try:
                page.goto(GOLDBOX_URL, wait_until="domcontentloaded", timeout=60000)
            except Exception as goto_err:
                print(f"[스크린샷] 기본 URL 접속 지연으로 폴백 URL 시도: {FALLBACK_GOLDBOX_URL} ({goto_err})")
                page.goto(FALLBACK_GOLDBOX_URL, wait_until="domcontentloaded", timeout=60000)

            page.wait_for_timeout(3000)

            print(f"[디버그] 페이지 제목: {page.title()}")
            print(f"[디버그] 최종 URL: {page.url}")

            # 1. 스크롤을 충분히 내려 지연 로딩(Lazy Loading) 카드 완벽 렌더링
            print("[스크린샷] 페이지 스크롤 및 상품 로딩 중...")
            for _ in range(15):
                page.mouse.wheel(0, 1200)
                page.wait_for_timeout(600)

            page.wait_for_timeout(2000)

            # 2. 광범위 상품 링크 탐색
            link_elements = page.query_selector_all("a[href*='/products/'], a[href*='itemId']")
            print(f"[스크린샷] 발견된 상품 관련 링크: {len(link_elements)}개")

            # 3. 각 링크의 실제 렌더링 크기 기반 상위 카드 컨테이너 감지
            cards = []
            for link in link_elements:
                try:
                    parent = link.evaluate_handle(
                        """el => {
                            let p = el;
                            for (let i = 0; i < 6; i++) {
                                if (!p.parentElement || p.tagName === 'BODY') break;
                                p = p.parentElement;
                                const rect = p.getBoundingClientRect();
                                // 카드 적정 크기 조건 (가로 120px 이상, 세로 150px 이상, 전체 페이지 이하)
                                if (rect.width >= 120 && rect.height >= 150 && rect.width < 1200) {
                                    return p;
                                }
                            }
                            return el;
                        }"""
                    ).as_element()

                    if parent and parent not in cards:
                        cards.append(parent)
                except Exception:
                    continue

            # 클래스 기반 다이렉트 탐색 보완 (기존/신규 디자인 호환)
            direct_cards = page.query_selector_all(
                "li.baby-product, .instant-n-item, div[class*='ProductItem'], [class*='ProductCard'], [class*='product-item']"
            )
            for dc in direct_cards:
                if dc not in cards:
                    cards.append(dc)

            print(f"[스크린샷] 화면에서 최종 추출된 카드: {len(cards)}개")

            # 4. 카드별 텍스트 및 링크 캐싱
            card_info_list = []
            for card in cards:
                try:
                    text = card.inner_text()
                    link_elem = card.query_selector("a[href*='/products/'], a[href*='itemId']")
                    href = link_elem.get_attribute("href") if link_elem else ""
                    if text and text.strip():
                        card_info_list.append((card, text, href))
                except Exception:
                    continue

            # 5. 후보군 상품 탐색 및 매칭
            for price, name, candidate in candidates_to_try:
                price_num = int(price)
                price_str = f"{price_num:,}"  # 예: "37,720"
                raw_price_str = str(price_num)  # 예: "37720"

                # 검색 키워드 정제 (대괄호/소괄호 패턴 제거)
                clean_name = re.sub(r"\[.*?\]|\(.*?\)", "", name).strip()
                name_fragment = clean_name[:6] if clean_name else name[:6]
                norm_name_fragment = _normalize_text(name_fragment)

                print(f"[스크린샷] 매칭 시도: {price_str}원 / 키워드 '{name_fragment}' (원본: {name})")

                # Target URL에서 상품 ID 추출
                target_url = candidate.get("url", "") if isinstance(candidate, dict) and candidate else ""
                target_pid = extract_product_id(target_url)

                for card, text, href in card_info_list:
                    norm_text = _normalize_text(text)
                    card_pid = extract_product_id(href)

                    # 1순위: URL 상품 ID 기반 정밀 매칭
                    pid_matched = bool(target_pid and card_pid and target_pid == card_pid)

                    # 2순위: 가격(콤마 포함/미포함) + 상품명 키워드 매칭
                    price_matched = (price_str in text) or (raw_price_str in norm_text)
                    name_matched = bool(norm_name_fragment and norm_name_fragment in norm_text)
                    text_matched = price_matched and name_matched

                    if pid_matched or text_matched:
                        match_type = "상품 ID" if pid_matched else "가격+키워드"
                        print(f"[스크린샷] 매칭 성공! (매칭 방식: {match_type})")

                        # 해당 요소를 화면 중앙으로 스크롤 후 이미지 로딩 대기
                        card.scroll_into_view_if_needed()
                        page.wait_for_timeout(600)

                        card.screenshot(path=output_path)
                        full_name, discount_rate = _parse_card_text(text, name)
                        print(f"[스크린샷] 캡처 저장 완료 ({output_path}) | 상품명: {full_name} | 할인율: {discount_rate}%")
                        return candidate, full_name, discount_rate

            print("[스크린샷] 시도한 후보 중 화면과 일치하는 카드를 찾지 못함")
            return None, None, None

        except Exception as e:
            print(f"[스크린샷] 오류 발생: {e}")
            return None, None, None
        finally:
            browser.close()


def capture_goldbox_card_screenshot(target_price: int, target_name: str, output_path: str):
    """단일 상품 스크린샷 캡처용 편의 함수"""
    matched, full_name, discount_rate = find_and_capture_first_match(
        [(target_price, target_name, None)], output_path
    )
    return matched is not None, full_name or target_name, discount_rate


if __name__ == "__main__":
    # 실행 테스트 예시
    test_candidates = [
        (
            37720,
            "제주삼다수 그린 무라벨",
            {"url": "https://www.coupang.com/vp/products/7666070794?itemId=23369380750&vendorItemId=86949016528"}
        ),
        (
            17900,
            "[로켓프레시] 한끼통살 닭가슴살 볼 5종 x 2개 믹스세트 (냉동)",
            {"url": "https://www.coupang.com/vp/products/8499354077?itemId=24602479280&vendorItemId=91613937910"}
        ),
    ]

    result, name, discount = find_and_capture_first_match(test_candidates, "result_card.png")
    print(f"\n최종 결과 -> 성공여부: {result is not None}, 이름: {name}, 할인율: {discount}%")
