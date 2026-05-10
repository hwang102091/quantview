"""
퀀트 투자 대시보드 - 메인 실행 엔트리포인트

실행 예:
  python run.py              # 전체 실행 (LAYER1→2→3)
  python run.py --fast       # LAYER3 집중종목 100개 (경량 수집)
  python run.py --layer 1    # LAYER1 수집만 (가격·기본지표)
  python run.py --test       # 종목 10개 테스트
"""
import argparse
import asyncio
import json
import logging
import shutil
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

from config import (
    DATA_DIR, DOCS_DATA_DIR, LAYER1, LAYER2, LAYER3, UNIVERSE_DIR,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("run")

KST = timezone(timedelta(hours=9))

_success_count = 0
_fail_count = 0


# ── 공통 유틸 ─────────────────────────────────────────────────────────────

def _now_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%dT%H:%M:%S+09:00")


def _write_json(path: Path, data: Any) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        log.error("JSON 저장 실패 %s: %s", path, e)


def _strip_df(items: List[Dict]) -> List[Dict]:
    """DataFrame·내부 전용 필드 제거 (JSON 직렬화 전처리)."""
    skip = {"_price_df"}
    out: List[Dict] = []
    for item in items:
        d = {
            k: v for k, v in item.items()
            if k not in skip and not hasattr(v, "to_dict")
        }
        out.append(d)
    return out


# ── 유니버스 로드 ────────────────────────────────────────────────────────

def load_universe(test_mode: bool = False) -> List[Dict]:
    items: List[Dict] = []
    for fname in ("kr_universe.json", "us_universe.json"):
        path = UNIVERSE_DIR / fname
        try:
            with open(path, "r", encoding="utf-8") as f:
                items.extend(json.load(f))
        except Exception as e:
            log.warning("유니버스 로드 실패 %s: %s", fname, e)

    if test_mode:
        items = items[:10]

    log.info("유니버스 로드 완료: %d 종목%s", len(items),
             " (테스트 모드)" if test_mode else "")
    return items


# ── 수집 (asyncio.gather 병렬) ────────────────────────────────────────────

async def _safe_collect(name: str, coro) -> Tuple[str, Any]:
    """개별 collector 실패 시 빈 dict 반환, 전체 중단 없음."""
    global _success_count, _fail_count
    try:
        result = await coro
        _success_count += 1
        log.info("[수집 완료] %s", name)
        return name, result if result is not None else {}
    except Exception as e:
        _fail_count += 1
        log.error("[수집 실패] %s: %s", name, e)
        return name, {}


async def _collect_async(universe: List[Dict]) -> Dict[str, Any]:
    from collectors import (
        etf_flows, kr_stocks, macro, ratings, sentiment, smart_money, us_stocks,
    )

    kr_uni = [u for u in universe if u["market"] == "kr"]
    us_uni = [u for u in universe if u["market"] == "us"]

    log.info("[1/4] 데이터 수집 시작 — KR %d종목 / US %d종목 (병렬)",
             len(kr_uni), len(us_uni))

    tasks = [
        _safe_collect("kr_stocks",   asyncio.to_thread(kr_stocks.fetch, kr_uni)),
        _safe_collect("us_stocks",   asyncio.to_thread(us_stocks.fetch, us_uni)),
        _safe_collect("macro",       asyncio.to_thread(macro.fetch)),
        _safe_collect("sentiment",   asyncio.to_thread(sentiment.fetch)),
        _safe_collect("smart_money", asyncio.to_thread(smart_money.fetch)),
        _safe_collect("ratings",     asyncio.to_thread(ratings.fetch, universe)),
        _safe_collect("etf_flows",   asyncio.to_thread(etf_flows.fetch)),
    ]

    results = await asyncio.gather(*tasks)
    bundle: Dict[str, Any] = {name: data for name, data in results}

    # 내부 키 정규화 (screener / signals 에서 kr_prices / us_prices 로 접근)
    bundle["kr_prices"] = bundle.pop("kr_stocks", {})
    bundle["us_prices"] = bundle.pop("us_stocks", {})
    return bundle


def step_collect(universe: List[Dict]) -> Dict[str, Any]:
    try:
        return asyncio.run(_collect_async(universe))
    except RuntimeError:
        # Jupyter 등 이미 이벤트 루프가 실행 중인 환경 대응
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_collect_async(universe))
        finally:
            loop.close()


# ── 스크리너 (LAYER1 → LAYER2) ───────────────────────────────────────────

def step_screen(
    universe: List[Dict],
    bundle: Dict[str, Any],
    target_size: int,
) -> List[Dict]:
    from processors.screener import run as screen

    log.info("[2/4] 스크리너 실행 (목표 %d종목)", target_size)
    try:
        result = screen(universe, bundle, target_size=target_size)
        log.info("스크리너 완료: %d종목", len(result))
        return result
    except Exception as e:
        log.error("스크리너 실패: %s", e)
        return []


# ── 시그널·랭킹 (LAYER2 → LAYER3) ────────────────────────────────────────

def step_signals_and_rankings(
    watchlist: List[Dict],
    bundle: Dict[str, Any],
    target_size: int,
) -> Tuple[Dict, List[Dict], Dict]:
    """
    Returns:
        (signals_dict, focus_list, rankings_dict)
    """
    from processors import rankings, signals

    log.info("[3/4] 시그널·랭킹 생성 (집중종목 목표 %d종목)", target_size)

    # price_df / short_ratio 를 watchlist item 에 주입 (signals.generate_signals 에서 사용)
    kr_prices = bundle.get("kr_prices") or {}
    us_prices = bundle.get("us_prices") or {}
    for item in watchlist:
        snap = (kr_prices if item["market"] == "kr" else us_prices).get(item["ticker"], {})
        item["_price_df"] = snap.get("price")
        info = snap.get("info") or {}
        item.setdefault("short_ratio", info.get("shortRatio"))

    smart_money = bundle.get("smart_money") or {}
    ratings_data = bundle.get("ratings") or {}

    try:
        sigs = signals.generate_signals(watchlist, smart_money)
    except Exception as e:
        log.error("시그널 생성 실패: %s", e)
        sigs = {}

    try:
        rnks = rankings.generate_rankings(watchlist, smart_money, ratings_data)
    except Exception as e:
        log.error("랭킹 생성 실패: %s", e)
        rnks = {}

    # quant_score 기준 집중종목 선정
    focus = sorted(watchlist, key=lambda x: x.get("quant_score") or 0, reverse=True)
    focus = focus[:target_size]
    log.info("집중종목 선정: %d종목", len(focus))
    return sigs, focus, rnks


# ── 저장 ─────────────────────────────────────────────────────────────────

def step_save(
    watchlist: List[Dict],
    focus: List[Dict],
    bundle: Dict[str, Any],
    sigs: Dict,
    rnks: Dict,
    updated_at: str,
) -> None:
    log.info("[4/4] 결과 저장")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DATA_DIR.mkdir(parents=True, exist_ok=True)

    clean_watchlist = _strip_df(watchlist)
    clean_focus = _strip_df(focus)

    files = {
        "stocks.json": {"updated_at": updated_at, "stocks": clean_watchlist},
        "signals.json": {"updated_at": updated_at, "signals": sigs},
        "rankings.json": {"updated_at": updated_at, "rankings": rnks},
        "snapshot.json": {
            "updated_at": updated_at,
            "watchlist": clean_watchlist,
            "focus": clean_focus,
            "macro": bundle.get("macro"),
            "sentiment": bundle.get("sentiment"),
            "etf_flows": bundle.get("etf_flows"),
        },
    }

    for fname, data in files.items():
        _write_json(DATA_DIR / fname, data)
        try:
            shutil.copy2(DATA_DIR / fname, DOCS_DATA_DIR / fname)
        except Exception as e:
            log.warning("docs/data/%s 복사 실패: %s", fname, e)

    log.info("저장 완료 → data/ 및 docs/data/")


# ── 메인 ─────────────────────────────────────────────────────────────────

def main() -> None:
    global _success_count, _fail_count
    _success_count = 0
    _fail_count = 0

    parser = argparse.ArgumentParser(description="퀀트 투자 대시보드 데이터 수집·처리")
    parser.add_argument("--fast",  action="store_true",
                        help="LAYER3 집중종목 100개만 처리 (빠른 업데이트)")
    parser.add_argument("--layer", type=int, choices=[1, 2, 3],
                        help="실행 레이어 지정 (1: 수집만, 2: +스크리너, 3: 전체)")
    parser.add_argument("--test",  action="store_true",
                        help="종목 10개로 테스트 실행")
    args = parser.parse_args()

    t0 = time.time()
    updated_at = _now_kst()

    log.info("=== 퀀트 대시보드 시작 (%s) ===", updated_at)

    universe = load_universe(test_mode=args.test)

    layer = args.layer or (1 if args.fast else 3)

    # ── LAYER 1: 수집만 ────────────────────────────────────────────────────
    bundle = step_collect(universe)

    if layer == 1:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        DOCS_DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": updated_at,
            "macro": bundle.get("macro"),
            "sentiment": bundle.get("sentiment"),
        }
        _write_json(DATA_DIR / "snapshot.json", payload)
        try:
            shutil.copy2(DATA_DIR / "snapshot.json", DOCS_DATA_DIR / "snapshot.json")
        except Exception:
            pass
        _print_summary(t0)
        return

    # ── LAYER 2: +스크리너 ──────────────────────────────────────────────────
    l2_size = LAYER2["size"] if not args.test else min(LAYER2["size"], len(universe))
    watchlist = step_screen(universe, bundle, target_size=l2_size)

    if layer == 2:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        DOCS_DATA_DIR.mkdir(parents=True, exist_ok=True)
        clean = _strip_df(watchlist)
        payload = {"updated_at": updated_at, "stocks": clean}
        _write_json(DATA_DIR / "stocks.json", payload)
        try:
            shutil.copy2(DATA_DIR / "stocks.json", DOCS_DATA_DIR / "stocks.json")
        except Exception:
            pass
        _print_summary(t0)
        return

    # ── LAYER 3 (기본·fast·test): +시그널·랭킹·저장 ───────────────────────
    l3_size = LAYER3["size"] if not args.test else min(LAYER3["size"], len(universe))
    sigs, focus, rnks = step_signals_and_rankings(watchlist, bundle, target_size=l3_size)
    step_save(watchlist, focus, bundle, sigs, rnks, updated_at)
    _print_summary(t0)


def _print_summary(t0: float) -> None:
    elapsed = time.time() - t0
    log.info(
        "=== 완료 %.1f초 | 수집 성공 %d / 실패 %d ===",
        elapsed, _success_count, _fail_count,
    )


if __name__ == "__main__":
    main()
