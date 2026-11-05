"""Act 2: a weather app whose UI is driven by decisions, not text.

The browser gets your location, the backend fetches Open-Meteo, and then CODE
turns the raw numbers into plain words (decision models are weak at numbers,
see act1 step 3). That word summary is the State. One Decider call asks three
typed questions -- a Noul, a Choice and a Score -- and the page restyles itself
from the answers. The model never sees a coordinate or a temperature in degrees.

    uv run act2_weather/app.py                 # live: real location + Open-Meteo
    uv run act2_weather/app.py --replay        # offline: sample cities from fixtures
    uv run act2_weather/app.py --port 8001

Swapping the Backend (laya <-> kev) is just changing the model string in the UI.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import httpx
import typesafe_sdk as ts
import uvicorn
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from dm import Decider, certainty

HERE = Path(__file__).resolve().parent
OPENMETEO_CACHE = HERE.parent / "fixtures" / "act2_openmeteo.json"
# Overridable so --replay can point at a bogus URL and prove it is never called.
OPENMETEO_URL = os.environ.get("ACT2_OPENMETEO_URL", "https://api.open-meteo.com/v1/forecast")

# Sample cities for when geolocation is blocked or we are offline (coords rounded to 2dp).
CITIES = {
    "Lisbon": (38.72, -9.14),
    "Porto": (41.15, -8.61),
    "London": (51.51, -0.13),
    "Reykjavik": (64.15, -21.94),
}
MODEL_FALLBACK = ["laya:en", "laya:typed-decisions", "kev:0.8b", "kev:4b"]

# --- Numbers -> words. The model only ever sees the words. ---------------------

def bucket_temp(c: float) -> str:
    return ("freezing" if c < 3 else "cold" if c < 12 else
            "mild" if c < 20 else "warm" if c < 27 else "hot")


def bucket_rain(mm: float, prob: float) -> str:
    if mm >= 2.5 or (prob >= 60 and mm >= 0.5):
        return "heavy rain"
    if mm >= 0.2 or prob >= 40:
        return "drizzle"
    return "dry"


def bucket_wind(kmh: float) -> str:
    return "light wind" if kmh < 12 else "a stiff breeze" if kmh < 38 else "gale-force wind"


def bucket_sky(code: int) -> str:
    # Open-Meteo WMO weather codes, collapsed to three plain words.
    if code == 0:
        return "clear"
    if code <= 48:
        return "cloudy"
    return "wet"


def summarise(cur: dict, hourly: dict) -> str:
    """Turn the raw forecast into one short, plain-words State string."""
    temp = bucket_temp(cur["temperature_2m"])
    wind = bucket_wind(cur["wind_speed_10m"])
    sky = bucket_sky(int(cur["weather_code"]))
    # Look at the next 12 hours for rain, which matters more than the instant.
    rain_mm = max(hourly["precipitation"][:12] or [0])
    rain_prob = max(hourly["precipitation_probability"][:12] or [0])
    rain = bucket_rain(rain_mm, rain_prob)
    soon = "starting soon" if rain != "dry" and cur.get("precipitation", 0) < 0.2 else "right now"
    return (f"It is {temp} and {sky}, with {wind}. "
            f"Over the next few hours: {'no rain' if rain == 'dry' else rain + (' (' + soon + ')')}.")


# --- The three typed questions asked about every weather summary ---------------

QUESTIONS = {
    "umbrella": ts.Noul(instructions="You should carry an umbrella today."),
    "transport": ts.Choice(
        instructions="What is the best way to get around town right now?",
        criteria={
            "walk": "pleasant and dry enough to go on foot",
            "bike": "dry and not too windy for cycling",
            "bus": "wet, cold or windy enough to want shelter",
        },
    ),
    "pleasant": ts.Score(
        instructions="How pleasant is it to be outside right now?",
        criteria=["miserable", "unpleasant", "okay", "nice", "perfect"],
    ),
}


def fetch_openmeteo(lat: float, lon: float) -> dict:
    """Fetch current + next-12h forecast. Coordinates stay here, never go to the model."""
    r = httpx.get(OPENMETEO_URL, params={
        "latitude": lat, "longitude": lon,
        "current": "temperature_2m,precipitation,weather_code,wind_speed_10m",
        "hourly": "precipitation,precipitation_probability",
        "forecast_days": 1, "timezone": "auto",
    }, timeout=15.0)
    r.raise_for_status()
    return r.json()


def load_cache() -> dict:
    if OPENMETEO_CACHE.exists():
        return json.loads(OPENMETEO_CACHE.read_text())
    return {}


def build_app(replay: bool) -> FastAPI:
    app = FastAPI(title="Act 2 - Weather decisions")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])
    # Live is always fresh, even when the word summary matches an old fixture.
    # Keep the recorded weather and decisions intact for the offline demo.
    decider = Decider("act2", replay=replay, cache=replay)

    @app.middleware("http")
    async def no_store(request: Request, call_next):
        # A remote website must not drive the local model through this server.
        origin = request.headers.get("origin")
        if request.headers.get("sec-fetch-site") == "cross-site" or (origin and origin != str(request.base_url).rstrip("/")):
            return JSONResponse({"error": "Cross-origin requests are not allowed."}, status_code=403)
        if request.url.path == "/api/weather" and request.headers.get("x-demo-request") != "1":
            return JSONResponse({"error": "Use the weather demo page to request decisions."}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
        return response

    @app.get("/api/models")
    def models() -> JSONResponse:
        """List the models the demo offers. In replay we use the fixed list
        (every one has fixtures); live, GET /v1/models returns exactly the
        models the Ollaya server actually has loaded, so a model that is still
        pulling never shows up as a selectable string that would 404 on use."""
        if replay:
            return JSONResponse(MODEL_FALLBACK)
        try:
            available = {m.name for m in decider._sdk().models.list().models}
            ordered = [m for m in MODEL_FALLBACK if m in available]
            return JSONResponse(ordered or sorted(available))
        except Exception:
            return JSONResponse(MODEL_FALLBACK)

    @app.get("/api/weather")
    def weather(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180),
                model: str = Query("laya:en"), city: str = Query("")) -> JSONResponse:
        if model not in MODEL_FALLBACK:
            return JSONResponse({"error": "Choose one of the demo models."}, status_code=400)
        lat, lon = round(lat, 2), round(lon, 2)       # 2dp is enough for a city
        if replay:
            if not city:
                return JSONResponse({
                    "error": "My location needs live weather. Restart without --replay, or pick a sample city.",
                }, status_code=400)
            data = load_cache().get(city)
            if data is None:
                return JSONResponse({"error": f"no recorded weather for {city!r}"}, status_code=404)
        else:
            try:
                data = fetch_openmeteo(lat, lon)
            except httpx.HTTPError:
                return JSONResponse({
                    "error": "The weather service could not be reached. Please try again.",
                }, status_code=502)

        summary = summarise(data["current"], data["hourly"])
        try:
            d = decider.decide(summary, QUESTIONS, model=model)
        except LookupError as exc:                     # replay miss: never recorded
            return JSONResponse({"error": str(exc), "summary": summary}, status_code=404)
        except Exception:                              # e.g. model not pulled on Ollaya
            return JSONResponse({
                "error": f"{model} could not answer. Check that Ollaya is running and the model is installed.",
                "summary": summary,
            }, status_code=502)
        # Shape the answers for the page, adding a 0..1 certainty for every primitive.
        answers = {name: {**a, "certainty": round(certainty(a), 3)} for name, a in d.answers.items()}
        return JSONResponse({
            "summary": summary,          # the State -- note: NO coordinates, NO degrees
            "answers": answers,
            "model": d.model,
            "latency_ms": d.latency_ms,
            "cached": d.cached,
            "mode": "replay" if replay else "live",
        })

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return PAGE.replace("__REPLAY__", "true" if replay else "false")

    return app


# --- The page: one inline HTML string, vanilla JS, no build step ---------------

PAGE = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Weather, decided</title><style>
 :root{--bg:#1b2430;--fg:#f4f7fb}
 *{box-sizing:border-box}
 body{margin:0;font:clamp(16px,2.2vw,22px)/1.5 system-ui,sans-serif;color:var(--fg);
      background:var(--bg);transition:background .6s;min-height:100vh}
 main{max-width:52rem;margin:0 auto;padding:2rem}
 h1{font-size:clamp(2rem,6vw,3.5rem);margin:.2em 0}
 .sum{font-size:1.25em;opacity:.95;margin:.5em 0 1.5em}
 .controls{display:flex;gap:1rem;flex-wrap:wrap;align-items:end;margin-bottom:1rem}
 label{display:block;font-size:.8em;opacity:.8;margin-bottom:.2em}
 select,button{font:inherit;padding:.5rem .7rem;border-radius:.5rem;border:1px solid #fff5;
      background:#fff2;color:inherit}
 button{cursor:pointer;background:#fff3}
 button:disabled{cursor:default;opacity:.5}
 .mode{font-size:.8em;opacity:.8;margin:0 0 1rem}
 .card{background:#0003;border:1px solid #fff2;border-radius:.8rem;padding:1rem 1.2rem;margin:.8rem 0}
 .card h2{margin:.1em 0;font-size:1.1em}
 .bar{height:1.1rem;border-radius:.6rem;background:#fff2;overflow:hidden;margin:.4em 0}
 .bar>i{display:block;height:100%;background:#8fd;transition:width .5s}
 .row{display:flex;justify-content:space-between;font-size:.85em;opacity:.85}
 .meta{opacity:.7;font-size:.8em;margin-top:1.5rem}
 .win{font-weight:700}
</style></head><body><main>
 <p class=mode id=mode></p>
 <div class=controls>
  <div><label for=model>model (just a string)</label><select id=model></select></div>
  <div><label for=city>sample city</label><select id=city>
    <option value="">my location</option>
    <option selected>Lisbon</option><option>Porto</option><option>London</option><option>Reykjavik</option>
  </select></div>
  <button id=go>Refresh</button>
  <button id=locate>Get my location</button>
 </div>
 <h1 id=headline>…</h1>
 <p class=sum id=summary>Loading weather…</p>
 <div id=cards></div>
 <p class=meta id=meta></p>
</main><script>
const $=s=>document.querySelector(s);
const REPLAY=__REPLAY__;
let requestId=0;
let cancelLocation=null;
function setStatus(message){
 $("#summary").textContent=message;
 $("#headline").textContent="Weather, decided";
 $("#cards").innerHTML=""; $("#meta").textContent="";
}
// Pure-code restyle: the look is a function of the decisions, not of any text.
function restyle(a){
 const rain=a.umbrella.noul>0.5, p=a.pleasant.score;
 const emoji=rain?"🌧️":p>=3?"☀️":p>=2?"⛅":"🌫️";
 const head=rain?"Take an umbrella":p>=3?"Lovely out there":p>=2?"Not bad":"Stay cosy";
 $("#headline").textContent=emoji+" "+head;
 document.body.style.background=rain?"#24323f":p>=3?"#2e5d46":p>=2?"#334155":"#3a2f42";
}
function escapeHTML(value){return String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function bar(label,p,win){return `<div class=row><span class="${win?'win':''}">${escapeHTML(label)}</span>`+
 `<span>${(p*100).toFixed(0)}%</span></div><div class=bar><i style="width:${(p*100).toFixed(0)}%"></i></div>`;}
function card(title,inner){return `<div class=card><h2>${title}</h2>${inner}</div>`;}
function render(d){
 $("#summary").textContent=d.summary; restyle(d.answers);
 const u=d.answers.umbrella, t=d.answers.transport, s=d.answers.pleasant;
 let html="";
 html+=card("Umbrella? (Noul)", bar(u.noul>0.5?"yes, bring one":"no, leave it",u.noul,true)+
   `<div class=row><span>certainty</span><span>${(u.certainty*100).toFixed(0)}%</span></div>`);
 let ch=""; for(const [k,p] of Object.entries(t.probabilities)) ch+=bar(k,p,k===t.choice);
 html+=card("Get around? (Choice)", ch+`<div class=row><span>confidence</span><span>${(t.confidence*100).toFixed(0)}%</span></div>`);
 let sc=""; for(const [lvl,p] of Object.entries(s.probabilities)) sc+=bar(s.legend[lvl],p,Math.round(s.score)==lvl);
 html+=card("Pleasant outside? (Score)", sc+`<div class=row><span>confidence</span><span>${(s.confidence*100).toFixed(0)}%</span></div>`);
 $("#cards").innerHTML=html;
 $("#meta").textContent=(d.cached?"Recorded response":"Fresh response")+
   ` · answered by ${d.model} in ${d.latency_ms.toFixed(0)} ms`+
   " · the model saw only: \u201c"+d.summary+"\u201d";
}
async function decide(lat,lon,city,id){
 setStatus(REPLAY?"Loading recorded decisions…":"Fetching fresh weather and decisions…");
 const q=new URLSearchParams({lat,lon,model:$("#model").value,city:city||""});
 try{
   const r=await fetch("/api/weather?"+q,{cache:"no-store",headers:{"X-Demo-Request":"1"}});
   const d=await r.json();
   if(id!==requestId)return;
   if(!r.ok||d.error){setStatus("⚠️ "+(d.error||"Weather request failed. Please try again."));return;}
   render(d);
 }catch(error){
   if(id===requestId)setStatus("⚠️ Could not reach the weather demo. Check that its terminal command is still running.");
 }
}
function run(){
 const city=$("#city").value;
 if(city){const c={Lisbon:[38.72,-9.14],Porto:[41.15,-8.61],London:[51.51,-0.13],Reykjavik:[64.15,-21.94]}[city];
   if(cancelLocation)cancelLocation();
   return decide(c[0],c[1],city,++requestId);}
 return locate();
}
function locate(){
 if(cancelLocation)cancelLocation();
 const id=++requestId;
 if(REPLAY){setStatus("My location needs live mode. Restart without --replay, or pick a sample city.");return;}
 $("#city").value="";
 if(!navigator.geolocation){setStatus("Location is unavailable in this browser. Open the demo in a browser with location support, or pick a sample city.");return;}
 let settled=false, timer=null, permission=null, phase=null;
 const denied="Location permission was denied. Allow location for this page in your browser, or pick a sample city.";
 const finish=callback=>{
   if(settled)return;
   settled=true; clearTimeout(timer);
   if(permission)permission.removeEventListener("change",permissionChanged);
   cancelLocation=null;
   if(id===requestId)callback();
 };
 const setPhase=next=>{
   if(settled||id!==requestId||phase===next)return;
   phase=next; clearTimeout(timer);
   const prompt=phase==="prompt";
   setStatus(prompt?"Allow location in your browser to continue. If no permission prompt appears, try another browser or pick a sample city.":"Finding a fresh location…");
   // Native geolocation excludes permission waiting from its acquisition
   // timeout. Keep separate fallback waits for permission and the provider.
   timer=setTimeout(()=>finish(()=>setStatus(prompt
     ?"Location permission is still pending. If no permission prompt appears, try another browser or pick a sample city."
     :"Your browser did not return a location. Check browser permission and your device's Location Services, try another browser, or pick a sample city.")),prompt?60000:35000);
 };
 const permissionChanged=()=>{
   if(permission.state==="denied")finish(()=>setStatus(denied));
   else setPhase(permission.state);
 };
 cancelLocation=()=>finish(()=>{});
 setPhase("locating");
 try{
   // Request on the user's click, retaining the browser's user activation.
   navigator.geolocation.getCurrentPosition(
     p=>finish(()=>decide(p.coords.latitude,p.coords.longitude,"",id)),
     error=>finish(()=>setStatus(error.code===1?denied
       :error.code===3?"Your browser could not find a fresh location within 30 seconds. Check Location Services, try another browser, or pick a sample city."
       :"Your browser's location provider is unavailable. Check Location Services, try another browser, or pick a sample city.")),
     {maximumAge:0,timeout:30000});
 }catch(error){finish(()=>setStatus("This browser could not start a location request. Try another browser or pick a sample city."));}
 try{
   if(navigator.permissions)navigator.permissions.query({name:"geolocation"}).then(result=>{
     if(settled)return;
     permission=result;
     permission.addEventListener("change",permissionChanged);
     permissionChanged();
   }).catch(()=>{}); // Some browsers cannot query geolocation permission.
 }catch(error){}   // The native request and fallback timer still apply.
}
(async()=>{
 $("#mode").textContent=REPLAY?"Replay mode · recorded sample cities · location unavailable":"Live mode · fresh weather and model decisions on every request";
 $("#locate").disabled=REPLAY;
 $("#city option[value='']").disabled=REPLAY;
 $("#locate").title=REPLAY?"Restart without --replay to use your location":"Request a fresh location and weather";
 try{
   const m=await (await fetch("/api/models",{cache:"no-store"})).json();
   $("#model").innerHTML=m.map(x=>`<option>${escapeHTML(x)}</option>`).join("");
   $("#go").onclick=run; $("#locate").onclick=locate;
   $("#city").onchange=run; $("#model").onchange=run; run();
 }catch(error){setStatus("Could not load models. Check that the weather command is still running and refresh the page.");}
})();
</script></body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--replay", action="store_true", help="no network: cities from fixtures, decisions from cache")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    if args.replay:
        os.environ["DM_REPLAY"] = "1"   # belt and braces for anything reading the env
    # 127.0.0.1 only: geolocation works on http over localhost, and nothing is exposed.
    mode = "REPLAY (recorded cities; location unavailable)" if args.replay else "LIVE (fresh weather and decisions)"
    print(f"Weather demo: http://127.0.0.1:{args.port} — {mode}", flush=True)
    print("Keep this command running. Press Ctrl+C here to stop the weather server.", flush=True)
    uvicorn.run(build_app(args.replay), host="127.0.0.1", port=args.port,
                log_level="info", access_log=False)


if __name__ == "__main__":
    main()
