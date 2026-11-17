import fs from 'node:fs';
import assert from 'node:assert/strict';
const load=f=>JSON.parse(fs.readFileSync(new URL('../'+f,import.meta.url),'utf8'));
let wf=load('whatsapp-voice-dotcross.json');
const dot=wf, adfWf=load('whatsapp-voice-pilot.json');
const people=JSON.parse(fs.readFileSync(new URL('../actions/people.json',import.meta.url),'utf8'));
const node=name=>wf.nodes.find(n=>n.name===name);
const run=(name,input,refs={})=>{
 const items=input.map(json=>({json}));
 return new Function('$input','$',node(name).parameters.jsCode)(
  {first:()=>items[0],all:()=>items},
  name=>({first:()=>({json:refs[name][0]}),all:()=>refs[name].map(json=>({json}))}));
};
const S=()=>wf===adfWf?'default':'personal';
const ev=(body,from=people[0].ids[0],extra={})=>[{body:{event:'message',session:S(),payload:{from,fromMe:false,id:'false_'+from+'_ABCDEF123456',hasMedia:false,body,...extra}}}];
for(const person of people) for(const alias of person.ids){
 const r=run('Validate test message',ev('task: Review copy @victor',alias))[0].json;
 assert.equal(r.title,'Review copy'); assert.deepEqual(r.assignees,['victor']); assert.deepEqual(r.allowedActions,person.actions);
}
assert.equal(run('Validate test message',ev('task: x','unknown@c.us'))[0].json.ignored,true);
assert.equal(run('Validate test message',ev('task: x',undefined,{fromMe:true}))[0].json.ignored,true);
assert.equal(run('Validate test message',ev('hello'))[0].json.ignored,true);
assert.equal(run('Validate test message',ev('idea: Save the bundle suggestion'))[0].json.action,'save_idea');
assert.equal(run('Validate test message',ev('idea:'))[0].json.action,'clarify');
assert.equal(run('Validate test message',ev('yes abcdef1234'))[0].json.code,'abcdef1234');
assert.equal(run('Validate test message',ev('retry abcdef1234'))[0].json.action,'retry');
assert.equal(run('Validate test message',ev('No'))[0].json.answer,'no');
assert.equal(run('Validate test message',ev('Yes!'))[0].json.answer,'yes');
assert.equal(run('Validate test message',ev('yes please do it'))[0].json.freeText,true);
// Plain text becomes an AI text job carrying only the message ID; short chat and bare links skip the AI.
{const r=run('Validate test message',ev('please remind Victor to send the samples'))[0].json; assert.equal(r.freeText,true); assert.ok(r.messageId); assert.equal(r.title,undefined);}
for(const t of ['thanks','ok noted','https://x.com/some/post',' '.repeat(3),'word '.repeat(450)]) assert.equal(run('Validate test message',ev(t))[0].json.ignored,true,t);
assert.equal(run('Validate test message',ev('progress: https://app.clickup.com/t/1100310000034143/z8q7hbtnpp now is on progress'))[0].json.update,'now is on progress');
assert.equal(run('Validate test message',ev('progress: Launch is completed'))[0].json.task,'Launch is completed');
assert.ok(run('Validate test message',ev('',undefined,{hasMedia:true,media:{mimetype:'audio/ogg'}}))[0].json.messageId);
const voice={'Voice job':[{chatId:'c',reference:'ref',allowedActions:['create_task','save_idea','post_progress']}]};
const model=out=>[{choices:[{message:{content:JSON.stringify(out)}}]}];
assert.equal(run('Validate voice action',model({action:'save_idea',title:'Bundle',summary:'A seasonal bundle'}),voice)[0].json.description,'A seasonal bundle');
assert.equal(run('Validate voice action',model({action:'post_progress',task:'Launch',update:'Underway',inProgress:true}),voice)[0].json.inProgress,true);
assert.equal(run('Validate voice action',model({action:'post_progress',task:'Launch',update:'Underway',inProgress:'true'}),voice)[0].json.inProgress,false);
assert.throws(()=>run('Validate voice action',model({action:'delete_everything'}),voice));
assert.throws(()=>run('Validate voice action',model({action:'create_task',title:''}),voice));
assert.equal(run('Validate voice action',model({action:'save_idea',title:'x',summary:'y'}),{'Voice job':[{allowedActions:[]} ]})[0].json.action,'clarify');
assert.equal(run('Validate WAHA media URL',[{media:{mimetype:'audio/ogg',url:'http://waha:3000/api/files/default/audio.ogg'}}])[0].json.audioUrl,'http://waha:3000/api/files/default/audio.ogg');
for(const url of ['https://attacker.example/audio.ogg','http://waha:3000/api/files/../secret','http://waha:3000/api/files/%2e%2e/secret'])
 assert.throws(()=>run('Validate WAHA media URL',[{media:{mimetype:'audio/ogg',url}}]));
assert.equal(node('Receive WAHA message').parameters.responseMode,'lastNode');
assert.equal(node('Persist incoming action').parameters.url,'http://actions:8000/submit');
assert.equal(node('Persist extracted action').parameters.url,'http://actions:8000/plan');
assert.equal(node('Record voice failure').parameters.url,'http://actions:8000/failure');
assert.equal(wf.settings.saveDataSuccessExecution,'none');
assert.equal(wf.settings.saveDataErrorExecution,'none');
assert.equal(wf.settings.saveManualExecutions,false);
const names=new Set(wf.nodes.map(n=>n.name));
for(const [source,value] of Object.entries(wf.connections)){
 assert.ok(names.has(source));
 for(const output of value.main) for(const edge of output) assert.ok(names.has(edge.node));
}
assert.equal(wf.connections['Message accepted'].main[0][0].node,'Persist incoming action');
assert.equal(wf.connections['Validate voice action'].main[0][0].node,'Persist extracted action');
console.log('n8n intake, voice validation, privacy and routing self-tests passed');
const tool=body=>run('Validate tool request',[{body}])[0].json;
assert.equal(tool({service:'clickup',list:'1100310000198006',method:'GET',path:'/list/1100310000198006/task?include_closed=true&page=0'}).reject,undefined);
assert.equal(tool({service:'clickup',list:'1100310000198006',method:'PUT',path:'/task/86abc123',data:{status:'in progress'}}).preflight,true);
// Every ClickUp call must name an allowed list, and list paths must match it.
assert.equal(tool({service:'clickup',method:'GET',path:'/task/86abc123'}).reject,true);
assert.equal(tool({service:'clickup',list:'1',method:'GET',path:'/task/86abc123'}).reject,true);
assert.equal(tool({service:'clickup',list:'1100310000198006',method:'GET',path:'/list/1100380000200435/member'}).reject,true);
assert.equal(tool({service:'clickup',list:'1100310000198006',method:'DELETE',path:'/task/86abc123'}).reject,true);
assert.equal(tool({service:'clickup',list:'1100310000198006',method:'GET',path:'https://attacker.example'}).reject,true);
assert.equal(tool({service:'clickup',list:'1100310000198006',method:'POST',path:'/list/other/task',data:{name:'test'}}).reject,true);
assert.equal(tool({service:'waha',method:'POST',path:'/api/sendText',data:{session:S(),chatId:'unknown@c.us',text:'test'}}).reject,true);
assert.equal(run('Verify tool task scope',[{statusCode:200,body:{list:{id:'other'}}}],{'Validate tool request':[{list:'1100310000198006'}]})[0].json.response.statusCode,403);
// Both gateway nodes allow exactly the default list plus every list in groups.json.
{const groups=JSON.parse(fs.readFileSync(new URL('../actions/groups.json',import.meta.url),'utf8'));
 const def=/CLICKUP_LIST_ID: "(\d+)"/.exec(fs.readFileSync(new URL('../compose.actions.yaml',import.meta.url),'utf8'))[1];
 const compose=fs.readFileSync(new URL('../compose.actions.yaml',import.meta.url),'utf8');
 const adfList=/CLICKUP_ADF_LIST_ID: "(\d+)"/.exec(compose)[1];
 const want=[...new Set([def,...Object.values(groups).map(String)])].filter(id=>id!==adfList).sort();
 for(const name of ['Validate tool request']) assert.deepEqual(JSON.parse(/const LISTS = (\[[^\]]*\])/.exec(node(name).parameters.jsCode)[1]).sort(),want,name+' LISTS must match groups.json');
 assert.deepEqual(JSON.parse(/const ADF_LISTS = (\[[^\]]*\])/.exec(node('Validate tool request').parameters.jsCode)[1]),[],'Dotcross never uses the ADF credential');
 for(const id of want){
  const created=tool({service:'clickup',list:id,method:'POST',path:`/list/${id}/task`,data:{name:'t',markdown_content:''}});
  assert.equal(created.reject,undefined); assert.equal(created.adf,false,'credential for '+id);
  assert.equal(tool({service:'clickup',list:id,method:'GET',path:`/list/${id}/member`}).reject,undefined);
  assert.equal(run('Verify tool task scope',[{statusCode:200,body:{list:{id}}}],{'Validate tool request':[{ok:1,list:id}]})[0].json.ok,1);
  // A task from another allowed list is still out of scope for this call.
  assert.equal(run('Verify tool task scope',[{statusCode:200,body:{list:{id}}}],{'Validate tool request':[{list:want.find(x=>x!==id)}]})[0].json.reject,true);}
 assert.equal(tool({service:'clickup',list:'1',method:'GET',path:'/list/1/task'}).reject,true);
 assert.equal(tool({service:'clickup',list:adfList,method:'GET',path:`/list/${adfList}/member`}).reject,true,'Dotcross rejects the ADF list');
 // Each workflow holds one ClickUp workspace's credential.
 for(const n of wf.nodes.filter(n=>n.credentials?.clickUpApi)) assert.equal(n.credentials.clickUpApi.name,'ClickUp account',n.name);}
console.log('Authenticated tool gateway scope self-tests passed');
for(const n of wf.nodes.filter(n=>n.type==='n8n-nodes-base.webhook')) assert.ok(n.webhookId,'Explicit webhook identity required for '+n.name);
// n8n hides and drops body settings when sendBody is an expression; writes must use a literal true.
// n8n ends an expression at the first }}, so a body expression may contain {{ and }} only at its ends.
for(const w of [dot,adfWf]) for(const n of w.nodes){const b=n.parameters.jsonBody; if(typeof b==='string'&&b.startsWith('={{')) assert.ok(!b.slice(3,-2).includes('}}')&&!b.slice(3,-2).includes('{{'),n.name+' body has a nested }} or {{');}
for(const n of wf.nodes.filter(n=>n.type==='n8n-nodes-base.httpRequest')) assert.notEqual(typeof n.parameters.sendBody,'string',n.name);
for(const svc of ['ClickUp','WAHA']){
 assert.equal(node(`Execute ${svc} write`).parameters.jsonBody,'={{ $json.data ?? {} }}');
 assert.deepEqual(wf.connections[`${svc} write request`].main.map(b=>b[0].node),[`Execute ${svc} write`,`Execute ${svc} tool`]);
}
console.log('Gateway write nodes send bodies');
// Ignored messages must still answer 200, or WAHA retries them; the {ignored:true} item ends at a NoOp.
assert.equal(run('Validate test message',[{body:{event:'message.ack'}}])[0].json.ignored,true);
assert.deepEqual(wf.connections['Message accepted'].main.map(b=>b[0].node),['Persist incoming action','Ignore message']);
assert.equal(wf.connections['Validate test message'].main[0][0].node,'Message accepted');
console.log('Ignored messages answer 200');
// Text jobs skip audio and Whisper; the AI may ignore casual chat.
assert.deepEqual(wf.connections['Text job'].main.map(b=>b[0].node),['Request message text','Request authorized audio']);
assert.deepEqual(wf.connections['Use message text'].main.map(b=>b[0].node),['Check for Ama Da Flow','Record voice failure']);
assert.ok(node('Extract action with Orvix GPT-6 Sol').parameters.jsonBody.includes("$('Use message text')"));
assert.throws(()=>run('Use message text',[{fromMe:true,body:'task text here'}]));
assert.equal(run('Use message text',[{fromMe:false,body:'call the vendor today'}])[0].json.text,'call the vendor today');
{const job={chatId:'c',reference:'r',allowedActions:['create_task']};
 const v=content=>run('Validate voice action',[{choices:[{message:{content}}]}],{'Voice job':[job]})[0].json;
 assert.equal(v('{"action":"ignore"}').action,'ignore');
 assert.equal(v('{"action":"save_idea","title":"x","summary":""}').action,'clarify');}
console.log('Plain-text AI route self-tests passed');
// The three sender lists (people.json, intake, gateway sendText) must hold the same IDs.
{const ids=people.flatMap(p=>p.ids);
 const intake=node('Validate test message').parameters.jsCode, gateway=node('Validate tool request').parameters.jsCode;
 for(const id of ids){ assert.ok(intake.includes(`'${id}'`),id); assert.ok(gateway.includes(`"${id}"`),id); }
 assert.equal((intake.match(/@(c\.us|lid)'/g)||[]).length,ids.length);
 const g=gateway.match(/\[("[^\]]*@[^\]]*)\]\.includes\(data\.chatId\)/); assert.deepEqual(JSON.parse('['+g[1]+']').sort(),[...ids].sort());}
console.log('Sender lists match people.json');
// Groups: prefix commands from a pilot member are accepted and answered privately; everything else is ignored.
{const G='120363012345678901@g.us', lid=people[0].ids[1], key='3EB0ABCDEF123456';
 const gev=(body,participant=lid,extra={})=>[{body:{event:'message',session:S(),payload:{from:G,participant,fromMe:false,id:`false_${G}_${key}_${participant}`,hasMedia:false,body,...extra}}}];
 const r=run('Validate test message',gev('task: Review copy @victor'))[0].json;
 assert.equal(r.chatId,lid); assert.equal(r.replyTo,G); assert.equal(r.title,'Review copy'); assert.equal(r.reference,'WAHA pilot message '+key);
 assert.equal(run('Validate test message',[{body:{...gev('idea: x')[0].body,payload:{...gev('idea: x')[0].body.payload,id:`false_${G}_${key}`}}}])[0].json.action,'save_idea');
 assert.equal(run('Validate test message',gev('progress: Launch waiting for samples'))[0].json.action,'post_progress');
 assert.equal(run('Validate test message',gev('yes'))[0].json.answer,'yes'); assert.equal(run('Validate test message',gev('no abcdef1234'))[0].json.code,'abcdef1234');
 assert.equal(run('Validate test message',ev('task: DM'))[0].json.replyTo,undefined);
 for(const t of ['yes please','please create a task to review the budget','hello team']) assert.equal(run('Validate test message',gev(t))[0].json.ignored,true,t);
 assert.equal(run('Validate test message',gev('task: x','stranger@lid'))[0].json.ignored,true);
 assert.equal(run('Validate test message',gev('task: x',lid,{fromMe:true}))[0].json.ignored,true);
 assert.equal(run('Validate test message',gev('',lid,{hasMedia:true,media:{mimetype:'audio/ogg'}}))[0].json.ignored,true);
 assert.equal(run('Validate test message',gev('task: x',null))[0].json.ignored,true);
 assert.equal(run('Validate test message',ev(' task: Leading space'))[0].json.title,'Leading space');}
{const send=chatId=>tool({service:'waha',method:'POST',path:'/api/sendText',data:{session:S(),chatId,text:'hi'}}).reject;
 assert.equal(send('120363012345678901@g.us'),undefined); assert.equal(send('120363012345678901@c.us'),true); assert.equal(send('x@g.us'),true); assert.equal(send(people[0].ids[0]),undefined);}
console.log('Group prefix commands self-tests passed');
// Mentioning the bot in a group sends a normal message to the AI; the mention is removed.
{const G='120363012345678901@g.us', lid=people[0].ids[1];
 const gev=(body,extra={})=>[{body:{event:'message',session:S(),payload:{from:G,participant:lid,fromMe:false,id:`false_${G}_3EB0ABCDEF333333_${lid}`,hasMedia:false,body,...extra}}}];
 for(const at of ['@73710631411953','@6281119903888']){
  const r=run('Validate test message',gev(at+' please remind Victor to send the samples tomorrow'))[0].json;
  assert.equal(r.freeText,true,at); assert.equal(r.replyTo,G); assert.ok(r.messageId.startsWith('false_'+G+'_'));}
 assert.equal(run('Validate test message',gev('@73710631411953 task: Deck @victor'))[0].json.title,'Deck');
 assert.equal(run('Validate test message',gev('@737106314119539 please remind Victor tomorrow'))[0].json.ignored,true,'another number is not the bot');
 assert.equal(run('Validate test message',gev('@73710631411953 thanks'))[0].json.ignored,true,'too short for the AI');
 assert.equal(run('Validate test message',gev('@73710631411953',{hasMedia:true,media:{mimetype:'audio/ogg'}}))[0].json.ignored,true);
 assert.equal(run('Use message text',[{fromMe:false,body:'@73710631411953 please remind Victor'}])[0].json.text,'please remind Victor');}
console.log('Group bot-mention self-tests passed');
// WhatsApp formatting around a prefix, and multi-line tasks (title, then notes or links).
{const t=b=>run('Validate test message',ev(b))[0].json;
 const fig='https://www.figma.com/proto/xpJYeRKJ5TSkUjr2SXfKls/AMA-DA-FLOW?node-id=10-41&t=MThELgQ4RH8C6O7z-0&scaling=scale-down&content-scaling=fixed&page-id=5%3A36';
 for(const b of ['*task: Test bold*','*task:* Test bold','_task: Test bold_','task: *Test bold*','*task: Test bold']) assert.equal(t(b).title,'Test bold',b);
 const r=t('*task: Test from group two*\n'+fig); assert.equal(r.title,'Test from group two'); assert.equal(r.description,fig);
 assert.equal(t('task: Plain').description,undefined);
 assert.equal(t('task: Deck @victor\nnotes for @victor').assignees.length,2);
 assert.equal(t('*idea: Bundle*').action,'save_idea');
 assert.equal(t('*progress:* https://app.clickup.com/t/86abc123 waiting').task,'https://app.clickup.com/t/86abc123');
 const G='120363012345678901@g.us', lid=people[0].ids[1];
 const g=run('Validate test message',[{body:{event:'message',session:S(),payload:{from:G,participant:lid,fromMe:false,id:`false_${G}_3EB0ABCDEF999999_${lid}`,hasMedia:false,body:'*task: Test from group two*\n'+fig}}}])[0].json;
 assert.equal(g.title,'Test from group two'); assert.equal(g.replyTo,G);}
console.log('Formatted and multi-line command self-tests passed');
// Dotcross keeps #adf messages on its own number (tag dropped, no workspace); its model no longer picks a workspace.
{const t=b=>run('Validate test message',ev(b))[0].json;
 assert.equal(t('task: Prepare the deck #adf').title,'Prepare the deck'); assert.equal(t('task: Prepare the deck #adf').workspace,undefined);
 assert.equal(t('#ADF idea: Bundle').action,'save_idea');
 assert.equal(t('task: Fix #adfoo tag').title,'Fix #adfoo tag');
 const job={chatId:'c',reference:'r',allowedActions:['create_task']};
 assert.equal(run('Validate voice action',model({action:'create_task',title:'Deck',workspace:'adf'}),{'Voice job':[job]})[0].json.workspace,undefined);
 assert.ok(!node('Extract action with Orvix GPT-6 Sol').parameters.jsonBody.includes('workspace'));}
console.log('Dotcross #adf hand-off self-tests passed');

// Ama Da Flow: the same intake and gateway code, the other half of the traffic, its own lists, Claude Haiku 5.5.
{const groups=JSON.parse(fs.readFileSync(new URL('../actions/groups.json',import.meta.url),'utf8'));
 const adfList=/CLICKUP_ADF_LIST_ID: "(\d+)"/.exec(fs.readFileSync(new URL('../compose.actions.yaml',import.meta.url),'utf8'))[1];
 const adfGroups=Object.keys(groups).filter(g=>String(groups[g])===adfList).sort();
 const pick=(w,name)=>w.nodes.find(n=>n.name===name).parameters.jsCode;
 const strip=js=>js.replace(/const (ROUTE|LISTS|ADF_LISTS|SPACE|BOT) = [^\n]*/g,'').replace(/'(personal|default)'|\/api\/(personal|default)\/|\\\/api\\\/(personal|default)\\\//g,'SESSION');
 for(const name of ['Validate test message','Validate tool request','Use message text','Validate WAHA media URL','Voice job','Verify tool task scope'])
  assert.equal(strip(pick(adfWf,name)),strip(pick(dot,name)),name+' must match between workflows');
 {const v=(task,scope)=>new Function('$input','$',pick(adfWf,'Verify tool task scope'))({first:()=>({json:{statusCode:200,body:{list:{id:task}}}})},()=>({first:()=>({json:{ok:1,list:scope}})}))[0].json;
  assert.equal(v('1100380000175792','1100380000200435').ok,1,'ADF may update a Website task');
  assert.equal(v('1100380000210276','1100380000200435').reject,true,'ADF may not touch Support Tickets');}
 assert.deepEqual(JSON.parse(/const SPACE = (\[[^\]]*\])/.exec(pick(adfWf,'Verify tool task scope'))[1]).sort(),/CLICKUP_ADF_TASK_LISTS: "([\d,]+)"/.exec(fs.readFileSync(new URL('../compose.actions.yaml',import.meta.url),'utf8'))[1].split(',').sort(),'SPACE must match CLICKUP_ADF_TASK_LISTS');
 assert.deepEqual(JSON.parse(/const ADF_GROUPS = (\[[^\]]*\])/.exec(pick(dot,'Validate test message'))[1]),adfGroups,'ADF_GROUPS must match groups.json');
 const lid=people[0].ids[1];
 const gev=(G,body,session)=>[{body:{event:'message',session,payload:{from:G,participant:lid,fromMe:false,id:`false_${G}_3EB0ABCDEF555555_${lid}`,hasMedia:false,body}}}];
 const other='120363012345678901@g.us'; // an unmapped group such as DotCross (IJV is in CLICKUP_NO_ADF_GROUPS)
 const take=(w,input)=>new Function('$input','$',pick(w,'Validate test message'))({first:()=>({json:input[0]})},()=>null)[0].json.ignored!==true;
 const pev=(body,session)=>[{body:{event:'message',session,payload:{from:people[0].ids[0],fromMe:false,id:'false_'+people[0].ids[0]+'_ABCDEF123456',hasMedia:false,body}}}];
 // Ama Da Flow takes everything on its number; Dotcross takes everything on its number except the Ama Da Flow groups.
 for(const session of ['default','personal']){
  const own=w=>(w===adfWf)===(session==='default');
  for(const c of [pev('task: Private',session),pev('task: Private #adf',session),pev('yes abcdef1234',session),gev(other,'task: Group',session)])
   for(const w of [adfWf,dot]) assert.equal(take(w,c),own(w),session+' '+JSON.stringify(c[0].body.payload.body));
  assert.equal(take(adfWf,gev(adfGroups[0],'task: Group',session)),session==='default');
  assert.equal(take(dot,gev(adfGroups[0],'task: Group',session)),false);}
 assert.equal(take(dot,pev('task: x','other')),false); assert.equal(take(adfWf,pev('task: x','other')),false);
 wf=adfWf;
 // The ADF intake tags #adf work with workspace adf; that tag is what sends a private #adf message to the ADF list.
 {const t=b=>run('Validate test message',ev(b))[0].json;
  assert.equal(t('task: Prepare the deck #adf').workspace,'adf'); assert.equal(t('task: Prepare the deck #adf').title,'Prepare the deck');
  assert.equal(t('#ADF idea: Bundle').action,'save_idea'); assert.equal(t('#ADF idea: Bundle').workspace,'adf');
  assert.equal(t('progress: 86abc123 done #adf').update,'done');
  assert.equal(t('please remind Victor to send samples #adf').workspace,'adf');
  assert.equal(run('Validate test message',gev(other,'task: Deck #adf','default'))[0].json.workspace,'adf'); assert.equal(t('task: Deck').session,'default');
  assert.equal(run('Validate test message',gev(adfGroups[0],'task: Deck','default'))[0].json.replyTo,adfGroups[0]);}
 assert.equal(tool({service:'clickup',list:adfList,method:'GET',path:`/list/${adfList}/member`}).adf,true);
 for(const id of Object.values(groups).map(String).filter(id=>id!==adfList)) assert.equal(tool({service:'clickup',list:id,method:'GET',path:`/list/${id}/member`}).reject,true,id);
 for(const n of wf.nodes.filter(n=>n.credentials?.clickUpApi&&n.name!=='Read knowledge page')) assert.equal(n.credentials.clickUpApi.name,'ClickUp ADF',n.name);
 assert.deepEqual(wf.connections['Task needs scope check'].main[0].map(e=>e.node),['Read tool task scope (ADF)']);
 assert.deepEqual(wf.connections['ClickUp write request'].main.map(b=>b[0].node),['Execute ClickUp write (ADF)','Execute ClickUp tool (ADF)']);
 assert.equal(node('Execute ClickUp write (ADF)').parameters.jsonBody,'={{ $json.data ?? {} }}');
 for(const [w,paths] of [[adfWf,['waha-voice-inbox-pilot','waha-voice-action-worker','waha-action-tool']],[dot,['waha-voice-inbox-dotcross','waha-voice-action-worker-dotcross','waha-action-tool-dotcross']]])
  assert.deepEqual(w.nodes.filter(n=>n.type==='n8n-nodes-base.webhook').map(n=>n.parameters.path),paths);
 const hooks=[adfWf,dot].flatMap(w=>w.nodes.filter(n=>n.webhookId).map(n=>n.webhookId)); assert.equal(new Set(hooks).size,hooks.length,'webhook IDs must be unique');
 assert.notEqual(adfWf.id,dot.id);
 // Claude Haiku 5.5 with a JSON schema; refusals and cut-off answers go to the error branch.
 const h=node('Extract action with Claude Haiku 5.5');
 assert.equal(h.parameters.url,'https://api.anthropic.com/v1/messages'); assert.equal(h.parameters.sendBody,true);
 assert.ok(h.parameters.jsonBody.includes("model: 'claude-haiku-5-5'")); assert.ok(h.parameters.jsonBody.includes("output_config"));
 assert.ok(!h.parameters.jsonBody.includes('workspace')); assert.ok(!JSON.stringify(wf).includes('Orvix'));
 assert.deepEqual(wf.connections['Extract action with Claude Haiku 5.5'].main.map(b=>b[0].node),['Validate voice action','Record voice failure']);
 assert.deepEqual(wf.connections['Read knowledge page'].main[0].map(e=>e.node),['Extract action with Claude Haiku 5.5']);
 const job={chatId:'c',reference:'r',allowedActions:['create_task','save_idea','post_progress']};
 const claude=(out,stop='end_turn')=>[{stop_reason:stop,content:[{type:'text',text:JSON.stringify(out)}]}];
 assert.equal(run('Validate voice action',claude({action:'save_idea',title:'Bundle',summary:'A seasonal bundle'}),{'Voice job':[job]})[0].json.description,'A seasonal bundle');
 assert.equal(run('Validate voice action',claude({action:'create_task',title:'Deck',workspace:'adf'}),{'Voice job':[job]})[0].json.workspace,undefined);
 for(const stop of ['refusal','max_tokens']) assert.throws(()=>run('Validate voice action',claude({action:'ignore'},stop),{'Voice job':[job]}),stop);
 assert.throws(()=>run('Validate voice action',claude({action:'delete_everything'}),{'Voice job':[job]}));
 assert.throws(()=>run('Validate voice action',[{stop_reason:'end_turn',content:[]}],{'Voice job':[job]}));
 for(const n of wf.nodes.filter(n=>n.type==='n8n-nodes-base.httpRequest')) assert.notEqual(typeof n.parameters.sendBody,'string',n.name);
 const names=new Set(wf.nodes.map(n=>n.name));
 for(const [source,value] of Object.entries(wf.connections)){ assert.ok(names.has(source)); for(const o of value.main) for(const e of o) assert.ok(names.has(e.node),e.node); }
 assert.equal(wf.settings.saveDataSuccessExecution,'none');}
console.log('Ama Da Flow split, gateway and Claude Haiku self-tests passed');

// IJV and noAdf people never reach Ama Da Flow; Dotcross hands off jobs that mention Ama Da Flow.
{const groups=JSON.parse(fs.readFileSync(new URL('../actions/groups.json',import.meta.url),'utf8'));
 const compose=fs.readFileSync(new URL('../compose.actions.yaml',import.meta.url),'utf8');
 const adfList=/CLICKUP_ADF_LIST_ID: "(\d+)"/.exec(compose)[1];
 const noGroups=/CLICKUP_NO_ADF_GROUPS: "([^"]*)"/.exec(compose)[1].split(',').filter(Boolean);
 const noPeople=people.filter(p=>p.noAdf).flatMap(p=>p.ids);
 const pick=(w,name)=>w.nodes.find(n=>n.name===name).parameters.jsCode;
 const list=(js,name)=>JSON.parse(new RegExp(`const ${name} = (\\[[^\\]]*\\])`).exec(js)[1]);
 for(const w of [adfWf,dot]){
  assert.deepEqual(list(pick(w,'Validate test message'),'NO_ADF_GROUPS'),noGroups);
  assert.deepEqual(list(pick(w,'Validate test message'),'NO_ADF_PEOPLE'),noPeople);}
 assert.deepEqual(list(pick(dot,'Check for Ama Da Flow'),'NO_ADF_PEOPLE'),noPeople);
 assert.ok(noPeople.length && noGroups.length);
 const intake=(w,input)=>{input[0].body.session=w===adfWf?'default':'personal'; return new Function('$input','$',pick(w,'Validate test message'))({first:()=>({json:input[0]})},()=>null)[0].json;};
 const blocked=noPeople[1], ok=people.find(p=>!p.noAdf).ids[1], adfG=Object.keys(groups).find(g=>String(groups[g])===adfList);
 const gev=(G,body,who)=>[{body:{event:'message',session:S(),payload:{from:G,participant:who,fromMe:false,id:`false_${G}_3EB0ABCDEF444444_${who}`,hasMedia:false,body}}}];
 // #adf from a noAdf person or in IJV stays in Dotcross, without the workspace tag.
 for(const c of [ev('task: Deck #adf',blocked),gev(noGroups[0],'task: Deck #adf',ok)]){
  assert.equal(intake(adfWf,c).ignored,true); const d=intake(dot,c); assert.equal(d.title,'Deck'); assert.equal(d.workspace,undefined);}
 // A noAdf person in an Ama Da Flow group is ignored by both workflows.
 for(const w of [adfWf,dot]) assert.equal(intake(w,gev(adfG,'task: Deck',blocked)).ignored,true);
 assert.equal(intake(adfWf,gev(adfG,'task: Deck',ok)).title,'Deck');
 const mention=(text,chatId=ok,freeText=false)=>new Function('$input','$',pick(dot,'Check for Ama Da Flow'))({},name=>({first:()=>({json:name==='Voice job'?{chatId,freeText}:{text}})}))[0].json.adf;
 for(const t of ['Tolong buat task untuk Ama Da Flow ya','this is for amadaflow','ADF needs a new banner','for the A.D.F. team']) assert.equal(mention(t),true,t);
 for(const t of ['ada flow baru','adfoo','send the PDF','']) assert.equal(mention(t),false,t);
 assert.equal(mention('for Ama Da Flow',blocked),false);
 assert.equal(mention('for Ama Da Flow',ok,true),true);
 const c=dot.connections;
 for(const src of ['Transcribe on naspad-server','Use message text']) assert.equal(c[src].main[0][0].node,'Check for Ama Da Flow');
 assert.deepEqual(c['Mentions Ama Da Flow'].main.map(b=>b[0].node),['Hand off to Ama Da Flow','Read knowledge page']);
 assert.deepEqual(c['Hand off to Ama Da Flow'].main.map(b=>b[0].node),['Handed off','Record voice failure']);
 assert.deepEqual(c['Handed off'].main.map(b=>b[0].node),['Done in Ama Da Flow','Read knowledge page']);
 const h=dot.nodes.find(n=>n.name==='Hand off to Ama Da Flow'); assert.equal(h.parameters.url,'http://actions:8000/handoff'); assert.equal(h.parameters.sendBody,true);
 assert.ok(!adfWf.nodes.some(n=>n.name==='Check for Ama Da Flow'),'Ama Da Flow never hands back');}
console.log('No-ADF filter and Dotcross hand-off self-tests passed');
