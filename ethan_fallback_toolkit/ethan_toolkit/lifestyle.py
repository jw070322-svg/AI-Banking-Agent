"""Budgeted life-event drafts, with optional local calendar export."""
from datetime import timedelta
import hashlib
from .models import iso_date,money


def plan_event(*,event_date,as_of,budget_minor,available_minor,emergency_reserve_minor=0,label='家人生日',currency='CNY'):
    day,today=iso_date(event_date),iso_date(as_of)
    if day<today:raise ValueError('event_date cannot be in the past')
    if (day-today).days>3660:raise ValueError('event_date must be within ten years')
    if currency!='CNY':raise ValueError('only CNY is supported')
    if not isinstance(label,str) or not 1<=len(label.strip())<=200:raise ValueError('label must contain 1-200 characters')
    for k,v in [('budget_minor',budget_minor),('available_minor',available_minor),('emergency_reserve_minor',emergency_reserve_minor)]:money(v,k)
    affordable=max(0,available_minor-emergency_reserve_minor)
    base={'schema_version':'life-plan-1.0','label':label,'as_of':as_of,'event_date':event_date,'currency':currency,
          'requested_budget_minor':budget_minor,'affordable_minor':affordable,'emergency_reserve_minor':emergency_reserve_minor,
          'shortfall_minor':max(0,budget_minor-affordable),'planned_only':True,'ledger_modified':False,'requires_confirmation':True,
          'assumptions':['budget and date are user inputs; no merchant quote, reservation or money lock has occurred']}
    if budget_minor>affordable or available_minor<emergency_reserve_minor:
        return {**base,'status':'needs_adjustment','reserve_shortfall_minor':max(0,emergency_reserve_minor-available_minor),'allocations':[],'calendar':[]}
    gift=budget_minor//2;meal=budget_minor*3//10
    allocations=[{'category':'礼物','amount_minor':gift},{'category':'餐饮','amount_minor':meal},
                 {'category':'其他活动','amount_minor':budget_minor-gift-meal}]
    items=[]
    for offset,title in [(-7,'确认活动预算与偏好'),(-2,'核对商户报价并提醒本人决定是否预订'),(0,'活动当天')]:
        d=max(today,day+timedelta(days=offset)).isoformat()
        token=hashlib.sha256(f'{label}|{as_of}|{event_date}|{budget_minor}|{offset}'.encode()).hexdigest()[:24]
        items.append({'id':'LIFE-'+token,'date':d,'title':label+'：'+title,'action':'reminder_only'})
    return {**base,'status':'draft','reserve_shortfall_minor':0,'allocations':allocations,'calendar':items}


def export_ics(plan):
    if not isinstance(plan,dict) or plan.get('status')!='draft' or plan.get('planned_only') is not True:
        raise ValueError('only draft life plans can be exported')
    stamp=iso_date(plan['as_of']).strftime('%Y%m%d')+'T000000Z'
    def escape(value):
        if not isinstance(value,str):raise ValueError('calendar text must be text')
        return value.replace('\\','\\\\').replace('\r\n','\n').replace('\r','\n').replace('\n','\\n').replace(';','\\;').replace(',','\\,')
    lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//AI Banking//Ethan Toolkit//ZH','CALSCALE:GREGORIAN']
    for item in plan['calendar']:
        day=iso_date(item['date']);uid=hashlib.sha256(str(item['id']).encode()).hexdigest()+'@ethan-toolkit.local'
        lines+=['BEGIN:VEVENT','UID:'+uid,'DTSTAMP:'+stamp,'DTSTART;VALUE=DATE:'+day.strftime('%Y%m%d'),
                'DTEND;VALUE=DATE:'+(day+timedelta(days=1)).strftime('%Y%m%d'),
                'SUMMARY:'+escape(item['title']),'DESCRIPTION:'+escape('仅为计划提醒；未预订、未扣款，执行前须本人确认。'),'END:VEVENT']
    lines+=['END:VCALENDAR']
    # RFC 5545 octet folding, without splitting a UTF-8 character.
    folded=[]
    for line in lines:
        chunk=''
        for char in line:
            if len((chunk+char).encode('utf-8'))>75:
                folded.append(chunk);chunk=' '
            chunk+=char
        folded.append(chunk)
    return '\r\n'.join(folded)+'\r\n'
