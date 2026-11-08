// Read-only NAS acceptance: uses real published data and changes browser controls only.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdir,mkdtemp,readFile,writeFile} from 'node:fs/promises';
import {resolve,join} from 'node:path';

const browser=process.argv[2];
const origin=process.argv[3] || 'http://192.168.50.33:8503';
assert(browser,'Provide an existing Chromium executable');
const output=resolve('output');await mkdir(output,{recursive:true});
const profile=await mkdtemp(join(output,'nas-qa-'));
const health=await (await fetch(origin+'/healthz')).json();
assert.equal(health.version,'2026.11.08.1');
const child=spawn(browser,['--headless=new','--no-first-run','--no-default-browser-check',
  '--remote-debugging-port=0',`--user-data-dir=${profile}`,'about:blank'],{stdio:'ignore',windowsHide:true});
let ws;
try {
  let port;
  for(let attempt=0;attempt<100;attempt++) {
    try {port=(await readFile(join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0];break;} catch {}
    await new Promise(r=>setTimeout(r,100));
  }
  assert(port,'Browser did not start');
  let tab;
  for(let attempt=0;attempt<50;attempt++) {
    tab=(await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(t=>t.type==='page');
    if(tab) break;await new Promise(r=>setTimeout(r,100));
  }
  assert(tab);ws=new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
  let sequence=0;const pending=new Map(),errors=[];
  ws.onmessage=event=>{
    const message=JSON.parse(event.data);
    if(message.id) {const item=pending.get(message.id);if(item){clearTimeout(item.timer);pending.delete(message.id);message.error?item.reject(message.error):item.resolve(message.result);}}
    else if(message.method==='Runtime.exceptionThrown') errors.push(message.params.exceptionDetails.text);
  };
  const call=(method,params={})=>new Promise((resolve,reject)=>{
    const id=++sequence;const timer=setTimeout(()=>reject(new Error('CDP timeout '+method)),15000);
    pending.set(id,{resolve,reject,timer});ws.send(JSON.stringify({id,method,params}));
  });
  const evaluate=async expression=>{
    const result=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
    assert(!result.exceptionDetails,JSON.stringify(result.exceptionDetails));return result.result.value;
  };
  await call('Runtime.enable');await call('Page.enable');
  await call('Emulation.setDeviceMetricsOverride',{width:1280,height:960,deviceScaleFactor:1,mobile:false});
  await call('Page.navigate',{url:origin+'/dashboard.html'});
  let ready=false;
  for(let attempt=0;attempt<150;attempt++) {
    ready=await evaluate(`typeof trendData!=='undefined' && trendData?.real_dates?.includes('2026-10-15') && typeof TrendModel!=='undefined'`);
    if(ready) break;await new Promise(r=>setTimeout(r,100));
  }
  assert(ready,'Real NAS history did not load');
  await evaluate(`document.getElementById('trend-range').value='all';document.getElementById('trend-sector').value='nasdaq';renderCharts(trendData)`);
  assert((await evaluate(`trendView.dates`)).includes('2026-10-15'));
  assert((await evaluate(`trendView.dates`)).includes('2026-11-08'));
  assert(await evaluate(`trendView.recordedCount>=2`));
  await evaluate(`document.getElementById('trend-day').value='2026-10-15';renderTrendDetail('2026-10-15')`);
  assert(await evaluate(`document.getElementById('trend-detail').textContent.includes('2026-10-15')`));
  await evaluate(`document.getElementById('trend-metric').value='buy';renderCharts(trendData)`);
  assert.equal(await evaluate('trendView.metric'),'buy');
  await evaluate(`document.getElementById('trend-sector').value='gold';renderCharts(trendData)`);
  assert.equal(await evaluate(`document.getElementById('trend-sector').value`),'gold');
  await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:2,mobile:true});
  await call('Emulation.setPageScaleFactor',{pageScaleFactor:1});
  await evaluate('new Promise(r=>setTimeout(r,600))');
  assert(await evaluate(`innerWidth===390 && document.documentElement.scrollWidth<=391`),'NAS mobile overflow');
  assert.equal(errors.length,0,JSON.stringify(errors));
  const screenshot=await call('Page.captureScreenshot',{format:'png'});
  await writeFile(join(output,'nas-dashboard-mobile.png'),Buffer.from(screenshot.data,'base64'));
  console.log('PASS: real NAS version, historical dates, sector/metric controls, date details, mobile layout and runtime');
} finally {if(ws)ws.close();child.kill();}
