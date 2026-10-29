"""백분위수·Wilson 구간 등 통계 도구 (표준 라이브러리)."""
import math


def percentile(values, p):
    """nearest-rank 방식. 빈 입력이면 None."""
    if not values:
        return None
    s = sorted(values)
    k = max(1, math.ceil(p / 100.0 * len(s)))
    return s[min(k, len(s)) - 1]


def mean(values):
    return (sum(values) / len(values)) if values else None


def dist(values):
    """n, mean, p50, min, max. 빈 입력이면 n=0과 None들."""
    if not values:
        return {"n": 0, "mean": None, "p50": None, "min": None, "max": None}
    return {"n": len(values), "mean": round(mean(values), 4), "p50": percentile(values, 50),
            "min": min(values), "max": max(values)}


def wilson(k, n, z=1.96):
    """Wilson 점수 구간. n=0이면 None. 에피소드가 서로 독립이라는 가정에서만 맞는다."""
    if n <= 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [round(max(0.0, center - half), 4), round(min(1.0, center + half), 4)]


def rate(k, n):
    return {"k": k, "n": n, "rate": (round(k / n, 4) if n else None), "wilson95": wilson(k, n)}
