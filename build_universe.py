"""
유니버스 자동 생성 스크립트

KR: Naver Finance 전종목 스크래핑 (pykrx bulk API가 KRX 변경으로 미동작 시 대체)
    - pykrx get_market_ticker_list() 시도 → 실패 시 Naver Finance fallback
US: Wikipedia에서 S&P 500 + NASDAQ-100 파싱 (User-Agent 헤더 포함)
"""
import json
import re
import sys
import time
from io import StringIO
from pathlib import Path

import requests
import pandas as pd

UNIVERSE_DIR = Path(__file__).parent / "universe"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
}

# ── KR 섹터 키워드 → tag (선언 순서가 우선순위) ──────────────────────────────
KR_SECTOR_RULES = [
    ("semi",         ["반도체", "하이닉스", "실리콘", "마이크로"]),
    ("battery",      ["에너지솔루션", "배터리", "이차전지", "전지"]),
    ("bio",          ["바이오", "제약", "헬스", "메디", "파마"]),
    ("defense",      ["항공", "방산", "우주", "로템", "한화"]),
    ("it",           ["카카오", "네이버", "게임", "소프트"]),
    ("finance",      ["은행", "증권", "보험", "금융", "캐피탈"]),
    ("shipbuilding", ["중공업", "조선", "해양"]),
]

TAG_TO_SECTOR_KR = {
    "semi":         "반도체",
    "battery":      "2차전지",
    "bio":          "바이오",
    "defense":      "방산",
    "it":           "IT",
    "finance":      "금융",
    "shipbuilding": "조선",
    "consumer":     "소비재",
}


def _tag_kr(name: str) -> str:
    for tag, keywords in KR_SECTOR_RULES:
        if any(kw in name for kw in keywords):
            return tag
    return "consumer"


# ── pykrx 시도 ─────────────────────────────────────────────────────────────
def _try_pykrx(market: str, ref_str: str):
    """pykrx get_market_ticker_list 시도. 실패 또는 빈 결과 시 None 반환."""
    try:
        from pykrx import stock as pyk
        tickers = pyk.get_market_ticker_list(date=ref_str, market=market)
        if tickers and len(tickers) > 0:
            print(f"  pykrx {market}: {len(tickers)} tickers")
            return list(tickers)
        print(f"  pykrx {market}: empty (KRX API 변경으로 Naver fallback 사용)")
        return None
    except Exception as e:
        print(f"  pykrx {market} 실패: {e} → Naver fallback")
        return None


def _get_pykrx_name(ticker: str):
    """pykrx 개별 종목명 조회 (개별 조회는 동작)."""
    try:
        from pykrx import stock as pyk
        name = pyk.get_market_ticker_name(ticker)
        return name if name else None
    except Exception:
        return None


# ── Naver Finance 스크래핑 ────────────────────────────────────────────────────
def _scrape_naver_market(sosok: str, market_name: str) -> dict:
    """
    Naver Finance sise_market_sum 전 페이지 스크래핑.
    Returns {ticker: name}
    """
    base_url = "https://finance.naver.com/sise/sise_market_sum.naver"
    naver_headers = {**HEADERS, "Referer": "https://finance.naver.com"}
    result = {}

    # 1페이지로 마지막 페이지 번호 파악
    r = requests.get(base_url, params={"sosok": sosok, "page": "1"},
                     headers=naver_headers, timeout=15)
    r.raise_for_status()

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(r.content, "html.parser")
    pgRR = soup.find("td", class_="pgRR")
    last_page = 1
    if pgRR and pgRR.find("a"):
        m = re.search(r"page=(\d+)", pgRR.find("a").get("href", ""))
        if m:
            last_page = int(m.group(1))

    print(f"  Naver {market_name}: {last_page} pages 스크래핑 중...")

    def _parse_page(html_bytes) -> dict:
        s = BeautifulSoup(html_bytes, "html.parser")
        t = s.find("table", class_="type_2")
        rows = {}
        if t:
            for tr in t.find_all("tr"):
                a = tr.find("a", href=re.compile(r"code=\d{6}"))
                if a:
                    code = re.search(r"code=(\d{6})", a["href"]).group(1)
                    name = a.text.strip()
                    if code and name:
                        rows[code] = name
        return rows

    result.update(_parse_page(r.content))

    for page in range(2, last_page + 1):
        try:
            r2 = requests.get(base_url, params={"sosok": sosok, "page": str(page)},
                              headers=naver_headers, timeout=15)
            result.update(_parse_page(r2.content))
            if page % 10 == 0:
                print(f"    page {page}/{last_page} ({len(result)} tickers)")
            time.sleep(0.1)
        except Exception as e:
            print(f"    page {page} 실패: {e}")

    return result


def build_kr_universe() -> list:
    print("KR 유니버스 생성 중...")

    from datetime import date, timedelta
    ref = date.today()
    while ref.weekday() >= 5:
        ref -= timedelta(days=1)
    ref_str = ref.strftime("%Y%m%d")

    # pykrx 시도 → 실패 시 Naver scraping
    kospi_tickers = _try_pykrx("KOSPI", ref_str)
    kosdaq_tickers = _try_pykrx("KOSDAQ", ref_str)

    use_pykrx_names = False
    if kospi_tickers is not None and kosdaq_tickers is not None:
        # pykrx 성공: names도 pykrx로
        seen = set()
        all_tickers = []
        for t in kospi_tickers + kosdaq_tickers:
            if t not in seen:
                seen.add(t)
                all_tickers.append(t)
        ticker_names = {}
        for t in all_tickers:
            ticker_names[t] = _get_pykrx_name(t) or t
        use_pykrx_names = True
    else:
        # Naver Finance fallback
        kospi_map = _scrape_naver_market("0", "KOSPI")
        kosdaq_map = _scrape_naver_market("1", "KOSDAQ")
        ticker_names = {**kospi_map}
        for k, v in kosdaq_map.items():
            if k not in ticker_names:
                ticker_names[k] = v

    print(f"  총 종목 수: {len(ticker_names)}")

    universe = []
    for ticker, name in ticker_names.items():
        tag = _tag_kr(name)
        universe.append({
            "ticker": ticker,
            "name": name,
            "sector": TAG_TO_SECTOR_KR[tag],
            "tag": tag,
            "market": "kr",
            "filter_override": None,
        })

    return universe


# ── US GICS → tag ────────────────────────────────────────────────────────────
def _map_us_tag(gics_sector: str, sub_industry: str = "") -> str:
    s = (gics_sector or "").strip()
    sub = (sub_industry or "").lower()
    if s == "Information Technology":
        return "semi" if "semiconductor" in sub else "cloud"
    if s == "Health Care":
        return "bio"
    if s == "Financials":
        return "finance"
    if s == "Energy":
        return "energy"
    if s == "Industrials":
        return "defense" if ("aerospace" in sub or "defense" in sub) else "materials"
    if s == "Materials":
        return "materials"
    return "consumer"


def _fetch_wiki_tables(url: str):
    """User-Agent 헤더 포함해서 Wikipedia 테이블 파싱."""
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return pd.read_html(StringIO(r.text), flavor="lxml")


def _get_col(df: pd.DataFrame, candidates: list):
    for c in candidates:
        if c in df.columns:
            return c
    return None


def build_us_universe() -> list:
    print("US 유니버스 생성 중 (Wikipedia)...")
    rows: dict = {}

    # ── S&P 500 ──────────────────────────────────────────────────────────────
    try:
        tables = _fetch_wiki_tables(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        )
        sp_df = tables[0]
        sym_col  = _get_col(sp_df, ["Symbol", "Ticker symbol", "Ticker"])
        name_col = _get_col(sp_df, ["Security", "Company", "Name"])
        gics_col = _get_col(sp_df, ["GICS Sector", "Sector"])
        sub_col  = _get_col(sp_df, ["GICS Sub-Industry", "Sub-Industry"])

        for _, row in sp_df.iterrows():
            symbol = str(row[sym_col] if sym_col else "").strip().replace(".", "-")
            if not symbol or symbol == "nan":
                continue
            gics = str(row[gics_col] if gics_col else "").strip()
            sub  = str(row[sub_col]  if sub_col  else "").strip()
            name = str(row[name_col] if name_col else symbol).strip()
            tag  = _map_us_tag(gics, sub)
            rows[symbol] = {
                "ticker": symbol,
                "name": name,
                "sector": gics or "Other",
                "tag": tag,
                "market": "us",
                "filter_override": None,
            }
        print(f"  S&P 500: {len(sp_df)} rows parsed, {len(rows)} tickers")
    except Exception as e:
        print(f"  S&P 500 실패: {e}", file=sys.stderr)

    # ── NASDAQ-100 ────────────────────────────────────────────────────────────
    try:
        tables = _fetch_wiki_tables("https://en.wikipedia.org/wiki/Nasdaq-100")
        ndx_df = None
        for t in tables:
            col_lower = {str(c).lower() for c in t.columns}
            if "ticker" in col_lower or "symbol" in col_lower:
                ndx_df = t
                break

        if ndx_df is not None:
            sym_col  = _get_col(ndx_df, ["Ticker", "Symbol", "ticker", "symbol"])
            name_col = _get_col(ndx_df, ["Company", "Security", "Name"])
            gics_col = _get_col(ndx_df, ["GICS Sector", "Sector"])
            sub_col  = _get_col(ndx_df, ["GICS Sub-Industry", "Sub-Industry"])

            added = 0
            for _, row in ndx_df.iterrows():
                symbol = str(row[sym_col] if sym_col else "").strip().replace(".", "-")
                if not symbol or symbol == "nan" or symbol in rows:
                    continue
                gics = str(row[gics_col] if gics_col else "").strip()
                sub  = str(row[sub_col]  if sub_col  else "").strip()
                name = str(row[name_col] if name_col else symbol).strip()
                tag  = _map_us_tag(gics, sub)
                rows[symbol] = {
                    "ticker": symbol,
                    "name": name,
                    "sector": gics or "Other",
                    "tag": tag,
                    "market": "us",
                    "filter_override": None,
                }
                added += 1
            print(f"  NASDAQ-100: {added} 신규 추가 (중복 제외)")
        else:
            print("  NASDAQ-100 테이블 미발견", file=sys.stderr)
    except Exception as e:
        print(f"  NASDAQ-100 실패: {e}", file=sys.stderr)

    result = list(rows.values())
    print(f"  US 완료: {len(result)} tickers (중복 제거 후)")
    return result


if __name__ == "__main__":
    UNIVERSE_DIR.mkdir(exist_ok=True)

    kr = build_kr_universe()
    with open(UNIVERSE_DIR / "kr_universe.json", "w", encoding="utf-8") as f:
        json.dump(kr, f, ensure_ascii=False, indent=2)
    print(f"\nkr_universe.json 저장: {len(kr)} 종목")

    us = build_us_universe()
    with open(UNIVERSE_DIR / "us_universe.json", "w", encoding="utf-8") as f:
        json.dump(us, f, ensure_ascii=False, indent=2)
    print(f"us_universe.json 저장: {len(us)} 종목")
