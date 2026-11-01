"""Local calendar and optional, read-only Google Calendar provider."""
import json, os
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

CHINA=timezone(timedelta(hours=8))
def today(): return datetime.now(CHINA).date().isoformat()
def google_configured():
    return bool(os.environ.get('BANKING_GOOGLE_ACCESS_TOKEN') or all(os.environ.get(k) for k in ('BANKING_GOOGLE_CLIENT_ID','BANKING_GOOGLE_CLIENT_SECRET','BANKING_GOOGLE_REFRESH_TOKEN')))
def fetch_google(reference_date):
    """Credentials stay on the server and are never returned or logged."""
    if not google_configured(): return [],{'configured':False,'status':'not_connected','message':'Google 日历未配置只读授权；项目内日历仍可用。'}
    token=os.environ.get('BANKING_GOOGLE_ACCESS_TOKEN')
    try:
        if not token:
            raw=urlencode({'client_id':os.environ['BANKING_GOOGLE_CLIENT_ID'],'client_secret':os.environ['BANKING_GOOGLE_CLIENT_SECRET'],'refresh_token':os.environ['BANKING_GOOGLE_REFRESH_TOKEN'],'grant_type':'refresh_token'}).encode()
            req=Request('https://oauth2.googleapis.com/token',raw,{'Content-Type':'application/x-www-form-urlencoded'})
            with urlopen(req,timeout=8) as response: token=json.loads(response.read(65537)).get('access_token')
            if not token: raise ValueError('token')
        start=datetime.combine(date.fromisoformat(reference_date),datetime.min.time(),CHINA)
        query={'timeMin':start.isoformat(),'timeMax':(start+timedelta(days=7)).isoformat(),'singleEvents':'true','orderBy':'startTime','maxResults':250,'timeZone':'Asia/Shanghai'}
        calendar=os.environ.get('BANKING_GOOGLE_CALENDAR_ID','primary');result=[];pages=0
        while True:
            url='https://www.googleapis.com/calendar/v3/calendars/'+quote(calendar,safe='')+'/events?'+urlencode(query)
            with urlopen(Request(url,headers={'Authorization':'Bearer '+token}),timeout=8) as response:
                raw=response.read(2*1024*1024+1)
            if len(raw)>2*1024*1024: raise ValueError('size')
            payload=json.loads(raw)
            for event in payload.get('items',[]):
                if event.get('status')=='cancelled': continue
                start_data=event.get('start') or {};stamp=start_data.get('date')
                if not stamp:
                    stamp=datetime.fromisoformat(start_data['dateTime'].replace('Z','+00:00')).astimezone(CHINA).date().isoformat()
                title=str(event.get('summary') or '未命名事件')[:120]
                special=any(x in title.lower() for x in ('生日','纪念','聚餐','婚礼','旅行','周年','birthday','anniversary','wedding','dinner'))
                result.append({'id':'google:'+str(event['id']),'title':title,'date':stamp,'special':special,'source':'google','city':'','kind':'special' if special else 'normal'})
            pages+=1
            if not payload.get('nextPageToken'): break
            if pages>=4: raise ValueError('too_many_events')
            query['pageToken']=payload['nextPageToken']
        return result,{'configured':True,'status':'connected','message':'已读取 Google 日历未来七天事件','synced_at':datetime.now(CHINA).isoformat()}
    except (URLError,HTTPError,ValueError,KeyError,TypeError,TimeoutError):
        return None,{'configured':True,'status':'sync_failed','message':'Google 同步失败。请检查只读授权及网络；上次缓存不会冒充本次同步结果。'}
