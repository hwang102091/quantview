"""
스크리너 - LAYER1 → LAYER2
섹터별 필터(config.SECTOR_FILTERS) 적용 후 퀀트 스코어(0~100점) 산출.
결과를 data/stocks.json 에 저장한다.
"""
import json
import logging
import statistics
from typing import Any, Dict, List, Optional

from config import DATA_DIR, DOCS_DATA_DIR, UNIVERSE_DIR, get_sector_filter

log = logging.getLogger(__name__)


# ── 공개 API ───────────────────────────────────────────────────────────────

def load_universe() -> List[Dict]:
    """kr_universe.json + us_universe.json 통합 로드."""
    items: List[Dict] = []
    for fname in ("kr_universe.json", "us_universe.json"):
        path = UNIVERSE_DIR / fname
        try:
            with open(path, "r", encoding="utf-8") as f:
                items.extend(json.load(f))
        except Exception as e:
            log.warning("유니버스 로드 실패 %s: %s", fname, e)
    log.info("유니버스 로드: %d 종목", len(items))
    return items


def apply_filters(stocks: List[Dict], market_data: Dict[str, Any]) -> List[Dict]:
    """
    섹터별 필터 적용 → 통과 종목 반환.

    Args:
        stocks: 유니버스 종목 리스트
        market_data: bundle (kr_prices, us_prices, ...)
    Returns:
        필터 통과 종목 리스트
    """
    kr_prices = market_data.get("kr_prices") or {}
    us_prices = market_data.get("us_prices") or {}

    passed: List[Dict] = []
    for item in stocks:
        snap = (kr_prices if item["market"] == "kr" else us_prices).get(item["ticker"], {})
        rule = item.get("filter_override") or get_sector_filter(item.get("tag", "default"))
        if _passes_filter(item, snap, rule):
            passed.append(dict(item))

    log.info("섹터 필터 통과: %d / %d", len(passed), len(stocks))
    return passed


def score_stocks(stocks: List[Dict], market_data: Dict[str, Any]) -> List[Dict]:
    """
    통과 종목에 퀀트 스코어(0~100) 부여.

    퀀트 스코어 구성:
      밸류에이션 20pt · 모멘텀 20pt · 퀄리티 20pt · 수급 20pt · 시그널 20pt

    Returns:
        quant_score + score_detail 필드가 추가된 종목 리스트 (내림차순)
    """
    kr_prices = market_data.get("kr_prices") or {}
    us_prices = market_data.get("us_prices") or {}
    smart_money = market_data.get("smart_money") or {}
    ratings_data = market_data.get("ratings") or {}

    sector_stats = _compute_sector_stats(stocks, kr_prices, us_prices)

    form4 = smart_money.get("form4") or []
    dataroma = smart_money.get("dataroma") or {}
    congress = smart_money.get("congress") or []

    insider_tickers: set = {
        t
        for row in form4
        for t in (row.get("tickers") or [])
        if t
    }
    guru_tickers: set = {
        h["ticker"]
        for mgr in dataroma.values()
        for h in (mgr.get("holdings") or [])
        if (h.get("recent_activity") or "").strip().lower() in ("buy", "add", "new")
    }
    congress_buy: set = {
        row["ticker"]
        for row in congress
        if (row.get("transaction") or "").lower() in ("purchase", "buy") and row.get("ticker")
    }

    scored: List[Dict] = []
    for item in stocks:
        snap = (kr_prices if item["market"] == "kr" else us_prices).get(item["ticker"], {})
        info = snap.get("info") or {}
        price_df = snap.get("price")
        tag = item.get("tag", "default")

        val_s = _score_valuation(info, sector_stats.get(tag, {}))
        mom_s = _score_momentum(price_df)
        qual_s = _score_quality(info, tag)
        flow_s = _score_flow(info, item, market_data)
        sig_s = _score_signal(
            item["ticker"], insider_tickers, guru_tickers, congress_buy,
            ratings_data.get(item["ticker"]) or {},
        )

        quant_score = round(
            val_s * 0.20 + mom_s * 0.20 + qual_s * 0.20 + flow_s * 0.20 + sig_s * 0.20,
            2,
        )

        record = dict(item)
        record.update({
            "quant_score": quant_score,
            "score_detail": {
                "valuation": round(val_s, 2),
                "momentum": round(mom_s, 2),
                "quality": round(qual_s, 2),
                "flow": round(flow_s, 2),
                "signal": round(sig_s, 2),
            },
            "market_cap_bn": _safe_market_cap(snap),
            "per": info.get("trailingPE"),
            "pbr": info.get("priceToBook"),
            "roe": info.get("returnOnEquity"),
            "debt_ratio": info.get("debtToEquity"),
            "operating_margin": info.get("operatingMargins"),
        })
        scored.append(record)

    scored.sort(key=lambda x: x.get("quant_score") or 0, reverse=True)
    return scored


def save(stocks: List[Dict], updated_at: str) -> None:
    """data/stocks.json 및 docs/data/stocks.json 저장."""
    payload = {"updated_at": updated_at, "stocks": stocks}
    for d in (DATA_DIR, DOCS_DATA_DIR):
        d.mkdir(parents=True, exist_ok=True)
        path = d / "stocks.json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
            log.info("stocks.json 저장: %s", path)
        except Exception as e:
            log.error("stocks.json 저장 실패 %s: %s", path, e)


def run(universe: List[Dict], bundle: Dict[str, Any], target_size: int = 1000) -> List[Dict]:
    """run.py 호환 진입점 — 필터 → 스코어 → 상위 target_size 반환."""
    filtered = apply_filters(universe, bundle)
    scored = score_stocks(filtered, bundle)
    result = scored[:target_size]
    log.info("스크리너 완료: 전체 %d → 필터 %d → top %d",
             len(universe), len(filtered), len(result))
    return result


# ── 필터 ──────────────────────────────────────────────────────────────────

def _passes_filter(item: Dict, snap: Dict, rule: Dict) -> bool:
    info = snap.get("info") or {}
    price_df = snap.get("price")
    tag = item.get("tag", "default")

    if price_df is None or getattr(price_df, "empty", True):
        return False

    mcap = _safe_market_cap(snap)
    min_mcap = rule.get("min_market_cap_bn")
    if min_mcap and (mcap is None or mcap < min_mcap):
        return False

    turnover = _avg_turnover_bn(price_df)
    min_to = rule.get("min_turnover_bn")
    if min_to and (turnover is None or turnover < min_to):
        return False

    if tag == "finance":
        # 금융주: 부채비율 미적용, ROE 5% 이상
        roe = info.get("returnOnEquity")
        if roe is not None and roe < 0.05:
            return False
    elif tag in ("bio", "nuclear"):
        # 바이오·SMR: 적자 허용, 현금 12개월치 이상
        cash = info.get("totalCash") or info.get("cash")
        burn = info.get("operatingCashflow")
        if cash and burn and burn < 0:
            months_cash = (cash / abs(burn)) * 12
            if months_cash < 12:
                return False
    else:
        max_debt = rule.get("max_debt_ratio")
        if max_debt is not None:
            debt = info.get("debtToEquity")
            if debt is not None and debt > max_debt:
                return False
        if rule.get("require_profit"):
            eps = info.get("trailingEps")
            if eps is not None and eps <= 0:
                return False

    per = info.get("trailingPE")
    if per is not None:
        if rule.get("min_per") is not None and per < rule["min_per"]:
            return False
        if rule.get("max_per") is not None and per > rule["max_per"]:
            return False

    return True


# ── 스코어 계산 ───────────────────────────────────────────────────────────

def _compute_sector_stats(
    stocks: List[Dict], kr_prices: Dict, us_prices: Dict
) -> Dict[str, Dict]:
    """섹터별 PER·PBR 중앙값 계산 (상대 밸류에이션 기준점)."""
    from collections import defaultdict

    tag_pers: Dict[str, List[float]] = defaultdict(list)
    tag_pbrs: Dict[str, List[float]] = defaultdict(list)

    for item in stocks:
        snap = (kr_prices if item["market"] == "kr" else us_prices).get(item["ticker"], {})
        info = (snap.get("info") or {})
        tag = item.get("tag", "default")
        per = info.get("trailingPE")
        pbr = info.get("priceToBook")
        if per and 0 < per < 300:
            tag_pers[tag].append(per)
        if pbr and 0 < pbr < 50:
            tag_pbrs[tag].append(pbr)

    result: Dict[str, Dict] = {}
    all_tags = set(tag_pers) | set(tag_pbrs)
    for tag in all_tags:
        result[tag] = {
            "median_per": statistics.median(tag_pers[tag]) if tag_pers[tag] else None,
            "median_pbr": statistics.median(tag_pbrs[tag]) if tag_pbrs[tag] else None,
        }
    return result


def _score_valuation(info: Dict, sector: Dict) -> float:
    """밸류에이션 0~100 — PER·PBR 섹터 중앙값 대비."""
    scores: List[float] = []
    per = info.get("trailingPE")
    pbr = info.get("priceToBook")
    med_per = sector.get("median_per")
    med_pbr = sector.get("median_pbr")

    if per and per > 0 and med_per:
        scores.append(_clip(med_per / per * 50, 0, 100))
    if pbr and pbr > 0 and med_pbr:
        scores.append(_clip(med_pbr / pbr * 50, 0, 100))

    return statistics.mean(scores) if scores else 50.0


def _score_momentum(price_df) -> float:
    """모멘텀 0~100 — 1M(30%)·3M(40%)·6M(30%) 수익률 가중 합산."""
    if price_df is None or getattr(price_df, "empty", True):
        return 50.0
    try:
        close = price_df["Close"]
        weighted_sum = 0.0
        weight_total = 0.0
        for n, w in ((21, 0.3), (63, 0.4), (126, 0.3)):
            if len(close) > n:
                r = (close.iloc[-1] / close.iloc[-n] - 1) * 100
                weighted_sum += r * w
                weight_total += w
        if weight_total == 0:
            return 50.0
        avg_ret = weighted_sum / weight_total
        return _clip(avg_ret + 50, 0, 100)
    except Exception:
        return 50.0


def _score_quality(info: Dict, tag: str) -> float:
    """퀄리티 0~100 — ROE·영업이익률·부채비율."""
    scores: List[float] = []

    roe = info.get("returnOnEquity")
    if roe is not None:
        scores.append(_clip(roe * 300, 0, 100))  # ROE 33% → 100점

    margin = info.get("operatingMargins") or info.get("profitMargins")
    if margin is not None:
        scores.append(_clip(margin * 400, 0, 100))  # 25% 이익률 → 100점

    if tag != "finance":
        debt = info.get("debtToEquity")
        if debt is not None:
            scores.append(_clip(100 - debt / 3, 0, 100))  # 부채비율 낮을수록 고점

    return statistics.mean(scores) if scores else 50.0


def _score_flow(info: Dict, item: Dict, market_data: Dict) -> float:
    """
    수급 0~100.
    · KR: kr_prices 내 foreign_net_buy / inst_net_buy 활용
    · US: heldPercentInstitutions + shortRatio 활용
    """
    scores: List[float] = []

    inst_pct = info.get("heldPercentInstitutions")
    if inst_pct is not None:
        scores.append(_clip(inst_pct * 100, 0, 100))

    short_ratio = info.get("shortRatio")
    if short_ratio is not None:
        scores.append(_clip(100 - short_ratio * 10, 0, 100))

    if item.get("market") == "kr":
        kr_snap = (market_data.get("kr_prices") or {}).get(item["ticker"], {})
        foreign_net = kr_snap.get("foreign_net_buy")
        inst_net = kr_snap.get("inst_net_buy")
        if foreign_net is not None:
            scores.append(_clip(50 + foreign_net / 1e8, 0, 100))
        if inst_net is not None:
            scores.append(_clip(50 + inst_net / 1e8, 0, 100))

    return statistics.mean(scores) if scores else 50.0


def _score_signal(
    ticker: str,
    insider_tickers: set,
    guru_tickers: set,
    congress_buy: set,
    rating: Dict,
) -> float:
    """시그널 0~100 — 내부자·슈퍼인베스터·의회거래·컨센서스."""
    scores: List[float] = []

    if ticker in insider_tickers:
        scores.append(85.0)
    if ticker in guru_tickers:
        scores.append(80.0)
    if ticker in congress_buy:
        scores.append(75.0)

    buy = rating.get("buy") or 0
    hold = rating.get("hold") or 0
    sell = rating.get("sell") or 0
    total = buy + hold + sell
    if total > 0:
        scores.append(_clip(buy / total * 100, 0, 100))

    return statistics.mean(scores) if scores else 50.0


# ── 유틸 ─────────────────────────────────────────────────────────────────

def _safe_market_cap(snap: Dict) -> Optional[float]:
    info = snap.get("info") or {}
    mcap = info.get("marketCap")
    if mcap is None:
        return None
    try:
        return float(mcap) / 1_000_000_000
    except Exception:
        return None


def _avg_turnover_bn(price_df) -> Optional[float]:
    try:
        recent = price_df.tail(20)
        if recent.empty:
            return None
        return float((recent["Close"] * recent["Volume"]).mean()) / 1_000_000_000
    except Exception:
        return None


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(x)))
