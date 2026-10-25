"""Run-scoped SQLite learning store for published forecast calibration.

Bound to the exact cloud endpoint hash; refuses cross-run reuse. No credentials
are stored. Inputs are only this run's fetched forecasts and published history.
"""
from __future__ import annotations
import hashlib, json, math, sqlite3
from datetime import datetime, timezone
from pathlib import Path

HOUR = 3600.0

def iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def lead_bucket(hours):
    return max(0, min(3, int(max(0.0, hours) // 6.0)))

class RunMemory:
    SCHEMA = "1"
    def __init__(self, path: Path, endpoint: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_hash = hashlib.sha256(endpoint.encode()).hexdigest()
        self.db = sqlite3.connect(self.path, timeout=15)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS forecast_points(
          area TEXT NOT NULL, fetched_at TEXT NOT NULL, valid_at TEXT NOT NULL,
          intensity REAL NOT NULL, updated_at TEXT,
          PRIMARY KEY(area,fetched_at,valid_at));
        CREATE INDEX IF NOT EXISTS forecast_match ON forecast_points(area,valid_at,fetched_at);
        CREATE TABLE IF NOT EXISTS observations(
          area TEXT NOT NULL, valid_at TEXT NOT NULL, seen_at TEXT NOT NULL,
          intensity REAL NOT NULL, PRIMARY KEY(area,valid_at));
        CREATE TABLE IF NOT EXISTS errors(
          area TEXT NOT NULL, valid_at TEXT NOT NULL, lead_bucket INTEGER NOT NULL,
          ratio REAL NOT NULL, seen_at TEXT NOT NULL,
          PRIMARY KEY(area,valid_at,lead_bucket));
        CREATE TABLE IF NOT EXISTS status_samples(
          virtual_time TEXT PRIMARY KEY, run_state TEXT NOT NULL, qualification TEXT NOT NULL,
          delivered INTEGER NOT NULL, total INTEGER NOT NULL, workloads_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(
          id INTEGER PRIMARY KEY AUTOINCREMENT, virtual_time TEXT NOT NULL,
          kind TEXT NOT NULL, workload_id TEXT, payload TEXT NOT NULL);
        """)
        self.db.commit()
        meta = dict(self.db.execute("SELECT key,value FROM metadata"))
        if meta and meta.get("run_hash") != self.run_hash:
            self.db.close()
            raise ValueError("SQLite memory belongs to another simulation run; use a new --memory-db path")
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO metadata VALUES('run_hash',?)", (self.run_hash,))
            self.db.execute("INSERT OR REPLACE INTO metadata VALUES('schema',?)", (self.SCHEMA,))

    def close(self):
        self.db.commit(); self.db.close()

    def record_forecast(self, area, fetched_at, points, updated_at=None):
        rows=[(area,iso(fetched_at),iso(valid),float(value),updated_at) for valid,value in points]
        with self.db:
            self.db.executemany("INSERT OR REPLACE INTO forecast_points VALUES(?,?,?,?,?)",rows)

    def record_history(self, area, seen_at, points):
        inserted=0; seen=iso(seen_at)
        with self.db:
            for valid,intensity in points:
                if valid >= seen_at: # guard against anything future-dated
                    continue
                valid_s=iso(valid); value=float(intensity)
                cur=self.db.execute("INSERT OR IGNORE INTO observations VALUES(?,?,?,?)",(area,valid_s,seen,value))
                inserted += max(cur.rowcount,0)
                # Reconcile only forecasts fetched before the observed hour.
                rows=self.db.execute("SELECT fetched_at,intensity FROM forecast_points WHERE area=? AND valid_at=? AND fetched_at<? ORDER BY fetched_at DESC",(area,valid_s,valid_s)).fetchall()
                per_bucket={}
                for fetched_s,pred in rows:
                    fetched=datetime.fromisoformat(fetched_s.replace('Z','+00:00'))
                    b=lead_bucket((valid-fetched).total_seconds()/HOUR)
                    per_bucket.setdefault(b,float(pred))
                for b,pred in per_bucket.items():
                    ratio=max(.5,min(2.0,value/max(pred,1e-6)))
                    self.db.execute("INSERT OR REPLACE INTO errors VALUES(?,?,?,?,?)",(area,valid_s,b,ratio,seen))
        return inserted

    def correction(self, area, lead_hours):
        b=lead_bucket(lead_hours)
        ratios=[r[0] for r in self.db.execute("SELECT ratio FROM errors WHERE area=? AND lead_bucket=? ORDER BY seen_at DESC LIMIT 48",(area,b))]
        if len(ratios)<4: return 1.0,len(ratios),b
        logs=sorted(math.log(max(.5,min(2.0,r))) for r in ratios)
        if len(logs)>=8:
            trim=max(1,len(logs)//8); logs=logs[trim:-trim]
        shrink=len(ratios)/(len(ratios)+8.0)
        factor=math.exp(sum(logs)/len(logs)*shrink)
        return max(.8,min(1.25,factor)),len(ratios),b

    def calibrate(self, area, fetched_at, points):
        out=[]
        for valid,raw in points:
            lead=max(0.0,(valid-fetched_at).total_seconds()/HOUR)
            factor,_,_=self.correction(area,lead)
            out.append((valid,max(0.0,float(raw)*factor)))
        return out

    def record_status(self,status):
        ws=status.get('workloads',[])
        compact={w.get('id'):{'state':w.get('state'),'completed_work':w.get('completed_work'),
                 'lost_work':w.get('lost_work'),'delivered':bool(w.get('final_output_delivered'))} for w in ws}
        delivered=sum(bool(w.get('final_output_delivered')) for w in ws)
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO status_samples VALUES(?,?,?,?,?,?)",
                (status['virtual_time'],status['state'],status['qualification'],delivered,len(ws),json.dumps(compact,separators=(',',':'))))

    def event(self, virtual_time, kind, workload_id=None, **payload):
        with self.db:
            self.db.execute("INSERT INTO events(virtual_time,kind,workload_id,payload) VALUES(?,?,?,?)",
                (iso(virtual_time),kind,workload_id,json.dumps(payload,separators=(',',':'))))

    def stats(self):
        return {t:self.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ('forecast_points','observations','errors','status_samples','events')}
