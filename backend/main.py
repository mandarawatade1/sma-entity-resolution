import io
import json
from datetime import datetime, timezone

import pandas as pd
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from db import init_db, get_conn, row_to_dict
from normalize import normalize_record, CANONICAL_FIELDS
from resolution import cluster_records

app = FastAPI(title="Multi-Database Entity Resolution API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- Datasets ----------

@app.post("/api/datasets")
async def upload_dataset(
    name: str = Form(...),
    mapping: str = Form(...),  # JSON: {"name": "full_name", "email": "email_addr", ...}
    file: UploadFile = File(...),
):
    content = await file.read()
    try:
        if file.filename.lower().endswith(".json"):
            df = pd.read_json(io.BytesIO(content))
        else:
            df = pd.read_csv(io.BytesIO(content), dtype=str, keep_default_na=False)
    except Exception as exc:
        raise HTTPException(400, f"Could not parse file: {exc}")

    try:
        field_map = json.loads(mapping)
    except json.JSONDecodeError:
        raise HTTPException(400, "mapping must be valid JSON")

    columns = list(df.columns)
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO datasets (name, uploaded_at, row_count, columns_json, mapping_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, now(), len(df), json.dumps(columns), json.dumps(field_map)),
        )
        dataset_id = cur.lastrowid

        rows_to_insert = []
        for idx, row in df.iterrows():
            raw = {col: row[col] for col in columns}
            canonical = {
                field: raw.get(source_col, "")
                for field, source_col in field_map.items()
                if field in CANONICAL_FIELDS
            }
            normalized = normalize_record(canonical)
            rows_to_insert.append(
                (dataset_id, int(idx), json.dumps(raw), json.dumps(normalized))
            )
        conn.executemany(
            "INSERT INTO records (dataset_id, row_index, raw_json, normalized_json) "
            "VALUES (?, ?, ?, ?)",
            rows_to_insert,
        )

    return {"dataset_id": dataset_id, "rows_ingested": len(df), "columns": columns}


@app.get("/api/datasets")
def list_datasets():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM datasets ORDER BY id DESC").fetchall()
        result = []
        for r in rows:
            d = row_to_dict(r)
            d["columns"] = json.loads(d.pop("columns_json"))
            d["mapping"] = json.loads(d.pop("mapping_json"))
            result.append(d)
        return result


@app.delete("/api/datasets/{dataset_id}")
def delete_dataset(dataset_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM records WHERE dataset_id = ?", (dataset_id,))
        conn.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))
    return {"ok": True}


# ---------- Resolution ----------

@app.post("/api/resolve")
def run_resolution(threshold: float = 85.0):
    with get_conn() as conn:
        rows = conn.execute("SELECT id, normalized_json FROM records").fetchall()
        if not rows:
            raise HTTPException(400, "No records ingested yet")
        records = {r["id"]: json.loads(r["normalized_json"]) for r in rows}

        clusters, pairs = cluster_records(records, threshold=threshold)

        # Reset previous clustering state.
        conn.execute("DELETE FROM master_repository")
        conn.execute("DELETE FROM clusters")
        conn.execute("UPDATE records SET cluster_id = NULL")

        score_by_pair = {}
        for a, b, score in pairs:
            score_by_pair.setdefault(a, []).append(score)
            score_by_pair.setdefault(b, []).append(score)

        auto_confirmed = 0
        needs_review = 0
        for root, member_ids in clusters.items():
            max_score = max(
                [s for rid in member_ids for s in score_by_pair.get(rid, [0])],
                default=0.0,
            )
            cur = conn.execute(
                "INSERT INTO clusters (status, max_score, created_at) VALUES (?, ?, ?)",
                ("pending" if len(member_ids) > 1 else "auto", max_score, now()),
            )
            cluster_id = cur.lastrowid
            conn.executemany(
                "UPDATE records SET cluster_id = ? WHERE id = ?",
                [(cluster_id, rid) for rid in member_ids],
            )

            if len(member_ids) == 1:
                rid = member_ids[0]
                raw = json.loads(
                    conn.execute("SELECT raw_json FROM records WHERE id = ?", (rid,)).fetchone()["raw_json"]
                )
                normalized = records[rid]
                merged = {f: normalized.get(f, "") for f in CANONICAL_FIELDS}
                conn.execute(
                    "INSERT INTO master_repository (cluster_id, merged_json, source_record_ids, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (cluster_id, json.dumps(merged), json.dumps([rid]), now()),
                )
                auto_confirmed += 1
            else:
                needs_review += 1

        return {
            "clusters_found": len(clusters),
            "duplicate_groups_needing_review": needs_review,
            "auto_added_unique_records": auto_confirmed,
            "candidate_pairs_scored": len(pairs),
        }


@app.get("/api/clusters")
def list_clusters(status: str = "pending"):
    with get_conn() as conn:
        clusters = conn.execute(
            "SELECT * FROM clusters WHERE status = ? ORDER BY max_score DESC", (status,)
        ).fetchall()
        result = []
        for c in clusters:
            members = conn.execute(
                "SELECT r.id, r.dataset_id, r.raw_json, r.normalized_json, d.name as dataset_name "
                "FROM records r JOIN datasets d ON d.id = r.dataset_id WHERE r.cluster_id = ?",
                (c["id"],),
            ).fetchall()
            result.append({
                "cluster_id": c["id"],
                "max_score": c["max_score"],
                "members": [
                    {
                        "record_id": m["id"],
                        "dataset_id": m["dataset_id"],
                        "dataset_name": m["dataset_name"],
                        "raw": json.loads(m["raw_json"]),
                        "normalized": json.loads(m["normalized_json"]),
                    }
                    for m in members
                ],
            })
        return result


@app.post("/api/clusters/{cluster_id}/decision")
def decide_cluster(cluster_id: int, payload: dict):
    """payload: {"action": "confirm"|"reject", "merged_fields": {field: value}}"""
    action = payload.get("action")
    with get_conn() as conn:
        cluster = conn.execute("SELECT * FROM clusters WHERE id = ?", (cluster_id,)).fetchone()
        if not cluster:
            raise HTTPException(404, "Cluster not found")

        member_ids = [
            r["id"] for r in conn.execute(
                "SELECT id FROM records WHERE cluster_id = ?", (cluster_id,)
            ).fetchall()
        ]

        if action == "confirm":
            merged_fields = payload.get("merged_fields") or {}
            conn.execute(
                "INSERT INTO master_repository (cluster_id, merged_json, source_record_ids, created_at) "
                "VALUES (?, ?, ?, ?)",
                (cluster_id, json.dumps(merged_fields), json.dumps(member_ids), now()),
            )
            conn.execute("UPDATE clusters SET status = 'confirmed' WHERE id = ?", (cluster_id,))
        elif action == "reject":
            # Treat each member as its own distinct master record.
            for rid in member_ids:
                normalized = json.loads(
                    conn.execute("SELECT normalized_json FROM records WHERE id = ?", (rid,)).fetchone()["normalized_json"]
                )
                conn.execute(
                    "INSERT INTO master_repository (cluster_id, merged_json, source_record_ids, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (cluster_id, json.dumps(normalized), json.dumps([rid]), now()),
                )
            conn.execute("UPDATE clusters SET status = 'rejected' WHERE id = ?", (cluster_id,))
        else:
            raise HTTPException(400, "action must be 'confirm' or 'reject'")

    return {"ok": True}


# ---------- Master repository ----------

@app.get("/api/repository")
def get_repository(limit: int = 100, offset: int = 0):
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM master_repository").fetchone()["c"]
        rows = conn.execute(
            "SELECT * FROM master_repository ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)
        ).fetchall()
        result = []
        for r in rows:
            d = row_to_dict(r)
            d["merged"] = json.loads(d.pop("merged_json"))
            d["source_record_ids"] = json.loads(d.pop("source_record_ids"))
            result.append(d)
        return {"total": total, "items": result}


@app.get("/api/repository/export")
def export_repository():
    with get_conn() as conn:
        rows = conn.execute("SELECT merged_json FROM master_repository").fetchall()
    records = [json.loads(r["merged_json"]) for r in rows]
    df = pd.DataFrame(records, columns=CANONICAL_FIELDS)
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=master_repository.csv"},
    )


@app.get("/api/stats")
def stats():
    with get_conn() as conn:
        return {
            "datasets": conn.execute("SELECT COUNT(*) c FROM datasets").fetchone()["c"],
            "records": conn.execute("SELECT COUNT(*) c FROM records").fetchone()["c"],
            "pending_clusters": conn.execute(
                "SELECT COUNT(*) c FROM clusters WHERE status = 'pending'"
            ).fetchone()["c"],
            "master_records": conn.execute(
                "SELECT COUNT(*) c FROM master_repository"
            ).fetchone()["c"],
        }


frontend_dir = Path(__file__).parent.parent / "frontend"
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
