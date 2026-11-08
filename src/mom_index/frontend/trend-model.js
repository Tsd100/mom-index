/* Shared by browser and offline regression checks. No network or DOM access. */
(function(root) {
  const dayMs = 86400000;
  const metricNames = {index:'综合指数',buy:'买入表达评分',sell:'卖出表达评分'};
  function validDay(day) {
    return typeof day === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(day) &&
      Number.isFinite(Date.parse(day)) && new Date(day).toISOString().slice(0,10) === day;
  }
  function offset(day,n) { return new Date(Date.parse(day)+n*dayMs).toISOString().slice(0,10); }
  function todayShanghai() {
    const parts = new Intl.DateTimeFormat('en',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
    const get = type => parts.find(p=>p.type===type).value;
    return `${get('year')}-${get('month')}-${get('day')}`;
  }
  function valueFor(point,metric) {
    if (!point || point.quality?.status !== 'ok' || !Number.isFinite(point.index)) return null;
    const value = metric === 'index' ? point.index : point.details?.[metric === 'buy' ? 'mom_buy_index' : 'mom_sell_index'];
    return Number.isFinite(value) ? value : null;
  }
  function buildTrend(data,options,today=todayShanghai()) {
    const records = (data.sector_history?.[options.sector] || []).filter(p=>validDay(p.date));
    const prices = (data.price_history?.[options.sector] || []).filter(p=>validDay(p.date));
    let end = options.range === 'custom' ? options.end : today;
    let start = options.range === 'custom' ? options.start : offset(today,-(Number(options.range)||30)+1);
    if (options.range === 'all') start = [...records,...prices].map(p=>p.date).filter(d=>d<=today).sort()[0] || today;
    if (!validDay(start) || !validDay(end) || start>end || end>today || (Date.parse(end)-Date.parse(start))/dayMs>3660) {
      return {error:'请选择有效日期：开始不晚于结束，结束不晚于今天，范围不超过十年。',dates:[],values:[],samples:[],points:[],prices:[]};
    }
    const byDay = new Map(records.map(p=>[p.date,p]));
    const priceByDay = new Map(prices.map(p=>[p.date,p.price]));
    const captured = [...records].sort((a,b)=>a.date.localeCompare(b.date));
    const currentEtf = data.instruments?.[options.sector]?.etf;
    const dates = [];
    for (let day=start;day<=end;day=offset(day,1)) dates.push(day);
    const points = dates.map(date=>byDay.get(date) || {date,index:null,missing:true});
    const metric = metricNames[options.metric] ? options.metric : 'index';
    const values = points.map(p=>valueFor(p,metric));
    const samples = points.map(p=>Number.isFinite(p.quality?.valid_count) ? p.quality.valid_count : null);
    const valid = values.map((value,i)=>value === null ? -1 : i).filter(i=>i>=0);
    let comparison = null;
    if (valid.length>=2) {
      const first=valid[0],last=valid[valid.length-1],definition=points[first].definition_id;
      if (definition && points.slice(first,last+1).every((p,i)=>p.definition_id===definition && values[first+i]!==null)) {
        comparison={from:dates[first],to:dates[last],delta:Math.round((values[last]-values[first])*10)/10};
      }
    }
    return {start,end,dates,points,values,samples,comparison,metric,label:metricNames[metric],
      recordedCount:points.filter(p=>!p.missing).length,validCount:valid.length,
      prices:dates.map(date=>{
        const anchor=captured.filter(point=>point.date<=date).at(-1) || captured[0];
        const node=prices.find(point=>point.date===date);
        return currentEtf && anchor?.instrument?.etf===currentEtf && (!node?.etf || node.etf===currentEtf)
          && Number.isFinite(priceByDay.get(date)) ? priceByDay.get(date) : null;
      })};
  }
  const api={buildTrend,todayShanghai,valueFor};
  root.TrendModel=api;
  if (typeof module !== 'undefined' && module.exports) module.exports=api;
})(globalThis);
