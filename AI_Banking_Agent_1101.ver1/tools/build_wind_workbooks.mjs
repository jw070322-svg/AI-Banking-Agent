import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const out=path.join(root,'data'),proof=path.join(root,'reports','workbook-previews');
await fs.mkdir(out,{recursive:true});await fs.mkdir(proof,{recursive:true});
const headers={products:['code','name','category','risk_level','min_amount','lock_days','redemption_days','annual_fee','sector','currency','as_of','source','price_basis'],prices:['date','code','nav'],risk_free:['date','rate'],indices:['date','code','name','close','sector','source'],macro:['date','available_date','indicator','value','unit','source']};
const source='Synthetic demo / 合成数据，非 Wind 行情';
const dates=[];for(let d=new Date('2025-10-20T00:00:00Z');d<=new Date('2026-10-23T00:00:00Z');d.setUTCDate(d.getUTCDate()+1)){if(d.getUTCDay()!==0&&d.getUTCDay()!==6)dates.push(new Date(d));}
const products=[['SYN-CASH','合成现金管理','cash',1,100,0,1,0,'','CNY',new Date('2026-10-23'),source,'total_return_net'],['SYN-BOND','合成纯债基金','bond',2,100,0,2,.003,'债券','CNY',new Date('2026-10-23'),source,'total_return_net'],['SYN-INDEX','合成宽基基金','index',3,100,0,2,.006,'宽基','CNY',new Date('2026-10-23'),source,'total_return_net'],['SYN-TECH','合成科技基金','equity',4,100,0,2,.012,'科技','CNY',new Date('2026-10-23'),source,'total_return_net'],['SYN-TERM','合成锁定基金','bond',2,10000,365,2,.004,'债券','CNY',new Date('2026-10-23'),source,'total_return_net']];
const sample={products,prices:[],risk_free:dates.map(d=>[d,.015]),indices:[],macro:[[new Date('2026-09-30'),new Date('2026-10-01'),'制造业PMI',48.8,'点',source],[new Date('2026-09-30'),new Date('2026-10-15'),'CPI同比',.018,'小数',source]]};
products.forEach((p,k)=>{let nav=1;dates.forEach((d,i)=>{const r=[.00007,.00012,.00025,.00035,.00013][k]+Math.sin(i*1.37+k)*[.00003,.001,.012,.021,.0015][k];nav*=1+r;sample.prices.push([d,p[0],nav]);});});
[['SYN-BROAD','合成宽基指数',''],['SYN-TECH-IDX','合成科技指数','科技'],['SYN-CONSUME','合成消费指数','消费']].forEach((p,k)=>{let close=1000;dates.forEach((d,i)=>{close*=1+.0001+Math.sin(i*.8+k)*.008-(i>dates.length-24?.0035:0);sample.indices.push([d,p[0],p[1],close,p[2],source]);});});
for(const kind of ['template','sample']){
 const wb=Workbook.create();
 const guide=wb.worksheets.add('使用说明');guide.showGridLines=false;
 guide.getRange('A1:B9').values=[['Wind 数据接入','字段与校验约定'],['文件类型',kind==='sample'?'全部为合成样本，非实际 Wind 数据':'空白模板，填写后导入'],['工作表','products / prices / risk_free / indices / macro'],['数据单位','金额为人民币元；利率和费率使用小数，例如 2% 填 0.02'],['净值','使用含分红再投资的复权净值；不能填七日年化或累计净值'],['日期','使用 Excel 日期值或 YYYY-MM-DD'],['导入','数值文件，不含公式、宏、外部链接；8 MiB / 160000行以内'],['产品门槛','量化至少61个日净值点；建议2–3年日数据'],['来源','source填写来源；as_of为条款日期；available_date为宏观发布日期']];
 guide.getRange('A1:B9').format.font={name:'Arial',size:11};guide.getRange('A1:B1').format={fill:'#33445F',font:{bold:true,color:'#FFFFFF'}};guide.getRange('A1:A9').format.columnWidth=18;guide.getRange('B1:B9').format.columnWidth=92;guide.getRange('A1:B9').format.rowHeight=27;
 for(const [name,fields] of Object.entries(headers)){
  const sh=wb.worksheets.add(name);sh.showGridLines=false;const rows=kind==='sample'?sample[name]:[];
  sh.getRangeByIndexes(0,0,1,fields.length).values=[fields];
  if(rows.length)sh.getRangeByIndexes(1,0,rows.length,fields.length).values=rows;
  const range=sh.getRangeByIndexes(0,0,Math.max(2,rows.length+1),fields.length);range.format.font={name:'Arial',size:10};range.format.rowHeight=24;range.format.columnWidth=18;
  sh.getRangeByIndexes(0,0,1,fields.length).format={fill:'#33445F',font:{bold:true,color:'#FFFFFF'},rowHeight:29};
  fields.forEach((f,c)=>{if(['name','source','price_basis','indicator'].includes(f))sh.getRangeByIndexes(0,c,Math.max(2,rows.length+1),1).format.columnWidth=f==='source'?48:28;
   if(['date','available_date','as_of'].includes(f))sh.getRangeByIndexes(1,c,Math.max(1,rows.length),1).setNumberFormat('yyyy-mm-dd');
   if(['annual_fee','rate'].includes(f))sh.getRangeByIndexes(1,c,Math.max(1,rows.length),1).setNumberFormat('0.00%');
   if(['nav','close'].includes(f))sh.getRangeByIndexes(1,c,Math.max(1,rows.length),1).setNumberFormat('0.000000');
  });sh.freezePanes.freezeRows(1);
 }
 wb.recalculate();
 console.log((await wb.inspect({kind:'table',range:'products!A1:F6',include:'values',tableMaxRows:6,tableMaxCols:6,maxChars:1300})).ndjson);
 for(const name of ['使用说明',...Object.keys(headers)]){const image=await wb.render({sheetName:name,range:name==='products'?'A1:F6':name==='使用说明'?'A1:B9':'A1:F7',scale:1,format:'png'});await fs.writeFile(path.join(proof,`${kind}-${name}.png`),new Uint8Array(await image.arrayBuffer()));}
 await (await SpreadsheetFile.exportXlsx(wb)).save(path.join(out,`wind_${kind}.xlsx`));
}
console.log('Created blank template and synthetic sample.');
