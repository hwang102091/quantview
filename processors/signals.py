"""
기술적·정량 시그널 생성기
- 모멘텀 (1M / 3M / 6M 수익률)
- 추세 (이동평균선 대비 위치, 골든·데드크로스)
- 변동성 (20일 표준편차)
- 거래량 급증 (5일 / 20일 비율)
- 52주 고점 근접도
"""
import logging
from typing import List, Dict, Any

log = logging.getLogger(__name__)


def run(watchlist: List[Dict], bundle: Dict[str, Any]) -> Dict[str, dict]:
    """
    종목별 시그널 dict 반환.

    Returns:
        {"NVDA": {"momentum_1m": 5.2, "above_ma50": True, ...}, ...}
    """
    kr_prices = bundle.get("kr_prices", {})
    us_prices = bundle.get("us_prices", {})

    out: Dict[str, dict] = {}
    for item in watchlist:
        snap = (kr_prices if item["market"] == "kr" else us_prices).get(item["ticker"], {})
        df = snap.get("price")
        if df is None or getattr(df, "empty", True):
            out[item["ticker"]] = {}
            continue

        out[item["ticker"]] = _compute(df)
    log.info("시그널 산출 완료: %d 종목", len(out))
    return out


def _compute(df) -> dict:
    """단일 종목 가격 시계열에서 시그널 추출."""
    close = df["Close"]
    vol = df["Volume"]
    last = float(close.iloc[-1])

    sig = {
        "last_close": last,
        "momentum_1m": _ret(close, 21),
        "momentum_3m": _ret(close, 63),
        "momentum_6m": _ret(close, 126),
        "vol_20d": float(close.pct_change().tail(20).std() * 100) if len(close) > 20 else None,
        "above_ma50": _above_ma(close, 50),
        "above_ma200": _above_ma(close, 200),
        "golden_cross": _golden_cross(close),
        "vol_surge": _vol_surge(vol),
        "near_52w_high": _near_high(close, 252),
    }
    return sig


def _ret(s, n: int):
    """n거래일 수익률 %."""
    if len(s) <= n:
        return None
    try:
        return float((s.iloc[-1] / s.iloc[-n] - 1) * 100)
    except Exception:
        return None


def _above_ma(s, window: int):
    """현재가가 이동평균 위에 있는지."""
    if len(s) < window:
        return None
    return bool(s.iloc[-1] > s.tail(window).mean())


def _golden_cross(s) -> bool | None:
    """50일선이 200일선 위로 돌파한 상태인지(골든크로스 유지)."""
    if len(s) < 200:
        return None
    ma50 = s.tail(50).mean()
    ma200 = s.tail(200).mean()
    return bool(ma50 > ma200)


def _vol_surge(v) -> float | None:
    """5일 평균 거래량 / 20일 평균 거래량."""
    if len(v) < 20:
        return None
    try:
        return float(v.tail(5).mean() / v.tail(20).mean())
    except Exception:
        return None


def _near_high(s, window: int) -> float | None:
    """52주 고점 대비 현재가 비율(%). 100=신고가."""
    if len(s) < window:
        return None
    try:
        return float(s.iloc[-1] / s.tail(window).max() * 100)
    except Exception:
        return None
