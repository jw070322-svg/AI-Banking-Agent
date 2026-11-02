const assert = require('node:assert/strict');
const {links} = require('./source-links.js');
const render=uri=>links({results:[{tool:'knowledge',result:{citations:[{citation_uri:uri,title:'<安全>',start_line:12}]}}]});
assert.match(render('/relay/source/release-1/yuki-01#L12'), /&lt;安全&gt;/);
assert.match(render('/review/source/yuki-01#L12'), /noopener noreferrer/);
for(const uri of ['https://evil.test/','javascript:alert(1)','/relay/source/v/../../runtime/db','/relay/source/v/doc#L12?x=1']) assert.equal(render(uri),'');
console.log(JSON.stringify({passed:true,checks:6}));
