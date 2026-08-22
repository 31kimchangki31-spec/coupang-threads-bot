# -*- coding: utf-8 -*-
"""
쿠팡 골드박스 페이지에서 특정 상품 카드를 실제 브라우저로 열어
화면 그대로 스크린샷으로 캡처하는 모듈.
API가 안 주는 정가/할인율/전체 상품명이 카드 이미지 안에 이미 다 담겨있어서,
텍스트 파싱 없이 이미지 하나로 해결한다.
"""
from playwright.sync_api import sync_playwright

GOLDBOX_URL = "https://www.coupang.com/np/goldbox"


def capture_goldbox_card_screenshot(target_price: int, target_name: str, output_path: str) -> bool:
    """
    골드박스 페이지에서 target_price(가격)와 target_name(상품명 일부)이 둘 다 일치하는
    카드를 찾아 스크린샷으로 저장한다. 성공하면 True, 못 찾으면 False.
    """
    price_str = f"{int(target_price):,}"
    # 상품명이 너무 길면 앞부분 10자 정도만으로 느슨하게 매칭 (사소한 표기 차이 대비)
    name_fragment = target_name.strip()[:10]

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
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
            locale="ko-KR",
            timezone_id="Asia/Seoul",
        )
        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        found = False
        try:
            print(f"[스크린샷] 골드박스 페이지 접속 시도: {GOLDBOX_URL}")
            page.goto(GOLDBOX_URL, timeout=60000)
            page.wait_for_timeout(4000)
            page.mouse.wheel(0, 1000)
            page.wait_for_timeout(3000)

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

            print(f"[스크린샷] 후보 카드 {len(cards)}개 탐색됨. 가격/이름 매칭 시도: {price_str}원 / '{name_fragment}'")

            for card in cards:
                try:
                    text = card.inner_text()
                except Exception:
                    continue
                if price_str in text and name_fragment in text:
                    card.screenshot(path=output_path)
                    print(f"[스크린샷] 매칭 성공, 저장: {output_path}")
                    found = True
                    break

            if not found:
                print("[스크린샷] 일치하는 카드를 찾지 못함 (골드박스 페이지 순서가 API 조회 시점과 달라졌을 수 있음)")

        except Exception as e:
            print(f"[스크린샷] 실패: {e}")
        finally:
            browser.close()

    return found
