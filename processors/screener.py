"""
스크리너 - LAYER1 → LAYER2
섹터별 필터(config.SECTOR_FILTERS)를 적용해 관심 종목 풀을 만든다.
"""
import logging
from typing import List, Dict, Any

from config import get_sector_filter

log = logging.getLogger(__name__)


def run(universe: List[Dict], bundle: Dict[str, Any], target_size: int = 1000) -> List[Dict]:
    """
    섹터 태그별 필터를 적용한 뒤, 시총 기준 상위 target_size 개를 반환.

    Args:
        universe: 전체 유니버스
        bundle: collectors 결과 묶음
        target_size: 결과 종목 수 상한
    """
    kr_prices = bundle.get("kr_prices", {})
    us_prices = bundle.get("us_prices", {})

    passed: List[Dict] = []
    for item in universe:
        market_data = kr_prices if item["market"] == "kr" else us_prices
        snap = market_data.get(item["ticker"], {})

        # filter_override 가 있으면 그것을 사용, 없으면 섹터 태그 기준
        rule = item.get("filter_override") or get_sector_filter(item.get("tag", "default"))

        if _check(item, snap, rule):
            scored = dict(item)
            scored["_market_cap"] = _safe_market_cap(snap)
            passed.append(scored)

    # 시총 내림차순 정렬 후 상한 적용
    passed.sort(key=lambda x: x.get("_market_cap") or 0, reverse=True)
    result = passed[:target_size]
    log.info("스크리너 통과: %d (raw=%d -> top=%d)",
             len(result), len(passed), target_size)
    return result


def _check(item: Dict, snap: Dict, rule: Dict) -> bool:
    """단일 종목이 필터 룰을 통과하는지 검사."""
    info = snap.get("info") or {}
    price_df = snap.get("price")
    if price_df is None or getattr(price_df, "empty", True):
        return False

    # 시총 (단위: 십억 원/달러로 환산)
    mcap = _safe_market_cap(snap)
    min_mcap = rule.get("min_market_cap_bn")
    if min_mcap and mcap is not None and mcap < min_mcap:
        return False

    # 거래대금 (최근 20일 평균, 단위: 십억)
    turnover = _avg_turnover_bn(price_df)
    min_to = rule.get("min_turnover_bn")
    if min_to and turnover is not None and turnover < min_to:
        return False

    # 부채비율
    max_debt = rule.get("max_debt_ratio")
    if max_debt is not None:
        debt = info.get("debtToEquity")
        if debt is not None and debt > max_debt:
            return False

    # 흑자 요구
    if rule.get("require_profit"):
        eps = info.get("trailingEps")
        if eps is not None and eps <= 0:
            return False

    # PER 범위
    per = info.get("trailingPE")
    if per is not None:
        if rule.get("min_per") is not None and per < rule["min_per"]:
            return False
        if rule.get("max_per") is not None and per > rule["max_per"]:
            return False

    return True


def _safe_market_cap(snap: Dict) -> float | None:
    """시총을 십억 단위로 환산. 통화 구분은 단순화(절대치만 비교)."""
    info = snap.get("info") or {}
    mcap = info.get("marketCap")
    if mcap is None:
        return None
    try:
        return float(mcap) / 1_000_000_000  # → 단위: B (10억)
    except Exception:
        return None


def _avg_turnover_bn(price_df) -> float | None:
    """최근 20일 평균 거래대금(십억). Close * Volume 평균."""
    try:
        recent = price_df.tail(20)
        if recent.empty:
            return None
        turnover = (recent["Close"] * recent["Volume"]).mean()
        return float(turnover) / 1_000_000_000
    except Exception:
        return None
