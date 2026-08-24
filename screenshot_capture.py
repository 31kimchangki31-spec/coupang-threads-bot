# -*- coding: utf-8 -*-
"""
Playwright를 사용하여 골드박스 페이지에서 대상 상품 카드를 찾고 스크린샷을 캡처하는 모듈.
(쿠팡 Access Denied 우회 및 리뉴얼된 이벤트 페이지 DOM 탐색 지원)
"""
import re
import time
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright


def _clean_keywords(name: str) -> list:
    """상품명에서 공백 및 특수문자를 제거하고 의미 있는 단어 단위로 추출한다."""
    cleaned = re.sub(r"[^\w\s]", " ", name)
    tokens = [t.strip() for t in cleaned.split() if len(t.strip()) > 1]
    return tokens


def _deep_extract_ids(candidate_tuple: tuple) -> list:
    """상품 정보 및 URL 쿼리스트링에서 고유 ID(itemId, vendorItemId, pageKey)를 추출한다."""
    price, name, cand = candidate_tuple
    raw_url = cand.get("productUrl", "")
    parsed = urlparse(raw_url)
    params = parse_qs(parsed.query)

    ids = []
    for key in ["itemId", "vendorItemId", "pageKey"]:
        val = params.get(key, [None])[0]
        if val:
            ids.append(str(val))
    return ids


def find_and_capture_first_match(ready_candidates: list, screenshot_path: str):
    """
    ready_candidates: [(price, name, candidate_dict), ...]
    골드박스 페이지에 접속하여 브랜드 키워드가 포함된 정확한 상품 카드를 찾아 스크린샷을 저장한다.
    """
    goldbox_url = "https://www.coupang.com/np/goldbox"

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-infobars",
                "--window-size=1280,1024",
            ],
        )

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 1024},
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            extra_http_headers={
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            },
        )

        page = context.new_page()

        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        print(f"[스크린샷] 골드박스 페이지 접속 시도: {goldbox_url}")
        try:
            page.goto(goldbox_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)
        except Exception as e:
            print(f"[스크린샷] 페이지 접속 실패: {e}")
            browser.close()
            return None, None, None

        print(f"[디버그] 페이지 제목: {page.title()}")
        print(f"[디버그] 최종 URL: {page.url}")

        if "Access Denied" in page.title():
            print("[에러] 여전히 쿠팡 봇 차단에 걸렸습니다.")
            browser.close()
            return None, None, None

        # 가상 스크롤 로딩을 통해 동적 엘리먼트 렌더링 유도
        for _ in range(6):
            page.mouse.wheel(0, 800)
            time.sleep(0.5)

        # 리뉴얼된 골드박스 및 쿠팡 프로모션 페이지 범용 CSS 선택자
        selectors = [
            "a[href*='/products/']",
            "a[href*='/vp/products/']",
            "li.goldbox-product",
            "div.goldbox-product",
            ".product-card",
            "[data-product-id]",
            "div[class*='Product']",
            "div[class*='product']",
            "div[class*='Deal']",
            "div[class*='deal']",
            "li[class*='item']",
        ]
        
        combined_selector = ", ".join(selectors)
        card_elements = page.query_selector_all(combined_selector)

        # 구체적인 태그 탐색 실패 시 렌더링된 모든 링크/아이템을 후보군으로 확보
        if not card_elements:
            card_elements = page.query_selector_all("a, li, div")

        print(f"[스크린샷] 화면에서 상품 카드 {len(card_elements)}개 탐색됨")

        cards_data = []
        for card in card_elements:
            try:
                text = card.inner_text()
                # 텍스트가 없거나 지나치게 짧은 보일러플레이트 영역 제외
                if not text or len(text.strip()) < 5:
                    continue
                html = card.inner_html()
                cards_data.append((card, text, html))
            except Exception:
                continue

        # 후보 목록 순서대로 매칭 검증
        for price, name, candidate in ready_candidates:
            target_ids = _deep_extract_ids((price, name, candidate))
            keywords = _clean_keywords(name)

            brand_keyword = keywords[0] if keywords else ""
            price_num_str = str(int(price)) if price else ""
            price_formatted = f"{int(price):,}" if price else ""

            print(
                f"[스크린샷] 매칭 시도 -> 브랜드 필수 키워드: '{brand_keyword}' / "
                f"ID 후보군: {target_ids} / 가격: {price_formatted}원"
            )

            for card, text, html in cards_data:
                is_matched = False

                # 1. 고유 ID 일치 (최우선)
                if target_ids:
                    for tid in target_ids:
                        if tid in html or tid in text:
                            is_matched = True
                            print(f"[스크린샷] ✅ 고유 ID({tid}) 매칭 성공!")
                            break

                # 2. 브랜드 필수 키워드 포함 검증
                if not is_matched and brand_keyword and (brand_keyword in html or brand_keyword in text):
                    if price_num_str and (price_num_str in html or price_formatted in text):
                        is_matched = True
                        print(f"[스크린샷] ✅ 브랜드('{brand_keyword}') + 가격({price_formatted}) 매칭 성공!")
                    else:
                        matched_sub_kws = [kw for kw in keywords[1:4] if kw in html or kw in text]
                        if matched_sub_kws:
                            is_matched = True
                            print(f"[스크린샷] ✅ 브랜드('{brand_keyword}') + 서브키워드({matched_sub_kws}) 매칭 성공!")

                if is_matched:
                    card.scroll_into_view_if_needed()
                    time.sleep(0.5)

                    card.screenshot(path=screenshot_path)

                    lines = [l.strip() for l in text.split("\n") if l.strip()]
                    full_name = name
                    for l in lines:
                        if brand_keyword in l and len(l) > 5:
                            full_name = l
                            break

                    parsed_discount = None
                    discount_match = re.search(r"(\d+)%", text)
                    if discount_match:
                        parsed_discount = float(discount_match.group(1))

                    print(f"[스크린샷] 캡처 완료: {full_name} / 할인율: {parsed_discount}")
                    browser.close()
                    return candidate, full_name, parsed_discount

        browser.close()
        return None, None, None
