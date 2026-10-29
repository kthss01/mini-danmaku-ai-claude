"""고정 평가 세트(configs/eval-set-*.json)를 실행 순서가 정해진 에피소드 목록으로 펼친다.

실행기(#20)가 이 목록을 그대로 따르면 정책이 번갈아 실행되고 시드·반복이 기록된다.
"""


def expand(evalset, mode="seeded", include_holdout=False):
    pols = evalset["policies"]
    rows = []

    def add(scn, policy, seed, purpose, rep):
        rows.append({"order": len(rows) + 1, "policy": policy, "scenario": scn, "seed": seed,
                     "seed_control": "set" if seed is not None else "random", "purpose": purpose, "repeat_index": rep})

    dev = evalset["dev"]["scenario"]
    if mode == "uncontrolled":
        n = evalset["modes"]["uncontrolled"]["episodes_per_policy"]
        for i in range(n):
            for p in pols:
                add(dev, p, None, "dev_uncontrolled", i + 1)
    elif mode == "seeded":
        m = evalset["modes"]["seeded"]
        seeds = [m["seed_base"] + i for i in range(m["seed_count"])]
        for s in seeds:
            for _ in range(m["episodes_per_seed"]):
                for p in pols:
                    add(dev, p, s, "dev_seeded", 1)
        probe = m["determinism_probe"]
        ps = seeds[probe["seed_index"]]
        for r in range(probe["repeats"]):
            for p in pols:
                add(dev, p, ps, "determinism_probe", r + 1)
    else:
        raise ValueError(f"알 수 없는 mode {mode!r}")
    if include_holdout:
        for h in evalset["holdout"]:
            for p in pols:
                add(h["scenario"], p, None, "holdout:" + h["label"], 1)
    return rows
