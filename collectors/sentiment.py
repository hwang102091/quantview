"""
시장 센티먼트 수집기
- CNN Fear & Greed Index
- AAII Investor Sentiment Survey
- Put/Call Ratio (CBOE)
"""
import logging
import requests
from typing import Dict, Any

from config import REQUEST_TIMEOUT

log = logging.getLogger(__name__)

CNN_FNG_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"


def fetch() -> Dict[str, Any]:
    """주요 센티먼트 지표를 통합 dict로 반환."""
    out: Dict[str, Any] = {}
    out["fear_greed"] = _fetch_cnn_fear_greed()
    out["aaii"] = _fetch_aaii_placeholder()
    out["put_call"] = _fetch_put_call_placeholder()
    return out


def _fetch_cnn_fear_greed() -> Dict[str, Any]:
    """CNN Fear & Greed 최신 값."""
    try:
        r = requests.get(
            CNN_FNG_URL,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        fng = data.get("fear_and_greed", {})
        return {
            "score": fng.get("score"),
            "rating": fng.get("rating"),
            "timestamp": fng.get("timestamp"),
        }
    except Exception as e:
        log.warning("Fear & Greed 수집 실패: %s", e)
        return {}


def _fetch_aaii_placeholder() -> Dict[str, Any]:
    """AAII 주간 설문 - 실제 구현 시 aaii.com 또는 데이터 벤더 연결."""
    # TODO: AAII 주간 데이터 파서 구현
    return {"bullish": None, "bearish": None, "neutral": None}


def _fetch_put_call_placeholder() -> Dict[str, Any]:
    """CBOE Put/Call Ratio - 실제 구현 시 cboe.com CSV 파싱."""
    # TODO: CBOE 일일 P/C 파서 구현
    return {"total": None, "equity": None, "index": None}
