import {readFileSync, existsSync} from 'node:fs';
import {resolve} from 'node:path';
import {describe, expect, it, vi} from 'vitest';
// @ts-expect-error Dependency-free build adapter.
import {adaptSource} from '../scripts/adapt-harness-client.mjs';
function nativeMachine() {
  const saved = resolve('extra/dsh/.foundry-client-stock/conversation.js');
  const original = readFileSync(existsSync(saved) ? saved : resolve('extra/dsh/node_modules/@deepseek-ai/dsh-client-ui-conversation/lib/client.js'),'utf8');
  const adapted = adaptSource('conversation', original);
  const start = adapted.indexOf('var InputMachine = class {');
  const source = adapted.slice(start,adapted.indexOf('\n\t\t//#endregion',start));
  return new Function('EMPTY_QUEUE$1',source + '; return InputMachine;')([]);
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
      const machine = {core, get snapshot(){return core.state;}, actions:{} as any, mirrorFn:()=>{}};
      machine.actions.setDraft = vi.fn((draft:string)=>core.adopt(draft));
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
    first.store.set('fnd.submitted.a.click-1',JSON.stringify({fingerprint:JSON.stringify([request.sessionId,request.draft,true]),status:'pending',machineId:'old-runtime',seq:1}));
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
});
