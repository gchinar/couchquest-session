import os
from contextlib import asynccontextmanager
from copy import deepcopy
from uuid import uuid4
import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, MetaData, Table, Column, String, Integer, JSON, select, text, update

engine = create_engine(os.getenv('DATABASE_URL', 'sqlite:///./sessions.db'), pool_pre_ping=True)
CATALOG_URL = os.getenv('CATALOG_URL', 'http://localhost:8001')
metadata = MetaData()
sessions = Table('sessions', metadata, Column('id', String, primary_key=True),
    Column('version', Integer, nullable=False), Column('data', JSON, nullable=False))

@asynccontextmanager
async def lifespan(app):
    metadata.create_all(engine)
    yield

app = FastAPI(title='CouchQuest Play Sessions', lifespan=lifespan)

class Player(BaseModel):
    player_id: str = Field(min_length=1, max_length=40, pattern=r'^[A-Za-z0-9_-]+$')
class SessionInput(BaseModel):
    game_id: str = Field(min_length=1, max_length=50)
    host_id: str = Field(min_length=1, max_length=40, pattern=r'^[A-Za-z0-9_-]+$')
    controller_count: int = Field(ge=2, le=4)
class ReadyInput(BaseModel):
    ready: bool

# Kept as one function so tests can replace the remote dependency.
def fetch_game(game_id):
    try:
        response = httpx.get(f'{CATALOG_URL}/games/{game_id}', timeout=3.0)
        if response.status_code == 404: raise HTTPException(404, 'Game not found')
        response.raise_for_status()
        game = response.json()
        if not all(k in game for k in ['id','title','platform','display_mode','min_players','max_players']):
            raise ValueError('Invalid catalog response')
        return game
    except (httpx.HTTPError, ValueError, TypeError):
        raise HTTPException(503, 'Catalog unavailable; retry later')

def read_session(session_id):
    with engine.connect() as c:
        row = c.execute(select(sessions).where(sessions.c.id == session_id)).mappings().first()
    if not row: raise HTTPException(404, 'Session not found')
    return dict(row)

def mutate(session_id, operation):
    # Compare-and-swap prevents lost joins and overbooking across API replicas.
    for _ in range(5):
        old = read_session(session_id)
        data = deepcopy(old['data'])
        operation(data)
        with engine.begin() as c:
            result = c.execute(update(sessions).where(sessions.c.id == session_id,
                sessions.c.version == old['version']).values(data=data, version=old['version']+1))
        if result.rowcount == 1: return data
    raise HTTPException(409, 'Concurrent update; retry request')

def lobby(data):
    if data['status'] != 'LOBBY': raise HTTPException(409, 'Session is not in lobby')

def host(data, player_id):
    if data['host_id'] != player_id: raise HTTPException(403, 'Host action required')

@app.get('/health/live')
def live(): return {'status': 'alive'}

@app.get('/health/ready')
def ready():
    try:
        with engine.connect() as c: c.execute(text('SELECT 1'))
    except Exception: raise HTTPException(503, 'Database unavailable')
    return {'status': 'ready'}

@app.post('/sessions', status_code=201)
def create_session(body: SessionInput):
    game = fetch_game(body.game_id)
    capacity = min(body.controller_count, game['max_players'])
    if capacity < game['min_players']:
        raise HTTPException(422, 'Not enough controllers for this game')
    data = {'id': str(uuid4()), 'game': game, 'host_id': body.host_id,
        'controller_count': body.controller_count, 'capacity': capacity,
        'status': 'LOBBY', 'players': [{'player_id': body.host_id, 'slot': 1, 'ready': False}]}
    with engine.begin() as c:
        c.execute(sessions.insert().values(id=data['id'], version=0, data=data))
    return data

@app.get('/sessions/{session_id}')
def get_session(session_id: str): return read_session(session_id)['data']

@app.post('/sessions/{session_id}/players')
def join(session_id: str, body: Player):
    def operation(data):
        lobby(data)
        if any(p['player_id'] == body.player_id for p in data['players']): return
        if len(data['players']) >= data['capacity']: raise HTTPException(409, 'Session full')
        slot = next(n for n in range(1, data['capacity']+1) if n not in [p['slot'] for p in data['players']])
        data['players'].append({'player_id': body.player_id, 'slot': slot, 'ready': False})
    return mutate(session_id, operation)

@app.put('/sessions/{session_id}/players/{player_id}/ready')
def set_ready(session_id: str, player_id: str, body: ReadyInput):
    def operation(data):
        lobby(data)
        player = next((p for p in data['players'] if p['player_id'] == player_id), None)
        if player is None: raise HTTPException(404, 'Player not in session')
        player['ready'] = body.ready
    return mutate(session_id, operation)

@app.delete('/sessions/{session_id}/players/{player_id}')
def leave(session_id: str, player_id: str):
    def operation(data):
        lobby(data)
        if player_id == data['host_id']: raise HTTPException(409, 'Host must cancel the session')
        if not any(p['player_id'] == player_id for p in data['players']):
            raise HTTPException(404, 'Player not in session')
        data['players'] = [p for p in data['players'] if p['player_id'] != player_id]
    return mutate(session_id, operation)

@app.post('/sessions/{session_id}/start')
def start(session_id: str, body: Player):
    def operation(data):
        host(data, body.player_id)
        if data['status'] == 'IN_PROGRESS': return
        lobby(data)
        if len(data['players']) < data['game']['min_players'] or not all(p['ready'] for p in data['players']):
            raise HTTPException(409, 'Minimum players must join and every player must be ready')
        data['status'] = 'IN_PROGRESS'
    return mutate(session_id, operation)

@app.post('/sessions/{session_id}/finish')
def finish(session_id: str, body: Player):
    def operation(data):
        host(data, body.player_id)
        if data['status'] == 'COMPLETED': return
        if data['status'] != 'IN_PROGRESS': raise HTTPException(409, 'Session has not started')
        data['status'] = 'COMPLETED'
    return mutate(session_id, operation)

@app.post('/sessions/{session_id}/cancel')
def cancel(session_id: str, body: Player):
    def operation(data):
        host(data, body.player_id)
        if data['status'] == 'CANCELLED': return
        lobby(data)
        data['status'] = 'CANCELLED'
    return mutate(session_id, operation)
