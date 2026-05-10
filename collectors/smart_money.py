"""
스마트머니 추적 수집기
- 미국: 13F 공시 (SEC EDGAR), 다크풀 거래량
- 한국: 외국인·기관 순매수 (KRX)
- 옵션 시장: 대량 옵션 플로우 (unusual options activity)
"""
import logging
from typing import Dict, Any

log = logging.getLogger(__name__)


def fetch() -> Dict[str, Any]:
    """
    스마트머니 시그널 통합 dict 반환.

    Returns:
      {
        "us_13f": {...},          # 주요 헤지펀드 보유 변동
        "kr_foreign": {...},      # 한국 외국인 순매수 상위
        "kr_institution": {...},  # 한국 기관 순매수 상위
        "options_flow": [...],    # unusual options activity
      }
    """
    out: Dict[str, Any] = {
        "us_13f": _fetch_13f_placeholder(),
        "kr_foreign": _fetch_kr_foreign_placeholder(),
        "kr_institution": _fetch_kr_inst_placeholder(),
        "options_flow": _fetch_options_flow_placeholder(),
    }
    return out


def _fetch_13f_placeholder() -> Dict[str, Any]:
    """SEC EDGAR 13F-HR 분기 보고 파싱 - 추후 구현."""
    # TODO: whalewisdom 또는 EDGAR 직접 파싱
    return {}


def _fetch_kr_foreign_placeholder() -> Dict[str, Any]:
    """KRX 외국인 순매수 상위 - 추후 구현."""
    # TODO: pykrx 또는 KRX 정보데이터시스템
    return {}


def _fetch_kr_inst_placeholder() -> Dict[str, Any]:
    """KRX 기관 순매수 상위 - 추후 구현."""
    return {}


def _fetch_options_flow_placeholder() -> list:
    """대량 옵션 플로우 - 추후 구현 (CBOE/유료 벤더)."""
    return []
