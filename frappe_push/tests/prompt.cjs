const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync(__dirname + '/../public/js/push_prompt.js', 'utf8');
function environment({storage=new Map(),permission='default',path='/',blocked=false,locks=false}={}) {
 const timers=[], nodes=new Map(), events={}; let requests=0;
 const document={hidden:false,activeElement:null,getElementById:id=>nodes.get(id),querySelector:()=>host,querySelectorAll:()=>[],createElement:()=>new Element()};
 class Element {
  constructor(){this.dataset={};this.children=new Map();this.isConnected=true;this.hidden=false;}
  setAttribute(){} matches(){return false;} getClientRects(){return [1];}
  querySelector(selector){if(!this.children.has(selector))this.children.set(selector,new Element());return this.children.get(selector);}
  append(e){nodes.set(e.id,e);} addEventListener(){} focus(){document.activeElement=this;}
  contains(e){return [...this.children.values()].includes(e);}
  remove(){nodes.delete(this.id);this.isConnected=false;}
 }
 const host=new Element();document.body=new Element();document.activeElement=new Element();
 const context={console,document,location:{pathname:path},Notification:{permission}, navigator:locks?{locks:{request:async(_,f)=>f()}}:{},Date,
 localStorage:{getItem:k=>{if(blocked)throw Error();return storage.get(k)},setItem:(k,v)=>{if(blocked)throw Error();storage.set(k,v)}},
 setTimeout:(f,ms)=>{timers.push({f,ms});return timers.length},clearTimeout:()=>{},window:{addEventListener:(n,f)=>events[n]=f},
 frappe:{provide:()=>{},ui:{}},frappe_push:{},__:(s)=>s,MutationObserver:class {observe(){}disconnect(){}}};
 vm.createContext(context);vm.runInContext(source,context);
 const prompt=context.frappe_push.prompt;
 const enable=async()=>{requests++; return context.Notification.permission='granted';};
 return {context,prompt,storage,timers,nodes,events,setup:(config={})=>prompt.setup({prompt:config},enable),requests:()=>requests};
}
test('automatic invitation is once across page loads and does not request permission',()=>{
 const a=environment();a.setup();assert.equal(a.timers[0].ms<=10000,true);a.prompt.try_auto();assert(a.nodes.has('frappe-push-banner'));assert.equal(a.requests(),0);a.prompt.close();
 const b=environment({storage:a.storage});b.setup();b.prompt.try_auto();assert(!b.nodes.has('frappe-push-banner'));b.prompt.show(true);assert(b.nodes.has('frappe-push-banner'));
});
test('already granted, blocked, or unavailable storage never automatically prompts',()=>{
 for(const options of [{permission:'granted'},{permission:'denied'},{blocked:true}]) {const e=environment(options);e.setup();e.prompt.try_auto();assert(!e.nodes.has('frappe-push-banner'));}
});
test('settings separately disable website, Desk, and automatic prompting',()=>{
 for(const [path,settings] of [['/',{enabled:false}],['/',{website:false}],['/desk/home',{desk:false}]]) {const e=environment({path});e.setup(settings);assert.equal(e.timers.length,0);assert(e.nodes.has('frappe-push-settings'));}
});
test('typing, checkout, and visible dialogs defer without consuming the first display',()=>{
 for(const kind of ['typing','checkout','modal','hidden']) {
  const e=environment({path:kind==='checkout'?'/checkout':'/'});e.setup();
  if(kind==='typing')e.context.document.activeElement.matches=()=>true;
  if(kind==='modal')e.context.document.querySelectorAll=()=>[{getClientRects:()=>[1]}];
  if(kind==='hidden')e.context.document.hidden=true;
  e.prompt.try_auto();assert(!e.prompt.seen());assert(!e.nodes.has('frappe-push-banner'));assert.equal(e.timers.at(-1).ms,2000);
 }
});
test('a cross-tab display closes only automatic prompts',()=>{
 const e=environment();e.setup();e.prompt.try_auto();e.events.storage({key:e.prompt.storage_key,newValue:'1'});assert(!e.nodes.has('frappe-push-banner'));
 e.prompt.show(true);e.events.storage({key:e.prompt.storage_key,newValue:'2'});assert(e.nodes.has('frappe-push-banner'));
});
test('only Enable requests permission; success is displayed inline',async()=>{
 const e=environment();e.setup();e.prompt.try_auto();const card=e.nodes.get('frappe-push-banner');await card.querySelector('.frappe-push-enable').onclick();assert.equal(e.requests(),1);assert.equal(card.querySelector('.frappe-push-feedback').textContent,'Notifications enabled on this device.');
});
test('failed subscriptions stay retryable with an inline error',async()=>{
 const e=environment();e.setup();e.prompt.enable=async()=>{throw Error('network')};e.prompt.show(true);const card=e.nodes.get('frappe-push-banner');await card.querySelector('.frappe-push-enable').onclick();assert.equal(card.querySelector('.frappe-push-enable').disabled,false);assert.match(card.querySelector('.frappe-push-feedback').textContent,/couldn’t connect/);
});
test('Web Locks rechecks storage before displaying',async()=>{
 const e=environment({locks:true});e.setup();e.prompt.try_auto();await Promise.resolve();assert(e.prompt.seen());assert(e.nodes.has('frappe-push-banner'));
});
test('v16 adds a single manual item only to user menus',()=>{
 const e=environment({path:'/desk/home'});class Dropdown {open(){return 'opened'} set_options(o){this.options=o}}
 e.context.frappe.ui.Dropdown=Dropdown;e.setup();const menu=new Dropdown();menu.options=[{group:'',options:[{name:'settings'},{name:'logout'}]}];menu.open();menu.open();assert.equal(menu.options.length,2);assert.equal(menu.options[0].options[0].name,'frappe-push-settings');
 const other=new Dropdown();other.options=[{name:'edit'}];other.open();assert.equal(other.options.length,1);
});
test('settings initialize before Firebase, including when permission is blocked',()=>{
 const bundle=fs.readFileSync(__dirname+'/../public/js/frappe_push.bundle.js','utf8').replace(/^import .*;\n/gm,'');
 for(const permission of ['default','denied']) {
  let setups=0, firebaseLoads=0;
  const Notification={permission};
  const context={console:{log(){},warn(){},error(){}},Notification,window:{Notification,PushManager:{}},navigator:{serviceWorker:{}},
   frappe:{provide(){},session:{user:'Guest'},call({callback}){callback({message:{prompt:{enabled:true}}})},require(){firebaseLoads++}},
   frappe_push:{prompt:{setup(){setups++}}},$(){},setTimeout(){},clearTimeout(){}};
  vm.createContext(context);vm.runInContext(bundle,context);context.frappe_push.init();
  assert.equal(setups,1);assert.equal(firebaseLoads,permission==='denied'?0:1);
 }
});

test('disconnect removes the connected state and offers reconnection', async () => {
 const e = environment({permission:'granted'});
 let disconnected = false;
 e.prompt.setup({connected:true}, async () => 'granted', async () => {disconnected = true;});
 e.prompt.show(true);
 const card = e.nodes.get('frappe-push-banner');
 const button = card.querySelector('.frappe-push-disconnect');
 assert.equal(button.hidden, false);
 await button.onclick();
 assert.equal(disconnected, true);
 assert.equal(e.prompt.connected, false);
 assert.equal(button.hidden, true);
 assert.equal(card.querySelector('.frappe-push-enable').hidden, false);
});
