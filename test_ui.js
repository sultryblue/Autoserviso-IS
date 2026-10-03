/* UI logic regression tests in Node's VM. This is NOT a rendered browser test. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
class Element {
 constructor(){this.innerHTML='';this.textContent='';this.value='';this.children={};this.style={};this.attributes={}}
 querySelector(key){return this.children[key]??=new Element()}
 querySelectorAll(key){return Object.values(this.children).filter(x=>x.name)}
 setAttribute(key,value){this.attributes[key]=value}
 showModal(){this.open=true}
 close(){this.open=false}
}
const nodes={},document={querySelector(key){return nodes[key]??=new Element()}};
const sandbox={document,console,URLSearchParams,Intl,Date,BigInt,Number,Set,FormData,
 setTimeout:()=>0,fetch:async()=>({status:401}),crypto:require('node:crypto').webcrypto};
const context=vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname,'static/app.js'),'utf8'),context);
const run=s=>vm.runInContext(s,context),flush=()=>new Promise(resolve=>setImmediate(resolve));
const results=[];
function test(name,fn){try{fn();results.push({name,passed:true})}catch(e){results.push({name,passed:false,error:e.message})}}
const base=()=>({user:{id:2,name:'Vadybininkas',role:'vadybininkas'},users:[{id:2,name:'Vadybininkas',role:'vadybininkas',active:1}],clients:[],cars:[],appointments:[],orders:[{id:1,status:'Naujas',plate:'UI01',problem:'Patikra',mileage:100,confirmed_total_cents:0,paid_cents:0,balance_cents:0,reserved_cents:0,available_cents:0}],estimates:[],lines:[],decisions:[],tasks:[],payments:[],diagnostic_entries:[],diagnostic_assignments:[]});
function state(s){sandbox.fixture=s;run('S=fixture;chosen=1;selectedEstimate=null;view="order"')}
function orderHtml(){run('renderOrder(document.querySelector("#content"))');return nodes['#content'].innerHTML}
function approved(){const s=base();s.estimates=[{id:1,order_id:1,version:1,status:'Patvirtinta',total_cents:1000}];s.lines=[{id:1,estimate_id:1,kind:'Darbas',title:'Darbas',quantity_1000:1000,unit_cents:1000,line_total_cents:1000}];s.tasks=[{id:1,line_id:1,order_id:1,title:'Darbas',status:'Baigtas',minutes:10}];return s}
(async()=>{
 await flush();
 state(base());
 test('Naujas užsakymas nesiūlo paruošimo',()=>assert.equal(orderHtml().includes('Automobilis paruoštas'),false));
 test('Be diagnostikos nesiūloma rengti sąmatos',()=>assert.equal(orderHtml().includes('Parengti sąmatą'),false));
 let s=base();s.diagnostic_entries=[{order_id:1,result:'Patikrinta',proposed_works:'Pakeisti'}];state(s);
 test('Po diagnostikos galima rengti sąmatą',()=>assert.equal(orderHtml().includes('Parengti sąmatą'),true));
 s=approved();state(s);
 test('Visi patvirtinti darbai baigti – siūlomas paruošimas',()=>assert.equal(orderHtml().includes('Automobilis paruoštas'),true));
 s.tasks[0].status='Vykdomas';state(s);
 test('Vykdomas darbas neleidžia siūlyti paruošimo',()=>assert.equal(orderHtml().includes('Automobilis paruoštas'),false));
 s.tasks[0].status='Baigtas';s.tasks[0].line_id=99;state(s);
 test('Trūkstama patvirtintos eilutės užduotis neleidžia paruošti',()=>assert.equal(run('canCompleteOrder(1)'),false));
 s=approved();s.estimates.push({id:2,order_id:1,version:2,status:'Pateikta'});state(s);
 test('Neišspręstas papildymas neleidžia siūlyti paruošimo',()=>assert.equal(orderHtml().includes('Automobilis paruoštas'),false));
 s.estimates[1].status='Atmesta';state(s);
 test('Atmestas papildymas išlaiko baigtos v1 apimties paruošimą',()=>assert.equal(run('canCompleteOrder(1)'),true));
 s=base();s.estimates=[{id:1,order_id:1,version:1,status:'Atmesta',total_cents:1000}];state(s);
 test('Visas remontas atmestas – automobilį galima grąžinti',()=>assert.equal(run('canCompleteOrder(1)'),true));
 s=approved();s.orders[0].status='Uždarytas';state(s);
 test('Uždarytas užsakymas neturi keitimo veiksmų',()=>assert.equal(/Paskirti diagnostiką|Automobilis paruoštas|Uždaryti užsakymą/.test(orderHtml()),false));
 s=approved();s.orders[0].status='Paruoštas';s.orders[0].handover_at='2026-09-24T15:00';state(s);
 test('Po perdavimo siūlomas tik galutinis uždarymas',()=>{const html=orderHtml();assert(html.includes('Uždaryti užsakymą'));assert(!html.includes('Registruoti automobilio perdavimą'))});
 s=base();s.user.role='klientas';s.client={id:1,name:'Klientas',phone:'1234567',email:''};state(s);
 test('Kliento tuščia užsakymo kortelė be darbuotojo veiksmų',()=>{const html=orderHtml();assert(html.includes('Pateiktos sąmatos dar nėra.'));assert(!html.includes('Paskirti diagnostiką'));assert(!/undefined|null|\[object Object\]/.test(html))});
 test('Kliento navigacija ir aktyvi užsakymų skiltis',()=>{run('render()');const html=nodes['#app'].innerHTML;assert(html.includes('Mano kontaktai'));assert(html.includes('class="active" onclick="go(\'orders\')"'));assert(!/Veiksmų žurnalas|Naudotojai|Ataskaitos/.test(html))});
 for(const role of ['vadybininkas','mechanikas','vadovas']){
  s=base();s.user.role=role;state(s);run('view="overview"');if(role==='mechanikas')run('view="tasks"');
  test(role+' navigacija atitinka rolę',()=>{run('render()');const html=nodes['#app'].innerHTML;assert.equal(html.includes('Ataskaitos'),role==='vadovas');assert.equal(html.includes('Veiksmų žurnalas'),role==='vadovas');assert.equal(html.includes('Mano diagnostika'),role==='mechanikas')});
 }
 test('Suma pateikiama eurais, ne centais',()=>{const text=run('euro(12345)');assert(text.includes('123,45'));assert(text.includes('€'))});
 test('Kiekis nerodomas tūkstantosiomis dalimis',()=>assert.equal(run('unitsText(1500,1000)'),'1.5'));
 test('Užsakymo paieška atpažįsta rodomą numerį U-0001',()=>{const text=run('orderSearchText({id:1,plate:"DEMO01",client_name:"Klientas A"})');assert(text.includes('u-0001'));assert(text.includes('1'));assert(text.includes('demo01'));assert(text.includes('klientas a'))});
 test('Naudotojo tekstas saugiai užkoduojamas HTML',()=>assert.equal(run('E("<script> & ")'),'&lt;script&gt; &amp; '));
 test('Lentelę galima fokusuoti klaviatūra',()=>assert(run('table(["Testas"],[["Ilga reikšmė"]])').includes('tabindex="0"')));
 test('Dialogas turi pavadinimą ir tekstinių klaidų sritį',()=>{run('modal("Patikra","<p>Turinys</p>","Išsaugoti",()=>{})');assert.equal(nodes['#dialog'].attributes['aria-labelledby'],'dialogTitle');assert(nodes['#dialog'].innerHTML.includes('role="alert"'))});
 // Resolve actual app.js fetch calls out of order, with deterministic responses.
 const pending=[];sandbox.fetch=(url)=>new Promise(resolve=>pending.push({url,resolve}));
 function respond(index,data,ok=true){pending[index].resolve({ok,status:ok?200:400,json:async()=>data})}
 const reportData=n=>({totals:{orders:n,closed_orders:0,work_minutes:0,confirmed_cents:0,paid_cents:0},daily:[]});
 const c=new Element();for(const name of ['from','to']){const x=c.querySelector(`[name=${name}]`);x.name=name;x.value='2026-09-24'}
 sandbox.content=c;state(base());run('view="reports";renderReports(content)');c.querySelector('[name=from]').onchange();
 respond(1,reportData(222));await flush();respond(0,reportData(111));await flush();
 test('Senas suvestinės atsakymas neperrašo naujesnio filtro',()=>{const html=c.querySelector('#report').innerHTML;assert(html.includes('222'));assert(!html.includes('111'))});
 c.querySelector('[name=from]').onchange();c.querySelector('[name=to]').onchange();respond(3,reportData(333));await flush();respond(2,{error:'Sena klaida'},false);await flush();
 test('Sena suvestinės klaida neperrašo naujesnio rezultato',()=>assert.notEqual(c.querySelector('#report').textContent,'Sena klaida'));
 const ac=new Element();for(const name of ['from','to']){const x=ac.querySelector(`[name=${name}]`);x.name=name;x.value='2026-09-24'}
 sandbox.auditContent=ac;run('view="audit";renderAudit(auditContent)');ac.querySelector('[name=from]').onchange();
 respond(5,{total:2,audit:[]});await flush();respond(4,{total:1,audit:[]});await flush();
 test('Senas audito atsakymas neperrašo naujesnio filtro',()=>assert(ac.querySelector('#auditResults').innerHTML.includes('Iš viso įrašų: 2.')));
 ac.querySelector('[name=from]').onchange();run('view="orders"');respond(6,{total:9,audit:[]});await flush();
 test('Išėjus iš audito neliečiama naujos skilties sąsaja',()=>assert(!ac.querySelector('#auditResults').innerHTML.includes('Iš viso įrašų: 9.')));
 sandbox.fetch=async()=>({status:500,ok:false,json:async()=>({error:'Serverio patikros klaida.'})});
 let error='';try{await run('refresh()')}catch(e){error=e.message}
 test('Nesėkmingas duomenų atnaujinimas nerodo TypeError',()=>assert.equal(error,'Serverio patikros klaida.'));
 const report={type:'JS logikos patikra VM su DOM ir HTTP imitacijomis; ne reali naršyklė',total:results.length,passed:results.filter(x=>x.passed).length,tests:results};
 fs.writeFileSync(path.join(__dirname,'test_ui_results.json'),JSON.stringify(report,null,2));
 console.log(`UI logika: ${report.passed}/${report.total}`);for(const t of results.filter(x=>!x.passed))console.log(t);
 process.exitCode=report.passed===report.total?0:1;
})().catch(e=>{console.error(e);process.exitCode=1});
