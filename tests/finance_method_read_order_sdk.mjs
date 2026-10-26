// Real native SDK tools and Foundry CLI, controlled locally without a provider.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {mkdirSync, readFileSync} from 'node:fs';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {apply as applyAnalysis} from '../dsh-plugin/analysis.js';

const config=JSON.parse(readFileSync(process.argv[3],'utf8'));
const mod=async name=>import(pathToFileURL(join(process.argv[2],'@deepseek-ai',name,'lib/index.js')));
const {Context}=await mod('cordis');
const hash=value=>createHash('sha256').update(value).digest('hex');
const ctx=new Context();
for(const name of ['dsh-agent','dsh-session','dsh-llm','dsh-tools','dsh-skill']){
  await ctx.plugin((await mod(name)).default,{});
}
await ctx.plugin((await mod('dsh-system-prompt')).default,
  {includeHarnessIdentity:false,includeRuntimeContext:false});
await ctx.plugin((await mod('dsh-agent-loop')).default,{agents:[],maxParallelToolCalls:1});
ctx.provide('subagents',{});
const fsModule=await mod('dsh-skill-filesystem');
const workspace=join(config.tmp,'sdk-workspace');mkdirSync(workspace,{recursive:true});
await ctx.plugin({name:'method-order-fs',inject:['skills'],apply:fsModule.apply},{
  dshHome:join(config.tmp,'isolated-dsh'),agentsHome:join(config.tmp,'isolated-agents'),
  bundledSkillDir:join(config.root,'method'),watch:false,
});
const skillPlugin=await mod('dsh-tool-skill');
const cases=[];
for(const [mode,session] of Object.entries(config.sessions)){
  const events=[];let counter=0,successful=0,failed=0,resourceBodies=true,held=false,release,notifyHeld;
  const gate=new Promise(resolve=>release=resolve),started=new Promise(resolve=>notifyHeld=resolve);
  const identity=exec=>({seq:events.length,session_id:exec.agent.id,call_id:exec.callId,
    name:exec.name,arguments:exec.arguments,arguments_sha256:hash(JSON.stringify(exec.arguments))});
  const handle=await ctx.agents.create({sessionId:session,meta:{cwd:workspace},
    agentOptions:{provider:'unused-local',model:'unused-local'},async setup(agentCtx){
      applyAnalysis(agentCtx);
      await agentCtx.plugin(skillPlugin,{});
      agentCtx.on('tools/execute',async(exec,next)=>{
        events.push({...identity(exec),phase:'start'});
        const result=await next();
        if(mode==='concurrent_read'&&!held&&exec.name==='method-resource'
          &&exec.arguments.resource==='model-checks.md'){
          held=true;notifyHeld();await gate;
        }
        return result;
      });
      agentCtx.on('tools/result',(exec,result)=>{
        let digest;
        if(exec.name==='skill'&&!result.isError){
          digest=hash(result.value.content);
          resourceBodies&&=result.content.some(block=>block.type==='text'&&block.text.includes(result.value.content));
        }
        if(exec.name==='method-resource'&&!result.isError){
          const value=JSON.parse(result.value.stdout);digest=value.sha256;
          assert.equal(hash(value.content),digest);
          // The actual SDK render contains the unchanged resource body and hash.
          const text=result.content.filter(block=>block.type==='text').map(block=>block.text).join('\n');
          resourceBodies&&=text.includes(digest)&&JSON.parse(text).content===value.content;
        }
        if(exec.name==='explain_variance')result.isError?failed++:successful++;
        events.push({...identity(exec),phase:'end',is_error:result.isError===true,content_sha256:digest});
      });
    }});
  const call=async(name,args,expectedError=false)=>{
    const result=await ctx.tools.execute({callId:`${session}-${++counter}`,name,arguments:args,
      agent:handle.agent,signal:new AbortController().signal});
    assert.equal(result.isError===true,expectedError,`${name}: ${JSON.stringify(result.error)}`);
    return result.value?.stdout?JSON.parse(result.value.stdout):result.value;
  };
  const resource=(name,skill='variance-analysis')=>call('method-resource',{skill,resource:name});
  const calculation=context=>call('explain_variance',{spec:{context_id:context.id,kind:'price_quantity',
    method:'volume_mix_price',actual_scenario:'actual',baseline_scenario:'budget'}});
  try{
    const skill=mode==='wrong_skill'?'close':'variance-analysis';
    await call('skill',{name:skill});
    await resource('FOUNDRY.md',skill);
    if(mode==='missing_checks')await resource('CONNECTORS.md');
    else if(!['early_diagnostic','concurrent_read'].includes(mode))await resource('model-checks.md',skill);
    const context=await call('finance_context_save',{spec:{bindings:config.bindings[mode],
      scopes:{sales:config.scope}}});
    if(mode==='early_diagnostic'){
      // A genuine rejected computation remains the first calculation start.
      await call('explain_variance',{spec:{context_id:'f'.repeat(32),kind:'price_quantity',
        method:'volume_mix_price',actual_scenario:'actual',baseline_scenario:'budget'}},true);
      await resource('model-checks.md');
    }
    await call('analysis_requirements_save',{spec:{context_id:context.id,
      question:'Explain the complete same-period revenue variance and its three contributions',
      items:[{id:'bridge',metric:'price_quantity',requires_drilldown:false,
        dimensions:{method:'volume_mix_price',actual_scenario:'actual',baseline_scenario:'budget'}}]}});
    if(mode==='concurrent_read'){
      const pending=resource('model-checks.md');await started;
      try{await calculation(context);}finally{release();await pending;}
    }else await calculation(context);
    cases.push({mode,session,events,successful_calculations:successful,failed_calculations:failed,
      resource_bodies_preserved:resourceBodies});
  }finally{release();await handle.dispose();}
}
console.log(JSON.stringify({provider_calls:0,cases}));
