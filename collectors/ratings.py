"""
애널리스트 레이팅·목표주가 수집기
- 미국: Finviz, yfinance recommendations
- 한국: 네이버 금융 컨센서스, FnGuide
"""
import logging
from typing import List, Dict, Any

try:
    from finviz.screener import Screener  # noqa: F401
except ImportError:
    Screener = None

try:
    import yfinance as yf
except ImportError:
    yf = None

log = logging.getLogger(__name__)


def fetch(universe: List[Dict]) -> Dict[str, Any]:
    """
    유니버스 전체에 대해 컨센서스/레이팅 dict 반환.

    Returns:
      {
        "AAPL": {"rating": "Buy", "target_mean": 230.0, "target_high": 270.0, ...},
        "005930": {...}, ...
      }
    """
    out: Dict[str, Any] = {}
    for item in universe:
        ticker = item["ticker"]
        market = item["market"]
        try:
            if market == "us":
                out[ticker] = _us_ratings(ticker)
            else:
                out[ticker] = _kr_ratings(ticker)
        except Exception as e:
            log.warning("레이팅 실패 %s: %s", ticker, e)
            out[ticker] = {}
    log.info("레이팅 수집 완료: %d 종목", len(out))
    return out


def _us_ratings(ticker: str) -> Dict[str, Any]:
    """yfinance recommendation_summary + analyst_price_targets 기반."""
    if yf is None:
        return {}
    tk = yf.Ticker(ticker)
    info = {}
    try:
        info = dict(tk.info or {})
    except Exception:
        pass
    return {
        "target_mean": info.get("targetMeanPrice"),
        "target_high": info.get("targetHighPrice"),
        "target_low": info.get("targetLowPrice"),
        "rating": info.get("recommendationKey"),
        "n_analysts": info.get("numberOfAnalystOpinions"),
    }


def _kr_ratings(code: str) -> Dict[str, Any]:
    """네이버 금융/FnGuide 컨센서스 - 추후 구현."""
    # TODO: 네이버 금융 컨센서스 페이지 파싱
    return {
        "target_mean": None,
        "target_high": None,
        "target_low": None,
        "rating": None,
        "n_analysts": None,
    }
