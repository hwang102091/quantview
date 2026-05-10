"""
미국 주식 가격·재무 수집기
yfinance를 사용해 NYSE·NASDAQ 종목의 OHLCV 및 기본 펀더멘털을 가져온다.
"""
import logging
from typing import List, Dict
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    yf = None

from config import PRICE_HISTORY_DAYS

log = logging.getLogger(__name__)


def fetch(universe: List[Dict]) -> Dict[str, dict]:
    """
    미국 종목 가격·기본 정보를 수집해 ticker -> {price_df, info} 딕셔너리로 반환.

    Args:
        universe: us_universe.json 의 항목 리스트
    Returns:
        {"NVDA": {"price": pd.DataFrame, "info": dict}, ...}
    """
    if yf is None:
        log.warning("yfinance 미설치 - 빈 딕셔너리 반환")
        return {}

    out: Dict[str, dict] = {}
    period = f"{PRICE_HISTORY_DAYS}d"

    for item in universe:
        ticker = item["ticker"]
        try:
            tk = yf.Ticker(ticker)
            price = tk.history(period=period, auto_adjust=True)
            info = _safe_info(tk)
            out[ticker] = {"price": price, "info": info}
        except Exception as e:
            log.warning("US 수집 실패 %s: %s", ticker, e)
            out[ticker] = {"price": pd.DataFrame(), "info": {}}
    log.info("US 수집 완료: %d / %d", len(out), len(universe))
    return out


def _safe_info(tk) -> dict:
    """yfinance .info 호출 안전 래퍼."""
    try:
        return dict(tk.info or {})
    except Exception:
        return {}
