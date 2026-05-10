"""
종합 랭킹 - LAYER2 → LAYER3
시그널 + 스마트머니 + 센티먼트를 가중 합산해 집중 종목 100개를 선정한다.
"""
import logging
from typing import List, Dict, Any

log = logging.getLogger(__name__)

# 점수 가중치 (총합 1.0)
WEIGHTS = {
    "momentum": 0.30,
    "trend": 0.20,
    "volume": 0.10,
    "near_high": 0.15,
    "smart_money": 0.15,
    "rating": 0.10,
}


def run(watchlist: List[Dict], signals: Dict[str, dict],
        target_size: int = 100) -> List[Dict]:
    """
    시그널 dict 와 watchlist 를 결합해 종합 점수 상위 target_size 개 반환.
    """
    scored: List[Dict] = []
    for item in watchlist:
        sig = signals.get(item["ticker"], {}) or {}
        score = _score(sig)
        record = dict(item)
        record["score"] = score
        record["signals"] = sig
        scored.append(record)

    scored.sort(key=lambda x: x.get("score") or 0, reverse=True)
    result = scored[:target_size]
    log.info("랭킹 완료: top %d / %d", len(result), len(scored))
    return result


def _score(sig: dict) -> float:
    """시그널 dict 에서 0~100 사이 종합 점수 산출."""
    if not sig:
        return 0.0

    # 모멘텀: 3개월 수익률을 메인으로
    m3 = sig.get("momentum_3m")
    momentum_score = _clip((m3 or 0) + 50, 0, 100)   # -50%~+50% → 0~100

    # 추세: MA50 위 + MA200 위 + 골든크로스 = 만점
    trend_score = sum([
        40 if sig.get("above_ma50") else 0,
        30 if sig.get("above_ma200") else 0,
        30 if sig.get("golden_cross") else 0,
    ])

    # 거래량 급증
    vs = sig.get("vol_surge") or 1.0
    volume_score = _clip((vs - 1.0) * 100, 0, 100)

    # 52주 고점 근접도 (그대로 0~100)
    near = sig.get("near_52w_high") or 0
    near_score = _clip(near, 0, 100)

    # 스마트머니/레이팅은 별도 데이터 결합 시 채움 (placeholder)
    smart_money_score = 50.0
    rating_score = 50.0

    total = (
        WEIGHTS["momentum"] * momentum_score +
        WEIGHTS["trend"] * trend_score +
        WEIGHTS["volume"] * volume_score +
        WEIGHTS["near_high"] * near_score +
        WEIGHTS["smart_money"] * smart_money_score +
        WEIGHTS["rating"] * rating_score
    )
    return round(total, 2)


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))
