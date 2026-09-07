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

PICKS_FILE = "picks.txt"
CONFIG_FILE = "selector_config.json"

DEFAULT_CONFIG = {
    "min_price": 5000,
    "max_price": 150000,
    "rocket_only": False,
    "exclude_keywords": ["성인", "담배", "의약품", "렌즈", "주식", "코인"],
    "prefer_keywords": ["무드등", "조명", "피규어", "인테리어", "감성", "캠핑", "홈카페"],
    "prefer_weight": 40,
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
    if not item.get("product_url") or not item.get("image_url"):
        return False
    return True


def _score(item: dict, config: dict) -> float:
    """할인율 위주 + 선호 키워드 가점."""
    score = 0.0
    try:
        score += float(item.get("discount_rate") or 0)
    except (TypeError, ValueError):
        pass
    if item.get("is_rocket"):
        score += 5
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


def select_product(products: list, posted_ids: set) -> dict:
    """
    게시할 상품 하나를 고른다. 후보가 없으면 None.
    """
    config = load_config()
    items = [normalize(p) for p in products]
    fresh = [i for i in items if i["id"] and i["id"] not in posted_ids]

    print(f"[선정] 골드박스 {len(items)}개 / 미게시 {len(fresh)}개")

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
        return None

    eligible.sort(key=lambda i: _score(i, config), reverse=True)

    print("[선정] 상위 후보:")
    for item in eligible[:5]:
        print(
            f"  - [{item['id']}] {item['name'][:38]} / "
            f"{int(item['price']):,}원 / 점수 {_score(item, config):.0f}"
        )

    return eligible[0]
