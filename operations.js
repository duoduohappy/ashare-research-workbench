moduleInfo.operations={title:'研究任务与持续模拟',description:'质量闸门、不可变策略版本、持久任务队列、持续模拟、日报与恢复演练。'};
const opsStateNames={draft:'草稿',validated:'已验证',paper:'模拟运行',paused:'已暂停',archived:'已归档'};
let opsData=null,opsBusy=false,opsDetailData=null,opsDrawers=[];
async function opsApi(body){return postApi('/api/ops',body);}
function opsMessage(text,warning=false){$('opsMessage').textContent=text;$('opsMessage').className='message'+(warning?' warning':'');}
function opsOptions(id,rows,label,value){const el=$(id),selected=el.value;el.replaceChildren();const blank=document.createElement('option');blank.value='';blank.textContent='请选择';el.append(blank);for(const r of rows){const o=document.createElement('option');o.value=value(r);o.textContent=label(r);el.append(o);}if(rows.some(r=>value(r)===selected))el.value=selected;}
function opsSelected(){if(!$('opsStrategy').value)throw Error('请先选择策略版本');return $('opsStrategy').value;}
function opsPlot(title,type,body,wide=false){const box=document.createElement('section');box.className='wb-chart-card'+(wide?' wide':'');const heading=document.createElement('h3');heading.textContent=title;box.append(heading);const canvas=document.createElement('canvas');canvas.id='opsPlot'+opsDrawers.length;canvas.setAttribute('role','img');canvas.setAttribute('aria-label',title);box.append(canvas);$('opsCharts').append(box);opsDrawers.push({id:canvas.id,type,...body});}
function drawOperations(){if(activeModule!=='operations')return;for(const p of opsDrawers){if(p.type==='bar')barsChart(p.id,p.labels,p.values);if(p.type==='lines')wbDrawLine(p.id,p.series);if(p.type==='heat')wbHeat(p.id,p);}}
function opsRender(d){
 opsData=d;const selected=$('opsStrategy').value;const byId=Object.fromEntries(d.strategies.map(s=>[s.id,s]));
 const title=id=>byId[id]?(byId[id].name+' v'+byId[id].version):id.slice(0,8);
 $('opsHeartbeat').textContent=d.worker_alive?(d.scheduler_enabled?'后台在线 · 调度开启':'后台在线 · 调度暂停'):'后台无有效心跳';
 $('opsHeartbeat').style.color=d.worker_alive?'#209d7b':'#b86b21';$('opsScheduler').textContent=d.scheduler_enabled?'暂停全部新任务':'恢复后台调度';
 const alerts=[];if(!d.worker_alive)alerts.push('后台无有效租约与心跳，任务不会自动运行。');if(!d.scheduler_enabled)alerts.push('调度暂停，新任务将留在队列。');if(d.long_running)alerts.push('存在超过 30 分钟的执行记录，请核查日志和工作进程。');if(d.reconciliation.some(r=>!r.passed))alerts.push('账户净值核对异常，请暂停相关版本。');if(d.maintenance)alerts.push('维护进行中，暂不接受新任务。');$('opsAlerts').hidden=!alerts.length;$('opsAlerts').textContent=alerts.join(' ');
 opsOptions('opsStrategy',d.strategies,s=>s.name+' v'+s.version+' · '+opsStateNames[s.state]+' · '+(s.config.mode==='demo'?'演示':'真实行情'),s=>s.id);
 if(!selected&&d.strategies.length)$('opsStrategy').value=d.strategies[0].id;
 opsOptions('opsRunSelect',d.runs.filter(r=>r.strategy===$('opsStrategy').value),r=>r.started+' · '+r.kind+' · '+r.status,r=>r.id);
 opsOptions('opsBackupSelect',d.backups,r=>r.id+' · '+wbFmt(r.bytes/1024)+' KB',r=>r.id);
 const failures=d.runs.filter(r=>['blocked','failed'].includes(r.status)).length;
 cards('opsKpis',[['策略版本',d.strategies.length],['排队 / 执行中',d.requests.filter(r=>['queued','executing'].includes(r.state)).length],['近 60 次受阻 / 失败',failures],['账户核对异常',d.reconciliation.filter(r=>!r.passed).length]]);
 tableAt('opsVersions',['版本','数据模式','状态','股票池','创建时间','原因'],d.strategies.map(s=>[title(s.id),s.config.mode==='demo'?'合成隔离':'真实行情',opsStateNames[s.state],s.config.codes.join(' / '),s.created_at,s.reason]));
 tableAt('opsRequests',['请求编号','版本','任务','截止日','队列状态','错误'],d.requests.map(r=>[r.id.slice(0,8),title(r.strategy),r.kind,r.asof,r.state,r.error||'—']));
 tableAt('opsRuns',['任务编号','版本','类型','状态','开始时间','结束时间','快照编号'],d.runs.map(r=>[r.id.slice(0,8),title(r.strategy),r.kind,r.status,r.started,r.finished||'运行中',r.snapshot?.slice(0,12)||'—']));
 const sid=$('opsStrategy').value,chosen=d.strategies.find(s=>s.id===sid),reports=d.reports.filter(r=>r.strategy===sid).sort((a,b)=>a.day.localeCompare(b.day));
 if(opsDetailData&&opsDetailData.strategy!==sid){opsDetailData=null;$('opsTaskDetail').hidden=true;$('opsGateTable').replaceChildren();}
 $('opsConfig').textContent=chosen?JSON.stringify(chosen.config,null,2):'请选择版本';
 opsOptions('opsReportSelect',[...reports].reverse(),r=>r.day,r=>r.day);
 if(!$('opsReportSelect').value&&reports.length)$('opsReportSelect').value=reports.at(-1).day;
 tableAt('opsReports',['日期','版本','日盈亏','费用','已实现盈亏','回撤','净资产','核对差额','委托 / 受阻'],reports.slice(-30).reverse().map(r=>{const v=r.value;return [r.day,title(r.strategy),wbFmt(v.pnl),wbFmt(v.fees),wbFmt(v.realized),pct(v.drawdown),wbFmt(v.account.equity),wbFmt(v.reconciliation_difference),v.decisions.filter(x=>x.status==='filled').length+' / '+v.decisions.filter(x=>x.status==='rejected').length];}));
 tableAt('opsLogs',['时间','级别','组件','记录'],d.logs.map(r=>[r.at,r.level,title(r.component),r.message]));
 $('opsVersionNote').textContent=chosen?title(chosen.id)+'：'+chosen.reason+'。'+(chosen.config.mode==='demo'?'合成模式仅验证功能与流程，不代表市场收益。':'真实数据模式仍仅模拟，订单不会发送到券商。'):'先新建策略版本，再提交研究验证。';
 $('opsLimitations').textContent=d.note+' 旧研究图表不等同运营认证结果。数据快照是冻结时的当前修订版本，不是严格历史 PIT。未覆盖的停牌或公司行动会使模拟暂停，需要人工核对。';
 opsDrawers=[];$('opsCharts').replaceChildren();
 const states=['draft','validated','paper','paused','archived'];opsPlot('策略生命周期分布','bar',{labels:states.map(s=>opsStateNames[s]),values:states.map(s=>d.strategies.filter(v=>v.state===s).length)});
 const runStates=['success','queued','running','blocked','failed'];opsPlot('近期任务健康状态','bar',{labels:['成功','排队','执行','被闸门阻断','失败'],values:runStates.map(s=>s==='queued'?d.requests.filter(r=>r.state==='queued').length:d.runs.filter(r=>r.status===s).length)});
 opsPlot('所选版本 · 连续模拟净资产','lines',{series:[{name:'模拟净资产（元）',points:reports.map(r=>({date:r.day,value:r.value.account.equity}))}]},true);
 const dates=reports.slice(-20).map(r=>r.day),codes=chosen?.config.codes||[];
 opsPlot('最近 20 个日报 · 逐股收益归因（元）','heat',{labels:codes,columns:dates,values:codes.map(code=>reports.slice(-20).map(r=>r.value.contributions[code]??0))},true);
 if(opsDetailData?.gate){const c=opsDetailData.gate.checks;opsPlot('所选任务 · 数据质量检查','bar',{labels:['通过','阻断'],values:[c.filter(r=>r.pass).length,c.filter(r=>!r.pass).length]});}
 drawOperations();
 renderOpsReport();
}
function renderOpsReport(){
 const report=opsData?.reports.find(r=>r.strategy===$('opsStrategy').value&&r.day===$('opsReportSelect').value);
 if(!report){$('opsReportSummary').textContent='暂无日报；启动后在新的已核验交易日生成。';$('opsReportDecisions').replaceChildren();return;}
 const v=report.value;$('opsReportSummary').textContent=report.day+' · 净资产 '+wbFmt(v.account.equity)+' 元 · 现金 '+wbFmt(v.account.cash)+' 元 · 费用 '+wbFmt(v.fees)+' 元 · 归因核对差额 '+wbFmt(v.reconciliation_difference)+' 元';
 tableAt('opsReportDecisions',['股票','信号日期','动量','状态信号','方向','结果','股数','模拟价格','费用','原因'],v.decisions.map(r=>[r.code,r.signal?.date||'—',r.signal?pct(r.signal.momentum):'—',r.signal?.markov_signal?.toFixed(3)||'—',r.side,{filled:'模拟成交',rejected:'受阻',no_order:'不委托'}[r.status],r.qty||0,r.price?wbFmt(r.price):'—',wbFmt(r.fees||0),r.reason]));
}
let opsStatusPending=null;
async function refreshOperations(quiet=false,afterChange=false){
 if(afterChange&&opsStatusPending){try{await opsStatusPending;}catch{}}
 if(!opsStatusPending)opsStatusPending=opsApi({action:'status'}).then(d=>{opsRender(d);return d;}).finally(()=>{opsStatusPending=null;});
 try{const d=await opsStatusPending;if(!quiet)opsMessage('运营状态已刷新。共 '+d.strategies.length+' 个版本；后台'+(d.worker_alive?'在线':'尚未在线')+'。');return d;}
 catch(e){if(!quiet||!opsData)opsMessage(e.message,true);}
}
function switchOperations(){if(activeModule==='operations'){pause();$('mode').textContent='本地运营';refreshOperations(true);}else $('mode').textContent=data?(data.demo?(live?'演示数据':'演示回放'):(live?'最新行情':'历史回放')):'等待加载';}
async function opsAction(body,onSuccess){
 if(opsBusy)return;opsBusy=true;opsMessage('正在处理…');
 try{const d=await opsApi(body);if(onSuccess)await onSuccess(d);else opsMessage('操作完成。');await refreshOperations(true,true);}
 catch(e){opsMessage(e.name==='TimeoutError'?'请求超时，任务可能仍在后台执行；请刷新队列，避免重复提交。':e.message,true);}
 finally{opsBusy=false;}
}
function wireOperations(){
 $('opsAsOf').value=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai'}).format(new Date());
 $('opsReportSelect').onchange=renderOpsReport;
 $('opsClone').onclick=()=>{const s=opsData?.strategies.find(s=>s.id===$('opsStrategy').value);if(!s)return;const c=s.config;for(const [id,value] of Object.entries({opsName:s.name,opsCodes:c.codes.join(','),opsMode:c.mode,opsWindow:c.window,opsThreshold:c.threshold*100,opsMa:c.ma,opsMomentum:c.momentum,opsCapital:c.capital,opsWeight:c.max_weight*100,opsRisk:c.max_drawdown*100,opsOrders:c.daily_orders}))$(id).value=value;opsMessage('参数已复制到表单。保存会创建新草稿，原版本和账户不会改变。');};
 $('opsRefresh').onclick=()=>refreshOperations();$('opsStrategy').onchange=()=>{if(opsData)opsRender(opsData);};
 $('opsUsePool').onclick=()=>{$('opsCodes').value=wbKind==='watch'&&wbResult?.rows?.length?wbResult.rows.map(r=>r.code).join(','):$('candidatePool').value;opsMessage('股票池已填入，保存时会绑定到不可变版本。');};
 $('opsCreate').onclick=()=>{
  const config={codes:$('opsCodes').value.trim().split(/[,，\s]+/),mode:$('opsMode').value,window:Number($('opsWindow').value),threshold:Number($('opsThreshold').value)/100,ma:Number($('opsMa').value),momentum:Number($('opsMomentum').value),capital:Number($('opsCapital').value),max_weight:Number($('opsWeight').value)/100,max_drawdown:Number($('opsRisk').value)/100,daily_orders:Number($('opsOrders').value)};
  opsAction({action:'create',name:$('opsName').value,config},async d=>{await refreshOperations(true);$('opsStrategy').value=d.strategy_id;opsMessage('新版本已保存。请提交研究验证，闸门通过前不能启动模拟。');});
 };
 function queue(kind){try{opsAction({action:'queue',strategy_id:opsSelected(),kind,asof:$('opsAsOf').value,request_id:crypto.randomUUID().replaceAll('-','')},d=>opsMessage('已持久排队：'+d.request_id.slice(0,8)+'。后台将处理，关闭页面不会丢失任务。'));}catch(e){opsMessage(e.message,true);}}
 $('opsResearch').onclick=()=>queue('research');$('opsRunPaper').onclick=()=>queue('paper');
 for(const [id,state] of [['opsEnable','paper'],['opsPause','paused'],['opsArchive','archived']])$(id).onclick=()=>{try{opsAction({action:'transition',strategy_id:opsSelected(),state},()=>opsMessage('版本状态已更新为'+opsStateNames[state]+'。启动模拟只从验证截止日之后的新交易日开始，不补造历史成交。'));}catch(e){opsMessage(e.message,true);}};
 $('opsStartWorker').onclick=()=>opsAction({action:'worker_start'},d=>opsMessage(d.message));
 $('opsStopWorker').onclick=()=>opsAction({action:'worker_stop'},d=>opsMessage(d.message));
 $('opsScheduler').onclick=()=>opsAction({action:'scheduler',enabled:!opsData?.scheduler_enabled},()=>opsMessage('后台调度已切换；当前任务会完成，暂停策略可以阻止下一日事务推进。'));
 $('opsDetail').onclick=()=>{const id=$('opsRunSelect').value;if(!id)return;opsAction({action:'detail',run_id:id},d=>{opsDetailData=d;$('opsTaskDetail').hidden=false;$('opsTaskDetail').textContent='任务 '+d.id+' · '+d.status+'\n'+(d.error||'')+'\n快照：'+(d.snapshot||'无')+'\n引擎：'+d.engine;tableAt('opsGateTable',['质量检查','结果','说明'],(d.gate?.checks||[]).map(c=>[c.check,c.pass?'通过':'阻断',c.detail]));if(opsData)opsRender(opsData);opsMessage('已加载任务来源清单和质量闸门。');});};
 $('opsReplay').onclick=()=>{const id=$('opsRunSelect').value;if(!id)return;opsAction({action:'replay',run_id:id},d=>opsMessage(d.match?'冻结数据与同版引擎复现一致。':'复现存在差异，请停止使用此结果并检查日志。',!d.match));};
 $('opsExport').onclick=async()=>{try{const id=$('opsRunSelect').value;if(!id)throw Error('请选择任务');const d=await opsApi({action:'detail',run_id:id});const url=URL.createObjectURL(new Blob([JSON.stringify(d,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='task-'+id+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){opsMessage(e.message,true);}};
 $('opsBackup').onclick=()=>opsAction({action:'backup'},d=>opsMessage('已创建并校验备份：'+d.id+'。恢复操作默认进入隔离副本。'));
 $('opsDownload').onclick=()=>{const id=$('opsBackupSelect').value;if(!id)return;const a=document.createElement('a');a.href='/api/ops/backup-download?id='+encodeURIComponent(id);a.click();};
 $('opsRestore').onclick=()=>{const id=$('opsBackupSelect').value;if(!id)return;opsAction({action:'restore_drill',backup_id:id},d=>{$('opsRecovery').hidden=false;$('opsRecovery').textContent='完整性检查：'+d.database_integrity+'；恢复版本：'+d.strategies+'；原数据未覆盖。\n'+d.instructions;opsMessage('恢复演练完成。隔离副本调度默认关闭，原数据保持不变。');});};
 setInterval(()=>{if(activeModule==='operations'&&!document.hidden&&!opsBusy)refreshOperations(true);},10000);
 window.addEventListener('resize',drawOperations);
}
