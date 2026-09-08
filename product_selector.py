# -*- coding: utf-8 -*-
"""
골드박스 목록에서 게시할 상품 하나를 고르는 모듈.

선정 우선순위:
  1) picks.txt 에 상품ID/키워드를 적어두면 그것부터 (수동 지정)
  2) 없으면 필터 통과한 것 중 점수 상위 (자동 선정)

필터/가중치는 selector_config.json 으로 조정한다.
"""
import json
import os
import re

def normalize_name(name: str) -> str:
    """
    상품명 비교용 키. 대괄호 표기와 공백/기호를 걷어내고 소문자화한다.
    상품ID가 달라도 사실상 같은 상품이면 중복으로 걸러내기 위한 것.
    """
    if not name:
        return ""
    text = re.sub(r"\[[^\]]*\]", " ", name)      # [행복미트] 같은 판매자 표기 제거
    text = re.sub(r"[^0-9A-Za-z가-힣]", "", text)  # 공백/기호 제거
    return text.lower()


PICKS_FILE = "picks.txt"
CONFIG_FILE = "selector_config.json"

DEFAULT_CONFIG = {
    "min_price": 5000,
    "max_price": 150000,
    "rocket_only": False,
    "exclude_keywords": ["성인", "담배", "의약품", "렌즈", "주식", "코인"],
    "prefer_keywords": ["무드등", "조명", "피규어", "인테리어", "감성", "캠핑", "홈카페"],
    "prefer_weight": 40,
    "require_card_image": True,
    # 선정 순서. "page" = 페이지 노출 순서(상단 우선), "score" = 할인율/선호도 점수
    "order": "page",
}


def load_config() -> dict:
    config = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config.update(json.load(f))
        except Exception as exc:
            print(f"[선정] {CONFIG_FILE} 읽기 실패, 기본값 사용: {exc}")
    return config


def load_picks() -> list:
    """picks.txt 를 읽어 수동 지정 목록을 반환한다. 주석(#)과 빈 줄은 무시."""
    if not os.path.exists(PICKS_FILE):
        return []
    picks = []
    with open(PICKS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.split("#")[0].strip()
            if line:
                picks.append(line)
    return picks


def normalize(product: dict) -> dict:
    """골드박스 API 응답 항목을 파이프라인 공통 형식으로 바꾼다."""
    return {
        "id": str(product.get("productId") or ""),
        "name": product.get("productName") or "",
        "price": product.get("productPrice"),
        "original_price": product.get("productOriginalPrice"),
        "discount_rate": product.get("discountRate"),
        "image_url": product.get("productImage"),
        "product_url": product.get("productUrl"),
        "category": product.get("categoryName") or "",
        "is_rocket": bool(product.get("isRocket")),
        "position": None,
        "remaining_time": None,
        "coupon_required": False,
        "card_image": None,
        "from_page": False,
    }


def _passes_filters(item: dict, config: dict) -> bool:
    price = item.get("price")
    if not price:
        return False
    try:
        price = int(price)
    except (TypeError, ValueError):
        return False

    if price < config["min_price"] or price > config["max_price"]:
        return False
    if config["rocket_only"] and not item["is_rocket"]:
        return False

    haystack = f"{item['name']} {item['category']}"
    for word in config["exclude_keywords"]:
        if word and word in haystack:
            return False
    if not item.get("product_url"):
        return False
    # 캡처된 카드가 없는 상품은 게시할 수 없으므로 후보에서 제외한다.
    # (이 봇은 쿠팡 페이지 캡처 이미지만 사용한다)
    if config.get("require_card_image", True) and not item.get("card_image"):
        return False
    return True


def _score(item: dict, config: dict) -> float:
    """실제 할인율 위주 + 선호 키워드 가점 + 페이지 데이터 확보 가점."""
    score = 0.0
    try:
        score += float(item.get("discount_rate") or 0)
    except (TypeError, ValueError):
        pass
    if item.get("is_rocket"):
        score += 5
    # 페이지에서 정확한 가격/할인율을 확보한 상품을 우선한다.
    # (API만으로는 정가를 판매가로 잘못 표시할 위험이 있음)
    if item.get("from_page"):
        score += 15

    haystack = f"{item['name']} {item['category']}"
    for word in config["prefer_keywords"]:
        if word and word in haystack:
            score += config["prefer_weight"]
            break
    return score


def _matches_pick(item: dict, pick: str) -> bool:
    if re.fullmatch(r"\d+", pick):
        return item["id"] == pick
    return pick in item["name"]


def select_product(
    products: list,
    posted_ids: set,
    page_data: dict = None,
    posted_names: set = None,
) -> dict:
    """
    게시할 상품 하나를 고른다. 후보가 없으면 None.

    page_data가 있으면 API 값 위에 페이지에서 읽은 정확한 값을 덮어쓴 뒤 선정한다.
    posted_ids / posted_names 에 걸리는 상품은 중복으로 보고 제외한다.
    """
    from goldbox_page import merge

    config = load_config()
    posted_names = posted_names or set()
    items = [normalize(p) for p in products]
    if page_data:
        items = [merge(i, page_data) for i in items]
        enriched = sum(1 for i in items if i.get("from_page"))
        print(f"[선정] 페이지 데이터 병합: {enriched}/{len(items)}개")
    # 중복 제외는 페이지 병합 이후에 한다(병합 뒤 상품명이 정확해지므로)
    fresh = []
    dup_id = dup_name = 0
    for item in items:
        if not item["id"]:
            continue
        if item["id"] in posted_ids:
            dup_id += 1
            continue
        if posted_names and normalize_name(item["name"]) in posted_names:
            dup_name += 1
            continue
        fresh.append(item)

    print(
        f"[선정] 골드박스 {len(items)}개 / 미게시 {len(fresh)}개 "
        f"(중복제외 ID {dup_id}건, 상품명 {dup_name}건)"
    )

    if not fresh:
        return None

    # 1) 수동 지정 우선
    picks = load_picks()
    if picks:
        for pick in picks:
            for item in fresh:
                if _matches_pick(item, pick) and _passes_filters(item, config):
                    print(f"[선정] 수동 지정 매칭: '{pick}' -> {item['name'][:40]}")
                    return item
        print("[선정] picks.txt 항목이 오늘 목록에 없음, 자동 선정으로 진행")

    # 2) 자동 선정
    eligible = [i for i in fresh if _passes_filters(i, config)]
    print(f"[선정] 필터 통과 {len(eligible)}개")
    if not eligible:
        captured = sum(1 for i in fresh if i.get("card_image"))
        if captured == 0:
            print(
                "[선정] 캡처된 카드가 하나도 없습니다.\n"
                "       이 봇은 쿠팡 페이지 캡처 이미지만 사용하므로 게시할 수 없습니다.\n"
                "       페이지 수집 실패가 원인이니 [페이지] 로그를 확인하세요."
            )
        return None

    order = config.get("order", "page")
    if order == "page":
        # 페이지 상단 상품이 잘 팔리므로 노출 순서를 그대로 따른다.
        # 위치를 못 받은 상품(페이지 수집 실패분)은 뒤로 보낸다.
        eligible.sort(
            key=lambda i: (
                i.get("position") if i.get("position") is not None else 10**6
            )
        )
        print("[선정] 페이지 노출 순서 기준")
    else:
        eligible.sort(key=lambda i: _score(i, config), reverse=True)
        print("[선정] 점수 기준")

    print("[선정] 상위 후보:")
    for item in eligible[:5]:
        rate = item.get("discount_rate")
        rate_str = f"{float(rate):.0f}%" if rate else "할인율?"
        origin = item.get("original_price")
        price_str = (
            f"{int(origin):,}->{int(item['price']):,}원"
            if origin and origin > item["price"]
            else f"{int(item['price']):,}원"
        )
        pos = item.get("position")
        pos_str = f"{pos + 1}번째" if pos is not None else "순서?"
        print(
            f"  - {pos_str:>7s} [{item['id']}] {item['name'][:30]} / "
            f"{rate_str} / {price_str}"
        )

    return eligible[0]
