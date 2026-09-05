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
let page;try{
page=await app.firstWindow();await page.waitForLoadState('domcontentloaded');
await page.getByLabel('你想分析什么？').fill('冷启动：现金回款晚两周');
await page.getByRole('button',{name:'开始分析',exact:true}).click();
await page.getByRole('button',{name:'对话',exact:true}).waitFor();
await page.waitForFunction(()=>document.querySelector('[data-screen="workbench"]'),{},{timeout:45000});
const task=cli('task-list')[0].id;
const detail=cli('task-show',[],task);const first=detail.sessions.find(s=>s.role==='analysis').session_id;
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
    if(state.editable && state.composer.includes(expected))break;
    await new Promise(r=>setTimeout(r,100));
  }
  if(!state.editable || !state.composer.includes(expected))throw Error('visible composer lost: '+JSON.stringify(state));
  if(screenshot){
    const png=await app.evaluate(async({webContents})=>{const w=webContents.getAllWebContents().find(w=>w.getURL().startsWith('http://127.0.0.1:'));return (await w.capturePage()).toPNG().toString('base64');});
    fs.writeFileSync(qa+'/'+screenshot,Buffer.from(png,'base64'));
  }
  return state;
};
const one=await readPane();if(!one||!one.storage.includes(first)||!one.storage.includes('冷启动'))throw Error('cold start draft/session lost '+JSON.stringify(one));
const coldComposer=await visibleComposer('冷启动：现金回款晚两周','05-conversation.png');
if(!coldComposer.body.includes(detail.task.title))throw Error('task title missing in native workspace');
await page.getByRole('button',{name:'分析',exact:true}).click();
await page.getByRole('tab',{name:/文稿/}).click();
await page.locator('.analysis-draft textarea').first().fill('未保存的财务经理判断');
await page.getByRole('button',{name:'对话',exact:true}).click();
const file=qa+'/new.csv';fs.writeFileSync(file,'amount\n123\n');cli('dataset-add',['--path',file,'--name','助手补入资料'],task);
await page.getByRole('button',{name:'分析',exact:true}).click();
if(await page.locator('.analysis-draft textarea').first().inputValue()!=='未保存的财务经理判断')throw Error('draft lost');
await page.getByRole('tab',{name:/资料/}).click();await page.getByRole('button',{name:/助手补入资料/}).waitFor();
const other=cli('task-new',['--title','任务 B'],null,true);
// Reload task rows; source creates the second task as if another task had just been added.
await page.reload();await page.getByLabel('切换分析任务').selectOption(other);
await page.getByRole('button',{name:'对话',exact:true}).click();
const hidden=await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].contentView.children.map(v=>v.getBounds()));
if(hidden.some(b=>b.width>0&&b.height>0))throw Error('previous task pane visible '+JSON.stringify(hidden));
await page.getByRole('button',{name:'继续分析',exact:true}).click();
await page.waitForTimeout(1000);
const second=cli('task-show',[],other).sessions.find(s=>s.role==='analysis').session_id;
const two=await readPane();if(!two.storage.includes(second))throw Error('B did not open');
const bComposer=await visibleComposer('');if(bComposer.composer.includes('冷启动'))throw Error('A draft leaked into B');
if(!bComposer.body.includes('任务 B'))throw Error('second task title missing in native workspace');
await page.getByRole('button',{name:'分析',exact:true}).click();await page.getByLabel('切换分析任务').selectOption(task);
await page.getByRole('button',{name:'继续分析',exact:true}).click();
await page.waitForTimeout(1000);
const three=await readPane();const selected=JSON.parse(three.storage)['dsh.sessions.current'];if(JSON.parse(selected).sessionId!==first)throw Error('A not resumed');
await visibleComposer('冷启动：现金回款晚两周');
// Simulate a crash of this test app's own runtime, then resume the same task.
const row=execFileSync('/bin/ps',['-ax','-o','pid=,ppid=,command='],{encoding:'utf8'}).split('\n').map(r=>r.trim().split(/\s+/)).find(r=>Number(r[1])===app.process().pid && r.slice(2).join(' ').includes('@deepseek-ai/dsh/lib/bin.js'));if(!row)throw Error('test runtime PID not found');const runtimePid=Number(row[0]);
process.kill(runtimePid,'SIGTERM');
await page.getByRole('button',{name:'分析',exact:true}).click();
await page.getByLabel('接下来想了解什么？').fill('重启后保留的追问');
await page.getByRole('button',{name:'继续分析',exact:true}).click();
await page.waitForTimeout(1500);
const recovered=await readPane();if(recovered.url===three.url || !recovered.storage.includes('重启后保留的追问') || JSON.parse(JSON.parse(recovered.storage)['dsh.sessions.current']).sessionId!==first)throw Error('restart handoff failed '+JSON.stringify(recovered));
const native=await visibleComposer('重启后保留的追问','06-native-conversation.png');
console.log(JSON.stringify({status:'passed',qa,task,first,second,cases:['cold_start_seed','unsaved_draft_across_chat','refresh_after_chat','task_pane_isolation','resume_A_B_A','runtime_restart_seed','workspace_business_titles'],paneOrigin:three.url,recoveredOrigin:recovered.url,visibleComposer:native.composer,editable:native.editable,workspaceTitles:[detail.task.title,'任务 B']}));
}catch(e){console.error('QA failure',qa,await page.locator('body').innerText());await page.screenshot({path:qa+'/failure.png',fullPage:true});throw e;}finally{await app.close()}
})().catch(e=>{console.error(e);process.exit(1)});
