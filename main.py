# -*- coding: utf-8 -*-
"""
쿠팡 골드박스 -> 쓰레드 자동 게시.

흐름:
  1. 골드박스 Open API로 당일 특가 상품 목록 조회 (상품ID/링크 확보)
  2. 골드박스 페이지를 한 번 열어 모든 카드의 정확한 정보 수집 + 카드 캡처
     (API는 정가를 판매가로 주고 할인율을 주지 않으며 상품명도 잘려서 옴)
  3. 두 데이터를 병합해 상품 하나 선정 (picks.txt 우선, 없으면 필터+점수)
  4. 제휴 링크 확보 (골드박스 링크는 이미 제휴 링크라 변환 생략)
  5. 캡처한 카드를 Meta 요구 규격(JPEG, 4:5~1.91:1)으로 변환
  6. GitHub raw -> imgbb 순으로 공개 URL 확보
  7. 캡션 생성 (Claude -> 실패 시 템플릿) 후 쓰레드 게시
  8. posted.json에 기록 (상품ID + 상품명 기준 중복 제외, KST 06시 초기화)

DRY_RUN=1 이면 게시 직전까지만 수행한다.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from caption_generator import generate_caption
from coupang_api import deeplink_for, get_goldbox_products
from image_prep import prepare_for_threads
from product_selector import normalize_name, select_product
from threads_api import post_to_threads

POSTED_FILE = "posted.json"
KST = timezone(timedelta(hours=9))

# 게시 기록을 초기화하는 시각(KST). 기본 06시.
# 게시 스케줄이 07:05~05:35 이므로, 자정이 아니라 06시를 하루 경계로 삼는다.
RESET_HOUR = int(os.environ.get("RESET_HOUR", "6"))

# 직전 게시로부터 최소 이 시간은 지나야 다시 게시한다.
# 대기열에서 밀린 실행이 앞 실행 직후에 바로 돌면 게시가 몰리는데, 이를 막는다.
MIN_INTERVAL_MIN = int(os.environ.get("MIN_POST_INTERVAL_MINUTES", "25"))

# 저장소 밖 로컬 캐시.
# posted.json 은 push 가 실패하면 원격에 남지 않고, 다음 실행의 checkout 이
# 작업 디렉터리를 되돌려버린다. 그러면 같은 상품을 다시 게시하게 된다.
# 그래서 러너 홈에도 같은 기록을 남겨 두 곳을 합쳐서 읽는다.
LOCAL_STATE = os.path.join(
    os.path.expanduser("~"), ".coupang-threads-bot", "posted.json"
)


def cycle_label() -> str:
    """
    현재 게시 주기의 이름. RESET_HOUR 를 하루 경계로 쓴다.
    예) RESET_HOUR=6 이면 09-09 05:30 은 아직 '09-08' 주기에 속한다.
    """
    now = datetime.now(KST)
    if now.hour < RESET_HOUR:
        now -= timedelta(days=1)
    return now.strftime("%Y-%m-%d")


def _read_state(path: str) -> dict:
    """기록 파일 하나를 읽는다. 현재 주기가 아니면 빈 값."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    # 이전 버전은 "date"/"ids" 형식이었으므로 둘 다 인정한다
    label = data.get("cycle") or data.get("date")
    if label != cycle_label():
        return {}
    return data


def load_posted() -> tuple:
    """
    현재 주기의 게시 기록을 (상품ID 집합, 상품명키 집합, 마지막 게시시각) 으로 돌려준다.
    저장소 파일과 로컬 캐시를 합쳐서 읽으므로, push 가 실패했던 경우에도
    같은 상품을 다시 게시하지 않는다.
    """
    repo_state = _read_state(POSTED_FILE)
    local_state = _read_state(LOCAL_STATE)

    ids, names, last_at = set(), set(), None
    for state, origin in ((repo_state, "저장소"), (local_state, "로컬")):
        if not state:
            continue
        ids |= {str(i) for i in state.get("ids", [])}
        names |= {str(n) for n in state.get("names", [])}
        stamp = state.get("last_post_at")
        if stamp and (last_at is None or stamp > last_at):
            last_at = stamp

    if repo_state and local_state:
        only_local = len(ids) - len(repo_state.get("ids", []))
        if only_local > 0:
            print(f"[기록] 로컬 캐시에만 있는 게시 기록 {only_local}건 반영")
    if not repo_state and not local_state:
        print(f"[기록] 주기 {cycle_label()} 신규 시작")

    return ids, names, last_at


def save_posted(posted_ids: set, posted_names: set) -> None:
    payload = {
        "cycle": cycle_label(),
        "reset_hour": RESET_HOUR,
        "last_post_at": datetime.now(KST).isoformat(timespec="seconds"),
        "ids": sorted(posted_ids),
        "names": sorted(posted_names),
    }
    for path in (POSTED_FILE, LOCAL_STATE):
        try:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            print(f"[기록] {path} 저장 실패: {exc}")


def minutes_since(stamp: str):
    """마지막 게시로부터 지난 분. 기록이 없으면 None."""
    if not stamp:
        return None
    try:
        last = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if last.tzinfo is None:
        last = last.replace(tzinfo=KST)
    return (datetime.now(KST) - last).total_seconds() / 60


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"[오류] 환경변수 {name} 가 설정되지 않았습니다.")
        sys.exit(1)
    return value


def resolve_image(target: dict) -> str:
    """
    게시용 이미지를 준비한다.

    쿠팡 페이지에서 캡처한 실제 카드만 사용한다.
    카드를 직접 그려서 만드는 경로는 없다. 캡처가 없으면 None을 반환하고,
    호출부에서 게시하지 않고 종료한다.
    """
    captured = target.get("card_image")
    if not captured or not os.path.exists(captured):
        print("[이미지] 캡처된 카드가 없습니다.")
        return None

    print(f"[이미지] 캡처한 골드박스 카드 사용: {captured}")
    return prepare_for_threads(captured)


def main() -> None:
    dry_run = os.environ.get("DRY_RUN") == "1"

    access_key = require_env("COUPANG_ACCESS_KEY")
    secret_key = require_env("COUPANG_SECRET_KEY")
    sub_id = os.environ.get("COUPANG_SUB_ID")

    if not dry_run:
        threads_user_id = require_env("THREADS_USER_ID")
        threads_token = require_env("THREADS_ACCESS_TOKEN")

    # 0. 게시 기록을 먼저 읽고 최소 간격을 확인한다.
    #    브라우저를 띄우기 전에 걸러야 대기열 밀림이 낭비로 이어지지 않는다.
    posted_ids, posted_names, last_at = load_posted()
    print(f"[기록] 주기 {cycle_label()} / 게시됨 {len(posted_ids)}건")

    elapsed = minutes_since(last_at)
    if elapsed is not None:
        print(f"[기록] 직전 게시로부터 {elapsed:.1f}분 경과")
        if elapsed < MIN_INTERVAL_MIN and not dry_run:
            print(
                f"\n직전 게시가 {elapsed:.1f}분 전이라 게시하지 않고 종료합니다.\n"
                f"  최소 간격 {MIN_INTERVAL_MIN}분 (MIN_POST_INTERVAL_MINUTES 로 조정)\n"
                "  대기열에 밀린 실행으로 보입니다. 다음 슬롯에서 정상 게시됩니다."
            )
            sys.exit(0)

    # 1. 골드박스 API 목록
    try:
        products = get_goldbox_products(access_key, secret_key, limit=100)
    except Exception as exc:
        print(f"[오류] 골드박스 조회 실패: {exc}")
        sys.exit(1)

    if not products:
        print("골드박스 목록이 비어 있습니다. 다음 실행에서 재시도합니다.")
        sys.exit(0)

    # 2. 페이지에서 정확한 정보 수집 (실패해도 계속)
    page_data = {}
    try:
        from goldbox_page import scrape_all

        page_data = scrape_all(max_cards=60)
    except Exception as exc:
        print(f"[페이지] 수집 건너뜀: {exc}")

    # 3. 선정
    target = select_product(products, posted_ids, page_data, posted_names)
    if target is None:
        print("게시 가능한 상품이 없습니다. 다음 실행에서 재시도합니다.")
        sys.exit(0)

    origin = target.get("original_price")
    price_desc = (
        f"{int(origin):,}원 -> {int(target['price']):,}원"
        if origin and origin > target["price"]
        else f"{int(target['price']):,}원"
    )
    rate = target.get("discount_rate")
    print(
        f"\n선정: [{target['id']}] {target['name']}\n"
        f"      {price_desc}"
        + (f" ({float(rate):.0f}% 할인)" if rate else "")
        + (" [쿠폰 조건부]" if target.get("coupon_required") else "")
    )
    if not target.get("from_page"):
        print(
            "\n" + "!" * 60 + "\n"
            "  경고: 페이지 데이터 없음 -> API 값으로 게시합니다.\n"
            "  API 가격은 '정가'일 수 있어 특가로 잘못 광고될 위험이 있습니다.\n"
            "  상품명도 잘리고 할인율도 표시되지 않습니다.\n"
            "  캡처도 없으므로 이 상품은 게시되지 않습니다.\n"
            + "!" * 60
        )


    # 4. 제휴 링크
    deeplink = deeplink_for(target["product_url"], access_key, secret_key, sub_id)
    print(f"링크: {deeplink}")

    # 5~6. 이미지 준비 + 공개 URL
    image_url = None
    local_image = resolve_image(target)
    if not local_image:
        print(
            "\n캡처 이미지가 없어 게시하지 않고 종료합니다.\n"
            "  이 봇은 쿠팡 페이지에서 캡처한 카드만 사용합니다.\n"
            "  페이지 수집이 실패한 경우이니 위의 [페이지] 로그를 확인하세요."
        )
        sys.exit(0)

    if dry_run:
        print(f"[DRY_RUN] 이미지 준비 완료(업로드 생략): {local_image}")
    else:
        from image_host import publish

        image_url = publish(local_image)
        if not image_url:
            print(
                "\n이미지 공개 URL 확보에 실패해 게시하지 않고 종료합니다.\n"
                "  이미지 없이 올리면 링크 미리보기만 붙은 글이 됩니다.\n"
                "  다음 실행에서 재시도합니다."
            )
            sys.exit(0)

    # 7. 캡션
    caption = generate_caption(
        target["name"],
        target["price"],
        deeplink,
        discount_rate=target.get("discount_rate"),
        original_price=target.get("original_price"),
        coupon_required=target.get("coupon_required", False),
        category=target.get("category", ""),
    )
    print(f"\n--- 게시 문구 ---\n{caption}\n-----------------")

    if dry_run:
        print("\n[DRY_RUN] 게시하지 않고 종료합니다.")
        return

    # 8. 게시
    # 주제 태그. 기본 "광고". POST_TOPIC_TAG 로 변경하거나 빈 값으로 끌 수 있다.
    topic_tag = os.environ.get("POST_TOPIC_TAG", "광고").strip() or None
    if topic_tag:
        print(f"주제 태그: {topic_tag}")

    media_id = post_to_threads(
        threads_user_id, threads_token, caption,
        image_url=image_url, topic_tag=topic_tag,
    )
    print(f"게시 완료. media_id={media_id}")

    posted_ids.add(target["id"])
    posted_names.add(normalize_name(target["name"]))
    save_posted(posted_ids, posted_names)


if __name__ == "__main__":
    main()
