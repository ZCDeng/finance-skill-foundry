// Requires an existing Playwright installation; set PLAYWRIGHT_MODULE to its module path.
// Uses only synthetic data in an isolated temporary profile; no provider request is sent.
const {_electron}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs=require('fs'); const {execFileSync}=require('child_process');
(async()=>{
 const qa=fs.mkdtempSync('/tmp/finance-window-interactions-');fs.mkdirSync(qa,{recursive:true});
 const file=qa+'/actual.csv';fs.writeFileSync(file,'region,revenue,cost,expense\n华东,120,70,20\n');
 const root=require('node:path').resolve(__dirname, '..');const bin=root+'/app/release/mac-arm64/FA Foundry.app/Contents/Resources/foundry/foundry',varRoot=qa+'/var';
 const cli=(cmd,args=[],task)=>JSON.parse(execFileSync(bin,['--var',varRoot,...(task?['--task',task]:[]),cmd,...args],{encoding:'utf8'}));
 const app=await _electron.launch({executablePath:root+'/app/release/mac-arm64/FA Foundry.app/Contents/MacOS/FA Foundry',args:['--user-data-dir='+qa+'/profile'],env:{...process.env,FOUNDRY_VAR:varRoot,FOUNDRY_BIN:undefined,FOUNDRY_DSH_INSTALL:undefined,FOUNDRY_FORMULATOR_BIN:undefined},timeout:45000});
 try {
 const page=await app.firstWindow();await page.waitForLoadState('domcontentloaded');
 await page.getByLabel('你想分析什么？').fill('华东利润分析');
 await app.evaluate(({dialog},file)=>{dialog.showOpenDialog=async()=>({canceled:false,filePaths:[file]});},file);
 await page.getByRole('button',{name:'添加资料',exact:true}).click();
 await page.getByRole('button',{name:/actual.csv/}).waitFor({timeout:15000});
 const task=cli('task-list').at(-1).id;const dataset=cli('analysis-state',[],task).datasets[0];
 await page.getByRole('button',{name:/actual.csv/}).click();
 await page.getByRole('table',{name:'资料预览'}).waitFor();
 await page.screenshot({path:qa+'/02-data.png',fullPage:true});
 const analysis=cli('analysis-save',['--spec',JSON.stringify({question:'华东利润分析',bindings:{actual:dataset.id},sql:'SELECT revenue-cost-expense+CAST(? AS DECIMAL(38,2)) AS profit FROM actual',parameters:['0'],assumptions:[{name:'单列总部费用',value:'0'}],metrics:[{name:'经营利润',expression:'收入−成本−费用'}]})],task);
 await page.getByRole('button',{name:'刷新',exact:true}).click();
 await page.getByRole('tab',{name:/财务分析/}).click();
 await page.getByRole('button',{name:'重跑当前已保存版本'}).click();
 await page.getByRole('table',{name:'计算结果'}).waitFor({timeout:15000});
 await page.screenshot({path:qa+'/03-result.png',fullPage:true});
 await page.getByText('调整参数、假设与资料',{exact:true}).click();
 const parameter=page.getByLabel(/参数/).first();await parameter.fill('5');
 await page.getByRole('button',{name:'保存新版并重跑'}).click();
 await page.getByRole('cell',{name:'35.00',exact:true}).waitFor({timeout:15000});
 await page.getByRole('tab',{name:/汇报/}).click();
 await page.getByRole('tab',{name:/文稿/}).click();
 await page.getByLabel('文稿正文',{exact:true}).fill('华东利润30万元；单列总部费用后的测算为35万元。');
 await page.getByRole('button',{name:'保存文稿新版'}).click();
 await page.getByText('已保存为新的文稿版本。',{exact:true}).waitFor({timeout:15000}).catch(()=>{});
 await page.screenshot({path:qa+'/04-draft.png',fullPage:true});
 await app.evaluate(({shell})=>{globalThis.__qaOpened=[];shell.openPath=async file=>{globalThis.__qaOpened.push(file);return '';};});
 await page.getByRole('button',{name:'归档此版',exact:true}).click();
 await page.getByRole('button',{name:'导出工作簿',exact:true}).click();
 await page.waitForTimeout(1000);
 const opened=await app.evaluate(()=>globalThis.__qaOpened);
 if(opened.length!==1||!fs.readFileSync(opened[0]).subarray(0,2).equals(Buffer.from('PK')))throw Error('workbook export failed');
 const packed=await app.evaluate(({app})=>({packaged:app.isPackaged,path:app.getAppPath()}));if(!packed.packaged)throw Error('not packaged app');
 const state=cli('analysis-state',[],task);
 if(state.analyses.length!==2 || state.runs.length!==2 || state.drafts.length!==2)throw Error('unexpected state '+JSON.stringify(state));
 console.log(JSON.stringify({status:'passed',qa,task,packed,exported:opened[0],datasets:state.datasets.length,analyses:state.analyses.length,runs:state.runs.length,drafts:state.drafts.length,body:(await page.locator('body').innerText()).slice(0,2200)}));
 } finally {await app.close();}
})().catch(e=>{console.error(e);process.exit(1)});
