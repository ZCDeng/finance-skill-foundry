#!/usr/bin/env node
/** Packaged native-pane QA. Writes an isolated profile/report; never screenshots or calls a model.
 * PLAYWRIGHT_MODULE=/absolute/path/to/playwright QA_APP=/Applications/.../Contents/MacOS/... node tools/verify_native_workspace.cjs
 * Synthetic fixtures are explicitly labelled. They exercise the shipped renderer and input machine,
 * not real provider admission or an OS input-method implementation.
 */
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');
const {execFileSync} = require('node:child_process');
const {_electron} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const qa = fs.mkdtempSync('/tmp/finance-native-workspace-');
const executablePath = process.env.QA_APP;
if (!executablePath) throw new Error('QA_APP must identify the packaged Electron executable');
const resources = path.resolve(path.dirname(executablePath), '../Resources');
const appAsarSha256=createHash('sha256').update(fs.readFileSync(path.join(resources,'app.asar'))).digest('hex');
const bin = process.env.QA_FOUNDRY || path.join(resources, 'foundry/foundry');
if (!fs.existsSync(bin)) throw new Error('Packaged foundry binary missing: ' + bin);
const report = {status:'running', qa, executablePath, appAsarSha256, bin, checks:[], fixtures:[], notTested:['Physical macOS Chinese IME candidate window', 'Real provider admission/streaming', 'Screenshots and visual taste verdict', 'Permissions requiring external side effects']};
let app, page, nativeId, revision = 1000000;
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
function check(name, basis, observed, valid) {
  report.checks.push({name, basis, status:valid ? 'passed' : 'failed', observed});
  if (!valid) throw new Error(name + ': ' + JSON.stringify(observed));
}
async function until(read, accept, label, timeout = 15000) {
  const deadline=Date.now()+timeout;
  let value;
  while (Date.now()<deadline) {value=await read();if(accept(value))return value;await delay(50);}
  throw new Error(label + ': ' + JSON.stringify(value));
}
const cli = (command, args=[], task, raw=false) => {
  const result=execFileSync(bin,['--var',path.join(qa,'var'),...(task?['--task',task]:[]),command,...args],{encoding:'utf8'}).trim();
  return raw ? result : JSON.parse(result);
};
const native = (fn, arg) => app.evaluate(async ({webContents}, {id,code}) => {
  const view=webContents.fromId(id);
  if(!view)throw new Error('native WebContents disappeared');
  const reply=await view.executeJavaScript(code,true);
  if(!reply.ok)throw new Error(reply.error);
  return reply.value;
},{id:nativeId,code:`(async()=>{try{return {ok:true,value:await (${fn.toString()})(${JSON.stringify(arg) ?? 'undefined'})};}catch(error){return {ok:false,error:error.stack||String(error)};}})()`});
const api = (method,args=[]) => page.evaluate(async ({method,args})=>window.foundry[method](...args),{method,args});
const bounds = () => app.evaluate(({BrowserWindow},id)=>{
  const window=BrowserWindow.getAllWindows()[0];
  const view=window.contentView.children.find(child=>child.webContents?.id===id);
  return {rect:view?.getBounds(),visible:view?.getVisible(),content:window.getContentSize(),zoom:window.webContents.getZoomFactor()};
},nativeId);
async function layout(rect) {
  const reply=await api('harnessLayout',[{...rect,revision:++revision}]);
  if(!reply.ok || !reply.value.accepted)throw new Error('layout not accepted: '+JSON.stringify(reply));
  await api('paneVisible',['workbench']);
  return until(bounds,x=>x.rect?.width>0,'native layout');
}
const composer = () => native(()=>{
  const input=document.querySelector('[data-composer-card] textarea');
  return {sessionId:JSON.parse(localStorage.getItem('dsh.sessions.current') ?? 'null')?.sessionId,value:input?.value,editable:Boolean(input&&!input.disabled&&!input.readOnly),font:input?getComputedStyle(input).fontFamily:null,epoch:window.__qaEpoch};
});
// Inject only a context capture, never a replacement React component or CSS. The
// official module loader still invokes the original factory and original apply.
const captureContext = `(() => {
  window.__qaEpoch=crypto.randomUUID();
  window.__qaWireSends=[];
  const oldFetch=window.fetch;
  window.fetch=function(input,init){
    const url=typeof input==='string'?input:input.url;
    if (/\\/api\\/session\\.(prompt|send)(?:[/?]|$)/.test(url)) {window.__qaWireSends.push(url);return Promise.reject(new Error('QA forbids real prompt admission'));}
    return oldFetch.call(this,input,init);
  };
  let current;
  function hook(loader){
    if(!loader || loader.__qaHooked)return loader;
    loader.__qaHooked=true;
    let load=loader.load;
    Object.defineProperty(loader,'load',{configurable:true,get(){return registration=>{
      if(registration.id==='@deepseek-ai/dsh-client-ui-conversation'){
        const factory=registration.factory;
        registration={...registration,factory(require){
          const exports=factory(require),apply=exports.apply;
          exports.apply=function(ctx){
            const result=apply.call(this,ctx);
            ctx.inject(['conversation','sessions','layout'],function nativeQaObservation(ready){window.__qaContext=ready;});
            return result;
          };
          return exports;
        }};
      }
      return load.call(loader,registration);
    };},set(value){load=value;}});
    return loader;
  }
  Object.defineProperty(window,'__ModuleLoader__',{configurable:true,get(){return current;},set(value){current=hook(value);}});
})();`;
(async()=>{
  const taskA=cli('task-new',['--title','验收：区域收入分析'],undefined,true);
  const taskB=cli('task-new',['--title','验收：资金安排'],undefined,true);
  report.tasks=[taskA,taskB];
  const env={...process.env,FOUNDRY_VAR:path.join(qa,'var')};
  for(const key of ['FOUNDRY_BIN','FOUNDRY_DSH_INSTALL','FOUNDRY_FORMULATOR_BIN','OPENAI_API_KEY','ANTHROPIC_API_KEY','DEEPSEEK_API_KEY'])delete env[key];
  app=await _electron.launch({executablePath,args:['--user-data-dir='+path.join(qa,'profile')],env,timeout:60000});
  page=await app.firstWindow();
  await page.waitForLoadState('domcontentloaded');
  await page.waitForFunction(()=>window.foundry?.harnessOpen);
  await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setContentSize(1600,900));
  await until(()=>api('harnessStatus'),reply=>{
    if(reply.ok&&reply.value.wiring.state==='failed')throw new Error('packaged wiring failed: '+JSON.stringify(reply));
    return reply.ok&&reply.value.wiring.state==='ready';
  },'packaged wiring',90000);
  // Let the real shell finish its own initial task/session restore before
  // testing the native boundary directly. This avoids racing startup effects.
  const expandTasks=page.getByRole('button',{name:'展开任务列表',exact:true});
  if(await expandTasks.isVisible())await expandTasks.click();
  await page.locator('.workspace-task[title="验收：区域收入分析"]').click();
  await page.waitForFunction(()=>document.querySelector('.workspace-task[title="验收：区域收入分析"]')?.getAttribute('aria-current')==='true');
  nativeId=await until(()=>app.evaluate(({webContents})=>webContents.getAllWebContents().find(w=>w.getURL().startsWith('http://127.0.0.1:'))?.id),Boolean,'native WebContents',45000);
  await until(bounds,value=>value.rect?.width>0,'shell initial native restore',45000);
  const opened=await api('harnessOpen',['analysis',taskA,{verbatim:'未发送：比较区域收入'}]);
  check('open_bound_task','real packaged main/CLI/native service',opened,opened.ok&&Boolean(opened.value.sessionId));
  const sessionA=opened.value.sessionId;
  await native(id=>{
    const key='dsh.conversation.chat.'+id;
    const state=JSON.parse(localStorage.getItem(key)??'{}');
    localStorage.setItem(key,JSON.stringify({...state,selection:{callId:'qa-call',toolName:'qa_financial_fixture'}}));
  },sessionA);
  await app.evaluate(async ({webContents},{id,source})=>{
    const w=webContents.fromId(id);
    if(!w.debugger.isAttached())w.debugger.attach('1.3');
    await w.debugger.sendCommand('Page.enable');
    await w.debugger.sendCommand('Page.addScriptToEvaluateOnNewDocument',{source});
    // One explicit setup reload installs test observation. All no-reload tests
    // establish their baseline after this point.
    w.reload();
  },{id:nativeId,source:captureContext});
  await until(()=>native(()=>{try{return {ready:Boolean(window.__qaContext?.conversation?.input&&window.__foundryEmbedded),context:Boolean(window.__qaContext),bridge:Boolean(window.__foundryEmbedded)};}catch(error){return {ready:false,error:error.stack,context:Boolean(window.__qaContext),bridge:Boolean(window.__foundryEmbedded)};}}),value=>value.ready,'native fixture context',15000);
  await api('harnessOpen',['analysis',taskA]);
  await native(()=>Array.from(document.querySelectorAll('button')).find(b=>['Configure later','稍后配置','稍后设置'].includes(b.textContent.trim()))?.click());
  await layout({x:192,y:110,width:400,height:700});
  const initial=await until(composer,state=>state.editable&&state.value?.includes('未发送'),'native composer');
  check('native_composer_and_offline_font','real DOM/computed style',initial,initial.sessionId===sessionA&&initial.font.includes('Noto Sans SC'));
  // Playwright defaults every discovered page to light. Clear that test-only
  // override so the native page can observe Electron's actual system theme.
  for(const target of app.context().pages())await target.emulateMedia({colorScheme:null});
  for(const scheme of ['dark','light']){
    await app.evaluate(({nativeTheme},value)=>{nativeTheme.themeSource=value;},scheme);
    const theme=await until(()=>native(()=>({dark:matchMedia('(prefers-color-scheme: dark)').matches,scheme:document.documentElement.style.colorScheme,background:getComputedStyle(document.body).backgroundColor})),value=>value.scheme===scheme,'native theme '+scheme);
    check('native_system_theme_'+scheme,'real Electron nativeTheme; Playwright color override removed',theme,theme.dark===(scheme==='dark'));
  }
  await app.evaluate(({nativeTheme})=>{nativeTheme.themeSource='system';});
  const second=await api('harnessOpen',['analysis',taskB,{verbatim:'未发送：资金安排'}]);
  check('second_task_has_distinct_session','real main/CLI/native service',second,second.ok&&second.value.sessionId!==sessionA);
  await api('harnessOpen',['analysis',taskA]);
  const restored=await until(composer,state=>state.sessionId===sessionA&&state.value?.includes('区域收入'),'passive A restore');
  check('passive_A_B_A_preserves_draft_without_reload','real resident input and document identity',restored,restored.epoch===initial.epoch&&!restored.value.includes('资金安排'));
  await api('paneVisible',['']);
  const hidden=await bounds();
  check('hidden_native_surface','real WebContentsView visibility and bounds; zero bounds alone are insufficient',hidden,hidden.visible===false&&hidden.rect.width===0&&hidden.rect.height===0);
  await api('paneVisible',['workbench']);
  const shown=await composer();
  check('shown_native_surface','real WebContentsView visibility',await bounds(),(await bounds()).visible===true);
  check('hide_show_keeps_document_and_draft','real WebContentsView identity',shown,shown.epoch===initial.epoch&&shown.value===restored.value);

  for(const width of [400,460]){
    await layout({x:192,y:110,width,height:700});
    await until(()=>native(()=>window.innerWidth),value=>value===width,'native width');
    const shell=await native(()=>({width:innerWidth,sidebarWidth:document.querySelector('.pI_x6G_sidebarCol')?.getBoundingClientRect().width,nativeTaskButtons:document.querySelectorAll('[data-foundry-settings] button').length,hero:document.querySelector('[data-foundry-empty]')?.textContent,headline:document.querySelector('[class*="_headlineText"]')?.textContent}));
    check(`compact_shell_${width}`,'real DOM',shell,shell.width===width&&shell.sidebarWidth<=40&&!shell.headline);
    await native(()=>{const trigger=document.querySelector('[data-foundry-settings] button');if(!trigger)throw new Error('settings trigger absent');trigger.click();});
    const panel=await until(()=>native(()=>{
      const el=document.querySelector('.VOzbGW_panel');if(!el)return null;
      const r=el.getBoundingClientRect();
      return {x:r.x,y:r.y,width:r.width,height:r.height,viewport:{width:innerWidth,height:innerHeight},direction:getComputedStyle(el).flexDirection,close:el.querySelector('.VOzbGW_close')?.getBoundingClientRect().toJSON()};
    }),Boolean,'settings panel');
    check(`settings_fits_${width}`,'real native settings slot/render',panel,panel.x>=0&&panel.y>=0&&panel.x+panel.width<=width+1&&panel.y+panel.height<=panel.viewport.height+1&&panel.direction==='column'&&panel.close?.width>0);
    await native(()=>document.querySelector('.VOzbGW_close').click());
    await until(()=>native(()=>!document.querySelector('.VOzbGW_panel')),Boolean,'settings closed');
  }

  // The fixture enters through the shipped Session history-window assembler.
  // The tool card, details renderer and layout below are all the packaged UI.
  await native(id=>{
    const ctx=window.__qaContext, session=ctx.sessions.manager.get(id), time=Date.now();
    const events=[
      {seq:1,time,type:'tool/call',data:{callId:'qa-call',name:'qa_financial_fixture',arguments:JSON.stringify({region:'华东',expression:'SUM(revenue)'}),turn:1,step:1}},
      {seq:2,time:time+1,type:'tool/result',surfaceOp:'append',data:{message:{role:'tool',source:{callId:'qa-call'},content:[{type:'tool-result',content:[{type:'text',text:'QA_SYNTHETIC_RESULT: 区域收入 123456.78'}],isError:false}]}}}
    ];
    session.installWindow(events.map(event=>({event})),false);
    session.handleBlank(false);
    const list=ctx.sessions.list.getSnapshot();
    ctx.sessions.list.set({...list,byId:{...list.byId,[id]:{...list.byId[id],blank:false}}});
  },sessionA);
  report.fixtures.push({name:'tool_history',scope:'browser-only Session.installWindow',synthetic:'2 tool lifecycle events; no domain calculation or provider run'});
  await until(()=>native(()=>document.body.innerText.includes('qa_financial_fixture')),Boolean,'synthetic native tool row');
  for(const width of [400,460]){
    await layout({x:192,y:110,width,height:700});
    await until(()=>native(()=>window.innerWidth),value=>value===width,'details native width');
    await native(()=>{document.querySelector('[data-composer-card] textarea').focus();window.__qaContext.layout.openDetails();});
    const detail=await until(()=>native(()=>{
      const panel=document.querySelector('.pI_x6G_detailsCol');if(!panel||getComputedStyle(panel).visibility==='hidden')return null;
      const r=panel.getBoundingClientRect(),close=panel.querySelector('button'),cr=close?.getBoundingClientRect();
      return {width:r.width,x:r.x,height:r.height,text:panel.innerText,close:cr?.toJSON(),centerHidden:getComputedStyle(document.querySelector('.pI_x6G_centerCol')).visibility==='hidden',focusedClose:document.activeElement===close};
    }),value=>Boolean(value?.text.includes('QA_SYNTHETIC_RESULT')&&value.focusedClose&&Math.abs(value.width-width)<=1),'native tool details');
    check(`tool_details_full_width_${width}`,'synthetic tool data; real details DOM/layout/focus',detail,Math.abs(detail.width-width)<=1&&detail.x>=0&&detail.centerHidden&&detail.close.x+detail.close.width<=width+1);
    await app.evaluate(({webContents},id)=>{const w=webContents.fromId(id);w.focus();w.sendInputEvent({type:'keyDown',keyCode:'Escape'});w.sendInputEvent({type:'keyUp',keyCode:'Escape'});},nativeId);
    const closed=await until(()=>native(()=>({hidden:getComputedStyle(document.querySelector('.pI_x6G_detailsCol')).visibility==='hidden',focus:document.activeElement===document.querySelector('[data-composer-card] textarea')})),state=>state.hidden,'details Escape close');
    check(`details_escape_restores_focus_${width}`,'real keyboard dispatch/native focus restoration',closed,closed.focus);
  }

  await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(1.25));
  await layout({x:100,y:100,width:400,height:400});
  const zoomed=await bounds();
  check('layout_css_to_electron_dip','real sender zoom and native rectangle',zoomed,zoomed.zoom===1.25&&zoomed.rect.x===125&&zoomed.rect.y===125&&zoomed.rect.width===500&&zoomed.rect.height===500);
  const before=await bounds();
  const stale=await api('harnessLayout',[{x:0,y:0,width:100,height:100,revision:revision-1}]);
  const after=await bounds();
  check('stale_layout_rejected','real IPC', {stale,before:before.rect,after:after.rect},stale.ok&&!stale.value.accepted&&JSON.stringify(before.rect)===JSON.stringify(after.rect));
  const invalid=await api('harnessLayout',[{x:-1,y:0,width:400,height:400,revision:revision+1}]);
  check('invalid_layout_rejected','real IPC',invalid,!invalid.ok);
  await layout({x:1100,y:650,width:800,height:800});
  const clipped=await bounds();
  check('out_of_window_bounds_clamped','real native rectangle',clipped,clipped.rect.x+clipped.rect.width<=clipped.content[0]&&clipped.rect.y+clipped.rect.height<=clipped.content[1]);
  await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(1));
  await layout({x:192,y:110,width:460,height:700});

  await native(id=>{
    const ctx=window.__qaContext,shell=ctx.conversation.input.shell(id);
    window.__qaSyntheticAdmissions=0;
    shell.deps.defaultSink=async()=>{window.__qaSyntheticAdmissions++;return {kind:'success'};};
    ctx.conversation.blocks.set(id,{reason:'QA_MODEL_NOT_CONFIGURED'});
  },sessionA);
  report.fixtures.push({name:'native_admission',scope:'browser-only native InputShell defaultSink',synthetic:'success outcome replaces provider admission; no session.prompt/send is invoked'});
  const action={sessionId:sessionA,draft:'QA：阻断后同一问题重试',submit:true,requestId:'qa-one-explicit-action'};
  const blocked=await native(request=>window.__foundryEmbedded.dispatch(request),action);
  check('first_question_blocked_without_submission','injected composer block; real bridge/input',blocked,!blocked.submitted&&blocked.blockedReason==='QA_MODEL_NOT_CONFIGURED');
  await native(id=>window.__qaContext.conversation.blocks.set(id,undefined),sessionA);
  const retries=await native(async request=>Promise.all([window.__foundryEmbedded.dispatch(request),window.__foundryEmbedded.dispatch(request)]),action);
  const admission=await native(()=>({syntheticAdmissions:window.__qaSyntheticAdmissions,wireSends:window.__qaWireSends,draft:document.querySelector('[data-composer-card] textarea').value}));
  check('blocked_retry_native_admission_once','real native machine with explicit synthetic success sink',{retries,...admission},retries.every(reply=>reply.submitted)&&admission.syntheticAdmissions===1&&admission.wireSends.length===0&&admission.draft==='');
  // Successful synthetic admission can reopen provider onboarding in a fresh
  // profile. Dismiss through its real control, then verify the intended target.
  await native(()=>Array.from(document.querySelectorAll('button')).find(b=>['Configure later','稍后配置','稍后设置'].includes(b.textContent.trim()))?.click());
  await until(()=>native(()=>!Array.from(document.querySelectorAll('button')).some(b=>['Configure later','稍后配置','稍后设置'].includes(b.textContent.trim()))),Boolean,'onboarding dismissed before composition');
  await app.evaluate(({webContents},id)=>webContents.fromId(id).focus(),nativeId);
  await native(id=>{window.__qaContext.conversation.input.shell(id).actions.setDraft('');document.querySelector('[data-composer-card] textarea').focus();},sessionA);
  const imeTarget=await native(()=>({composerFocused:document.activeElement===document.querySelector('[data-composer-card] textarea'),activeTag:document.activeElement?.tagName}));
  check('composition_targets_native_composer','real focus after provider onboarding dismissal',imeTarget,imeTarget.composerFocused);
  let compositionSupported=true;
  try {
    await app.evaluate(async ({webContents},id)=>{
      const w=webContents.fromId(id);
      await w.debugger.sendCommand('Input.imeSetComposition',{text:'利润',selectionStart:2,selectionEnd:2,replacementStart:0,replacementEnd:0});
      await w.debugger.sendCommand('Input.insertText',{text:'利润'});
    },nativeId);
  } catch(error) {
    if(!/method.*(?:not found|wasn't found)|not supported|unknown method/i.test(error.message))throw error;
    compositionSupported=false;
    report.checks.push({name:'chromium_composition_preserves_text',basis:'optional CDP input-method support',status:'not_tested',reason:error.message});
  }
  if(compositionSupported){
    const ime=await until(composer,state=>state.value?.includes('利润'),'CDP composition commit');
    const sends=await native(()=>window.__qaSyntheticAdmissions);
    check('chromium_composition_preserves_text','synthetic CDP IME; real textarea/input events',{...ime,syntheticAdmissions:sends},sends===1);
  }
  check('zero_real_prompt_requests','browser admission tripwire',await native(()=>window.__qaWireSends),await native(()=>window.__qaWireSends.length===0));
  report.status='passed';
})().catch(async error=>{
  report.status='failed';report.error=error.stack||String(error);
  if(app&&nativeId)try{report.nativeFailure=await native(()=>({body:document.body.innerText.slice(0,16000),url:location.href}));}catch{}
  process.exitCode=1;
}).finally(async()=>{
  if(app)try{await app.close();}catch(error){report.status='failed';report.closeError=String(error);process.exitCode=1;}
  const output=path.join(qa,'report.json');
  fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify({...report,reportPath:output}));
});
