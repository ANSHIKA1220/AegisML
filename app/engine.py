"""Deterministic synthetic ML workload and thread-safe local failover engine."""
import math
import random
import sqlite3
import threading
import time
from pathlib import Path


def sigmoid(x):
    return 1 / (1 + math.exp(-max(-40, min(40, x))))


class RiskModel:
    def __init__(self, seed):
        rng = random.Random(seed)
        rows = []
        for _ in range(900):
            x = [rng.random(), rng.random(), rng.random()]
            y = int(2.8*x[0] + 2*x[1] + 1.7*x[2] + rng.gauss(0, .25) > 3.6)
            rows.append((x, y))
        self.weights = [0.] * 4
        for _ in range(160):
            gradients = [0.] * 4
            for x, y in rows:
                features = [1.] + x
                error = sigmoid(sum(a*b for a, b in zip(self.weights, features))) - y
                for j in range(4):
                    gradients[j] += error * features[j]
            self.weights = [w - 1.5*g/len(rows) for w, g in zip(self.weights, gradients)]

    def predict(self, features):
        return sigmoid(sum(a*b for a, b in zip(self.weights, [1.] + features)))


class Engine:
    def __init__(self, db_path):
        self.lock = threading.RLock()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(db_path), check_same_thread=False)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS requests(id INTEGER PRIMARY KEY, ts REAL, latency REAL, ok INTEGER, model TEXT, score REAL, amount REAL);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, ts REAL, kind TEXT, title TEXT, detail TEXT);
        ''')
        self.models = {'primary': RiskModel(42), 'standby': RiskModel(43)}
        self.active = 'primary'
        self.fault = None
        self.auto = True
        self.started = time.time()
        self.event('system', 'Inference engine online', 'Two independently trained logistic models loaded. Synthetic transaction data; local process failover.')

    def event(self, kind, title, detail):
        with self.lock:
            self.db.execute('INSERT INTO events(ts,kind,title,detail) VALUES(?,?,?,?)', (time.time(), kind, title, detail))
            self.db.commit()

    def inject(self, fault):
        with self.lock:
            if self.active != 'primary':
                raise ValueError('Restore the primary before injecting another fault.')
            self.fault = fault
            self.event('warning', 'Fault injected: ' + fault, 'Primary model only. The monitor checks availability, latency, and a fixed prediction canary every 2 seconds.')

    def infer(self, amount, velocity, distance):
        with self.lock:
            start = time.perf_counter()
            model = self.active
            fault = self.fault if model == 'primary' else None
            if fault == 'latency':
                time.sleep(.32)
            ok = fault != 'error'
            score = self.models[model].predict([amount / 10000, velocity / 30, distance / 10000]) if ok else None
            if fault == 'corruption' and ok:
                score = 1 - score
            latency = (time.perf_counter() - start) * 1000
            self.db.execute('INSERT INTO requests(ts,latency,ok,model,score,amount) VALUES(?,?,?,?,?,?)', (time.time(), latency, int(ok), model, score, amount))
            self.db.commit()
            return {'ok': ok, 'model': model, 'score': round(score, 4) if ok else None, 'decision': ('review' if score >= .5 else 'approve') if ok else 'unavailable', 'latency_ms': round(latency, 2)}

    def check(self):
        with self.lock:
            if self.active != 'primary' or not self.fault:
                return
            # Probe the real inference path; probes are recorded as requests.
            probe = self.infer(200, 1, 50)
            expected = self.models['primary'].predict([.02, 1/30, .005])
            reason = ('Availability probe failed' if not probe['ok'] else
                      'Latency exceeded 250 ms' if probe['latency_ms'] > 250 else
                      'Canary prediction mismatch' if abs(probe['score'] - expected) > .1 else None)
            if reason and self.auto:
                self.active = 'standby'
                self.event('recovery', 'Traffic switched to standby', reason + '. Primary quarantined; subsequent requests use the healthy standby. Manual restore required.')
            elif reason:
                last = self.db.execute('SELECT title FROM events ORDER BY id DESC LIMIT 1').fetchone()
                if not last or last[0] != 'Unhealthy primary detected':
                    self.event('critical', 'Unhealthy primary detected', reason + '. Automatic recovery is disabled.')

    def restore(self):
        with self.lock:
            self.fault = None
            self.active = 'primary'
            self.event('system', 'Primary restored', 'Injected fault cleared and traffic returned to primary.')

    def snapshot(self):
        with self.lock:
            rows = self.db.execute('SELECT ts,latency,ok,model,score,amount FROM requests ORDER BY id DESC LIMIT 100').fetchall()
            total, success = self.db.execute('SELECT COUNT(*),COALESCE(SUM(ok),0) FROM requests').fetchone()
            events = self.db.execute('SELECT id,ts,kind,title,detail FROM events ORDER BY id DESC LIMIT 30').fetchall()
            latencies = sorted(r[1] for r in rows)
            return {'active': self.active, 'fault': self.fault, 'auto': self.auto, 'uptime': int(time.time()-self.started), 'total': total,
                    'success_rate': round(100*success/total, 2) if total else None,
                    'p95': round(latencies[max(0, math.ceil(len(latencies)*.95)-1)], 2) if latencies else 0,
                    'requests': [dict(zip(['ts','latency','ok','model','score','amount'], r)) for r in rows],
                    'events': [dict(zip(['id','ts','kind','title','detail'], e)) for e in events]}
