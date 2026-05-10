"""
퀀트 투자 대시보드 - 메인 실행 엔트리포인트

실행 흐름:
  1) 유니버스 로드 (universe/*.json)
  2) 데이터 수집 (collectors/*) - LAYER1 전체
  3) 스크리너 (processors.screener) - LAYER2 1000개
  4) 시그널·랭킹 (processors.signals, rankings) - LAYER3 100개
  5) 결과 저장 (data/, docs/data/)
"""
import json
import logging
from pathlib import Path
from datetime import datetime

from config import (
    UNIVERSE_DIR, DATA_DIR, DOCS_DATA_DIR,
    LAYER1, LAYER2, LAYER3,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("run")


def load_universe() -> list:
    """KR/US 유니버스를 합쳐서 단일 리스트로 반환."""
    items = []
    for fname in ("kr_universe.json", "us_universe.json"):
        path = UNIVERSE_DIR / fname
        with open(path, "r", encoding="utf-8") as f:
            items.extend(json.load(f))
    log.info("유니버스 로드 완료: %d 종목", len(items))
    return items


def step_collect(universe: list) -> dict:
    """LAYER1: 가격·재무·거시·센티먼트·스마트머니 수집."""
    from collectors import us_stocks, kr_stocks, macro, sentiment, smart_money, ratings, etf_flows

    log.info("[1/4] 데이터 수집 시작 (LAYER1: %s)", LAYER1["name"])
    bundle = {}
    bundle["kr_prices"] = kr_stocks.fetch([u for u in universe if u["market"] == "kr"])
    bundle["us_prices"] = us_stocks.fetch([u for u in universe if u["market"] == "us"])
    bundle["macro"] = macro.fetch()
    bundle["sentiment"] = sentiment.fetch()
    bundle["smart_money"] = smart_money.fetch()
    bundle["ratings"] = ratings.fetch(universe)
    bundle["etf_flows"] = etf_flows.fetch()
    return bundle


def step_screen(universe: list, bundle: dict) -> list:
    """LAYER2: 섹터별 필터 통과 종목 1000개 추림."""
    from processors.screener import run as screen

    log.info("[2/4] 스크리너 실행 (LAYER2: %s, 목표 %d)",
             LAYER2["name"], LAYER2["size"])
    return screen(universe, bundle, target_size=LAYER2["size"])


def step_rank(watchlist: list, bundle: dict) -> list:
    """LAYER3: 시그널·랭킹 종합 점수 상위 100개."""
    from processors import signals, rankings

    log.info("[3/4] 시그널·랭킹 (LAYER3: %s, 목표 %d)",
             LAYER3["name"], LAYER3["size"])
    sigs = signals.run(watchlist, bundle)
    return rankings.run(watchlist, sigs, target_size=LAYER3["size"])


def step_save(watchlist: list, focus: list, bundle: dict) -> None:
    """결과를 data/ 및 docs/data/ 에 JSON으로 저장 (대시보드 배포용)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DATA_DIR.mkdir(parents=True, exist_ok=True)

    snapshot = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "watchlist": watchlist,
        "focus": focus,
        "macro": bundle.get("macro"),
        "sentiment": bundle.get("sentiment"),
    }
    for outdir in (DATA_DIR, DOCS_DATA_DIR):
        with open(outdir / "snapshot.json", "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2, default=str)
    log.info("[4/4] 저장 완료: data/snapshot.json, docs/data/snapshot.json")


def main() -> None:
    universe = load_universe()
    bundle = step_collect(universe)
    watchlist = step_screen(universe, bundle)
    focus = step_rank(watchlist, bundle)
    step_save(watchlist, focus, bundle)
    log.info("DONE - watchlist=%d, focus=%d", len(watchlist), len(focus))


if __name__ == "__main__":
    main()
