"""Independent, bounded source review of the audit's matched candidates.

Uses fetched public bytes with checked hashes; no network or canonical mutation.
Directory IDs/addresses/coordinates and visible page text corroborate identities.
"""
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

HERE = Path(__file__).parent
ROOT = HERE.parents[2]
INPUT = ROOT/'eval/runs/2026-10-19-catalog-refresh/source-audit/candidates.jsonl'
CHECKPOINT = INPUT.with_name('audit-review-checkpoint-67.jsonl')
CHECKPOINT_SHA256 = 'b4b07ee065f7868fdf3cebdfbf66a2e8a4af36ca999b3e2693132ae03afd24e7'
DAY = '2026-10-19'
rows = {r['id']:r for r in json.loads((ROOT/'data/processed/pois.json').read_text())}
all_candidates = [json.loads(line) for line in INPUT.read_text().splitlines()]
checkpoint_raw=CHECKPOINT.read_bytes()
if hashlib.sha256(checkpoint_raw).hexdigest()!=CHECKPOINT_SHA256:
    raise ValueError('Immutable review checkpoint hash mismatch')
candidates = [json.loads(line) for line in checkpoint_raw.splitlines()]
approved, decisions = [], []


def normalized(value):
    return re.sub(r'\s+', ' ', str(value).replace('\u200b','')).strip().casefold()


def hours(schedule):
    """Convert the provider's explicit seven-day seconds, without mixing channels."""
    aliases = dict(zip(['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'],
                       ['Mo','Tu','We','Th','Fr','Sa','Su']))
    if not isinstance(schedule,list) or len(schedule)!=7:
        return None
    result=[]
    for item in schedule:
        if item.get('DayAlias') not in aliases:
            return None
        start,end=item.get('WorkingTimeStart'),item.get('WorkingTimeEnd')
        if not all(isinstance(v,int) and 0<=v<=86400 for v in (start,end)):
            return None
        start_text=f'{start//3600:02d}:{start%3600//60:02d}'
        end_text='24:00' if end==0 and start>0 else f'{end//3600:02d}:{end%3600//60:02d}'
        result.append(f'{aliases[item["DayAlias"]]} {start_text}-{end_text}')
    return '; '.join(result)


for candidate in candidates:
    ident=candidate['canonical_id'];row=rows[ident];si=candidate['source_identity']
    raw=(ROOT/candidate['raw_cache']).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=candidate['raw_sha256']:
        raise ValueError('Raw source hash mismatch: '+ident)
    fetched=datetime.fromisoformat(candidate['fetched_at']).astimezone(ZoneInfo('Asia/Almaty')).date().isoformat()
    if fetched>DAY:
        raise ValueError('Future source capture')
    soup=BeautifulSoup(raw,'html.parser')
    for tag in soup(['script','style','noscript']):tag.decompose()
    visible=normalized(soup.get_text(' ',strip=True))
    decision={'candidate_id':candidate['candidate_id'],'canonical_id':ident,
              'source_url':candidate['source_url'],'raw_cache':candidate['raw_cache'],
              'raw_sha256':candidate['raw_sha256'],'checked_at':DAY,
              'accepted_fields':[],'withheld_fields':[]}
    if ident in {'osm:node/11764970669','osm:node/14002297974'}:
        decision.update(status='held',reason=('Canonical address is street-only; source house65 has no corroborating canonical house/geo'
           if ident=='osm:node/11764970669' else 'Visible brand/phone but branch address/hours occur only in JSON-LD; no independent location corroboration'))
        decisions.append(decision);continue
    identity={'canonical_name':row['name'],'canonical_address':row.get('address'),
              'source_name':si['name'].strip(),'source_address':si['address'].strip(),
              'source_url':candidate['source_url'],'branch_confirmed':True,'match_basis':'name_address'}
    # Explicitly reviewed punctuation/transliteration: canonical Amman Ulitsa 2,
    # source JSON-LD ул. Амман 2, visible merchant branch card Амман, д. 2.
    if ident=='overture:ccebc14a-ed0b-40f6-a13c-82d68292fabc':
        if ('oldboy barbershop' not in visible or 'астана, ул. амман, д. 2' not in visible
            or row.get('address')!='Amman Ulitsa 2'):
            raise ValueError('Oldboy independently visible branch changed')
        si={**si,'address':'Астана, ул. Амман, д. 2'}
        identity['source_address']=si['address']
    if si.get('lat') is not None and si.get('lon') is not None:
        identity.update(match_basis='name_coordinates',canonical_lat=row['lat'],canonical_lon=row['lon'],
                        source_lat=si['lat'],source_lon=si['lon'])
    rec={'canonical_id':ident,'identity':identity,'facts':[],'menu_items':[],'prices':[]}
    def evidence(excerpt,**more):
        return {'status':'accepted','conflict_status':'none','branch_scope':'exact',
                'branch_confirmation':{k:identity[k] for k in ['source_name','source_address']},
                'valid_from':None,'valid_to':None,
                'source':{'url':candidate['source_url'],'excerpt':excerpt,'checked_at':DAY,
                          'fetched_at':candidate['fetched_at'],'raw_cache':candidate['raw_cache'],
                          'response_sha256':candidate['raw_sha256'],'review_method':'independent raw-source identity and field review',**more}}
    def add(field,value,excerpt,**more):
        rec['facts'].append({'field':field,'value':value,**evidence(excerpt,**more)})
        decision['accepted_fields'].append(field)
    if ident.startswith('dodo:'):
        unit_id=int(ident.split(':')[1]);unit=next(u for u in json.loads(raw) if u.get('Id')==unit_id)
        if (normalized(unit['Alias'])!=normalized(row['name']) or normalized(unit['Address'])!=normalized(row['address'])
            or unit['Location']['Latitude']!=row['lat'] or unit['Location']['Longitude']!=row['lon']
            or unit.get('IsTemporarilyClosed') is not False or unit.get('State')!=1
            or str(unit.get('BeginDateWork',''))>DAY):
            raise ValueError('Dodo source identity/validity changed: '+ident)
        add('address',unit['Address'],f'Id {unit_id}; Alias {unit["Alias"]}; Address {unit["Address"]}')
        if unit.get('StationaryEnabled') is True and hours(unit.get('RestaurantWeekWorkingTime')):
            value=hours(unit['RestaurantWeekWorkingTime'])
            add('opening_hours',value,'RestaurantWeekWorkingTime; '+value,channel='onsite',source_field='RestaurantWeekWorkingTime')
        if hours(unit.get('DeliveryWeekWorkingTime')):
            value=hours(unit['DeliveryWeekWorkingTime'])
            add('delivery_hours',value,'DeliveryWeekWorkingTime; '+value,channel='delivery',source_field='DeliveryWeekWorkingTime')
        if isinstance(unit.get('DeliveryEnabled'),bool):
            add('delivery',unit['DeliveryEnabled'],f'DeliveryEnabled: {unit["DeliveryEnabled"]}',source_field='DeliveryEnabled')
        if unit.get('FormatName'):
            add('format',unit['FormatName'],'FormatName: '+unit['FormatName'],source_field='FormatName')
        if 'Pickup' in unit.get('OrderTypes',[]):
            add('takeaway',True,'OrderTypes includes Pickup',source_field='OrderTypes')
        decision['withheld_fields'].append({'field':'website','reason':'Parser supplied generic chain homepage; absent from raw per-unit fields'})
    elif ident.startswith('marwin:'):
        code=ident.split(':')[1];text=raw.decode();decoder=json.JSONDecoder();shop=None
        for match in re.finditer(r'\{"name":',text):
            try:obj,_=decoder.raw_decode(text[match.start():])
            except ValueError:continue
            if obj.get('code')==code:shop=obj;break
        if (not shop or normalized(shop['name'])!=normalized(row['name'])
            or normalized(shop['address'])!=normalized(row['address'])
            or shop['location']['lat']!=row['lat'] or shop['location']['lng']!=row['lon']):
            raise ValueError('Marwin source identity changed: '+ident)
        add('address',shop['address'].strip(),f'code {code}; {shop["name"].strip()}; {shop["address"].strip()}')
        schedule=shop.get('schedule','')
        if 'без перерывов и выходных' in schedule and re.search(r'10:00.*22:00',schedule):
            add('opening_hours','Mo-Su 10:00-22:00',schedule,channel='onsite',source_field='schedule')
        else:
            decision['withheld_fields'].append({'field':'opening_hours','reason':'Source gives10:00-22:00 without explicit weekdays'})
        phone=next((p for p in shop.get('phoneNumbers',[]) if 'WhatsApp' in p),None)
        if phone:
            add('phone',phone.replace('WhatsApp','').strip(),f'code {code}; phoneNumbers: {phone}',
                contact_channel='whatsapp',contact_scope='shared official WhatsApp explicitly listed in each exact store object')
    else:
        if normalized(si['name']) not in visible or normalized(si['address']) not in visible:
            raise ValueError('Visible independent branch identity missing: '+ident)
        add('address',si['address'],si['name']+'; '+si['address'])
        if ident=='citypass:119':
            if '8 777 555 75 75' not in visible:raise ValueError('RedBus contact missing')
            add('phone','8 777 555 75 75','Время экскурсии просим заранее уточнять по номеру:8 777 555 75 75',contact_scope='tour operator')
        elif ident=='citypass:120':
            if 'каждый день 10:00 - 18:00' not in visible:raise ValueError('Museum hours missing')
            add('opening_hours','Mo-Su 10:00-18:00','Каждый день 10:00 - 18:00',channel='onsite')
        elif ident=='citypass:65':
            decision['withheld_fields'].append({'field':'opening_hours','reason':'10:00-22:00 visible,but no weekday scope'})
            decision['withheld_fields'].append({'field':'price','reason':'3000.00 withoutCityPass visible,but no explicit currency/unit in extracted card'})
        elif ident=='overture:b7cb3aaa-65ae-4b9a-97fe-521c5d7ae482':
            if 'monday 10:00-22:00 tuesday 10:00-22:00' not in visible:raise ValueError('Terranova visible hours missing')
            add('opening_hours','Mo-Su 10:00-22:00','Monday 10:00-22:00 Tuesday 10:00-22:00 Wednesday 10:00-22:00 Thursday 10:00-22:00 Friday 10:00-22:00 Saturday 10:00-22:00 Sunday 10:00-22:00',channel='onsite')
        else:
            phone=candidate['facts'].get('phone')
            digits=re.sub(r'\D','',phone or '')
            if phone and digits in re.sub(r'\D','',visible):
                add('phone',phone,'Telephone: '+phone,source_field='telephone')
            if 'price_range' in candidate['facts']:
                decision['withheld_fields'].append({'field':'price_range','reason':'Unstructured priceRange is not a typed branch price with known unit/channel'})
            if ident=='sxodim:52966':
                # Literal schedule reviewed from the visible address/contact card.
                if not re.search(r'пн-чт, вс: с 15:00 до 02:00; пт-сб: с 15:00 до 04:00',visible):
                    raise ValueError('22BAR weekly hours missing')
                add('opening_hours','Mo-Th 15:00-02:00; Fr-Sa 15:00-04:00; Su 15:00-02:00',
                    'Пн-Чт, Вс: с 15:00 до 02:00; Пт-Сб: с 15:00 до 04:00',channel='onsite')
            if 'rating' in candidate['facts']:
                decision['withheld_fields'].append({'field':'rating','reason':'One-review aggregate not imported into the rich-place contract'})
        # These are hand-reviewed literal statements from each exact visible
        # branch card. A schedule with no weekdays is intentionally not promoted.
        reviewed_hours={
            'citypass:121':('Tu-Su 09:00-18:00','Вторник-Воскресенье 09:00-18:00'),
            'citypass:122':('Mo-Su 11:00-21:00','Ежедневно 11:00 - 21:00'),
            'citypass:157':('Tu-Su 10:00-19:00','График работы: вторник–воскресенье, 10:00–19:00'),
            'citypass:63':('Mo-Su 10:00-20:00','Ежедневно 10:00-20:00'),
            'citypass:88':('Tu-Sa 10:00-18:00','Вторник - Суббота 10:00 - 18:00'),
            'citypass:89':('Tu-Su 09:00-18:00','Вторник - Восресенье 09:00 - 18:00'),
            'citypass:97':('Mo-Fr 10:00-17:30','Понедельник - Пятница 10:00–17:30'),
            'citypass:98':('Tu-Su 10:00-18:00; Mo off','Вторник - Воскресенье, Понедельник( выходной) 10:00–18:00'),
            'overture:ccebc14a-ed0b-40f6-a13c-82d68292fabc':('Mo-Su 10:00-21:00','ПН-ВС | 10:00 - 21:00'),
            'overture:829a5935-9243-49dd-86a2-6c026a09345c':('Mo-Fr 10:00-19:00; Sa 11:00-15:00; Su off','Пн–Пт 10:00–19:00, Сб 11:00–15:00, Вс — выходной'),
            'sxodim:18722':('Mo-Th 11:00-02:00; Fr-Sa 11:00-04:00; Su 11:00-02:00','11:00–02:00 (пн-чт, вс); 11:00–04:00 (пт-сб)'),
            'sxodim:18727':('Mo-Su 09:00-24:00','с 09:00 до 24:00 (ежедневно)'),
            'sxodim:28348':('Mo-Su 07:00-23:00','Ежедневно с 07:00 до 23:00'),
            'sxodim:42538':('Mo-Fr 09:00-18:00','с 09:00 до 18:00 (пн-пт)'),
            'sxodim:46068':('Mo-Su 18:00-02:00','Ежедневно c 18:00 до 02:00'),
        }
        if ident in reviewed_hours:
            value,excerpt=reviewed_hours[ident]
            if normalized(excerpt) not in visible:raise ValueError('Reviewed literal hours absent: '+ident)
            add('opening_hours',value,excerpt,channel='onsite')
        reviewed_facts={
            'citypass:142':[
                ('activities','Экскурсии: вторник–воскресенье, 11:00; 15:00','Ежедневно. Кроме понедельника. 11:00; 15:00'),
                ('group_policy','Экскурсия от 5 человек','Экскурсия проводиться от 5 человек.'),
                ('phone','+7 7172 709 612; +7 7172 709 600 (касса)','Контакты: +7 7172 709 612, +7 7172 709 600(номер кассы)')],
            'citypass:157':[
                ('phone','+7 702 0000 934','Телефон: +7 702 0000 934'),
                ('website','https://railwaymuseum.kz','Сайт: railwaymuseum.kz')],
            'citypass:97':[
                ('booking_policy','Посещение только по предварительной записи','Посещение возможно только по предварительной записи'),
                ('phone','+7 (7172) 70-83-65; +77022586608','+7 (7172) 70-83-65, + 77022586608')],
            'overture:9cc33bec-640e-4e28-bd2c-f796d7524c75':[
                ('wifi',True,'бесплатный Wi-Fi на всей территории'),
                ('luggage_storage',True,'камера хранения багажа'),
                ('parking',True,'охраняемая парковка')],
        }
        for field,value,excerpt in reviewed_facts.get(ident,[]):
            if normalized(excerpt) not in visible:raise ValueError('Reviewed literal field absent: '+ident+' '+field)
            add(field,value,excerpt)
        if ident=='sxodim:18728':
            decision['withheld_fields'].append({'field':'opening_hours','reason':'Source separately describes restaurant floor1 and cafe floor2; canonical record does not identify floor'})
        if ident=='citypass:81':
            decision['withheld_fields'].append({'field':'opening_hours','reason':'Source hours describe Singularity Museum within Alem.AI, whereas canonical name identifies the entire center'})
    decision.update(status='approved',approved_fact_count=len(rec['facts']),
                    reason='Exact public source record or visible name+address corroborated; source hash checked')
    approved.append(rec);decisions.append(decision)

payload={'schema_version':1,'as_of':DAY,'canonical_sha256':hashlib.sha256((ROOT/'data/processed/pois.json').read_bytes()).hexdigest(),
         'records':approved}
(HERE/'places-audit-approved.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
(HERE/'places-audit-matched-candidates.json').write_text(json.dumps(decisions,ensure_ascii=False,indent=2)+'\n')
summary={'as_of':DAY,'input_total_candidates':len(all_candidates),'identity_matched_reviewed':len(candidates),
         'review_checkpoint':str(CHECKPOINT.relative_to(ROOT)),'review_checkpoint_sha256':CHECKPOINT_SHA256,
         'unmatched_ineligible_candidates':len(all_candidates)-len(candidates),
         'approved_branches':len(approved),'approved_facts':sum(len(r['facts'])for r in approved),
         'held_matched_branches':len(decisions)-len(approved),
         'approved_fields':dict(Counter(f['field']for r in approved for f in r['facts'])),
         'all_reviewed_raw_hashes_verified':True,'changes_to_canonical_master':False,'decisions':decisions}
(HERE/'places-audit-review-report.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print({k:v for k,v in summary.items()if k!='decisions'})
