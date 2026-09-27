"""Entity resolution: blocking + fuzzy scoring + union-find clustering."""
from collections import defaultdict
from rapidfuzz import fuzz

FIELD_WEIGHTS = {
    "name": 0.35,
    "email": 0.25,
    "phone": 0.20,
    "address": 0.15,
    "company": 0.05,
}


class UnionFind:
    def __init__(self, ids):
        self.parent = {i: i for i in ids}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def _blocking_keys(record: dict):
    """Cheap keys that must share a value for two records to even be compared."""
    keys = []
    name = record.get("name", "")
    if name:
        keys.append(("name3", name[:3]))
    email = record.get("email", "")
    if email:
        keys.append(("email", email))
    phone = record.get("phone", "")
    if phone:
        keys.append(("phone", phone))
    zip_code = record.get("zip", "")
    if zip_code and name:
        keys.append(("zipname", zip_code + name[:1]))
    return keys or [("none", "")]


def pair_score(a: dict, b: dict) -> float:
    total_weight = 0.0
    score = 0.0
    for field, weight in FIELD_WEIGHTS.items():
        va, vb = a.get(field, ""), b.get(field, "")
        if not va or not vb:
            continue
        total_weight += weight
        if field in ("email", "phone"):
            sim = 100.0 if va == vb else fuzz.ratio(va, vb)
        else:
            sim = fuzz.token_sort_ratio(va, vb)
        score += weight * sim
    if total_weight == 0:
        return 0.0
    return score / total_weight


def find_candidate_pairs(records: dict):
    """records: {record_id: normalized_dict}. Returns [(id_a, id_b, score), ...]."""
    blocks = defaultdict(list)
    for rid, rec in records.items():
        for key in _blocking_keys(rec):
            blocks[key].append(rid)

    seen_pairs = set()
    scored_pairs = []
    for key, ids in blocks.items():
        if key[0] == "none" or len(ids) < 2:
            continue
        if len(ids) > 500:
            ids = ids[:500]  # guard against pathological blocks
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = ids[i], ids[j]
                pair = (a, b) if a < b else (b, a)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                score = pair_score(records[a], records[b])
                if score > 0:
                    scored_pairs.append((pair[0], pair[1], score))
    return scored_pairs


def cluster_records(records: dict, threshold: float = 85.0):
    """Returns (clusters, scored_pairs) where clusters: {root_id: [record_ids]}."""
    pairs = find_candidate_pairs(records)
    uf = UnionFind(records.keys())
    for a, b, score in pairs:
        if score >= threshold:
            uf.union(a, b)

    clusters = defaultdict(list)
    for rid in records:
        clusters[uf.find(rid)].append(rid)
    return clusters, pairs
