// 使用已有 Chromium 与原生 CDP，无额外 npm 依赖。截图只放 output/。
import {spawn} from 'node:child_process';
import {readFile, writeFile, mkdir, mkdtemp} from 'node:fs/promises';
import {createServer} from 'node:http';
import {resolve, join} from 'node:path';
import assert from 'node:assert/strict';

const browser = process.argv[2] || process.env.CHROME_PATH;
assert(browser, '提供已有 Chromium 可执行文件路径');
const out = resolve('output');
await mkdir(out, {recursive: true});
const profile = await mkdtemp(join(out, 'qa-browser-'));
const html = await readFile('src/mom_index/frontend/dashboard.html', 'utf8');
const chartjs = await readFile('src/mom_index/frontend/vendor/chart.umd.min.js');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
await writeFile(join(out, 'dashboard-check.js'), scripts.join('\n'));
const ids = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(m => m[1]));
for (const script of scripts) {
  for (const match of script.matchAll(/getElementById\(['"]([^'"]+)['"]\)/g)) {
    assert(ids.has(match[1]), `缺少 ID ${match[1]}`);
  }
}
const fixture = {
  schema_version: 2, mode: 'production', real_record_count: 3, record_count: 3,
  excluded_records: {mock: 29, unverified: 3}, real_dates: ['2026-10-13', '2026-10-14', '2026-10-15'],
  price_real_dates: ['2026-10-13', '2026-10-14', '2026-10-15'],
  latest: {date: '2026-10-15', provenance: {schema_version: 2, run_id: 'browser-test', mock_excluded: true,
    started_at: new Date(Date.now() - 12000).toISOString(), finished_at: new Date().toISOString(),
    definition: {id: 'browser-test-definition', audit_id: 'browser-audit-fingerprint'},
    sources: {guba: {status: 'partial', sectors: {gold: {status: 'partial', parsed_count: 30,
      requested_pages: 3, fetched_pages: 2, error_type: 'Timeout'}}}, xhs: {status: 'disabled'}, xueqiu: {status: 'disabled'}}},
    sectors: {gold: {index: 45, interpretation: '开始升温', quality: {status: 'ok', sample_count: 50,
      valid_count: 45, fresh_count: 40, newly_seen_count: 20, previously_seen_count: 30},
      details: {}, top_newbie_posts: [{title: '<img src=x onerror="window.injected=true">', source_url: 'https://guba.eastmoney.com/news,sh518880,1.html', score: 50,
        reasoning: '测试转义', key_signals: ['小白'], intent_label: '买入'}]}}},
  signals: [{sector: 'gold', name: '黄金', index: 45, delta: 1, level: 'watch', action: '开始升温', extras: ''}],
  sector_history: {gold: [{date: '2026-10-15', index: 45}]},
  price_history: {gold: [{date: '2026-10-13', price: 8}, {date: '2026-10-14', price: 9}, {date: '2026-10-15', price: 8.5}]},
  daily_summary: {status:'ready',date:'2026-10-15',available_count:1,total_count:1,
    highlights:[{sector:'gold',index:45,delta:15,comparison_date:'2026-10-12',valid_count:45,sample_count:50,
      evidence:[{title:'<img src=x onerror="window.injected=true">',reasoning:'命中加仓',
        source_url:'https://guba.eastmoney.com/news,sh518880,1.html'}]}],unavailable:[],not_comparable:[]},
};
fixture.latest.sectors.gold.recent_observation = {version:'recent-updated-v1',status:'ok',recent_count:35,valid_count:45,
  unknown_time_count:0,directions:{buy:20,sell:5,neutral:10},mean_sentiment:0.25};
fixture.quality_overview = {expired:false,current_qualified_count:1,total_count:1,observed_dates:3,
  sectors:{gold:{status:'ok',collection_status:'ok',valid_count:45,recent_count:35,
    last_collection_success_at:'2026-10-15T17:00:00+08:00',last_qualified_at:'2026-10-15T17:00:00+08:00',
    consecutive_failed_observations:0,reasons:[]}}};
fixture.daily_summary.highlights[0].component_change = {status:'ok',items:[
  {key:'feature_share',label:'特征帖占比',change:5}, {key:'feature_strength',label:'平均特征分',change:5},
  {key:'emotion_extremity',label:'情绪极端度',change:5},{key:'feature_purity',label:'高分特征帖占比',change:0}],rounding_residual:0};
const server = createServer((req, res) => {
  if (req.url === '/vendor/chart.umd.min.js') {
    res.setHeader('Content-Type', 'application/javascript'); res.end(chartjs);
  } else if (req.url === '/data/service_status.json') {
    res.setHeader('Content-Type', 'application/json');
    res.end(JSON.stringify({collection_time:'17:00',status:'partial',next_run_at:'2026-10-25T17:00:00+08:00',result:{valid_sectors:1,total_sectors:12}}));
  } else if (req.url?.startsWith('/data/')) {
    if (dashboardFailure) {res.statusCode = 503; res.end('offline'); return;}
    res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(fixture));
  } else {res.setHeader('Content-Type', 'text/html; charset=utf-8'); res.end(html);}
});
let dashboardFailure = false;
await new Promise(r => server.listen(0, '127.0.0.1', r));
const chrome = spawn(browser, ['--headless=new', '--no-first-run', '--no-default-browser-check',
  '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank'], {stdio: 'ignore', windowsHide: true});
let ws;
try {
  let port;
  for (let i = 0; i < 100; i++) {
    try {port = (await readFile(join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0]; break;} catch {}
    await new Promise(r => setTimeout(r, 100));
  }
  assert(port, 'Chromium 未启动');
  const tabs = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  ws = new WebSocket(tabs.find(t => t.type === 'page').webSocketDebuggerUrl);
  await new Promise((r, reject) => {ws.onopen = r; ws.onerror = reject;});
  let sequence = 0;
  const pending = new Map(), errors = [];
  ws.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.id) {
      const p = pending.get(message.id);
      if (p) {clearTimeout(p.timer); pending.delete(message.id); message.error ? p.reject(message.error) : p.resolve(message.result);}
    } else if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails.text);
  };
  const call = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence;
    const timer = setTimeout(() => reject(new Error(`CDP timeout: ${method}`)), 15000);
    pending.set(id, {resolve, reject, timer}); ws.send(JSON.stringify({id, method, params}));
  });
  const evaluate = async expression => {
    const result = await call('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
    assert(!result.exceptionDetails, JSON.stringify(result.exceptionDetails));
    return result.result.value;
  };
  await call('Runtime.enable');
  await call('Page.enable');
  for (const dpr of [1, 2]) {
    await call('Emulation.setDeviceMetricsOverride', {width: 1280, height: 960, deviceScaleFactor: dpr, mobile: false});
    await call('Page.navigate', {url: `http://127.0.0.1:${server.address().port}/`});
    let ready = false;
    for (let i = 0; i < 100; i++) {
      ready = await evaluate(`typeof Chart !== 'undefined' && document.querySelectorAll('canvas').length === 1`);
      if (ready) break;
      await new Promise(r => setTimeout(r, 100));
    }
    assert(ready, 'Chart.js 未加载或画布没有生成');
    assert(await evaluate(`document.getElementById('quality-overview')?.textContent.includes('最近抓取成功')`), '缺少质量面板');
    assert(await evaluate(`document.getElementById('recent-observations')?.textContent.includes('35/45') && document.getElementById('recent-observations')?.textContent.includes('买入表达 20')`), '近期观察数量或方向缺失');
    assert(await evaluate(`document.querySelector('.component-change')?.textContent.includes('特征帖占比')`), '公式变化拆解未显示');
    const precisionText = await evaluate(`renderComponentChange({status:'ok',items:[{label:'分量',change:-1.3333}],rounding_residual:-0.0503})`);
    assert(precisionText.includes('-1.3333') && precisionText.includes('-0.0503'), '展示舍入丢失核对精度');
    assert(await evaluate(`document.getElementById('daily-summary')?.textContent.includes('2026-10-12') && document.getElementById('daily-summary')?.textContent.includes('+15.0')`), '每日摘要未显示实际比较日期与变化');
    assert(await evaluate(`document.querySelector('#daily-summary .summary-source')?.getAttribute('href') === 'https://guba.eastmoney.com/news,sh518880,1.html'`), '摘要原帖链接丢失');
    await evaluate(`document.querySelector('#daily-summary details').open = true`);
    assert(await evaluate(`document.getElementById('runtime-status').textContent.includes('17:00') && document.getElementById('runtime-status').textContent.includes('1/12')`), 'NAS每日采集状态未显示');
    await new Promise(r => setTimeout(r, 1200));
    const chartData = await evaluate(`(() => {const chart=Object.values(Chart.instances)[0];return {labels:chart?.data.labels,series:chart?.data.datasets.map(d=>d.data)}})()`);
    assert.deepEqual(chartData.labels, ['10-13', '10-14', '10-15'], '价格日期不应被情绪记录日期截断');
    assert.deepEqual(chartData.series[0], [null, null, 45], '缺少情绪记录的价格日应保持空值');
    assert.deepEqual(chartData.series[1], [8, 9, 8.5]);
    const segmentColors = await evaluate(`(() => {
      const a={index:30,definition_id:'v1'}, b={index:60,definition_id:'v1'}, failed={index:null,definition_id:'v1'}, changed={index:45,definition_id:'v2'};
      return [emotionSegmentColor([a,null,b],0,2,'#abc'), emotionSegmentColor([a,failed,b],0,2,'#abc'), emotionSegmentColor([a,null,changed],0,2,'#abc')];
    })()`);
    assert.deepEqual(segmentColors, ['#abc', 'transparent', 'transparent'], '曲线应只跨过纯价格日期');
    const pixels = await evaluate(`Array.from(document.querySelectorAll('canvas')).map(canvas => {
      const rgba=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;
      let painted=0,colorful=0; for(let i=0;i<rgba.length;i+=4){if(rgba[i+3])painted++; if(Math.max(rgba[i],rgba[i+1],rgba[i+2])-Math.min(rgba[i],rgba[i+1],rgba[i+2])>30&&rgba[i+3])colorful++;}
      return {painted,colorful,ratio:colorful/(canvas.width*canvas.height),dpr:canvas.width/canvas.clientWidth};
    })`);
    assert(pixels.every(p => p.painted > 500 && p.ratio > .01 && Math.abs(p.dpr-dpr) < .1), JSON.stringify(pixels));
    await evaluate('loadData(); new Promise(r=>setTimeout(r,300))');
    assert.equal(await evaluate(`document.querySelectorAll('.post-item').length`), 1, '刷新重复追加帖子');
    assert.equal(await evaluate('window.injected === true'), false, '帖子 HTML 未转义');
    assert.equal(await evaluate(`document.querySelector('.post-source')?.getAttribute('href')`),
      'https://guba.eastmoney.com/news,sh518880,1.html', '典型帖未保留原帖链接');
    const runStatus = await evaluate(`document.getElementById('mock-banner').textContent`);
    assert(runStatus.includes('Timeout') && runStatus.includes('30') && runStatus.includes('代码审计指纹'), '缺少采集运行状态明细');
    const unsafePost = structuredClone(fixture);
    unsafePost.latest.sectors.gold.top_newbie_posts[0].source_url = 'javascript:alert(1)';
    await evaluate(`renderTopPosts(${JSON.stringify(unsafePost)})`);
    assert.equal(await evaluate(`document.querySelector('.post-source')`), null, '不可信链接被生成为可点击链接');
    assert.equal(await evaluate(`Object.keys(Chart.instances).length`), 1, '刷新泄漏图表');
    dashboardFailure = true;
    await evaluate('loadData(); new Promise(r=>setTimeout(r,300))');
    assert(await evaluate(`document.getElementById('cards').textContent.includes('加载失败')`), '网络失败未显示状态');
    assert.equal(await evaluate(`document.getElementById('signals-panel').textContent.trim()`), '', '网络失败后仍显示旧信号');
    assert.equal(await evaluate(`document.getElementById('daily-summary').textContent.trim()`), '', '网络失败后仍显示旧摘要');
    assert.equal(await evaluate(`document.getElementById('recent-observations').textContent.trim()`), '', '网络失败后仍显示旧近期观察');
    assert.equal(await evaluate(`document.getElementById('quality-overview').textContent.trim()`), '', '网络失败后仍显示旧质量面板');
    assert.equal(await evaluate(`document.getElementById('top-posts').textContent.trim()`), '', '网络失败后仍显示旧帖子');
    assert.equal(await evaluate(`document.getElementById('charts').children.length`), 0, '网络失败后仍显示旧图表');
    assert.equal(await evaluate(`Object.keys(Chart.instances).length`), 0, '网络失败后未销毁旧图表');
    dashboardFailure = false;
    const stale = structuredClone(fixture); stale.latest.provenance.finished_at = '2026-08-08T00:00:00+08:00';
    const view = await evaluate(`productionView(${JSON.stringify(stale)})`);
    assert.equal(view.latest.sectors.gold.index, null);
    assert.equal(view.signals[0].delta, null);
    assert.equal(view.daily_summary.highlights.length, 0, '过期摘要仍显示排名');
    await evaluate(`renderRecentObservations(${JSON.stringify(view)});renderQualityOverview(${JSON.stringify(view)})`);
    assert(await evaluate(`document.getElementById('recent-observations').textContent.includes('过期') && !document.getElementById('recent-observations').textContent.includes('买入表达 20')`), '过期样本仍显示方向判断');
    await evaluate(`renderDailySummary(${JSON.stringify(view)})`);
    assert(await evaluate(`document.getElementById('daily-summary').textContent.includes('过期')`), '过期摘要缺少说明');
    const unsafeSummary = structuredClone(fixture); unsafeSummary.daily_summary.highlights[0].evidence[0].source_url = 'javascript:alert(1)';
    await evaluate(`renderDailySummary(${JSON.stringify(unsafeSummary)})`);
    assert.equal(await evaluate(`document.querySelector('#daily-summary .summary-source')`), null, '摘要生成了不可信原帖链接');
    assert.equal(await evaluate('window.injected === true'), false, '摘要原帖文本未转义');
    const unsafeQuality = structuredClone(fixture); unsafeQuality.quality_overview.sectors.gold.reasons = ['<img src=x onerror="window.injected=true">'];
    await evaluate(`renderQualityOverview(${JSON.stringify(unsafeQuality)})`);
    assert.equal(await evaluate('window.injected === true'), false, '质量原因文本未转义');
    await evaluate(`renderDailySummary(${JSON.stringify(fixture)})`);
    assert.equal((await evaluate(`productionView({latest:{sectors:{gold:{index:99}}},record_count:31})`)).latest, null);
    await evaluate('loadData(); new Promise(r=>setTimeout(r,350))');
    await evaluate(`document.querySelector('#daily-summary details').open = true`);
    const shot = await call('Page.captureScreenshot', {format: 'png'});
    await writeFile(join(out, `dashboard-dpr${dpr}.png`), Buffer.from(shot.data, 'base64'));
    console.log(`DPR ${dpr}: PASS`, JSON.stringify(pixels));
  }
  await call('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 2, mobile: true});
  await call('Emulation.setPageScaleFactor', {pageScaleFactor:1});
  await evaluate('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
  const mobileLayout = await evaluate(`({inner:innerWidth,client:document.documentElement.clientWidth,visual:visualViewport.width,wide:[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>400).slice(0,8).map(e=>({tag:e.tagName,cls:e.className,w:e.getBoundingClientRect().width,right:e.getBoundingClientRect().right}))})`);
  assert.equal(mobileLayout.inner,390,JSON.stringify(mobileLayout));
  await evaluate('new Promise(r=>setTimeout(r,350))');
  assert(await evaluate(`[...document.querySelectorAll('canvas')].every(canvas => Math.abs(canvas.width/canvas.clientWidth-2)<0.1)`), '手机图表未按设备像素比重绘');
  // 如果工作区已有本地生产快照，补查实际12板块映射在移动端的展示。
  try {
    const actual = JSON.parse(await readFile('src/mom_index/frontend/data/dashboard_data.json', 'utf8'));
    if (actual.instruments && actual.latest) {
      await evaluate(`{const d=productionView(${JSON.stringify(actual)});renderCards(d);renderDataNotice(d);}`);
      assert(await evaluate(`document.getElementById('cards').textContent.includes('159206') && document.getElementById('cards').textContent.includes('159731')`), '实际映射未显示');
    }
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
  assert(await evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), '手机横向溢出');
  await evaluate(`renderDailySummary(${JSON.stringify(fixture)}); document.querySelector('#daily-summary details').open = true`);
  await evaluate(`document.querySelector('#quality-overview details').open = true; document.querySelector('#recent-observations details').open = true`);
  assert(await evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), '手机摘要横向溢出');
  const mobileShot = await call('Page.captureScreenshot', {format:'png'});
  await writeFile(join(out,'dashboard-mobile.png'),Buffer.from(mobileShot.data,'base64'));
  const empty = {schema_version: 2, mode: 'production', latest: null, sector_history: {}, price_history: {}, signals: []};
  await evaluate(`{const d=${JSON.stringify(empty)};renderCards(d);renderCharts(d);renderTopPosts(d);renderSignals(d);renderDataNotice(d);renderDailySummary(d);renderRecentObservations(d);renderQualityOverview(d);}`);
  assert(await evaluate(`document.getElementById('daily-summary').textContent.includes('等待')`), '无数据摘要未提示等待');
  assert.equal(await evaluate(`document.querySelectorAll('canvas').length`), 0);
  assert.equal(errors.length, 0, JSON.stringify(errors));
  console.log('PASS: 语法对应的 DOM ID、刷新、过期、旧 JSON 拒绝、转义、空数据、移动端与运行时检查');
} finally {
  if (ws) ws.close();
  chrome.kill();
  server.close();
}
