import math
import statistics

import numpy as np

LOW_FPS = "Точное измерение GtG недоступно при текущей частоте камеры. Доступна только грубая оптическая оценка."

def simulate(options):
    fps = options["camera_fps"]
    a, b = options["gray_from"], options["gray_to"]
    hold, repeats = options["hold"], options["repeats"]
    rng = np.random.default_rng(17)
    samples = []
    for n in range(math.ceil(fps * hold * (2 * repeats + 1))):
        t = n / fps
        index = int(t / hold)
        level, previous = (b, a) if index % 2 else (a, b)
        y = level + ((previous - level) * math.exp(-(t - index * hold)/.015) if index else 0)
        mean = float(np.clip(y + rng.normal(0, .65), 0, 255))
        samples.append({"frame": n, "time_ns": round(t*1e9), "mean": mean,
                        "min": max(0, mean-2), "max": min(255, mean+2),
                        "gap": False, "read_ns": None, "process_ns": None})
    return samples

def analyze(samples, hold, simulated=False, timing="OpenCV read completion", exposure_ns=None):
    result = {"fps": None, "period_ms": None, "transitions": [], "summaries": {},
              "warnings": [], "timing": timing, "gtg_ms": None, "quality": "Недостаточно данных"}
    if len(samples) < 8:
        result["warnings"].append("Недостаточно кадров для анализа")
        return result
    times = np.array([s["time_ns"] for s in samples], dtype=np.int64)
    t = (times - times[0]) / 1e9
    y = np.array([s["mean"] for s in samples])
    deltas = np.diff(t)
    if not np.all(deltas > 0):
        result["warnings"].append("Временные метки кадров идут вне порядка")
        return result
    dt = float(np.median(deltas))
    fps = 1 / dt
    result["fps"] = round(fps, 2)
    result["period_ms"] = round(dt * 1000, 3)
    result["gap_count"] = sum(bool(s["gap"] or (i and deltas[i-1] > dt*1.6))
                              for i, s in enumerate(samples))
    result["warnings"].append(LOW_FPS if fps < 200 else
                              "Точный GtG требует калиброванного сенсора и проверенных временных меток.")
    result["warnings"].append("Яркость ROI в кодах камеры. Оптический момент отсчитывается от начала записи.")
    if timing == "OpenCV read completion":
        result["warnings"].append("Метки означают получение кадров на агенте. Возможны буферизация и интеграция экспозиции.")
    lo, hi = np.percentile(y, [15, 85])
    if hi - lo < 6 or hold / dt < 5:
        result["warnings"].append("Малый перепад яркости или слишком короткая выдержка уровня.")
        return result
    state = y[0] > (hi + lo) / 2
    candidate = None
    window = max(2, round(hold / dt * .18))
    for i in range(1, len(t)-1):
        switched = y[i] < lo + .35*(hi-lo) if state else y[i] > lo + .65*(hi-lo)
        if not switched:
            candidate = None
            continue
        if candidate is None:
            candidate = i
        if i - candidate < 1:
            continue
        edge = candidate
        direction = "↓" if state else "↑"
        state = not state
        candidate = None
        if edge < window*2 or edge + window*3 >= len(t):
            continue
        before = float(np.median(y[edge-window*2:edge-window]))
        after = float(np.median(y[edge+window*2:edge+window*3]))
        if abs(after-before) < 6 or (after > before) != state:
            continue
        start, end = edge-window, edge+window*2
        response = (y[start:end] - before) / (after-before)
        c10, c90 = np.flatnonzero(response >= .1), np.flatnonzero(response >= .9)
        if not len(c10) or not len(c90):
            continue
        i10, i90 = start+int(c10[0]), start+int(c90[0])
        stride = i90-i10
        gaps = any(s["gap"] for s in samples[max(0,i10-1):i90+1])
        segments = deltas[max(0,i10-1):i90]
        duration = t[i90]-t[i10]
        if segments.size:
            gaps |= bool(np.any(segments > 1.6*dt))
        bounds = None
        if stride >= 4 and not gaps and i10 > start:
            bounds = [max(0, t[i90-1]-t[i10])*1000, (t[i90]-t[i10-1])*1000]
        settled = next((k for k in range(i90, end-3) if np.all(
                        np.abs(y[k:end]-after) <= max(.05*abs(after-before), 2))), None)
        stable_ms = round((t[settled]-t[i10])*1000, 2) if (
                    settled is not None and not gaps and stride >= 4 and
                    not any(s["gap"] for s in samples[i90:end]) and
                    not np.any(deltas[i90:end-1] > 1.6*dt)) else None
        result["transitions"].append({
            "direction": direction, "detected_s": round(float(t[edge]), 6),
            "optical_10_90_ms": round(float(duration)*1000, 2) if bounds else None,
            "sampling_bounds_ms": [round(float(x), 2) for x in bounds] if bounds else None,
            "stabilization_ms": stable_ms,
        })
    for direction in ("↑", "↓"):
        group = [row for row in result["transitions"] if row["direction"] == direction]
        values = [row["optical_10_90_ms"] for row in group if row["optical_10_90_ms"] is not None]
        stabilization = [row["stabilization_ms"] for row in group if row["stabilization_ms"] is not None]
        result["summaries"][direction] = {
            "detected": len(group), "resolved": len(values),
            "median_optical_ms": statistics.median(values) if values else None,
            "spread_ms": round(max(values)-min(values), 2) if len(values) > 1 else None,
            "median_stabilization_ms": statistics.median(stabilization) if stabilization else None,
        }
    result["quality"] = ("Синтетические данные" if simulated else
                         "Грубая оптическая оценка" if result["transitions"] else "Переходы не распознаны")
    if exposure_ns:
        result["exposure_ms"] = exposure_ns/1e6
    return result
