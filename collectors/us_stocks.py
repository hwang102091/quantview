"""
미국 주식 가격·재무·기관보유·내부자거래 수집기

yfinance를 사용해 NYSE·NASDAQ 종목의 OHLCV·펀더멘털·홀더 정보를 가져온다.
yfinance 자체는 동기 라이브러리이므로 asyncio.to_thread + Semaphore 로
병렬도를 제어하고, 요청 간 0.5초 throttle 을 둔다.

사용 예:
    import asyncio
    from collectors import us_stocks

    prices  = asyncio.run(us_stocks.fetch_price_data(["AAPL", "NVDA", "MSFT"]))
    fund    = asyncio.run(us_stocks.fetch_fundamentals(["AAPL", "NVDA"]))
    holders = us_stocks.fetch_holders("AAPL")

    # run.py 호환 진입점
    bundle  = us_stocks.fetch([{"ticker": "AAPL"}, {"ticker": "NVDA"}])
"""
import asyncio
import logging
from typing import List, Dict, Optional
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    yf = None

from config import PRICE_HISTORY_DAYS

log = logging.getLogger(__name__)

REQUEST_DELAY = 0.5      # 요청 간 throttle (초)
MAX_CONCURRENT = 5       # yfinance 동시 호출 상한


async def _throttled(sem: asyncio.Semaphore, coro):
    async with sem:
        result = await coro
        await asyncio.sleep(REQUEST_DELAY)
        return result


def _yf_price_sync(ticker: str) -> Optional[Dict]:
    """yfinance 가격 + info 동기 호출 (worker thread 에서 실행)."""
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period=f"{PRICE_HISTORY_DAYS}d", auto_adjust=True)
        info: Dict = {}
        try:
            info = dict(tk.info or {})
        except Exception:
            pass
        if hist is None or hist.empty:
            return None
        last = hist.iloc[-1]
        return {
            "ticker": ticker,
            "close": float(last["Close"]),
            "volume": int(last["Volume"]) if not pd.isna(last["Volume"]) else None,
            "market_cap": info.get("marketCap"),
            "week52_high": info.get("fiftyTwoWeekHigh"),
            "week52_low": info.get("fiftyTwoWeekLow"),
            "currency": info.get("currency"),
            "history": hist,
        }
    except Exception as e:
        log.warning("US 가격 수집 실패 %s: %s", ticker, e)
        return None


async def fetch_price_data(tickers: List[str]) -> Dict[str, Dict]:
    """
    종가·거래량·시총·52주 고저 + 가격 히스토리 수집.

    Returns:
        {ticker: {close, volume, market_cap, week52_high, week52_low, history}}
    """
    if yf is None:
        log.warning("yfinance 미설치 - 가격 수집 스킵")
        return {}

    sem = asyncio.Semaphore(MAX_CONCURRENT)

    async def _one(t: str):
        return await _throttled(sem, asyncio.to_thread(_yf_price_sync, t))

    results = await asyncio.gather(*[_one(t) for t in tickers])
    out = {t: r for t, r in zip(tickers, results) if r}
    log.info("US 가격 수집 완료: %d / %d", len(out), len(tickers))
    return out


def _yf_fundamentals_sync(ticker: str) -> Optional[Dict]:
    """yfinance 펀더멘털 동기 호출."""
    try:
        tk = yf.Ticker(ticker)
        info: Dict = {}
        try:
            info = dict(tk.info or {})
        except Exception:
            pass
        if not info:
            return None
        return {
            "ticker": ticker,
            "per": info.get("trailingPE"),
            "forward_per": info.get("forwardPE"),
            "pbr": info.get("priceToBook"),
            "roe": info.get("returnOnEquity"),
            "debt_ratio": info.get("debtToEquity"),
            "eps": info.get("trailingEps"),
            "fcf": info.get("freeCashflow"),
            "operating_cf": info.get("operatingCashflow"),
            "profit_margin": info.get("profitMargins"),
            "revenue": info.get("totalRevenue"),
            "revenue_growth": info.get("revenueGrowth"),
            "earnings_growth": info.get("earningsGrowth"),
            "dividend_yield": info.get("dividendYield"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
        }
    except Exception as e:
        log.warning("US 펀더멘털 실패 %s: %s", ticker, e)
        return None


async def fetch_fundamentals(tickers: List[str]) -> Dict[str, Dict]:
    """
    PER·PBR·ROE·부채비율·EPS·FCF 등 핵심 펀더멘털.
    """
    if yf is None:
        log.warning("yfinance 미설치 - 펀더멘털 수집 스킵")
        return {}

    sem = asyncio.Semaphore(MAX_CONCURRENT)

    async def _one(t: str):
        return await _throttled(sem, asyncio.to_thread(_yf_fundamentals_sync, t))

    results = await asyncio.gather(*[_one(t) for t in tickers])
    out = {t: r for t, r in zip(tickers, results) if r}
    log.info("US 펀더멘털 수집 완료: %d / %d", len(out), len(tickers))
    return out


def fetch_holders(ticker: str) -> Optional[Dict]:
    """
    기관보유비율 + 내부자거래 내역.

    Returns:
        {
          "ticker": str,
          "major_holders": [...],          # 주요 보유 비율
          "institutional_holders": [...],  # 상위 기관 (최대 20)
          "insider_transactions": [...],   # 최근 내부자 거래 (최대 50)
        }
    """
    if yf is None:
        log.warning("yfinance 미설치 - 홀더 정보 스킵")
        return None
    try:
        tk = yf.Ticker(ticker)

        major = None
        try:
            mh = tk.major_holders
            if isinstance(mh, pd.DataFrame) and not mh.empty:
                major = mh.reset_index().to_dict("records")
        except Exception as e:
            log.debug("major_holders 실패 %s: %s", ticker, e)

        institutional = None
        try:
            ih = tk.institutional_holders
            if isinstance(ih, pd.DataFrame) and not ih.empty:
                institutional = ih.head(20).to_dict("records")
        except Exception as e:
            log.debug("institutional_holders 실패 %s: %s", ticker, e)

        insider_tx = None
        try:
            it = tk.insider_transactions
            if isinstance(it, pd.DataFrame) and not it.empty:
                insider_tx = it.head(50).to_dict("records")
        except Exception as e:
            log.debug("insider_transactions 실패 %s: %s", ticker, e)

        return {
            "ticker": ticker,
            "major_holders": major,
            "institutional_holders": institutional,
            "insider_transactions": insider_tx,
        }
    except Exception as e:
        log.warning("US 홀더 수집 실패 %s: %s", ticker, e)
        return None


def fetch(universe: List[Dict]) -> Dict[str, dict]:
    """
    run.py 호환 진입점 - 유니버스 일괄 수집.
    내부적으로 fetch_price_data + fetch_fundamentals 를 호출한다.
    """
    if yf is None:
        log.warning("yfinance 미설치 - 빈 딕셔너리 반환")
        return {}

    tickers = [u["ticker"] for u in universe]
    if not tickers:
        return {}

    async def _gather():
        return await asyncio.gather(
            fetch_price_data(tickers),
            fetch_fundamentals(tickers),
        )

    try:
        prices, fund = asyncio.run(_gather())
    except RuntimeError:
        # 이미 실행 중인 이벤트 루프(예: Jupyter) 대응
        loop = asyncio.new_event_loop()
        try:
            prices, fund = loop.run_until_complete(_gather())
        finally:
            loop.close()

    out: Dict[str, dict] = {}
    for t in tickers:
        p = prices.get(t, {}) or {}
        f = fund.get(t, {}) or {}
        out[t] = {
            "price": p.get("history", pd.DataFrame()),
            "info": {**{k: v for k, v in p.items() if k != "history"}, **f},
        }
    log.info("US 통합 수집 완료: %d / %d", len(out), len(tickers))
    return out
