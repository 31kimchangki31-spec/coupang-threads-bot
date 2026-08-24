# -*- coding: utf-8 -*-
"""
쿠팡 골드박스 페이지 캡처 모듈 (봇 감지 우회 & 범용 DOM 텍스트 탐색 적용 풀버전)
"""

import re
import math
import time
from playwright.sync_api import sync_playwright

# 쿠팡 골드박스 URL
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
    """두 가격 패턴을 추출하여 할인율 계산"""
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
    """카드 내 텍스트에서 전체 상품명과 할인율 추출"""
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


def extract_product_id(text: str) -> str:
    """URL 또는 속성 텍스트에서 상품 ID 추출"""
    if not text:
        return ""
    m = re.search(r"products/(\d+)", text) or re.search(r"itemId=(\d+)", text) or re.search(r"(\d{7,12})", text)
    if m:
        return m.group(1)
    return ""


def find_and_capture_first_match(candidates_to_try: list, output_path: str):
    """
    [Anti-Bot 우회 + Direct DOM Text 탐색]
    쿠팡의 봇 탐지를 방지하는 스텔스 설정과 함께,
    a 태그 외에도 화면상에 가격+상품명이 표시된 최하위 카드 요소를 탐색합니다.
    """
    with sync_playwright() as p:
        # 봇 감지 방지용 Chromium 옵션 강화
        browser = p.chromium.launch(
            headless=True,
            channel="chromium",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-web-security",
                "--window-size=1920,1080",
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

        # 브라우저 위장 스크립트 주입
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.navigator.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'languages', {get: () => ['ko-KR', 'ko', 'en-US', 'en']});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
        """)

        try:
            print(f"[스크린샷] 골드박스 페이지 접속 시도: {GOLDBOX_URL}")
            try:
                page.goto(GOLDBOX_URL, wait_until="networkidle", timeout=60000)
            except Exception as goto_err:
                print(f"[스크린샷] 기본 접속 지연 -> 폴백 URL 접속: {FALLBACK_GOLDBOX_URL}")
                page.goto(FALLBACK_GOLDBOX_URL, wait_until="domcontentloaded", timeout=60000)

            page.wait_for_timeout(3000)
            print(f"[디버그] 접속 성공 페이지 제목: '{page.title()}'")

            # 매칭 후보군 키워드 전처리
            prepared_candidates = []
            for price, name, candidate in candidates_to_try:
                price_num = int(price) if price else 0
                price_str = f"{price_num:,}" if price_num > 0 else ""
                raw_price_str = str(price_num) if price_num > 0 else ""

                clean_name = re.sub(r"\[.*?\]|\(.*?\)", "", name).strip()
                name_fragment = clean_name[:4] if clean_name else name[:4]

                target_url = candidate.get("url", "") if isinstance(candidate, dict) and candidate else ""
                target_pid = extract_product_id(target_url)

                prepared_candidates.append({
                    "price_str": price_str,
                    "raw_price_str": raw_price_str,
                    "norm_name_fragment": _normalize_text(name_fragment),
                    "orig_name_fragment": name_fragment,
                    "target_pid": target_pid,
                    "fallback_name": name,
                    "candidate_data": candidate,
                })

            processed_elements = set()

            # --- [실시간 스크롤 & DOM 탐색 (최대 25회)] ---
            for scroll_step in range(25):
                print(f"[스크린샷] 실시간 탐색 단계 {scroll_step + 1}/25")

                for frame in page.frames:
                    try:
                        # 1. 태그 종류에 상관없이 가격 텍스트가 포함된 모든 요소 검색
                        for cand in prepared_candidates:
                            if not cand["price_str"]:
                                continue

                            # 가격 텍스트(예: "37,720")를 포함하는 모든 Locator 추출
                            price_locators = frame.locator(f"text={cand['price_str']}").all()

                            for price_loc in price_locators:
                                try:
                                    if not price_loc.is_visible():
                                        continue

                                    # 가격 표시 요소의 상위 카드 컨테이너(가장 가까운 div/li/a) 추적
                                    card_loc = price_loc.locator("xpath=ancestor::*[self::li or self::a or contains(@class, 'item') or contains(@class, 'card') or contains(@class, 'Product') or contains(@class, 'unit')][1]")
                                    
                                    if card_loc.count() == 0:
                                        card_loc = price_loc.locator("xpath=ancestor::div[contains(@style, 'width') or contains(@class, 'div')][2]")

                                    if card_loc.count() == 0:
                                        continue

                                    text = card_loc.inner_text()
                                    norm_text = _normalize_text(text)

                                    # 중복 처리 방지
                                    if norm_text in processed_elements:
                                        continue

                                    # 상품명 키워드 매칭 검사
                                    name_matched = cand["norm_name_fragment"] and (cand["norm_name_fragment"] in norm_text)
                                    card_pid = extract_product_id(text)
                                    pid_matched = bool(cand["target_pid"] and card_pid and cand["target_pid"] in text)

                                    if name_matched or pid_matched:
                                        match_reason = "상품 ID" if pid_matched else "가격 + 키워드"
                                        print(f"[스크린샷] ★ 매칭 성공! ({match_reason}) -> 키워드: '{cand['orig_name_fragment']}' / 가격: {cand['price_str']}원")

                                        # 카드로 스크롤 후 이미지 렌더링 대기
                                        card_loc.scroll_into_view_if_needed()
                                        page.wait_for_timeout(1000)

                                        # 스크린샷 캡처
                                        card_loc.screenshot(path=output_path)

                                        full_name, discount_rate = _parse_card_text(text, cand["fallback_name"])
                                        print(f"[스크린샷] 캡처 완료 -> {output_path} (상품명: {full_name}, 할인율: {discount_rate}%)")
                                        return cand["candidate_data"], full_name, discount_rate

                                    processed_elements.add(norm_text)

                                except Exception:
                                    continue
                    except Exception:
                        continue

                # 마우스 휠 스크롤 후 콘텐츠 추가 로딩 대기
                page.mouse.wheel(0, 650)
                page.wait_for_timeout(1000)

            # 탐색 실패 시 원인 진단을 위한 현재 화면 스크린샷 저장
            print("[스크린샷] 매칭 실패 -> 원인 진단용 화면 'debug_page.png' 저장 중...")
            page.screenshot(path="debug_page.png", full_page=True)
            print("[스크린샷] debug_page.png 파일이 생성되었습니다. 브라우저에 표시된 화면을 확인하세요.")
            return None, None, None

        except Exception as e:
            print(f"[스크린샷] 실행 오류: {e}")
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
    print(f"\n[최종 결과] 성공 여부: {result is not None} | 상품명: {name} | 할인율: {discount}%")
