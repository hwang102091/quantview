"""
한국 주식 가격·재무 수집기
yfinance(.KS/.KQ 접미사)와 DART 전자공시를 함께 사용한다.
"""
import logging
from typing import List, Dict
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    yf = None

from config import PRICE_HISTORY_DAYS, DART_API_KEY

log = logging.getLogger(__name__)


def _yf_ticker(code: str) -> str:
    """6자리 종목코드 -> yfinance 형식 (.KS 우선, 코스닥 호출 실패 시 .KQ)."""
    return f"{code}.KS"


def fetch(universe: List[Dict]) -> Dict[str, dict]:
    """
    한국 종목 가격 + 펀더멘털 수집.

    DART 재무 데이터는 DART_API_KEY 가 설정된 경우만 호출 (별도 워커 권장).
    """
    if yf is None:
        log.warning("yfinance 미설치 - 빈 딕셔너리 반환")
        return {}

    out: Dict[str, dict] = {}
    period = f"{PRICE_HISTORY_DAYS}d"

    for item in universe:
        code = item["ticker"]
        yf_code = _yf_ticker(code)
        try:
            tk = yf.Ticker(yf_code)
            price = tk.history(period=period, auto_adjust=True)
            if price.empty:
                # 코스닥(.KQ)으로 재시도
                tk = yf.Ticker(f"{code}.KQ")
                price = tk.history(period=period, auto_adjust=True)
            out[code] = {
                "price": price,
                "info": _safe_info(tk),
                "dart": None,   # DART 재무는 비동기로 채움
            }
        except Exception as e:
            log.warning("KR 수집 실패 %s: %s", code, e)
            out[code] = {"price": pd.DataFrame(), "info": {}, "dart": None}

    if DART_API_KEY:
        log.info("DART_API_KEY 감지 - 재무 데이터는 dart 워커가 별도 채움")
    else:
        log.info("DART_API_KEY 없음 - 재무 데이터 스킵")

    log.info("KR 수집 완료: %d / %d", len(out), len(universe))
    return out


def _safe_info(tk) -> dict:
    try:
        return dict(tk.info or {})
    except Exception:
        return {}
