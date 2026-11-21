# AegisML

A runnable local ML inference platform with a live dashboard, fault injection, health probes, automatic standby routing, and a persistent SQLite activity log.

## Run on Windows

```powershell
cd D:\projects\Aegis
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. Interactive API documentation: http://127.0.0.1:8000/docs.
If dependencies are already installed, use `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`.

## Demonstrate recovery

1. Start demo traffic or submit a transaction in the prediction form.
2. Inject an availability, latency, or prediction-corruption fault.
3. Within the next monitor cycle, the monitor probes the primary, detects the problem, and switches subsequent requests to standby.
4. Read the recovery event and confirm that predictions identify the standby model.
5. Restore primary, disable auto-recovery, and inject a fault again to demonstrate manual intervention.

No paid API, cloud account, model download, Docker, or administrator access is required. Fonts use Google Fonts when reachable, with system fallbacks.

## Architecture

The browser polls FastAPI for recorded state. FastAPI validates input and sends requests through a thread-safe router to one of two logistic regression models. Both models train at process startup on 900 deterministic synthetic transactions, using independent seeds. Features are transaction amount, transactions per hour, and distance. SQLite stores requests and events. A background monitor probes the inference path every two seconds; failed availability, latency over 250 ms, or a known canary prediction mismatch triggers routing to standby. Injected corruption inverts the prediction score; this is a controlled fault, not a general data-drift detector.

Model training and inference are implemented in Python without an external ML runtime. Risk scores demonstrate the serving architecture and are not calibrated or validated for financial decisions. Requests to the standby use a separately trained model, so scores may change slightly after failover.

## API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/health` | Serving health; 503 for degraded primary |
| GET | `/api/state` | Metrics, recent requests, and events |
| POST | `/api/predict` | `{ "amount": 1200, "velocity": 3, "distance": 120 }` |
| POST | `/api/fault` | `{ "kind": "error" }`, `latency`, or `corruption` |
| POST | `/api/restore` | Clear fault and restore primary |
| POST | `/api/policy` | `{ "enabled": false }` |

Input bounds: amount 0–10000, velocity 0–30, distance 0–10000. Prediction errors return 503 and are recorded in metrics. Invalid payloads return 422. Fault injection while on standby returns 409.

## Validation

```powershell
python -m unittest discover -s tests -v
```

Tests cover score ordering, all three recovery triggers, healthy standby predictions, restore, disabled automatic recovery, fault conflicts, and persisted request history.

## MVP scope

This is a single-process local prototype. Run exactly one Uvicorn worker: in-memory routing and model state are not shared between processes. Request/event history survives restarts; faults, policy, and active routing reset at startup. Health probes count in request metrics. P95 uses the last 100 requests. Demo traffic is generated only while the dashboard is open and enabled. In-flight requests are not retried; requests arriving before detection can fail. The latency fault intentionally holds the inference lock for 320 ms, and monitor scheduling adds detection time. No authentication is included: keep the server bound to loopback.

Future production work: model artifact registry, real evaluation datasets, rolling-window circuit breakers, independent serving workers, distributed state, authentication, Prometheus instrumentation, deployment automation, and measured load/failure benchmarks. No production or accuracy claims are implied by this prototype.
