# -*- coding: utf-8 -*-
"""
Playwright를 사용하여 골드박스 페이지에서 대상 상품 카드를 찾고 스크린샷을 캡처하는 모듈.
(쿠팡 Access Denied 봇 차단 우회 기법 적용)
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
        # 1. 자동화 브라우저 감지 플래그 제거
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

        # 2. 실제 일반 한국 사용자와 동일한 헤더 및 컨텍스트 설정
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

        # 3. navigator.webdriver 속성을 숨겨 봇 감지 회피
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
            print("[에러] 여전히 쿠팡 봇 차단에 걸렸습니다. 잠시 후 재시도해야 합니다.")
            browser.close()
            return None, None, None

        # 가상 스크롤 로딩을 위해 하단 스크롤 수행
        for _ in range(5):
            page.mouse.wheel(0, 1000)
            time.sleep(0.5)

        # 골드박스 상품 카드 요소 수집
        card_elements = page.query_selector_all(
            "li.goldbox-product, div.goldbox-product, a.goldbox-product, "
            ".product-card, [data-product-id], ul.products > li, .deals-item"
        )
        print(f"[스크린샷] 화면에서 상품 카드 {len(card_elements)}개 탐색됨")

        cards_data = []
        for card in card_elements:
            try:
                text = card.inner_text()
                html = card.inner_html()
                cards_data.append((card, text, html))
            except Exception:
                continue

        # 후보 목록 순서대로 매칭 검증
        for price, name, candidate in ready_candidates:
            target_ids = _deep_extract_ids((price, name, candidate))
            keywords = _clean_keywords(name)

            # 첫 번째 키워드를 필수 브랜드/상호 키워드로 지정
            brand_keyword = keywords[0] if keywords else ""
            price_num_str = str(int(price)) if price else ""
            price_formatted = f"{int(price):,}" if price else ""

            print(
                f"[스크린샷] 매칭 시도 -> 브랜드 필수 키워드: '{brand_keyword}' / "
                f"ID 후보군: {target_ids} / 가격: {price_formatted}원"
            )

            for card, text, html in cards_data:
                is_matched = False

                # 1. 고유 ID 일치 (최우선 정확도)
                if target_ids:
                    for tid in target_ids:
                        if tid in html:
                            is_matched = True
                            print(f"[스크린샷] ✅ 고유 ID({tid}) 매칭 성공!")
                            break

                # 2. 브랜드 키워드 필수 검증
                if not is_matched and brand_keyword and (brand_keyword in html or brand_keyword in text):
                    # 가격 일치 확인
                    if price_num_str and (price_num_str in html or price_formatted in text):
                        is_matched = True
                        print(f"[스크린샷] ✅ 브랜드('{brand_keyword}') + 가격({price_formatted}) 매칭 성공!")
                    else:
                        # 브랜드명이 포함된 경우에 한해 서브 키워드 연관성 확인
                        matched_sub_kws = [kw for kw in keywords[1:4] if kw in html or kw in text]
                        if matched_sub_kws:
                            is_matched = True
                            print(f"[스크린샷] ✅ 브랜드('{brand_keyword}') + 서브키워드({matched_sub_kws}) 매칭 성공!")

                if is_matched:
                    # 캡처를 위해 시야 위치 이동
                    card.scroll_into_view_if_needed()
                    time.sleep(0.5)

                    card.screenshot(path=screenshot_path)

                    # 카드 내 실제 텍스트에서 전체 상품명 파싱
                    lines = [l.strip() for l in text.split("\n") if l.strip()]
                    full_name = name
                    for l in lines:
                        if brand_keyword in l and len(l) > 5:
                            full_name = l
                            break

                    # 할인율 파싱
                    parsed_discount = None
                    discount_match = re.search(r"(\d+)%", text)
                    if discount_match:
                        parsed_discount = float(discount_match.group(1))

                    print(f"[스크린샷] 캡처 완료: {full_name} / 할인율: {parsed_discount}")
                    browser.close()
                    return candidate, full_name, parsed_discount

        browser.close()
        return None, None, None
