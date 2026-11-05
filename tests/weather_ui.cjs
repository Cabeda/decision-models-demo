// Run the app's actual inline script with controlled browser callbacks.
// Python supplies the HTML and a real replay response on stdin; no browser,
// user coordinates, or external service is involved in these checks.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const source = input.html.match(/<script>([\s\S]*?)<\/script>/)[1];
const flush = () => new Promise(resolve => setImmediate(resolve));

async function boot(replay, permissionState) {
  const nodes = {};
  for (const key of ['model','city','mode','locate','go','summary','headline','cards','meta']) {
    nodes['#'+key] = {value:'',textContent:'',innerHTML:'',disabled:false};
  }
  nodes['#city'].value = 'Lisbon';
  nodes['#model'].value = 'laya:en';
  nodes["#city option[value='']"] = {disabled:false};
  const calls = [], positions = [], timers = new Map();
  let nextTimer = 0, now = 0;
  const permissionListeners = new Set();
  const permission = {
    state: permissionState,
    addEventListener:(name,callback)=>permissionListeners.add(callback),
    removeEventListener:(name,callback)=>permissionListeners.delete(callback),
  };
  const context = {
    document:{querySelector:key=>nodes[key],body:{style:{}}},
    navigator:{geolocation:{getCurrentPosition:(success,error,options)=>positions.push({success,error,options})}},
    URLSearchParams,
    setTimeout:(callback,delay)=>{timers.set(++nextTimer,{callback,at:now+delay});return nextTimer;},
    clearTimeout:id=>timers.delete(id),
    fetch:async (url,options)=>{
      calls.push({url,options});
      return {ok:true,json:async()=>url==='/api/models'
        ?['laya:en']:{...input.response,cached:replay}};
    },
  };
  if (permissionState) context.navigator.permissions={query:async()=>permission};
  function advance(ms) {
    const target=now+ms;
    while(true) {
      const next=[...timers].filter(([,timer])=>timer.at<=target).sort((a,b)=>a[1].at-b[1].at)[0];
      if(!next)break;
      now=next[1].at;timers.delete(next[0]);next[1].callback();
    }
    now=target;
  }
  function setPermission(state) {
    permission.state=state;
    for(const listener of [...permissionListeners])listener();
  }
  vm.runInNewContext(source.replace('__REPLAY__',String(replay)),context);
  await flush();
  return {nodes,calls,positions,timers,advance,setPermission,permissionListeners};
}

(async()=>{
  const delayed = await boot(false,'granted');
  delayed.nodes['#locate'].onclick();
  await flush();
  delayed.advance(12000);
  assert.doesNotMatch(delayed.nodes['#summary'].textContent,/timed out|did not return/i,
    'a valid position after twelve seconds must not be discarded');
  delayed.positions[0].success({coords:{latitude:41.15,longitude:-8.61}});
  await flush();
  assert.match(delayed.nodes['#meta'].textContent,/Fresh response/);
  assert.equal(delayed.permissionListeners.size,0,'release permission listener after success');

  const live = await boot(false);
  assert.equal(live.positions.length,0,'page load should not silently request location');
  live.nodes['#locate'].onclick();
  assert.equal(live.positions[0].options.maximumAge,0,'cached positions must be rejected');
  assert.ok(live.positions[0].options.timeout>=30000,'allow a reasonable acquisition window');
  live.positions[0].success({coords:{latitude:41.15,longitude:-8.61}});
  await flush();
  assert.match(live.nodes['#meta'].textContent,/Fresh response/);
  assert.equal(live.calls.at(-1).options.cache,'no-store');
  assert.equal(new URLSearchParams(live.calls.at(-1).url.split('?')[1]).get('city'),'');
  live.nodes['#go'].onclick();
  assert.equal(live.positions.length,2,'Refresh must request a new position again');
  live.positions[1].error({code:1});
  assert.match(live.nodes['#summary'].textContent,/permission was denied/);
  assert.equal(live.nodes['#cards'].innerHTML,'','old answers should not survive a failed location request');

  const stuck = await boot(false);
  stuck.nodes['#locate'].onclick();
  const weatherCalls = stuck.calls.length;
  stuck.advance(35000);
  assert.match(stuck.nodes['#summary'].textContent,/browser did not return a location/i);
  stuck.positions[0].success({coords:{latitude:41.15,longitude:-8.61}});
  await flush();
  assert.equal(stuck.calls.length,weatherCalls,'a late position must not undo the timeout');

  const prompt = await boot(false,'prompt');
  prompt.nodes['#locate'].onclick();
  await flush();
  assert.match(prompt.nodes['#summary'].textContent,/allow location/i);
  prompt.advance(45000);
  assert.doesNotMatch(prompt.nodes['#summary'].textContent,/timed out|did not return/i);
  prompt.setPermission('granted');
  assert.match(prompt.nodes['#summary'].textContent,/finding a fresh location/i);
  prompt.advance(12000);
  prompt.positions[0].success({coords:{latitude:41.15,longitude:-8.61}});
  await flush();
  assert.match(prompt.nodes['#meta'].textContent,/Fresh response/,
    'permission waiting time must not consume the acquisition window');

  const unanswered = await boot(false,'prompt');
  unanswered.nodes['#locate'].onclick();
  await flush();
  unanswered.advance(60000);
  assert.match(unanswered.nodes['#summary'].textContent,/permission.*pending/i);

  const denied = await boot(false,'denied');
  denied.nodes['#locate'].onclick();
  await flush();
  assert.match(denied.nodes['#summary'].textContent,/permission was denied/);
  assert.equal(denied.timers.size,0,'permission rejection should end the wait immediately');

  const unavailable = await boot(false,'granted');
  unavailable.nodes['#locate'].onclick();
  await flush();
  unavailable.positions[0].error({code:2});
  assert.match(unavailable.nodes['#summary'].textContent,/location provider is unavailable/);
  assert.equal(unavailable.timers.size,0);

  const nativeTimeout = await boot(false,'granted');
  nativeTimeout.nodes['#locate'].onclick();
  await flush();
  nativeTimeout.advance(30000);
  nativeTimeout.positions[0].error({code:3});
  assert.match(nativeTimeout.nodes['#summary'].textContent,/within 30 seconds/);
  assert.equal(nativeTimeout.timers.size,0);

  const stale = await boot(false);
  stale.nodes['#locate'].onclick();
  stale.nodes['#city'].value='Porto';
  stale.nodes['#city'].onchange();
  await flush();
  const latestCalls = stale.calls.length;
  stale.positions[0].success({coords:{latitude:38.72,longitude:-9.14}});
  await flush();
  assert.equal(stale.calls.length,latestCalls,'old location must not overwrite a newer city selection');

  const replay = await boot(true);
  assert.equal(replay.nodes['#locate'].disabled,true);
  assert.equal(replay.nodes["#city option[value='']"].disabled,true);
  assert.match(replay.nodes['#mode'].textContent,/Replay mode/);
  assert.match(replay.nodes['#meta'].textContent,/Recorded response/);
  assert.equal(replay.positions.length,0);
  console.log('Weather UI passed: fresh location/refresh, delayed positions, permission waits, denial, timeout, late callbacks, replay.');
})().catch(error=>{console.error(error);process.exitCode=1;});
