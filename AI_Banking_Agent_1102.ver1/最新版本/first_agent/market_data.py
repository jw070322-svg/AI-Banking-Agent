"""Bounded XLSX ingestion and reproducible historical research. No Wind API required."""
from __future__ import annotations
import base64, hashlib, io, math, posixpath, statistics, zipfile
from datetime import date, datetime, timedelta, timezone
from xml.etree import ElementTree as ET

class MarketError(ValueError):
    def __init__(self, code, message):
        super().__init__(message); self.code=code; self.message=message

def fail(message): raise MarketError('INVALID_WORKBOOK', message)
def number(value, field, minimum=None, maximum=None, integer=False):
    if isinstance(value,bool) or value in (None,''): fail(field+' 缺少有效数字')
    try: result=float(value)
    except (TypeError,ValueError): fail(field+' 必须为数字')
    if not math.isfinite(result) or (minimum is not None and result<minimum) or (maximum is not None and result>maximum) or (integer and not result.is_integer()): fail(field+' 超出允许范围或单位不符')
    return int(result) if integer else result
def day(value, epoch=False):
    if isinstance(value,(int,float)):
        if not 1<=value<=100000: fail('Excel 日期序号无效')
        return ((date(1904,1,1) if epoch else date(1899,12,30))+timedelta(days=int(value))).isoformat()
    try: return date.fromisoformat(str(value).strip()[:10].replace('/','-')).isoformat()
    except ValueError: fail('日期必须为 YYYY-MM-DD 或 Excel 日期值')

ALIASES={'产品代码':'code','证券代码':'code','Wind代码':'code','产品名称':'name','证券名称':'name','产品类别':'category','风险等级':'risk_level','起购金额':'min_amount','锁定天数':'lock_days','赎回到账天数':'redemption_days','年费率':'annual_fee','所属板块':'sector','币种':'currency','数据日期':'as_of','数据来源':'source','净值口径':'price_basis','日期':'date','交易日期':'date','复权净值':'nav','收盘价':'close','年化无风险利率':'rate','指标':'indicator','数值':'value','单位':'unit','发布日期':'available_date'}
SHEETS={'产品':'products','产品信息':'products','净值':'prices','历史净值':'prices','无风险利率':'risk_free','指数':'indices','宏观':'macro'}

def read_xlsx(raw):
    if len(raw)>8*1024*1024: fail('XLSX 文件超过 8 MiB')
    try: z=zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile: fail('不是有效的 XLSX ZIP 文件')
    with z:
        files=z.infolist()
        if len(files)>500 or sum(x.file_size for x in files)>64*1024*1024: fail('工作簿解压体积过大')
        if any(x.flag_bits&1 for x in files): fail('不支持加密工作簿')
        if any('vbaProject' in x.filename or 'externalLinks/' in x.filename for x in files): fail('请移除宏及外部数据链接后导出数值文件')
        def xml(name):
            try: data=z.read(name)
            except KeyError: fail('工作簿缺少 '+name)
            except (zipfile.BadZipFile,RuntimeError,NotImplementedError,EOFError): fail('工作簿压缩条目损坏或压缩方式不支持')
            if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper(): fail('不支持 XML 实体声明')
            try: return ET.fromstring(data)
            except ET.ParseError: fail('工作簿 XML 无效')
        wb=xml('xl/workbook.xml');epoch=any(x.attrib.get('date1904') in ('1','true') for x in wb.iter() if x.tag.endswith('workbookPr'))
        rel={x.attrib['Id']:x.attrib['Target'] for x in xml('xl/_rels/workbook.xml.rels') if x.attrib.get('TargetMode')!='External'}
        shared=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            shared=[''.join(x.itertext()) for x in xml('xl/sharedStrings.xml')]
        out={};total=0
        for sheet in wb.iter():
            if not sheet.tag.endswith('}sheet'): continue
            name=SHEETS.get(sheet.attrib['name'],sheet.attrib['name'].lower())
            if name not in {'products','prices','risk_free','indices','macro'}: continue
            if name in out: fail('存在重复工作表 '+name)
            rid=next((v for k,v in sheet.attrib.items() if k.endswith('}id')),None)
            target=rel.get(rid,'');path=posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'xl/'+target)
            if not path.startswith('xl/worksheets/'): fail('工作表路径无效')
            rows=[]
            for row in xml(path).iter():
                if not row.tag.endswith('}row'): continue
                values={}
                for cell in row:
                    if any(x.tag.endswith('}f') for x in cell): fail(name+' 含公式，请先复制并粘贴为数值后导入')
                    ref=cell.attrib.get('r','A1');col=0
                    for ch in ref:
                        if ch.isalpha(): col=col*26+ord(ch.upper())-64
                    if not 1<=col<=40: fail('最多支持 40 列')
                    typ=cell.attrib.get('t');node=next((x for x in cell if x.tag.endswith('}v')),None)
                    value=node.text if node is not None else None
                    if typ=='inlineStr': value=''.join(x.text or '' for x in cell.iter() if x.tag.endswith('}t'))
                    elif typ=='s':
                        try: value=shared[int(value)]
                        except (ValueError,TypeError,IndexError): fail('共享字符串索引无效')
                    elif typ=='e': fail('工作簿含 Excel 错误值')
                    elif value is not None and typ not in ('str','d'):
                        try: value=float(value)
                        except ValueError: fail('数值单元格无效')
                    if isinstance(value,str) and len(value)>1000: fail('单元格文本过长')
                    values[col-1]=value
                if any(v not in (None,'') for v in values.values()): rows.append(values)
                total+=1
                if total>160000: fail('工作簿超过 160000 行，请分批导入')
            if not rows: out[name]=[];continue
            headers={i:ALIASES.get(str(v).strip(),str(v).strip().lower()) for i,v in rows[0].items() if v not in (None,'')}
            if len(set(headers.values()))!=len(headers): fail(name+' 存在重复字段')
            out[name]=[{headers[i]:v for i,v in row.items() if i in headers} for row in rows[1:]]
    return out,epoch

def import_workbook(content_base64, filename='wind.xlsx'):
    if not isinstance(filename,str) or not filename.lower().endswith('.xlsx'): fail('仅支持 .xlsx')
    if not isinstance(content_base64,str) or len(content_base64)>12*1024*1024: fail('文件编码或体积无效')
    try: raw=base64.b64decode(content_base64,validate=True)
    except (ValueError,TypeError): fail('Base64 编码无效')
    sheets,epoch=read_xlsx(raw)
    products={};prices={};indices={};rf={};macro=[];warnings=[]
    for row in sheets.get('products',[]):
        required={'code','name','category','risk_level','min_amount','lock_days','redemption_days','annual_fee','currency','as_of','source','price_basis'}
        if any(row.get(k) in (None,'') for k in required): fail('products 必须填写 '+', '.join(sorted(required)))
        code=str(row['code']).strip()
        if code in products: fail('重复产品代码 '+code)
        item={k:str(row[k]).strip() for k in ['code','name','category','currency','source','price_basis']};item['sector']=str(row.get('sector') or '')
        item['min_amount_unit']=str(row.get('min_amount_unit') or 'CNY_yuan')
        item['min_amount_semantics']=str(row.get('min_amount_semantics') or 'per_share_class_min_purchase')
        item.update(risk_level=number(row['risk_level'],'risk_level',1,5,True),min_amount=number(row['min_amount'],'min_amount',0,10000000),lock_days=number(row['lock_days'],'lock_days',0,36500,True),redemption_days=number(row['redemption_days'],'redemption_days',0,365,True),annual_fee=number(row['annual_fee'],'annual_fee',0,.2),as_of=day(row['as_of'],epoch))
        if item['currency']!='CNY': fail('本版仅接受 CNY 产品；外币须单独建模')
        if item['price_basis'] not in ('total_return_net','total_return_gross','price_only'): fail('price_basis 需为 total_return_net、total_return_gross 或 price_only')
        products[code]=item;prices[code]={}
    for row in sheets.get('prices',[]):
        code=str(row.get('code','')).strip();dt=day(row.get('date'),epoch)
        if code not in products: fail('prices 存在未定义产品 '+code)
        if dt in prices[code]: fail('重复净值日期 '+code+' '+dt)
        prices[code][dt]=number(row.get('nav'),'nav',.00000001,1e10)
    for row in sheets.get('risk_free',[]):
        dt=day(row.get('date'),epoch)
        if dt in rf: fail('重复无风险利率日期 '+dt)
        rf[dt]=number(row.get('rate'),'rate（小数）',-.05,.5)
    for row in sheets.get('indices',[]):
        if any(row.get(k) in (None,'') for k in ('code','name','date','close','source')): fail('indices 缺少 code/name/date/close/source')
        code=str(row['code']);dt=day(row['date'],epoch);item=indices.setdefault(code,{'code':code,'name':str(row['name']),'sector':str(row.get('sector') or ''),'source':str(row['source']),'values':{}})
        if dt in item['values']: fail('重复指数日期 '+code+' '+dt)
        item['values'][dt]=number(row['close'],'close',.00000001,1e10)
    for row in sheets.get('macro',[]):
        if any(row.get(k) in (None,'') for k in ('date','available_date','indicator','value','unit','source')): fail('macro 缺少必要字段')
        item={k:str(row[k]) for k in ('indicator','unit','source')};item.update(date=day(row['date'],epoch),available_date=day(row['available_date'],epoch),value=number(row['value'],'macro.value'))
        if item['available_date']<item['date']: fail('宏观发布日期早于观察日期')
        if any(x['indicator']==item['indicator'] and x['date']==item['date'] for x in macro):fail('重复宏观指标日期')
        macro.append(item)
    if not products and not indices and not macro: fail('工作簿没有产品、指数或宏观数据。空模板需先填写。')
    if products and not rf: warnings.append('未提供无风险利率，夏普率不可计算，产品不进入量化排名')
    sources={p['source'] for p in products.values()}|{p['source'] for p in indices.values()}|{p['source'] for p in macro}
    synthetic=any('synthetic' in s.lower() or '合成' in s for s in sources)
    return {'products':products,'prices':prices,'risk_free':rf,'indices':indices,'macro':macro,
            'metadata':{'filename':filename.replace('\\','/').rsplit('/',1)[-1],'sha256':hashlib.sha256(raw).hexdigest(),'imported_at':datetime.now(timezone.utc).isoformat(),'synthetic':synthetic,'sources':sorted(sources),'warnings':warnings}}

def market_status(dataset):
    if not dataset: return {'loaded':False,'message':'本地 Wind 数据暂不可用'}
    dates=[d for series in dataset['prices'].values() for d in series]+[d for item in dataset['indices'].values() for d in item['values']]
    return {'loaded':True,**dataset['metadata'],'product_count':len(dataset['products']),'price_rows':sum(map(len,dataset['prices'].values())),'index_count':len(dataset['indices']),'macro_rows':len(dataset['macro']),'start_date':min(dates) if dates else None,'end_date':max(dates) if dates else None,'products':[{'code':x['code'],'name':x['name']} for x in dataset['products'].values()]}

def metrics(values, rf=None, fee=0):
    dates=sorted(values);v=[values[d] for d in dates]
    if len(v)<61: raise MarketError('INSUFFICIENT_DATA','至少需要 61 个净值点 / 60 个收益观察值')
    gaps=[(date.fromisoformat(b)-date.fromisoformat(a)).days for a,b in zip(dates,dates[1:])]
    if max(gaps)>12 or statistics.median(gaps)>3: raise MarketError('IRREGULAR_DATA','日频序列间隔过大，不按 252 日直接年化')
    r=[b/a-1 for a,b in zip(v,v[1:])];vol=statistics.stdev(r)*math.sqrt(252);span=(date.fromisoformat(dates[-1])-date.fromisoformat(dates[0])).days
    annual=(v[-1]/v[0])**(365/span)-1-fee
    peak=v[0];dd=0
    for n in v: peak=max(peak,n);dd=max(dd,1-n/peak)
    sharpe=None;excess=[]
    if rf:
        rd=sorted(rf)
        for i,ret in enumerate(r):
            known=[d for d in rd if d<=dates[i]]
            if not known or (date.fromisoformat(dates[i])-date.fromisoformat(known[-1])).days>40: raise MarketError('RISK_FREE_GAP','无风险利率缺失或距观察日超过 40 天')
            excess.append(ret-((1+rf[known[-1]])**(1/252)-1)-fee/252)
        sigma=statistics.stdev(excess)
        if sigma>1e-12: sharpe=statistics.mean(excess)/sigma*math.sqrt(252)
    return {'annualized_return':annual,'annualized_volatility':vol,'sharpe':sharpe,'max_drawdown':dd,'observations':len(r),'start_date':dates[0],'end_date':dates[-1]}

def market_context(dataset, as_of):
    if not dataset: return {'available':False,'headline':'本地 Wind 数据暂不可用，请核对项目内数据文件。','indices':[],'macro':[],'risk_off':False}
    cards=[]
    for item in dataset['indices'].values():
        dates=sorted(d for d in item['values'] if d<=as_of)
        if len(dates)<2: continue
        v=[item['values'][d] for d in dates];age=(date.fromisoformat(as_of)-date.fromisoformat(dates[-1])).days
        cards.append({k:item[k] for k in ('code','name','sector','source')}|{'close':v[-1],'as_of':dates[-1],'stale':age>10,'change_1d':v[-1]/v[-2]-1,'change_20d':v[-1]/v[-21]-1 if len(v)>20 else None,'points':[{'date':d,'close':item['values'][d]} for d in dates[-60:]]})
    broad=[x for x in cards if not x['sector'] and not x['stale'] and x['change_20d'] is not None]
    trend=statistics.mean(x['change_20d'] for x in broad) if broad else None
    latest={}
    for item in sorted(dataset['macro'],key=lambda x:x['available_date']):
        if item['available_date']<=as_of: latest[item['indicator']]=item
    macro=[{**x,'stale':(date.fromisoformat(as_of)-date.fromisoformat(x['available_date'])).days>90} for x in latest.values()]
    signals=[]
    if trend is not None and trend<-.05: signals.append('宽基 20 日跌幅超过 5%')
    # Explicit demo policy: publication-aware PMI can only tighten suitability.
    pmi=[x for x in macro if dataset['metadata'].get('macro_publication_dates_verified',True) and not x['stale'] and x['indicator'].strip().upper() in ('PMI','制造业PMI','中国制造业PMI') and x['unit'] in ('指数','index','点')]
    if any(x['value']<49 for x in pmi): signals.append('已发布制造业 PMI 低于 49')
    risk_off=bool(signals)
    source='合成样本' if dataset['metadata']['synthetic'] else '本地 Wind 快照'
    headline=f'依据市场快照（{source}，分析日期 {as_of}）：'
    headline+=f'宽基指数近 20 个观察日平均涨跌 {trend:.2%}。' if trend is not None else '缺少近期宽基指数。'
    headline+=('；'.join(signals)+'，采用防守筛选，风险上限暂降至 2。') if risk_off else '维持个人风险上限。'
    headline+=(' 宏观发布日期未经独立核验，暂不用于风险门槛。' if not dataset['metadata'].get('macro_publication_dates_verified',True) else ' 宏观指标按发布日期使用。')+' 规则阈值属于演示策略，不保证收益。'
    observations=[]
    for code,p in dataset['products'].items():
        series=dataset['prices'].get(code,{})
        dates=sorted(d for d in series if d<=as_of)
        if not dates: continue
        selected=dates[-60:];age=(date.fromisoformat(as_of)-date.fromisoformat(dates[-1])).days
        observations.append({'code':code,'name':p['name'],'as_of':dates[-1],'stale':age>10,
            'latest_nav':series[dates[-1]],'change_20_observations':series[dates[-1]]/series[dates[-21]]-1 if len(dates)>=21 else None,
            'basis_label':'单位净值，分红口径未核验' if code.endswith('.LC') and dataset['metadata'].get('bank_unit_nav_unverified') else p['price_basis'],
            'points':[{'date':d,'close':series[d]} for d in selected]})
    return {'available':bool(cards or macro),'headline':headline,'indices':cards,'macro':macro,'product_observations':observations,'risk_off':risk_off,'signals':signals,'synthetic':dataset['metadata']['synthetic'],'as_of':as_of}

def recommend(dataset, profile, as_of):
    if not dataset: raise MarketError('DATA_REQUIRED','本地 Wind 数据暂不可用，请核对项目内数据文件')
    context=market_context(dataset,as_of);cap=min(profile['risk_tolerance'],profile['risk_capacity']);cap=min(cap,2) if context['risk_off'] else cap
    ranked=[];excluded=[]
    for code,p in dataset['products'].items():
        reasons=[];dates=sorted(d for d in dataset['prices'][code] if d<=as_of)
        sector_cards=[x for x in context['indices'] if p['sector'] and x['sector']==p['sector'] and not x['stale'] and x['change_20d'] is not None]
        sector_return=statistics.mean(x['change_20d'] for x in sector_cards) if sector_cards else None
        if p['risk_level']>=3 and sector_return is not None and sector_return<-.10: reasons.append('所属板块近 20 日跌幅超过 10%，演示策略暂缓配置')
        if profile['amount_minor']<=0: reasons.append('预留后没有可配置资金')
        if p['risk_level']>cap: reasons.append('超过当前风险上限')
        if p.get('min_amount_unit','CNY_yuan')!='CNY_yuan' or p.get('min_amount_semantics','per_share_class_min_purchase')!='per_share_class_min_purchase': reasons.append('起购单位为ETF申赎份额，不能当作客户现金起购额；交易门槛待核验')
        elif profile['amount_minor']/100<p['min_amount']: reasons.append('预留资金后金额低于起购额')
        if p['lock_days']+p['redemption_days']>profile['horizon_days']: reasons.append('锁定与赎回到账晚于用款期限')
        if p['price_basis']=='price_only': reasons.append('只有价格，缺少分红再投资口径，不能与总回报直接比较')
        if dataset['metadata'].get('bank_unit_nav_unverified') and code.endswith('.LC'): reasons.append('银行理财仅提供单位净值，分红再投资口径尚未核实')
        if dataset['metadata'].get('min_scoring_points') and len(dates)<dataset['metadata']['min_scoring_points']: reasons.append('净值历史不足 253 个观察点，无法进入本次排名')
        if p['as_of']>as_of or (date.fromisoformat(as_of)-date.fromisoformat(p['as_of'])).days>90: reasons.append('产品条款日期超前或超过 90 天')
        if not dates or (date.fromisoformat(as_of)-date.fromisoformat(dates[-1])).days>10: reasons.append('缺少近期净值（超过 10 个自然日）')
        if not reasons:
            try:
                values={d:dataset['prices'][code][d] for d in dates[-253:]}
                m=metrics(values,dataset['risk_free'],0 if p['price_basis']=='total_return_net' else p['annual_fee'])
                if m['sharpe'] is None: reasons.append('无风险利率缺失或波动为零，夏普率不可计算')
            except MarketError as e: reasons.append(e.message)
        if reasons: excluded.append({'code':code,'name':p['name'],'reasons':reasons});continue
        years=profile['horizon_days']/365
        try:
            if 1+m['annualized_return']<=0: raise ValueError('negative net annual factor')
            rate=math.expm1(math.log1p(m['annualized_return'])*years)
            gain=profile['amount_minor']*rate
            if not math.isfinite(gain) or abs(gain)>9007199254740991: raise ValueError('not representable as safe minor units')
        except (OverflowError,ValueError):
            excluded.append({'code':code,'name':p['name'],'reasons':['历史回报或费率导致情景结果超出有效范围，请核对净值单位及数据质量']});continue
        ranked.append({'code':code,'name':p['name'],'category':p['category'],'sector':p['sector'],'sector_return_20d':sector_return,'risk_level':p['risk_level'],'metrics':m,'scenario_return':rate,'scenario_gain_minor':round(gain),'source':p['source']})
    ranked.sort(key=lambda p:(-p['metrics']['sharpe'],p['metrics']['max_drawdown'],p['code']))
    return {'ranked':ranked,'excluded':excluded,'profile':profile,'effective_risk_cap':cap,'market':context,
            'methodology':'先筛风险、预留后金额、锁定到账期和数据日期。宽基指数20日平均跌超5%时，风险上限降至2；'+('经核验的已发布PMI低于49也会触发压降。' if dataset['metadata'].get('macro_publication_dates_verified',True) else '本地宏观发布日期未核验，不启用PMI压降。')+'风险3以上且对应板块20日跌超10%时暂缓。阈值为可解释演示策略，尚未回测优化。候选按历史夏普率降序、回撤升序排列。年化收益为365天几何年化，波动/夏普以252交易日年化。情景收益是假设历史年化收益持续的计算，不是未来预测。',
            'warnings':dataset['metadata']['warnings']+(['当前为合成数据，不能用于真实投资'] if dataset['metadata']['synthetic'] else []),'ledger_modified':False}
