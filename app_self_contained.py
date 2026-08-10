import asyncio, time
from dataclasses import dataclass, asdict
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import httpx

app = FastAPI(title="Solana Momentum Bot V2")

START=1000.0
RISK=0.08
MAX_POS=0.20
STOP=-0.08
TP1=0.12
TP2=0.20
TRAIL_TRIGGER=0.10
TRAIL=0.06
MAX_HOLD=45*60
DAILY_LIMIT=-0.20
FEE=0.006
SLIPPAGE=0.003

state={"cash":START,"equity":START,"day_start":START,"paused":False,
       "candidates":[],"positions":[],"trades":[],"last_scan":0,"errors":[]}

@dataclass
class Pos:
    symbol:str; address:str; entry:float; qty:float; invested:float
    peak:float; opened:float; tp1_done:bool=False

def f(x,d=0.0):
    try:return float(x)
    except:return d

async def get_pairs():
    out=[]; seen=set()
    async with httpx.AsyncClient(timeout=8) as c:
        for q in ["meme","ai","inu","dog","cat","sol"]:
            try:
                r=await c.get("https://api.dexscreener.com/latest/dex/search",params={"q":q})
                for p in r.json().get("pairs",[]):
                    if p.get("chainId")=="solana" and p.get("pairAddress") not in seen:
                        seen.add(p.get("pairAddress")); out.append(p)
            except Exception as e: state["errors"].append(str(e))
    return out

def analyze(p):
    liq=f((p.get("liquidity") or {}).get("usd"))
    vol=f((p.get("volume") or {}).get("h24"))
    h1=f((p.get("priceChange") or {}).get("h1"))
    h6=f((p.get("priceChange") or {}).get("h6"))
    tx=(p.get("txns") or {}).get("h1") or {}
    buys=f(tx.get("buys")); sells=f(tx.get("sells")); total=buys+sells
    if liq<25000 or vol<50000 or total<20:return None
    br=buys/total if total else 0
    score=0
    if h1>3:score+=15
    if h1>7:score+=20
    if h1>15:score+=15
    if h6>5:score+=10
    if vol>100000:score+=15
    if vol>500000:score+=10
    if br>.55:score+=8
    if br>.65:score+=7
    if h1>40:score-=12
    if liq<50000:score-=8
    return {"symbol":(p.get("baseToken") or {}).get("symbol","?"),
            "price":f(p.get("priceUsd")),"liq":liq,"vol":vol,"h1":h1,
            "score":max(0,min(100,score)),"address":p.get("pairAddress")}

async def scan():
    rows=[]
    for p in await get_pairs():
        x=analyze(p)
        if x and x["score"]>=55: rows.append(x)
    rows.sort(key=lambda x:x["score"], reverse=True)
    state["candidates"]=rows[:25]; state["last_scan"]=time.time()

def open_trade(c):
    if state["paused"] or c["score"]<75:return
    if any(p.address==c["address"] for p in state["positions"]):return
    if (state["cash"]-state["day_start"])/state["day_start"]<=DAILY_LIMIT:
        state["paused"]=True; return
    invested=min(state["equity"]*RISK,state["equity"]*MAX_POS)
    px=c["price"]*(1+SLIPPAGE)
    if px<=0 or invested<=0:return
    state["cash"]-=invested
    state["positions"].append(Pos(c["symbol"],c["address"],px,invested/px,invested,px,time.time()))

def close(p,px,reason,qty=None):
    q=p.qty if qty is None else min(qty,p.qty)
    proceeds=q*px*(1-FEE-SLIPPAGE)
    cost=p.invested*(q/p.qty)
    pnl=proceeds-cost
    state["cash"]+=proceeds
    p.qty-=q; p.invested-=cost
    state["trades"].append({"symbol":p.symbol,"pnl":pnl,"pct":pnl/cost*100 if cost else 0,"reason":reason,"time":time.time()})
    if p.qty<=1e-12: state["positions"].remove(p)

async def manage():
    pm={c["address"]:c["price"] for c in state["candidates"]}
    for p in list(state["positions"]):
        px=pm.get(p.address)
        if not px:continue
        p.peak=max(p.peak,px); ret=px/p.entry-1; age=time.time()-p.opened
        if ret<=STOP: close(p,px,"hard stop")
        elif not p.tp1_done and ret>=TP1:
            close(p,px,"take profit 1",p.qty*.5); p.tp1_done=True
        elif ret>=TP2: close(p,px,"take profit 2")
        elif ret>=TRAIL_TRIGGER and px<=p.peak*(1-TRAIL): close(p,px,"trailing stop")
        elif age>=MAX_HOLD: close(p,px,"time exit")

async def loop():
    while True:
        try:
            await scan()
            if state["candidates"]: open_trade(state["candidates"][0])
            await manage()
            state["equity"]=state["cash"]+sum(p.invested for p in state["positions"])
        except Exception as e: state["errors"].append(str(e))
        await asyncio.sleep(20)

@app.on_event("startup")
async def start(): asyncio.create_task(loop())

@app.get("/")
async def home():
    return HTMLResponse("""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Solana Momentum V2</title><style>
body{margin:0;background:#080b10;color:#f4f6f8;font-family:-apple-system,BlinkMacSystemFont,sans-serif}main{max-width:760px;margin:auto;padding:16px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.card{background:#121720;border:1px solid #252d39;border-radius:17px;padding:14px;margin:10px 0}h1{font-size:24px}.muted{color:#8e99a8;font-size:12px}.big{font-size:25px;font-weight:800}button{padding:11px 15px;border:0;border-radius:11px;font-weight:700;margin:3px}.row{display:flex;justify-content:space-between;gap:8px}.item{padding:11px 0;border-bottom:1px solid #252d39}.green{color:#66e197}.red{color:#ff7c89}.tag{font-size:11px;border:1px solid #3a4352;border-radius:99px;padding:4px 7px}</style></head>
<body><main><h1>⚡ Solana Momentum V2</h1><div class="muted">PAPER TRADING ONLY • aggressive research model</div>
<div class="grid"><div class="card"><div class="muted">Equity</div><div id="eq" class="big">$1,000.00</div></div><div class="card"><div class="muted">P&L</div><div id="pl" class="big">$0.00</div></div></div>
<div class="card"><button onclick="act('pause')">Pause</button><button onclick="act('resume')">Resume</button><span id="st" class="tag">Loading</span></div>
<div class="card"><b>Risk model</b><p class="muted">8% risk/trade • 20% max position • −8% hard stop • +12% partial TP • +20% TP • trailing protection • daily −20% circuit breaker • simulated fees/slippage.</p></div>
<div class="card"><h3>Top signals</h3><div id="cand">Loading…</div></div><div class="card"><h3>Positions</h3><div id="pos">None</div></div><div class="card"><h3>Recent trades</h3><div id="tr">None</div></div>
<div class="muted">No real transactions or wallet keys. No strategy can guarantee profits.</div></main>
<script>let start=1000;const $=x=>document.getElementById(x),m=x=>'$'+(+x).toFixed(2);function table(a,fn){return a.length?a.map(fn).join(''):'<span class="muted">None yet.</span>'}
async function load(){try{let s=await(await fetch('/api/state')).json();$('eq').textContent=m(s.equity);$('pl').textContent=m(s.equity-start);$('pl').className='big '+(s.equity>=start?'green':'red');$('st').textContent=s.paused?'PAUSED':'RUNNING';
$('cand').innerHTML=table(s.candidates.slice(0,10),x=>`<div class="item"><div class="row"><b>${x.symbol}</b><b>${x.score}/100</b></div><div class="row muted"><span class="${x.h1>=0?'green':'red'}">${x.h1.toFixed(1)}% 1h</span><span>$${Math.round(x.liq).toLocaleString()} liq</span></div></div>`);
$('pos').innerHTML=table(s.positions,x=>`<div class="item"><div class="row"><b>${x.symbol}</b><span>${m(x.invested)}</span></div></div>`);
$('tr').innerHTML=table(s.trades.slice(0,10),x=>`<div class="item"><div class="row"><b>${x.symbol}</b><span class="${x.pnl>=0?'green':'red'}">${x.pnl>=0?'+':''}${m(x.pnl)}</span></div><div class="muted">${x.reason} • ${x.pct.toFixed(2)}%</div></div>`)}catch(e){$('st').textContent='DATA ERROR'}}async function act(x){await fetch('/api/'+x,{method:'POST'});load()}load();setInterval(load,5000)</script></body></html>""")

@app.get("/api/state")
async def api():
    return {"cash":state["cash"],"equity":state["equity"],"paused":state["paused"],"candidates":state["candidates"],
            "positions":[asdict(p) for p in state["positions"]],"trades":state["trades"][-50:][::-1],
            "errors":state["errors"][-5:]}

@app.post("/api/pause")
async def pause(): state["paused"]=True; return {"paused":True}
@app.post("/api/resume")
async def resume(): state["paused"]=False; return {"paused":False}
