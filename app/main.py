import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Literal
from .engine import Engine

ROOT = Path(__file__).resolve().parent
engine = Engine(Path(os.environ.get('AEGIS_DB', str(ROOT.parent / 'data' / 'aegis.db'))))


@asynccontextmanager
async def lifespan(app):
    async def monitor():
        while True:
            await asyncio.sleep(2)
            await asyncio.to_thread(engine.check)
    task = asyncio.create_task(monitor())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title='AegisML', version='0.1.0', lifespan=lifespan)
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')


class Transaction(BaseModel):
    amount: float = Field(default=1200, ge=0, le=10000)
    velocity: float = Field(default=3, ge=0, le=30)
    distance: float = Field(default=120, ge=0, le=10000)


class Fault(BaseModel):
    kind: Literal['error', 'latency', 'corruption']


class Policy(BaseModel):
    enabled: bool


@app.get('/')
def home():
    return FileResponse(ROOT / 'static' / 'index.html')


@app.get('/health')
def health():
    state = engine.snapshot()
    healthy = state['active'] == 'standby' or state['fault'] is None
    return JSONResponse({'status': 'healthy' if healthy else 'degraded', 'active_model': state['active']}, status_code=200 if healthy else 503)


@app.get('/api/state')
def state():
    return engine.snapshot()


@app.post('/api/predict')
def predict(transaction: Transaction):
    result = engine.infer(transaction.amount, transaction.velocity, transaction.distance)
    return JSONResponse(result, status_code=200 if result['ok'] else 503)


@app.post('/api/fault')
def fault(body: Fault):
    try:
        engine.inject(body.kind)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return {'status': 'injected'}


@app.post('/api/restore')
def restore():
    engine.restore()
    return {'status': 'restored'}


@app.post('/api/policy')
def policy(body: Policy):
    with engine.lock:
        engine.auto = body.enabled
        engine.event('system', 'Recovery policy updated', 'Automatic recovery ' + ('enabled' if body.enabled else 'disabled'))
    return {'enabled': body.enabled}
