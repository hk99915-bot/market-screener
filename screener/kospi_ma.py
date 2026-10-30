"""코스피 20일선 단일 계산 (req-quant-d3a3735d, 퀀트 10/30).

정의: 종가 단순평균, 창 = 시계열 끝 n개(기본 20). 장중이면 끝 값이 '오늘 잠정가'라 창에 그 값이 들어간다
(= 확정 종가 기준선과 다름: 10/30 11:39 6,041 ≠ 10/29 확정 6,102). 그래서 소비자는 항상 이 함수로 계산하고,
표시할 때 `기준일`(창의 마지막 날짜)과 확정/잠정 여부를 같이 적는다. 값 정의는 기존 committee·views 와 동일(규칙 불변).
"""
from __future__ import annotations

import statistics as st


def sma_tail(closes: list[float], n: int = 20) -> float:
    """끝에서 n개 종가의 단순평균."""
    return st.mean(closes[-n:])


def sma_streak(closes: list[float], n: int = 20) -> int:
    """끝에서부터 종가가 (자기 포함 n일) 이동평균 위인 날이 몇 일 연속인지."""
    k = 0
    for i in range(len(closes) - 1, n - 1, -1):
        if closes[i] > sma_tail(closes[: i + 1], n):
            k += 1
        else:
            break
    return k
