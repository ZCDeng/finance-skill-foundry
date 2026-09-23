import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {describe, expect, it, vi} from 'vitest';
const STAGED_CLIENT = resolve('extra/dsh/node_modules/@deepseek-ai/dsh-client-ui-conversation/lib/client.js');
function nativeMachine() {
  const staged = readFileSync(STAGED_CLIENT,'utf8');
  const start = staged.indexOf('var InputMachine = class {');
  expect(start).toBeGreaterThan(-1);
  const end = staged.indexOf('\n\t\t//#endregion',start);
  const source = staged.slice(start,end);
  return new Function('EMPTY_QUEUE$1','const LOG_LIMIT = 100;\nconst referenceDraftText = reference => reference.label;\n' + source + '; return InputMachine;')([]);
}
function fixture(store = new Map<string,string>()) {
  const source = readFileSync(new URL('../harness-client/bridge.js', import.meta.url), 'utf8');
  const install = new Function(`${source}; return installFoundryEmbeddedBridge;`)();
  const NativeMachine = nativeMachine();
  const control = {blocked:undefined as undefined | {reason:string},fail:false};
  const machines = new Map<string, any>();
  const get = (id: string) => {
    if (!machines.has(id)) {
      const core = new NativeMachine();
      const machine: any = {core, get snapshot(){return core.state;}, actions:{} as any, mirrorFn:()=>{}};
      machine.actions.setDraft = vi.fn((draft:string)=>core.adopt(draft));
      machine.insertReference = vi.fn((reference:any, span:any) => {
        const before = core.state.draftRev;
        core.dispatch({type:'insert-ref',reference,span});
        return core.state.draftRev !== before;
      });
      machine.actions.submit = vi.fn(()=>{
        const [effect] = core.dispatch({type:'enter',mode:'queue'});
        queueMicrotask(()=>core.dispatch({type:'submit-settled',attempt:effect.attempt,ok:!control.fail,message:control.fail ? '模型拒绝' : undefined}));
      });
      machines.set(id,machine);
    }
    return machines.get(id);
  };
  const page = {localStorage:{get length(){return store.size;},key:(index:number)=>[...store.keys()][index],getItem:(key:string)=>store.get(key)??null,setItem:(key:string,value:string)=>store.set(key,value),removeItem:(key:string)=>store.delete(key)}} as any;
  let current = '';
  const sessions = {open:vi.fn((id:string)=>{current=id;}),list:{getSnapshot:()=>({current,byId:{a:{},b:{}}})},binding:()=>({session:{getSnapshot:()=>({openState:'open',removed:false,subagent:null})}})};
  const document = {querySelector:()=>({disabled:false,focus:vi.fn()})};
  install({effect:(run:()=>any)=>run()},sessions,{shell:get},{storeFor:()=>({getSnapshot:()=>control.blocked})},page,document);
  return {bridge:page.__foundryEmbedded,get,sessions,store,control};
}
const request = {sessionId:'a',draft:'利润\n为什么下降？',submit:true,requestId:'click-1'};
describe('resident native input handoff',()=>{
  it('waits for native admission and submits one concurrent/retried action once',async()=>{
    const {bridge,get}=fixture();
    const [first,second]=await Promise.all([bridge.dispatch(request),bridge.dispatch(request)]);
    expect(first).toEqual({sessionId:'a',submitted:true});
    expect(second).toEqual(first);
    expect(get('a').actions.submit).toHaveBeenCalledOnce();
    expect(get('a').snapshot.draft).toBe('');
  });
  it('preserves every task draft on passive selection',async()=>{
    const {bridge,get}=fixture();
    await bridge.dispatch({sessionId:'a',draft:'未发送 A'});
    await bridge.dispatch({sessionId:'b',draft:'未发送 B'});
    await bridge.dispatch({sessionId:'a'});
    expect(get('a').snapshot.draft).toBe('未发送 A');
    expect(get('b').snapshot.draft).toBe('未发送 B');
  });
  it('inserts a structured revision chip without placing the draft id in composer text',async()=>{
    const {bridge,get,store}=fixture();
    await bridge.dispatch({sessionId:'a',draft:'继续说明差异',draftReference:{draftId:'draft-123',revision:3}});
    expect(get('a').snapshot.draft).toBe('基于修订 3 继续说明差异');
    expect(get('a').snapshot.draft).not.toContain('draft-123');
    expect(get('a').snapshot.occurrences[0]).toMatchObject({
      source:'foundry-draft',
      label:'基于修订 3',
      clipboardText:'基于修订 3',
    });
    expect(JSON.parse(get('a').snapshot.occurrences[0].ref)).toEqual({draftId:'draft-123',revision:3});
    expect([...store.keys()]).toContain('fnd.references.a');
  });
  it('rejects draft reference ids that would leak through the protocol projection',async()=>{
    const {bridge}=fixture();
    await expect(bridge.dispatch({sessionId:'a',draft:'继续',draftReference:{draftId:'bad]id',revision:1}})).rejects.toThrow('invalid draft reference');
  });
  it('restores structured revision references from the sidecar when only plain draft text persisted',async()=>{
    const first=fixture();
    await first.bridge.dispatch({sessionId:'a',draft:'追问预算口径',draftReference:{draftId:'draft-456',revision:4}});
    const snapshot = first.bridge.snapshot();
    const next=fixture(first.store);
    next.get('a').actions.setDraft('基于修订 4 追问预算口径');
    expect(next.get('a').snapshot.occurrences).toHaveLength(0);
    expect(snapshot.references['fnd.references.a']).toContain('draft-456');
    await next.bridge.dispatch({sessionId:'a'});
    expect(next.get('a').snapshot.occurrences[0]).toMatchObject({source:'foundry-draft',label:'基于修订 4'});
  });
  it('removes and undoes only the edited revision chip occurrence',async()=>{
    const {bridge,get}=fixture();
    await bridge.dispatch({sessionId:'a',draft:'继续说明差异',draftReference:{draftId:'draft-123',revision:3}});
    const shell=get('a');
    const atEnd = shell.snapshot.draft.length;
    expect(shell.insertReference({source:'other-source',ref:'other-1',label:'其他引用',clipboardText:'其他引用'}, {start:atEnd,end:atEnd,draftRev:shell.snapshot.draftRev})).toBe(true);
    expect(shell.snapshot.occurrences.map((o:any)=>o.source)).toEqual(['foundry-draft','other-source']);
    shell.core.dispatch({type:'draft-changed',draft:'继续说明差异其他引用 ',editRange:{start:0,end:'基于修订 3 '.length,insertedLength:0}});
    expect(shell.snapshot.occurrences).toHaveLength(1);
    expect(shell.snapshot.occurrences[0].source).toBe('other-source');
    shell.core.dispatch({type:'undo'});
    expect(shell.snapshot.occurrences.map((o:any)=>o.source)).toEqual(['foundry-draft','other-source']);
  });
  it('does not resurrect a deleted revision reference across A-B-A selection or client restart',async()=>{
    const first=fixture();
    await first.bridge.dispatch({sessionId:'a',draft:'继续说明差异',draftReference:{draftId:'draft-789',revision:5}});
    const shell=first.get('a');
    shell.core.dispatch({type:'draft-changed',draft:'继续说明差异',editRange:{start:0,end:'基于修订 5 '.length,insertedLength:0}});
    expect(shell.snapshot.occurrences).toHaveLength(0);
    await first.bridge.dispatch({sessionId:'b',draft:'B 的问题'});
    await first.bridge.dispatch({sessionId:'a'});
    expect(first.get('a').snapshot.occurrences).toHaveLength(0);
    expect(first.store.has('fnd.references.a')).toBe(false);
    const restarted=fixture(first.store);
    restarted.get('a').actions.setDraft('继续说明差异');
    await restarted.bridge.dispatch({sessionId:'a'});
    expect(restarted.get('a').snapshot.occurrences).toHaveLength(0);
    expect(restarted.store.has('fnd.references.a')).toBe(false);
  });
  it('snapshot flushes current native draft and references before host persistence reads localStorage',async()=>{
    const {bridge,get,store}=fixture();
    await bridge.dispatch({sessionId:'a',draft:'继续说明差异',draftReference:{draftId:'draft-live',revision:9}});
    const shell=get('a');
    shell.core.dispatch({type:'draft-changed',draft:'基于修订 9 用户手动改字',editRange:{start:'基于修订 9 '.length,end:shell.snapshot.draft.length,insertedLength:'用户手动改字'.length}});
    const snapshot=bridge.snapshot();
    expect(snapshot.drafts.a.draft).toBe('基于修订 9 用户手动改字');
    expect(store.get('dsh.conversation.chat.a')).toContain('用户手动改字');
    expect(snapshot.references['fnd.references.a']).toContain('draft-live');
  });
  it('snapshot writes cleared native state so durable host storage cannot resurrect deleted references',async()=>{
    const {bridge,get,store}=fixture();
    await bridge.dispatch({sessionId:'a',draft:'继续说明差异',draftReference:{draftId:'draft-clear',revision:10}});
    const shell=get('a');
    shell.core.dispatch({type:'draft-changed',draft:'',editRange:{start:0,end:shell.snapshot.draft.length,insertedLength:0}});
    const snapshot=bridge.snapshot();
    expect(snapshot.drafts.a.draft).toBe('');
    expect(snapshot.references['fnd.references.a']).toBeUndefined();
    expect(store.has('fnd.references.a')).toBe(false);
  });
  it('clears revision sidecar after successful autosubmit and preserves it after failed submit',async()=>{
    const ok=fixture();
    await ok.bridge.dispatch({sessionId:'a',draft:'继续说明差异',draftReference:{draftId:'draft-ok',revision:6}});
    expect(ok.store.has('fnd.references.a')).toBe(true);
    const okDraft=ok.get('a').snapshot.draft;
    expect(await ok.bridge.dispatch({sessionId:'a',draft:okDraft,submit:true,requestId:'send-ok'})).toEqual({sessionId:'a',submitted:true});
    expect(ok.get('a').snapshot.draft).toBe('');
    expect(ok.get('a').snapshot.occurrences).toHaveLength(0);
    expect(ok.store.has('fnd.references.a')).toBe(false);

    const fail=fixture();
    fail.control.fail=true;
    await fail.bridge.dispatch({sessionId:'a',draft:'继续说明差异',draftReference:{draftId:'draft-fail',revision:7}});
    const failDraft=fail.get('a').snapshot.draft;
    expect(await fail.bridge.dispatch({sessionId:'a',draft:failDraft,submit:true,requestId:'send-fail'})).toEqual({sessionId:'a',submitted:false,blockedReason:'模型拒绝'});
    expect(fail.get('a').snapshot.draft).toBe(failDraft);
    expect(fail.get('a').snapshot.occurrences[0]).toMatchObject({source:'foundry-draft',label:'基于修订 7'});
    expect(fail.store.get('fnd.references.a')).toContain('draft-fail');
  });
  it('preserves the busy native input guard instead of steering over an in-flight submit',async()=>{
    const {bridge,get,store}=fixture();
    await bridge.dispatch({sessionId:'a',draft:'继续说明差异',draftReference:{draftId:'draft-busy',revision:8}});
    const shell=get('a');
    const [effect]=shell.core.dispatch({type:'enter',mode:'queue'});
    expect(effect.type).toBe('default-sink');
    expect(shell.snapshot.phase).toBe('submitting');
    await expect(bridge.dispatch({sessionId:'a',draft:'忙碌时的新问题'})).rejects.toThrow('输入正在提交');
    expect(shell.snapshot.draft).toBe('基于修订 8 继续说明差异');
    expect(shell.snapshot.occurrences[0]).toMatchObject({source:'foundry-draft'});
    expect(store.get('fnd.references.a')).toContain('draft-busy');
  });
  it('refuses an action id reused for changed content',async()=>{
    const {bridge,get}=fixture();
    await bridge.dispatch(request);
    await expect(bridge.dispatch({...request,draft:'新问题'})).rejects.toThrow();
    expect(get('a').actions.submit).toHaveBeenCalledOnce();
  });
  it('allows the same action after a model block is resolved',async()=>{
    const {bridge,get,control}=fixture();
    control.blocked={reason:'Model not configured'};
    expect((await bridge.dispatch(request)).submitted).toBe(false);
    control.blocked=undefined;
    expect((await bridge.dispatch(request)).submitted).toBe(true);
    expect(get('a').actions.submit).toHaveBeenCalledOnce();
  });
  it('allows an explicitly failed native admission to retry and keeps its draft',async()=>{
    const {bridge,get,control}=fixture();
    control.fail=true;
    expect(await bridge.dispatch(request)).toEqual({sessionId:'a',submitted:false,blockedReason:'模型拒绝'});
    expect(get('a').snapshot.draft).toBe(request.draft);
    control.fail=false;
    expect((await bridge.dispatch(request)).submitted).toBe(true);
    expect(get('a').actions.submit).toHaveBeenCalledTimes(2);
  });
  it('a succeeded receipt survives a client restart without restoring sent text',async()=>{
    const first=fixture();
    await first.bridge.dispatch(request);
    const next=fixture(first.store);
    expect((await next.bridge.dispatch(request)).submitted).toBe(true);
    expect(next.get('a').actions.setDraft).not.toHaveBeenCalled();
    expect(next.get('a').actions.submit).not.toHaveBeenCalled();
  });
  it('does not resend an unresolved admission from another runtime instance',async()=>{
    const first=fixture();
    first.store.set('fnd.submitted.a.click-1',JSON.stringify({fingerprint:JSON.stringify([request.sessionId,request.draft,null,true]),status:'pending',machineId:'old-runtime',seq:1}));
    expect((await first.bridge.dispatch(request)).blockedReason).toContain('没有自动重发');
    expect(first.get('a').actions.submit).not.toHaveBeenCalled();
  });
  it('records admission only for the native current attempt',()=>{
    const Machine=nativeMachine();
    const machine=new Machine();
    machine.adopt('问题');
    const [effect]=machine.dispatch({type:'enter',mode:'queue'});
    machine.dispatch({type:'submit-settled',attempt:{...effect.attempt,seq:999},ok:true});
    expect(machine.foundryAdmission).toBeUndefined();
    expect(machine.phase).toBe('submitting');
    machine.dispatch({type:'submit-settled',attempt:effect.attempt,ok:false,message:'拒绝'});
    expect(machine.foundryAdmission).toEqual({seq:effect.attempt.seq,ok:false,message:'拒绝'});
    expect(machine.draft).toBe('问题');
  });
  it('keeps manual Enter native and autosubmit exactly-once while locked',()=>{
    const Machine=nativeMachine();
    const machine=new Machine();
    machine.adopt('手动发送的问题');
    const [effect]=machine.dispatch({type:'enter',mode:'manual'});
    expect(effect).toMatchObject({type:'default-sink',draft:'手动发送的问题',mode:'manual'});
    expect(machine.dispatch({type:'enter',mode:'manual'})).toEqual([]);
    machine.dispatch({type:'submit-settled',attempt:effect.attempt,ok:true});
    expect(machine.draft).toBe('');
    expect(machine.occurrences).toHaveLength(0);
  });
});
