"""
애널리스트 컨센서스·레이팅 수집기

- 미국: yfinance (recommendations_summary, recommendations, info의 target*)
- 한국: 네이버 금융 종목정보 페이지 스크래핑 (목표주가, 컨센서스 의견)

사용 예:
    from collectors import ratings
    us = ratings.fetch_ratings("AAPL", market="us")
    kr = ratings.fetch_ratings("005930", market="kr")
    bundle = ratings.fetch([{"ticker": "AAPL", "market": "us"}, ...])
"""
import logging
import re
from typing import List, Dict, Any, Optional
import requests

try:
    import yfinance as yf
except ImportError:
    yf = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

import pandas as pd

from config import REQUEST_TIMEOUT

log = logging.getLogger(__name__)

NAVER_COINFO_URL = "https://finance.naver.com/item/coinfo.naver"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,*/*",
}


def fetch_ratings(ticker: str, market: str = "us") -> Optional[Dict[str, Any]]:
    """
    단일 종목 컨센서스 + 최근 애널리스트 의견.

    Returns:
        {
          "ticker": str,
          "market": "us"|"kr",
          "buy": int|None,
          "hold": int|None,
          "sell": int|None,
          "target": float|None,    # 목표주가 평균
          "rows": [...]            # 최근 의견 (있으면)
        }
    """
    try:
        if market == "us":
            return _fetch_ratings_us(ticker)
        return _fetch_ratings_kr(ticker)
    except Exception as e:
        log.warning("레이팅 수집 실패 %s/%s: %s", market, ticker, e)
        return None


def _fetch_ratings_us(ticker: str) -> Optional[Dict[str, Any]]:
    """yfinance recommendations_summary + recommendations."""
    if yf is None:
        log.warning("yfinance 미설치 - %s 스킵", ticker)
        return None

    tk = yf.Ticker(ticker)

    info: Dict[str, Any] = {}
    try:
        info = dict(tk.info or {})
    except Exception:
        pass

    buy = hold = sell = None
    try:
        summary = tk.recommendations_summary
        if isinstance(summary, pd.DataFrame) and not summary.empty:
            row = summary.iloc[0]
            buy = _safe_int(row.get("strongBuy", 0)) + _safe_int(row.get("buy", 0))
            hold = _safe_int(row.get("hold", 0))
            sell = _safe_int(row.get("sell", 0)) + _safe_int(row.get("strongSell", 0))
    except Exception as e:
        log.debug("recommendations_summary 실패 %s: %s", ticker, e)

    rows: List[Dict[str, Any]] = []
    try:
        recs = tk.recommendations
        if isinstance(recs, pd.DataFrame) and not recs.empty:
            tail = recs.tail(20).reset_index()
            rows = tail.to_dict("records")
    except Exception as e:
        log.debug("recommendations 실패 %s: %s", ticker, e)

    return {
        "ticker": ticker,
        "market": "us",
        "buy": buy,
        "hold": hold,
        "sell": sell,
        "target": info.get("targetMeanPrice"),
        "target_high": info.get("targetHighPrice"),
        "target_low": info.get("targetLowPrice"),
        "rating": info.get("recommendationKey"),
        "n_analysts": info.get("numberOfAnalystOpinions"),
        "rows": rows,
    }


def _fetch_ratings_kr(code: str) -> Optional[Dict[str, Any]]:
    """네이버 금융 종목정보 페이지 (목표주가, 의견 텍스트) 스크래핑."""
    if BeautifulSoup is None:
        log.warning("beautifulsoup4 미설치 - %s 스킵", code)
        return None
    try:
        r = requests.get(
            NAVER_COINFO_URL,
            params={"code": code},
            headers=DEFAULT_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        # 네이버 금융은 EUC-KR 가 섞인 페이지가 많음
        r.encoding = r.apparent_encoding or "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text(" ", strip=True)

        target = None
        m = re.search(r"목표주가[^0-9]{0,20}([0-9,]+)\s*원", text)
        if m:
            target = _safe_float(m.group(1).replace(",", ""))

        rating = None
        m2 = re.search(r"투자의견[^가-힣A-Za-z]{0,10}([가-힣A-Za-z]+)", text)
        if m2:
            rating = m2.group(1)

        return {
            "ticker": code,
            "market": "kr",
            "buy": None,
            "hold": None,
            "sell": None,
            "target": target,
            "rating": rating,
            "n_analysts": None,
            "rows": [],
        }
    except Exception as e:
        log.warning("네이버 컨센서스 실패 %s: %s", code, e)
        return None


def fetch(universe: List[Dict]) -> Dict[str, Any]:
    """run.py 호환 - 유니버스 일괄 컨센서스 수집."""
    out: Dict[str, Any] = {}
    for item in universe:
        ticker = item["ticker"]
        market = item.get("market", "us")
        result = fetch_ratings(ticker, market)
        out[ticker] = result or {}
    log.info("레이팅 수집 완료: %d 종목", len(out))
    return out


def _safe_int(v) -> int:
    try:
        return int(v) if v is not None and not pd.isna(v) else 0
    except (TypeError, ValueError):
        return 0


def _safe_float(v) -> Optional[float]:
    try:
        return float(v) if v not in (None, "", ".") else None
    except (TypeError, ValueError):
        return None
