import type {BrowserWindow} from 'electron';
import {beforeEach, describe, expect, it, vi} from 'vitest';
const native = vi.hoisted(()=>({construct:vi.fn(),bounds:vi.fn(),visible:vi.fn(),focus:vi.fn(),mainFocus:vi.fn(),isFocused:vi.fn(()=>false),load:vi.fn(),add:vi.fn(),remove:vi.fn()}));
vi.mock('electron',()=>({WebContentsView:class {
  constructor(){native.construct();}
  setBounds = native.bounds;
  setVisible = native.visible;
  webContents = {isFocused:native.isFocused,focus:native.focus,loadURL:native.load,setWindowOpenHandler:vi.fn(),on:vi.fn()};
}}));
import {Pane} from '../electron/harness/pane.js';
const window = {contentView:{addChildView:native.add,removeChildView:native.remove},webContents:{focus:native.mainFocus},getContentSize:()=>[1000,800]} as unknown as BrowserWindow;
beforeEach(()=>{vi.clearAllMocks();native.isFocused.mockReturnValue(false);});
describe('resident pane lifecycle',()=>{
  it('starts hidden before mounting and actually hides the native surface on overlays',async()=>{
    const pane = new Pane();
    await pane.attach(window,'http://127.0.0.1:41000');
    expect(native.visible).toHaveBeenLastCalledWith(false);
    expect(native.visible.mock.invocationCallOrder[0]).toBeLessThan(native.add.mock.invocationCallOrder[0]);
    pane.layout(window,{x:192,y:100,width:420,height:650,revision:1},1);
    pane.place(window,true);
    expect(native.visible).toHaveBeenLastCalledWith(true);
    native.isFocused.mockReturnValue(true);
    pane.place(window,false);
    expect(native.visible).toHaveBeenLastCalledWith(false);
    expect(native.mainFocus).toHaveBeenCalledOnce();
    expect(native.visible.mock.invocationCallOrder.at(-1)).toBeLessThan(native.bounds.mock.invocationCallOrder.at(-1)!);
    pane.place(window,true);
    expect(native.visible).toHaveBeenLastCalledWith(true);
    expect(native.bounds).toHaveBeenLastCalledWith({x:192,y:100,width:420,height:650});
    expect(native.load).toHaveBeenCalledOnce();
  });
  it('does not draw or focus an empty clipped rectangle and defers focus until space returns',async()=>{
    const pane = new Pane();
    await pane.attach(window,'http://127.0.0.1:41000');
    pane.layout(window,{x:1000,y:100,width:420,height:650,revision:1},1);
    pane.place(window,true);
    expect(native.visible).toHaveBeenLastCalledWith(false);
    pane.focus();
    expect(native.focus).not.toHaveBeenCalled();
    pane.layout(window,{x:192,y:100,width:420,height:650,revision:2},1);
    expect(native.visible).toHaveBeenLastCalledWith(true);
    expect(native.focus).toHaveBeenCalledOnce();
  });
  it('keeps one native view and defers explicit input focus until shown',async()=>{
    const pane = new Pane();
    await pane.attach(window,'http://127.0.0.1:41000');
    await pane.attach(window,'http://127.0.0.1:41000');
    pane.layout(window,{x:192,y:100,width:420,height:650,revision:1},1);
    pane.focus();
    expect(native.focus).not.toHaveBeenCalled();
    pane.place(window,true);
    expect(native.focus).toHaveBeenCalledOnce();
    pane.layout(window,{x:192,y:100,width:460,height:650,revision:2},1);
    pane.place(window,false);
    pane.place(window,true);
    expect(native.focus).toHaveBeenCalledOnce();
    expect(native.construct).toHaveBeenCalledOnce();
    expect(native.load).toHaveBeenCalledOnce();
    expect(native.remove).not.toHaveBeenCalled();
  });
});
