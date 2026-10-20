import {test, expect} from '@playwright/test';

const description = 'Полное описание культурного события.\n\n' + 'На сцене выступят артисты и приглашённые музыканты. '.repeat(24) + '\nПоследний абзац с важными условиями посещения.';
const fixture = {
  id:'detail-poster', title:'Вечер музыки в Астане', description,
  venue:'Городской концертный зал', address:'проспект Республики, 32',
  start:'2026-10-24T19:00:00+05:00', end:'2026-10-31T21:00:00+05:00',
  sessions:['2026-10-24T19:00:00+05:00','2026-10-26T19:30:00+05:00','2026-10-31T19:00:00+05:00'],
  price_from:4000,currency:'KZT',category:'music',category_label:'Музыка',
  image_url:'https://event-detail-images.test/portrait.svg',
  announced_at:'2026-10-19T09:00:00+05:00',first_seen_at:'2026-10-20T09:00:00+05:00',
  sources:[{name:'sxodim',url:'https://sxodim.com/astana/event/concert'},{name:'ticketon',url:'https://ticketon.kz/event/concert'}],
  is_archived:false,
};
const dimensions = {landscape:[1600,900],portrait:[900,1600],square:[900,900],wide:[2000,400]};

async function api(page, changes = {}) {
  const state={event:{...fixture,...changes},status:200};
  await page.addInitScript(()=>localStorage.setItem('seruendesh.language','ru'));
  await page.route('https://event-detail-images.test/**',async route=>{
    const name=new URL(route.request().url()).pathname.slice(1).replace('.svg','');
    if(!dimensions[name]) return route.fulfill({status:404,body:'missing poster'});
    const [width,height]=dimensions[name];
    await route.fulfill({contentType:'image/svg+xml',body:`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><rect width="${width}" height="${height}" fill="#dce9d6"/><rect x="10" y="10" width="${width-20}" height="${height-20}" fill="none" stroke="#123f31" stroke-width="20"/><text x="50%" y="50%" text-anchor="middle" fill="#123f31" font-size="70">${name}</text></svg>`});
  });
  await page.route('**/api/**',route=>{
    const path=new URL(route.request().url()).pathname;
    if(path.startsWith('/api/events/')) return route.fulfill({status:state.status,json:state.status === 200 ? state.event : {detail:'Unavailable'}});
    if(path === '/api/events') return route.fulfill({json:{items:[state.event],total:1,offset:0,limit:20,today:'2026-10-20',categories:[],months:[]}});
    return route.fulfill({json:path === '/api/auth/me' ? {user:null} : {}});
  });
  return state;
}
async function open(page, state, format, width) {
  state.event.image_url=`https://event-detail-images.test/${format}.svg`;
  await page.setViewportSize({width,height:1000});
  await page.goto('/events/detail-poster');
  const image=page.locator('.events-detail-cover>img');
  await expect(image).toBeVisible();
  await expect.poll(()=>image.evaluate(img=>img.complete && img.naturalWidth>0)).toBe(true);
  await expect(image).toHaveCSS('object-fit','contain');
  const layout=await page.locator('.events-detail-layout').boundingBox();
  const back=await page.locator('.events-back').boundingBox();
  expect(Math.abs(back.x-layout.x)).toBeLessThan(1);
  return {image,frame:await page.locator('.events-detail-cover').boundingBox(),summary:await page.locator('.events-detail-content').boundingBox(),layout};
}

test('portrait posters sit left of the event summary on desktop and above it on smaller screens',async({page})=>{
  const state=await api(page);
  for(const width of [1440,1024,899,768,390,320]){
    const {frame,summary,layout}=await open(page,state,'portrait',width);
    expect(frame.width/frame.height).toBeCloseTo(9/16,2);
    expect(frame.width).toBeLessThanOrEqual(300);
    if(width>=900){
      expect(frame.width).toBeGreaterThanOrEqual(260);
      expect(frame.x+frame.width).toBeLessThan(summary.x);
      expect(Math.abs(frame.y-summary.y)).toBeLessThan(8);
    }else{
      expect(frame.y+frame.height).toBeLessThan(summary.y);
      expect(Math.abs(frame.x+frame.width/2-layout.x-layout.width/2)).toBeLessThan(1);
    }
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  }
});

test('landscape and very wide posters stay complete in a centered 16:9 frame above the summary',async({page})=>{
  const state=await api(page);
  for(const width of [1440,768,390,320]){
    for(const format of ['landscape','wide']){
      const {frame,summary,layout}=await open(page,state,format,width);
      expect(frame.width/frame.height).toBeCloseTo(16/9,2);
      expect(frame.width).toBeLessThanOrEqual(720);
      expect(Math.abs(frame.x+frame.width/2-layout.x-layout.width/2)).toBeLessThan(1);
      expect(frame.y+frame.height).toBeLessThan(summary.y);
      expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    }
  }
});

test('square posters keep a moderate square frame above event information',async({page})=>{
  const state=await api(page);
  for(const width of [1440,768,320]){
    const {frame,summary,layout}=await open(page,state,'square',width);
    expect(frame.width/frame.height).toBeCloseTo(1,2);
    expect(frame.width).toBeLessThanOrEqual(420);
    expect(Math.abs(frame.x+frame.width/2-layout.x-layout.width/2)).toBeLessThan(1);
    expect(frame.y+frame.height).toBeLessThan(summary.y);
  }
});

test('the title leads the summary, with price beside a clear source action and complete details below',async({page})=>{
  const state=await api(page);
  await open(page,state,'portrait',1440);
  expect(await page.locator('.events-detail-content').evaluate(el=>el.firstElementChild.tagName)).toBe('H1');
  const action=page.locator('.events-detail-action');
  await expect(action).toHaveAccessibleName('Открыть в Freedom Ticketon');
  await expect(action).toHaveAttribute('href','https://ticketon.kz/event/concert');
  await expect(action).toHaveAttribute('target','_blank');
  await expect(action).toHaveAttribute('rel','noopener noreferrer');
  const price=await page.locator('.events-detail-price').boundingBox(),cta=await action.boundingBox();
  expect(Math.abs((price.y+price.height/2)-(cta.y+cta.height/2))).toBeLessThan(28);
  expect(cta.x-price.x-price.width).toBeLessThanOrEqual(30);
  await expect(page.locator('.events-detail-place')).toContainText(fixture.venue);
  await expect(page.locator('.events-detail-place')).toContainText(fixture.address);
  await expect(page.locator('.events-detail-description')).toHaveText(description);
  const hero=await page.locator('.events-detail-layout').boundingBox(),body=await page.locator('.events-detail-description').boundingBox();
  expect(body.y).toBeGreaterThan(hero.y+hero.height);
  await expect(page.locator('.events-sessions time')).toHaveCount(3);
  await expect(page.locator('.events-original-sources a')).toHaveCount(2);
  const sources=await page.locator('.events-original-sources').boundingBox(),sessions=await page.locator('.events-sessions').boundingBox();
  expect(sources.y).toBeGreaterThan(sessions.y+sessions.height);
  await expect(page.locator('.events-detail-publication time')).toHaveCount(2);
  await page.screenshot({path:'/tmp/event-detail-portrait-desktop.png',fullPage:true});
  await page.setViewportSize({width:320,height:780});
  await expect(action).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:'/tmp/event-detail-portrait-mobile.png'});
  await action.scrollIntoViewIfNeeded();
  await page.screenshot({path:'/tmp/event-detail-portrait-mobile-summary.png'});
});

test('free or unknown prices use available safe source links without speculative ticket labels',async({page})=>{
  const state=await api(page,{price_from:0,sources:[{name:'ticketon',url:'javascript:alert(1)'},{name:'sxodim',url:'https://sxodim.com/astana/event/free'}]});
  await page.goto('/events/detail-poster');
  await expect(page.locator('.events-detail-price')).toHaveText('Вход свободный');
  await expect(page.locator('.events-detail-action')).toHaveAccessibleName('Открыть в Sxodim');
  await expect(page.locator('.events-detail-action')).toHaveAttribute('href','https://sxodim.com/astana/event/free');
  await expect(page.locator('.events-detail a[href^="javascript:"]')).toHaveCount(0);
  await expect(page.locator('.events-original-sources a')).toHaveCount(1);
  state.event={...state.event,price_from:null,sources:[{name:'sxodim',url:'data:text/html,invalid'}]};
  await page.reload();
  await expect(page.locator('.events-detail-price')).toHaveText('Стоимость у организатора');
  await expect(page.locator('.events-detail-action')).toHaveCount(0);
  await expect(page.locator('.events-detail-description')).toHaveText(description);
});

test('missing or failed posters stay compact and leave the event data usable',async({page})=>{
  const state=await api(page);
  for(const image of [null,'https://event-detail-images.test/broken.svg']){
    state.event.image_url=image;
    await page.goto('/events/detail-poster');
    await expect(page.locator('.events-detail-cover .events-category-cover')).toBeVisible();
    const frame=await page.locator('.events-detail-cover').boundingBox();
    expect(frame.height).toBeLessThanOrEqual(180);
    await expect(page.getByRole('heading',{level:1,name:fixture.title})).toBeVisible();
    await expect(page.locator('.events-detail-action')).toBeVisible();
  }
});

test('detail errors retry and archived events retain their archive navigation and full description',async({page})=>{
  const state=await api(page,{is_archived:true});state.status=503;
  await page.goto('/events/detail-poster');
  await expect(page.getByRole('heading',{name:'Не удалось загрузить события'})).toBeVisible();
  state.status=200;await page.getByRole('button',{name:'Повторить',exact:true}).click();
  await expect(page.getByRole('heading',{level:1,name:fixture.title})).toBeVisible();
  await expect(page.locator('.events-back')).toHaveAttribute('href','/events/archive');
  await expect(page.locator('.events-archived-label')).toHaveText('Событие завершилось');
  await expect(page.locator('.events-detail-description')).toHaveText(description);
  await expect(page.locator('.events-tabs a[href="/events/archive"]')).toHaveAttribute('aria-current','page');
  state.status=404;await page.reload();
  await expect(page.getByRole('heading',{name:'Событие не найдено'})).toBeVisible();
  await expect(page.locator('.events-detail .events-primary')).toHaveAttribute('href','/events');
});

test('first discovery is labelled as feed addition when source publication is unknown',async({page})=>{
  await api(page,{announced_at:null});
  await page.goto('/events/detail-poster');
  const metadata=page.locator('.events-detail-publication');
  await expect(metadata).toContainText('Добавлено в нашу ленту');
  await expect(metadata).not.toContainText('Опубликовано источником');
  await expect(metadata.locator('time')).toHaveCount(1);
  await expect(metadata.locator('time')).toHaveAttribute('datetime','2026-10-20T09:00:00+05:00');
});

test('source publication preserves its original year and avoids inventing a time for date-only data',async({page})=>{
  const state=await api(page,{announced_at:'2024-06-05T15:12:00+05:00'});
  await page.goto('/events/detail-poster');
  const publication=page.locator('.events-detail-publication time').first();
  await expect(publication).toContainText('2024');
  await expect(publication).toContainText('15:12');
  await expect(publication).toHaveAttribute('datetime','2024-06-05T15:12:00+05:00');
  state.event.announced_at='2024-06-05';await page.reload();
  await expect(publication).toContainText('2024');
  await expect(publication).not.toContainText(/\d{2}:\d{2}/);
  await expect(publication).toHaveAttribute('datetime','2024-06-05');
});

test('loading a different event discards a late response and its archive state',async({page})=>{
  await api(page);
  let release,started=false,finished=false;
  const gate=new Promise(resolve=>{release=resolve});
  await page.route('**/api/events/slow',async route=>{
    started=true;await gate;
    await route.fulfill({json:{...fixture,id:'slow',title:'Устаревшее событие',is_archived:true}}).catch(()=>{});
    finished=true;
  });
  await page.goto('/events/slow');
  await expect.poll(()=>started).toBe(true);
  await expect(page.locator('.events-detail [role="status"]')).toContainText('Загружаем события…');
  await page.evaluate(async()=>{const {navigate}=await import('/src/navigation.jsx');navigate('/events/detail-poster');});
  await expect(page.getByRole('heading',{level:1,name:fixture.title})).toBeVisible();
  release();await expect.poll(()=>finished).toBe(true);
  await expect(page.getByRole('heading',{name:'Устаревшее событие'})).toHaveCount(0);
  await expect(page.locator('.events-tabs a[href="/events"]')).toHaveAttribute('aria-current','page');
});
