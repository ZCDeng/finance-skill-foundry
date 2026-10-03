// Requires an existing Playwright installation; set PLAYWRIGHT_MODULE to its module path.
// Uses only synthetic data in an isolated temporary profile; no provider request is sent.
const {_electron}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs=require('fs');const {execFileSync}=require('child_process');
(async()=>{
const qa=fs.mkdtempSync('/tmp/finance-session-qa-'),root=require('node:path').resolve(__dirname, '..');
const bin=process.env.QA_FOUNDRY||root+'/app/extra/foundry/foundry';
const executablePath=process.env.QA_APP||root+'/app/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron';
const env={...process.env,FOUNDRY_VAR:qa+'/var'};delete env.FOUNDRY_DSH_INSTALL;delete env.FOUNDRY_FORMULATOR_BIN;if(!process.env.QA_APP)env.FOUNDRY_BIN=bin;else delete env.FOUNDRY_BIN;
const cli=(cmd,args=[],task,raw=false)=>{const x=execFileSync(bin,['--var',qa+'/var',...(task?['--task',task]:[]),cmd,...args],{encoding:'utf8'});return raw?x.trim():JSON.parse(x)};
const app=await _electron.launch({executablePath,args:[...(process.env.QA_APP?[]:[root+'/app']),'--user-data-dir='+qa+'/profile'],env,timeout:45000});
let page,stage='launch';
// Layout buttons live in the 工作区布局 group; locate them there so a rename shows up as a named stage, not a bare timeout.
const focus=(name)=>page.getByRole('group',{name:'工作区布局'}).getByRole('button',{name,exact:true});
const step=(name)=>{stage=name;};
// Tasks are switched from the workspace task list, as in verify_ui_workspace.cjs.
const openTask=async(title)=>{const expand=page.getByRole('button',{name:'展开任务列表'});if(await expand.isVisible())await expand.click();await page.locator('.workspace-task').filter({hasText:title}).first().click();};
try{
page=await app.firstWindow();await page.waitForLoadState('domcontentloaded');
step('cold_start_seed');await page.getByLabel('你想分析什么？').fill('冷启动：现金回款晚两周');
await page.getByRole('button',{name:'开始分析',exact:true}).click();
await focus('对话专注').waitFor();
const task=cli('task-list')[0].id;
// The analysis session is filed once the runtime opens it; poll instead of assuming it is already there.
let detail;for(let attempt=0;attempt<450;attempt++){detail=cli('task-show',[],task);if(detail.sessions.some(s=>s.role==='analysis'))break;await new Promise(r=>setTimeout(r,100));}
const firstSession=detail.sessions.find(s=>s.role==='analysis');if(!firstSession)throw Error('analysis session never opened '+JSON.stringify(detail.sessions));const first=firstSession.session_id;
const readPane=()=>app.evaluate(async({webContents})=>{const w=webContents.getAllWebContents().find(w=>w.getURL().startsWith('http://127.0.0.1:'));if(!w)return null;return {url:w.getURL(),storage:await w.executeJavaScript('JSON.stringify(Object.fromEntries(Object.entries(localStorage).filter(([k])=>k.startsWith("dsh.sessions.current")||k.startsWith("dsh.conversation.chat"))))')};});
const visibleComposer=async(expected,screenshot)=>{
  let state;
  for(let attempt=0;attempt<60;attempt++){
    state=await app.evaluate(async({webContents})=>{
      const w=webContents.getAllWebContents().find(w=>w.getURL().startsWith('http://127.0.0.1:'));
      return w.executeJavaScript(`(()=>{
        Array.from(document.querySelectorAll('button')).find(b=>b.textContent.trim()==='Configure later')?.click();
        const inputs=Array.from(document.querySelectorAll('textarea,[contenteditable=true]'));
        return {body:document.body.innerText,composer:inputs.map(e=>e.value??e.textContent).join('\\n'),editable:inputs.some(e=>!e.disabled && !e.readOnly)};
      })()`);
    });
    // 开始分析/继续分析 without files submit the question (Analysis.tsx submit: !withFiles), so it may sit in the transcript instead of the composer.
    if(state.editable && (state.composer.includes(expected)||state.body.includes(expected)))break;
    await new Promise(r=>setTimeout(r,100));
  }
  if(!state.editable || !(state.composer.includes(expected)||state.body.includes(expected)))throw Error('visible conversation lost: '+JSON.stringify(state));
  if(screenshot){
    const png=await app.evaluate(async({webContents})=>{const w=webContents.getAllWebContents().find(w=>w.getURL().startsWith('http://127.0.0.1:'));return (await w.capturePage()).toPNG().toString('base64');});
    fs.writeFileSync(qa+'/'+screenshot,Buffer.from(png,'base64'));
  }
  return state;
};
// Picking a task connects its conversation on its own (App.tsx effect); 继续分析 in the conversation
// slot only shows when that did not happen. Either way the native pane must end up on screen:
// a filed session behind a zero-size pane is the blank workspace this check exists to catch.
const openConversation=async(taskId)=>{
  const resume=page.getByRole('region',{name:'持续对话'}).getByRole('button',{name:'继续分析',exact:true});
  let session,pane,views;
  for(let attempt=0;attempt<450;attempt++){
    if(await resume.isVisible().catch(()=>false))await resume.click();
    session=cli('task-show',[],taskId).sessions.find(s=>s.role==='analysis')?.session_id;
    pane=await readPane();
    views=await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].contentView.children.map(v=>({...v.getBounds(),visible:v.getVisible?.()})));
    const current=pane&&JSON.parse(JSON.parse(pane.storage)['dsh.sessions.current']||'{}').sessionId;
    if(session&&current===session&&views.some(b=>b.width>0&&b.height>0&&b.visible!==false))return session;
    await new Promise(r=>setTimeout(r,100));
  }
  throw Error('conversation not shown for '+taskId+' '+JSON.stringify({session,pane,views}));
};
// The conversation pane is a separate webContents; wait until it has stored the seeded session.
let one;for(let attempt=0;attempt<450;attempt++){one=await readPane();if(one&&one.storage.includes(first))break;await new Promise(r=>setTimeout(r,100));}
if(!one||!one.storage.includes(first))throw Error('cold start session lost '+JSON.stringify(one));
const coldComposer=await visibleComposer('冷启动：现金回款晚两周','05-conversation.png');
// The business title is drawn in the workspace header (Workspace.tsx), not inside the native pane.
const headerTitle=()=>page.locator('.workspace-header h1').innerText();
if((await headerTitle()).trim()!==detail.task.title)throw Error('task title missing in workspace header');
step('unsaved_draft_across_chat');await focus('成果专注').click();
await page.getByRole('tab',{name:/文稿/}).click();
await page.locator('.analysis-draft textarea').first().fill('未保存的财务经理判断');
await focus('对话专注').click();
const file=qa+'/new.csv';fs.writeFileSync(file,'amount\n123\n');cli('dataset-add',['--path',file,'--name','助手补入资料'],task);
await focus('成果专注').click();
if(await page.locator('.analysis-draft textarea').first().inputValue()!=='未保存的财务经理判断')throw Error('draft lost');
await page.getByRole('tab',{name:/资料/}).click();await page.getByRole('button',{name:/助手补入资料/}).waitFor();
step('task_pane_isolation');const other=cli('task-new',['--title','任务 B'],null,true);
// Reload task rows; source creates the second task as if another task had just been added.
await page.reload();await openTask('任务 B');
await focus('对话专注').click();
const second=await openConversation(other);
const bComposer=await visibleComposer('');if(bComposer.composer.includes('冷启动')||bComposer.body.includes('冷启动'))throw Error('A conversation leaked into B');
if((await headerTitle()).trim()!=='任务 B')throw Error('second task title missing in workspace header');
step('resume_A_B_A');await openTask(detail.task.title);await focus('对话专注').click();
if(await openConversation(task)!==first)throw Error('A not resumed');
const three=await readPane();
await visibleComposer('冷启动：现金回款晚两周');
step('runtime_restart_seed');
// Simulate a crash of this test app's own runtime, then resume the same task.
const row=execFileSync('/bin/ps',['-ax','-o','pid=,ppid=,command='],{encoding:'utf8'}).split('\n').map(r=>r.trim().split(/\s+/)).find(r=>Number(r[1])===app.process().pid && r.slice(2).join(' ').includes('@deepseek-ai/dsh/lib/bin.js'));if(!row)throw Error('test runtime PID not found');const runtimePid=Number(row[0]);
process.kill(runtimePid,'SIGTERM');
// Follow-ups go through the native composer once a task is open (Analysis.tsx hides its own box), so the
// recovered runtime must serve the same session from a new origin and accept typing again.
let recovered;
for(let attempt=0;attempt<450;attempt++){
  const reconnect=page.getByRole('button',{name:/重新连接|继续分析/}).first();
  if(await reconnect.isVisible().catch(()=>false))await reconnect.click().catch(()=>undefined);
  recovered=await readPane();
  if(recovered&&recovered.url!==three.url&&JSON.parse(JSON.parse(recovered.storage)['dsh.sessions.current']||'{}').sessionId===first)break;
  await new Promise(r=>setTimeout(r,100));
}
if(!recovered||recovered.url===three.url||JSON.parse(JSON.parse(recovered.storage)['dsh.sessions.current']||'{}').sessionId!==first)throw Error('restart handoff failed '+JSON.stringify(recovered));
await openConversation(task);
await app.evaluate(async({webContents},text)=>{
  const w=webContents.getAllWebContents().find(w=>w.getURL().startsWith('http://127.0.0.1:'));
  w.focus();
  await w.executeJavaScript(`(()=>{const e=Array.from(document.querySelectorAll('textarea,[contenteditable=true]')).find(e=>!e.disabled&&!e.readOnly);e?.focus();return Boolean(e)})()`);
  w.insertText(text);
},'重启后保留的追问');
const native=await visibleComposer('重启后保留的追问','06-native-conversation.png');
console.log(JSON.stringify({status:'passed',qa,task,first,second,cases:['cold_start_seed','unsaved_draft_across_chat','refresh_after_chat','task_pane_isolation','resume_A_B_A','runtime_restart_seed','workspace_business_titles'],paneOrigin:three.url,recoveredOrigin:recovered.url,visibleComposer:native.composer,editable:native.editable,workspaceTitles:[detail.task.title,'任务 B']}));
}catch(e){console.error('QA failure at stage',stage,qa,await page.locator('body').innerText());await page.screenshot({path:qa+'/failure.png',fullPage:true});throw e;}finally{await app.close()}
})().catch(e=>{console.error(e);process.exit(1)});
