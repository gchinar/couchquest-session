import pytest
import httpx
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

GAME={'id':'g1','title':'Twin Trails','platform':'PC','display_mode':'split_screen','min_players':2,'max_players':2}
@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import main
    monkeypatch.setattr(main,'engine',create_engine('sqlite:///'+str(tmp_path/'sessions.db')))
    monkeypatch.setattr(main,'fetch_game',lambda _: GAME.copy())
    with TestClient(main.app) as c: yield c

def new(client):
    r=client.post('/sessions',json={'game_id':'g1','host_id':'alice','controller_count':2})
    assert r.status_code==201
    return '/sessions/'+r.json()['id']

def test_full_lifecycle(client):
    p=new(client)
    assert client.post(p+'/start',json={'player_id':'alice'}).status_code==409
    assert client.post(p+'/players',json={'player_id':'bob'}).status_code==200
    for name in ['alice','bob']:
        assert client.put(p+'/players/'+name+'/ready',json={'ready':True}).status_code==200
    assert client.post(p+'/start',json={'player_id':'bob'}).status_code==403
    assert client.post(p+'/start',json={'player_id':'alice'}).json()['status']=='IN_PROGRESS'
    assert client.post(p+'/players',json={'player_id':'eve'}).status_code==409
    assert client.post(p+'/finish',json={'player_id':'alice'}).json()['status']=='COMPLETED'
    assert client.post(p+'/start',json={'player_id':'alice'}).status_code==409

def test_duplicate_join_capacity_leave(client):
    p=new(client)
    for _ in range(2): assert client.post(p+'/players',json={'player_id':'bob'}).status_code==200
    assert len(client.get(p).json()['players'])==2
    assert client.post(p+'/players',json={'player_id':'eve'}).status_code==409
    assert client.delete(p+'/players/alice').status_code==409
    assert client.delete(p+'/players/bob').status_code==200
    assert client.post(p+'/players',json={'player_id':'eve'}).json()['players'][-1]['slot']==2

def test_cancel_and_missing(client):
    p=new(client)
    assert client.put(p+'/players/missing/ready',json={'ready':True}).status_code==404
    assert client.post(p+'/finish',json={'player_id':'alice'}).status_code==409
    assert client.post(p+'/cancel',json={'player_id':'alice'}).json()['status']=='CANCELLED'
    assert client.get('/sessions/missing').status_code==404

def test_contending_joins(client):
    p=new(client)
    def join(n): return client.post(p+'/players',json={'player_id':'p'+str(n)}).status_code
    with ThreadPoolExecutor(max_workers=8) as pool: codes=list(pool.map(join,range(8)))
    assert codes.count(200)==1
    assert codes.count(409)==7
    assert len(client.get(p).json()['players'])==2

def test_controller_validation(client,monkeypatch):
    from app import main
    monkeypatch.setattr(main,'fetch_game',lambda _: dict(GAME,min_players=3,max_players=4))
    assert client.post('/sessions',json={'game_id':'g1','host_id':'alice','controller_count':2}).status_code==422

def test_remote_failure_mapping(monkeypatch):
    from app import main
    from fastapi import HTTPException
    def fail(*args,**kwargs): raise httpx.ConnectError('offline')
    monkeypatch.setattr(main.httpx,'get',fail)
    with pytest.raises(HTTPException) as e: main.fetch_game('g1')
    assert e.value.status_code==503

def test_remote_404_mapping(monkeypatch):
    from app import main
    from fastapi import HTTPException
    monkeypatch.setattr(main.httpx,'get',lambda *a,**kw:httpx.Response(404,request=httpx.Request('GET','http://catalog/games/no')))
    with pytest.raises(HTTPException) as e: main.fetch_game('no')
    assert e.value.status_code==404

def test_existing_session_survives_catalog_outage(client,monkeypatch):
    from app import main
    from fastapi import HTTPException
    p=new(client)
    def fail(_): raise HTTPException(503,'Catalog unavailable')
    monkeypatch.setattr(main,'fetch_game',fail)
    assert client.get(p).status_code==200
    assert client.post(p+'/players',json={'player_id':'bob'}).status_code==200
    assert client.post('/sessions',json={'game_id':'g1','host_id':'alice','controller_count':2}).status_code==503
