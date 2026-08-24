# -*- coding: utf-8 -*-
"""
쿠팡 골드박스 페이지(iframe/Shadow DOM 구조)에서 특정 상품 카드를 
실시간 탐색/스크롤 방식으로 검색하여 스크린샷으로 캡처하는 모듈 (완전판).
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


def extract_product_id(url: str) -> str:
    """URL에서 쿠팡 상품 고유 ID(ProductID) 추출"""
    if not url:
        return ""
    m = re.search(r"products/(\d+)", url) or re.search(r"itemId=(\d+)", url)
    if m:
        return m.group(1)
    return ""


def find_and_capture_first_match(candidates_to_try: list, output_path: str):
    """
    [Iframe + Realtime Scroll 탐색 방식]
    모든 프레임(Iframe 포함)을 탐색하며 상품 ID(ProductID) 및 상품명 키워드로 매칭합니다.
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
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        try:
            print(f"[스크린샷] 골드박스 페이지 접속 시도: {GOLDBOX_URL}")
            try:
                page.goto(GOLDBOX_URL, wait_until="domcontentloaded", timeout=60000)
            except Exception as goto_err:
                print(f"[스크린샷] 폴백 URL 접근: {FALLBACK_GOLDBOX_URL} ({goto_err})")
                page.goto(FALLBACK_GOLDBOX_URL, wait_until="domcontentloaded", timeout=60000)

            page.wait_for_timeout(3000)
            print(f"[디버그] 접속 페이지 제목: {page.title()}")

            # 매칭 후보군 정보 전처리
            prepared_candidates = []
            for price, name, candidate in candidates_to_try:
                price_num = int(price) if price else 0
                price_str = f"{price_num:,}" if price_num > 0 else ""
                raw_price_str = str(price_num) if price_num > 0 else ""
                
                # 특수문자 제거 후 핵심 상품명 키워드 (4글자 추출)
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

            processed_hrefs = set()

            # --- [실시간 Iframe / DOM 감지 및 스크롤 루프 (35회)] ---
            for scroll_step in range(35):
                # 페이지 내 모든 프레임(Main + Iframe) 수집
                frames_to_search = page.frames

                for frame_idx, frame in enumerate(frames_to_search):
                    try:
                        # Playwright Locator로 링크 탐색 (Iframe/Shadow DOM 지원)
                        link_locators = frame.locator("a[href*='products/'], a[href*='itemId']").all()
                        if not link_locators:
                            continue

                        for link_loc in link_locators:
                            try:
                                if not link_loc.is_visible():
                                    continue

                                href = link_loc.get_attribute("href") or ""
                                if href in processed_hrefs:
                                    continue

                                # 링크의 상위 카드 컨테이너 찾기
                                card_loc = link_loc.locator("xpath=ancestor::*[self::li or contains(@class, 'item') or contains(@class, 'card') or contains(@class, 'Product')][1]")
                                if card_loc.count() == 0:
                                    card_loc = link_loc  # 컨테이너 미발견 시 링크 자체 선택

                                text = card_loc.inner_text()
                                if not text or not text.strip():
                                    continue

                                norm_text = _normalize_text(text)
                                card_pid = extract_product_id(href)

                                for cand in prepared_candidates:
                                    # 1순위: URL 상품 고유 ID(ProductID) 완전 일치
                                    pid_matched = bool(cand["target_pid"] and card_pid and cand["target_pid"] == card_pid)

                                    # 2순위: 상품명 키워드 매칭 (가격은 쿠폰/변동 가능성이 있어 보조 조건)
                                    name_matched = bool(cand["norm_name_fragment"] and cand["norm_name_fragment"] in norm_text)
                                    price_matched = (cand["price_str"] in text) or (cand["raw_price_str"] in norm_text) if cand["price_str"] else True
                                    
                                    text_matched = name_matched and price_matched

                                    if pid_matched or text_matched:
                                        match_type = "상품 ID" if pid_matched else "상품명 키워드"
                                        print(f"[스크린샷] 매칭 성공! (단계 {scroll_step+1}, 방식: {match_type}) -> 키워드 '{cand['orig_name_fragment']}'")

                                        # 요소를 화면 중앙으로 스크롤 후 이미지 렌더링 대기
                                        card_loc.scroll_into_view_if_needed()
                                        page.wait_for_timeout(1200)

                                        # 스크린샷 저장
                                        card_loc.screenshot(path=output_path)

                                        full_name, discount_rate = _parse_card_text(text, cand["fallback_name"])
                                        print(f"[스크린샷] 캡처 완료 ({output_path}) | 상품명: {full_name} | 할인율: {discount_rate}%")
                                        return cand["candidate_data"], full_name, discount_rate

                                if href:
                                    processed_hrefs.add(href)

                            except Exception:
                                continue
                    except Exception:
                        continue

                # 화면 탐색 후 스크롤 내림
                page.mouse.wheel(0, 700)
                page.wait_for_timeout(1000)

            print("[스크린샷] 전체 스크롤 탐색 완료 후에도 일치하는 카드를 찾지 못함")
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
    # 테스트 실행
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
