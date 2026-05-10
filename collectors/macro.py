"""
거시경제 지표 수집기
FRED(미국 연준 데이터)에서 금리·물가·실업률·달러지수 등을 가져온다.
한국 지표는 한국은행 ECOS API 또는 yfinance 보조 사용.
"""
import logging
import requests
from typing import Dict, Any

from config import FRED_API_KEY, REQUEST_TIMEOUT

log = logging.getLogger(__name__)

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# 수집 대상 FRED 시리즈 ID
FRED_SERIES = {
    "DGS10": "10Y_treasury",       # 미국 10년물 국채금리
    "DGS2": "2Y_treasury",         # 미국 2년물 국채금리
    "DFF": "fed_funds",            # 연방기금금리
    "CPIAUCSL": "cpi_all",         # 미국 CPI
    "UNRATE": "unemployment",      # 실업률
    "DTWEXBGS": "dxy_broad",       # 광의 달러지수
    "VIXCLS": "vix",               # VIX
    "WTISPLC": "wti_oil",          # WTI 유가
}


def fetch() -> Dict[str, Any]:
    """FRED 주요 시리즈 + 환율 + 원자재를 dict로 반환."""
    out: Dict[str, Any] = {"fred": {}}

    if not FRED_API_KEY:
        log.warning("FRED_API_KEY 없음 - 거시 데이터 빈 값 반환")
        return out

    for sid, alias in FRED_SERIES.items():
        try:
            r = requests.get(
                FRED_BASE,
                params={
                    "series_id": sid,
                    "api_key": FRED_API_KEY,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 1,
                },
                timeout=REQUEST_TIMEOUT,
            )
            r.raise_for_status()
            obs = r.json().get("observations", [])
            if obs:
                out["fred"][alias] = {
                    "date": obs[0]["date"],
                    "value": obs[0]["value"],
                }
        except Exception as e:
            log.warning("FRED %s 실패: %s", sid, e)

    log.info("거시 지표 수집 완료: %d 시리즈", len(out["fred"]))
    return out
