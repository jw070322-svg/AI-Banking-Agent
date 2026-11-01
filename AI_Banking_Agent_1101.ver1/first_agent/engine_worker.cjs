// One deterministic operation per SQLite transaction; no shell or evaluated code.
const fs=require('node:fs');
const {createSession}=require('../web/journey-engine.js');
const req=JSON.parse(fs.readFileSync(0,'utf8'));
if(Number.isFinite(req.now))Date.now=()=>req.now*1000;
const bank=createSession(req.state,{preserveVerification:true});
let result=null,error=null;
try { if(req.method) result=bank[req.method](...(req.args||[])); }
catch(e) { error=String(e.message); }
process.stdout.write(JSON.stringify({state:bank.state,catalog:bank.catalog,total:bank.total(),capacity:bank.capacity(),result:result===undefined?null:result,error}));
