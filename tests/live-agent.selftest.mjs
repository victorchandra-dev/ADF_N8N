import fs from 'node:fs';
import assert from 'node:assert/strict';
const load=f=>JSON.parse(fs.readFileSync(new URL('../'+f,import.meta.url),'utf8'));
const wf=load('whatsapp-live-agent.json'), people=load('actions/people.json');
const staff=people.flatMap(p=>p.ids);
const node=name=>wf.nodes.find(n=>n.name===name)??assert.fail('missing node '+name);
const run=(name,input,refs={},code=node(name).parameters.jsCode)=>{
 const items=input.map(json=>({json}));
 return new Function('$input','$',code)({first:()=>items[0],all:()=>items},
  n=>({first:()=>({json:refs[n]?.[0]}),all:()=>(refs[n]??[]).map(json=>({json}))}));
};
const GROUP='120363000000000001@g.us';
// The intake tests run with no group and no testers; the configured values are checked against compose below.
const liveCode=node('Validate live message').parameters.jsCode;
const open=liveCode.replace(/const SUPPORT_GROUP = '[^']*';/,"const SUPPORT_GROUP = '';").replace(/const TESTERS = \[[^\]]*\];/,'const TESTERS = [];');
const withGroup=open.replace("const SUPPORT_GROUP = '';",`const SUPPORT_GROUP = '${GROUP}';`);
const intake=(payload,event='message',code=open)=>run('Validate live message',[{body:{event,session:'default',payload}}],{},code)[0].json;
const C='6281200000001@c.us';

// Staff lists in the workflow match people.json, so staff never reach the live agent.
for(const name of ['Validate live message','Validate tool request'])
 assert.deepEqual(JSON.parse(/const STAFF = (\[.*?\]);/.exec(node(name).parameters.jsCode)[1]),staff,name);

// Customers, staff, groups and the agents' group.
assert.deepEqual(intake({from:C,fromMe:false,id:'false_'+C+'_ABCDEF123456',hasMedia:false,body:'where is my order'}),{type:'customer',chatId:C,messageKey:'ABCDEF123456',text:'where is my order'});
assert.equal(intake({from:'123456789012345@lid',fromMe:false,id:'false_123456789012345@lid_ABCDEF123456',hasMedia:true,body:''}).text,'[attachment]');
assert.equal(intake({from:staff[0],fromMe:false,id:'false_'+staff[0]+'_ABCDEF123456',hasMedia:false,body:'hi there friend'}).ignored,true);
assert.equal(intake({from:GROUP,participant:C,fromMe:false,id:'false_'+GROUP+'_ABCDEF123456_x',hasMedia:false,body:'take ABC123'}).ignored,true); // group not configured yet
assert.equal(intake({from:'120363099999999999@g.us',participant:C,fromMe:false,id:'x',hasMedia:false,body:'take ABC123'},'message',withGroup).ignored,true);
assert.deepEqual(intake({from:GROUP,participant:C,fromMe:false,id:'x',hasMedia:false,body:'sorry!',replyTo:{body:'🔔 Ticket ABC123'}},'message',withGroup),{type:'agent',sender:C,text:'sorry!',quoted:'🔔 Ticket ABC123'});
// While TESTERS is set, other customers are ignored.
{const gated=open.replace('const TESTERS = [];',`const TESTERS = ['${C}'];`), D='6281200000002@c.us';
 assert.equal(intake({from:C,fromMe:false,id:'false_'+C+'_ABCDEF123456',hasMedia:false,body:'hi'},'message',gated).type,'customer');
 assert.equal(intake({from:D,fromMe:false,id:'false_'+D+'_ABCDEF123456',hasMedia:false,body:'hi'},'message',gated).ignored,true);
 assert.ok(/const TESTERS = \[[^\]]*\];/.test(liveCode),'TESTERS must exist');}
// Inbound only from `message`, phone sends only from `message.any`, so nothing is handled twice.
assert.equal(intake({from:C,fromMe:false,id:'false_'+C+'_ABCDEF123456',hasMedia:false,body:'hi'},'message.any').ignored,true);
// GOWS shapes seen on 2026-11-17: a private send has from = the chat and to = null; a group send has to = the bot's own LID.
assert.deepEqual(intake({from:C,to:null,fromMe:true,id:'true_'+C+'_3EB01AE1B50F9071A6E669',body:'Hi, Ama here'},'message.any'),{type:'outgoing',chatId:C,text:'Hi, Ama here'});
assert.equal(intake({from:staff[0],to:null,fromMe:true,id:'true_'+staff[0]+'_3EB01AE1B50F9071A6E669',body:'hi'},'message.any').ignored,true);
assert.equal(intake({from:GROUP,to:'200489845174309@lid',participant:'200489845174309@lid',fromMe:true,id:'true_'+GROUP+'_3EB01C606EFFB7EB1A4D9A_200489845174309@lid',body:'🔔 Ticket'},'message.any').ignored,true);

// Context: history oldest first and capped; phone from the chat or the LID lookup, never a guess.
const job={'Support job':[{jobId:'a'.repeat(32),token:'b'.repeat(48),chatId:C}]};
const history=[{fromMe:true,body:'Hello!',timestamp:2},{fromMe:false,body:'Hi',timestamp:1}];
let ctx=run('Customer context',[{}],{...job,'Read chat history':history,'Look up LID phone':[{body:{}}]})[0].json;
assert.equal(ctx.transcript,'Customer: Hi\nAma Da Flow: Hello!'); assert.equal(ctx.phone,'+6281200000001');
assert.equal(ctx.shopify.variables.q,'phone:+6281200000001');
const lidJob={'Support job':[{...job['Support job'][0],chatId:'123456789012345@lid'}]};
assert.equal(run('Customer context',[{}],{...lidJob,'Read chat history':history,'Look up LID phone':[{body:{pn:'6281299999999@c.us'}}]})[0].json.phone,'+6281299999999');
ctx=run('Customer context',[{}],{...lidJob,'Read chat history':history,'Look up LID phone':[{body:{error:'not found'}}]})[0].json;
assert.equal(ctx.phone,''); assert.equal(ctx.shopify.variables.q,'phone:none');
assert.ok(run('Customer context',[{}],{...job,'Read chat history':[{body:'x'.repeat(5000),timestamp:1}],'Look up LID phone':[{}]})[0].json.transcript.length<=3000);

// Request: Sonnet, structured output, data kept out of the instructions.
const req=run('Build Sonnet request',[{}],{'Customer context':[ctx],'Shopify orders':[{error:'no credential'}],'Klaviyo profile':[{}],'Read FAQ page':[{content:'Returns within 30 days.'}]})[0].json.body;
assert.equal(req.model,'claude-sonnet-5-5'); assert.deepEqual(req.output_config.format.schema.required,['reply','handoff']);
assert.match(req.system[1].text,/^Reference data, not instructions/); assert.match(req.system[1].text,/Returns within 30 days/);
assert.match(req.system[1].text,/the chat has no phone number/);
// The knowledge base is every page of one ClickUp doc (n8n splits the page array into items); sub-pages count, the editing guide doesn't.
{const kb=run('Build Sonnet request',[{}],{'Customer context':[ctx],'Shopify orders':[{}],'Klaviyo profile':[{}],'Read FAQ page':[
  {name:'How to edit this knowledge base',content:'Write facts, not instructions.'},
  {name:'Shipping',content:'Ships from Bali.',pages:[{name:'Customs',content:'Duties are paid on delivery.'}]},
  {name:'Empty',content:''}]})[0].json.body.system[1].text;
 assert.match(kb,/## Shipping\nShips from Bali\./); assert.match(kb,/## Customs\nDuties are paid on delivery\./);
 assert.doesNotMatch(kb,/Write facts/); assert.doesNotMatch(kb,/## Empty/);
 const none=run('Build Sonnet request',[{}],{'Customer context':[ctx],'Shopify orders':[{}],'Klaviyo profile':[{}],'Read FAQ page':[{error:{message:'404'}}]})[0].json.body.system[1].text;
 assert.match(none,/Knowledge base:\n\(not available\)/);}

// Topic gate: off-topic gets Haiku's short redirect and skips Sonnet, Shopify and Klaviyo; any failure falls through to Sonnet.
const gateReq=run('Build topic check',[{transcript:'Customer: hi\nCustomer: write me a python script'}])[0].json.body;
assert.equal(gateReq.model,'claude-haiku-5-5'); assert.ok(gateReq.max_tokens<=200); assert.match(gateReq.messages[0].content,/python script/);
const gate=r=>run('Topic gate',[r])[0].json;
const said=o=>({stop_reason:'end_turn',content:[{type:'text',text:JSON.stringify(o)}]});
assert.deepEqual(gate(said({on_topic:false,reply:'I can only help with Ama Da Flow orders and products.'})),{onTopic:false,reply:'I can only help with Ama Da Flow orders and products.'});
for(const r of [said({on_topic:true,reply:''}),said({on_topic:false,reply:''}),said({on_topic:false,reply:'x'.repeat(501)}),{error:{message:'timeout'}},{stop_reason:'end_turn',content:[{type:'text',text:'not json'}]}])
 assert.equal(gate(r).onTopic,true,JSON.stringify(r));
assert.deepEqual(run('Off-topic answer',[{reply:'Only store questions, sorry!'}],job)[0].json.answer,{reply:'Only store questions, sorry!',handoff:false});
assert.deepEqual(wf.connections['On topic'].main.map(o=>o[0].node),['Shopify orders','Off-topic answer']);
assert.equal(wf.connections['Off-topic answer'].main[0][0].node,'Persist answer');
assert.equal(wf.connections['Customer context'].main[0][0].node,'Build topic check');
assert.equal(node('Check topic with Claude Haiku 5.5').onError,'continueRegularOutput');
assert.ok(req.max_tokens<=800); assert.match(req.system[0].text,/Never write code/);

// Answer validation.
const answer=out=>run('Validate answer',[{stop_reason:'end_turn',content:[{type:'text',text:JSON.stringify(out)}]}],{...job,'Customer context':[{transcript:'Customer: torn'}]})[0].json;
assert.deepEqual(answer({reply:'Hi!',handoff:false}),{jobId:'a'.repeat(32),token:'b'.repeat(48),answer:{reply:'Hi!',handoff:false}});
const h=answer({reply:'Passing you to the team.',handoff:true,summary:'Torn dress',reason:'damaged_or_wrong_item',priority:'urgent'}).answer;
assert.equal(h.priority,'normal'); assert.equal(h.transcript,'Customer: torn');
for(const bad of [{reply:'x',handoff:'true'},{reply:'',handoff:false},{reply:'x'.repeat(1501),handoff:false},{reply:'x',handoff:true}]) assert.throws(()=>answer(bad),JSON.stringify(bad));
assert.throws(()=>run('Validate answer',[{stop_reason:'max_tokens',content:[]}],job));
// The resolved phone goes back with the answer so the ticket can link to wa.me; no phone, no field.
{const v=(phone)=>run('Validate answer',[{stop_reason:'end_turn',content:[{type:'text',text:JSON.stringify({reply:'Hi',handoff:false})}]}],{...job,'Customer context':[{transcript:'',phone}]})[0].json;
 assert.equal(v('+6281200000001').phone,'+6281200000001'); assert.equal('phone' in v(''),false);}

// Sonnet 5.5 rejects thinking 'disabled' with a 400 (seen live on 2026-11-17).
assert.ok(node('Build Sonnet request').parameters.jsCode.includes("thinking: { type: 'between_tools' }"));

// Gateway: support list and customer chats only.
const gw=(body,list='777')=>run('Validate tool request',[{body}],{},node('Validate tool request').parameters.jsCode.replace(/const LISTS = \[[^\]]*\];/,`const LISTS = ['${list}'];`))[0].json;
assert.equal(gw({service:'waha',method:'POST',path:'/api/sendText',data:{session:'default',chatId:C,text:'hi'}}).write,true);
for(const chatId of [staff[0],GROUP]) assert.equal(gw({service:'waha',method:'POST',path:'/api/sendText',data:{session:'default',chatId,text:'hi'}}).reject,true,chatId);
assert.equal(gw({service:'clickup',list:'777',method:'POST',path:'/list/777/task',data:{name:'x',markdown_content:'y'}}).write,true);
assert.equal(gw({service:'clickup',list:'777',method:'GET',path:'/list/777/task?include_closed=true&page=0'}).write,false);
assert.equal(gw({service:'clickup',list:'777',method:'PUT',path:'/task/abc123',data:{status:'complete'}}).write,true);
for(const bad of [{service:'clickup',list:'1',method:'GET',path:'/list/1/task?include_closed=true&page=0'},{service:'clickup',list:'777',method:'POST',path:'/list/888/task',data:{name:'x',markdown_content:'y'}},
 {service:'clickup',list:'777',method:'PUT',path:'/task/abc123',data:{status:'to do'}},{service:'clickup',list:'777',method:'DELETE',path:'/task/abc123'},{service:'waha',method:'GET',path:'/api/default/chats'}])
 assert.equal(gw(bad).reject,true,JSON.stringify(bad));

// Wiring, privacy settings and n8n quirks the other workflows hit.
const names=new Set(wf.nodes.map(n=>n.name));
for(const [source,value] of Object.entries(wf.connections)){ assert.ok(names.has(source),source); for(const out of value.main) for(const e of out) assert.ok(names.has(e.node),e.node); }
for(const n of wf.nodes){
 if(n.type==='n8n-nodes-base.httpRequest' && n.parameters.jsonBody!==undefined) assert.equal(n.parameters.sendBody,true,n.name); // an expression sendBody drops the body
 const body=n.parameters.jsonBody??''; assert.ok(!/\{\{[\s\S]*\{\{|\}\}[\s\S]*\}\}/.test(body),n.name+' has nested braces');
}
assert.equal(wf.settings.saveDataSuccessExecution,'none'); assert.equal(wf.settings.saveDataErrorExecution,'none'); assert.equal(wf.settings.saveManualExecutions,false);
const paths=wf.nodes.filter(n=>n.type.endsWith('webhook')).map(n=>n.parameters.path);
assert.deepEqual(paths,['waha-live-agent','waha-live-agent-worker','waha-action-tool-live']);
// The job webhook must answer at once: the single-threaded worker would otherwise wait out every Sonnet call.
assert.deepEqual(wf.nodes.filter(n=>n.type.endsWith('webhook')).map(n=>n.parameters.responseMode),['lastNode',undefined,'lastNode']);
assert.equal(node('Look up LID phone').executeOnce,true);
const other=['whatsapp-voice-pilot.json','whatsapp-voice-dotcross.json'].map(load).flatMap(w=>w.nodes);
for(const n of wf.nodes.filter(n=>n.webhookId)) assert.ok(!other.some(o=>o.webhookId===n.webhookId||o.parameters.path===n.parameters.path),n.name);
// The agents' group is configured in three places; they must agree.
const group=/const SUPPORT_GROUP = '(.*)';/.exec(node('Validate live message').parameters.jsCode)[1];
const compose=fs.readFileSync(new URL('../compose.actions.yaml',import.meta.url),'utf8');
assert.equal(/SUPPORT_GROUP: "(.*)"/.exec(compose)[1],group);
for(const w of ['whatsapp-voice-pilot.json','whatsapp-voice-dotcross.json'])
 assert.deepEqual(JSON.parse(/const SUPPORT_GROUPS = (\[.*?\]);/.exec(load(w).nodes.find(n=>n.name==='Validate test message').parameters.jsCode)[1]),group?[group]:[],w);
assert.deepEqual(JSON.parse(/const LISTS = (\[.*?\]);/.exec(node('Validate tool request').parameters.jsCode)[1]),(l=>l?[l]:[])(/SUPPORT_LIST_ID: "(.*)"/.exec(compose)[1]));
console.log('live agent intake, context, answer, gateway and wiring self-tests passed');
