import {test, expect} from '@playwright/test';

// Deliberately isolated API fixtures: these titles never enter the production feed.
const event = {
  id:'sxodim:fixture-1', title:'Проверка календаря', description:'Описание события из тестового API.',
  venue:'Тестовый зал', address:'Тестовый адрес', start:'2026-02-21T19:00:00+05:00',end:'2026-10-31T21:00:00+05:00',
  sessions:['2026-10-24T19:00:00+05:00','2026-10-26T19:00:00+05:00','2026-10-31T19:00:00+05:00'],price_from:4000,currency:'KZT',category:'music',category_label:'Музыка',image_url:null,
  announced_at:'2026-10-20T09:00:00+05:00',first_seen_at:'2026-10-20T09:00:00+05:00',
  sources:[{name:'sxodim',url:'https://sxodim.com/astana/event/test'},{name:'ticketon',url:'https://ticketon.kz/event/test'}],is_archived:false,
};
async function api(page, options = {}) {
  const state = {queries:[],fail:false,total:1,...options};
  await page.addInitScript(() => {localStorage.setItem('seruendesh.language','ru');});
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url()), path=url.pathname;
    if(path === '/api/events') {
      state.queries.push(Object.fromEntries(url.searchParams));
      if(state.fail) return route.fulfill({status:503,json:{detail:'test unavailable'}});
      const offset=Number(url.searchParams.get('offset') || 0), archived=url.searchParams.get('view') === 'archive';
      return route.fulfill({json:{items:[{...event,id:offset ? 'fixture-2' : event.id,title:offset ? 'Следующее тестовое событие' : event.title,is_archived:archived}],total:state.total,offset,limit:1,today:'2026-10-20',categories:[{value:'music',label:'Музыка'},{value:'art',label:'Искусство'}],months:['2026-09','2026-08'],updated_at:'2026-10-20T09:00:00+05:00'}});
    }
    if(path.startsWith('/api/events/')) return route.fulfill({json:{...event,is_archived:state.archived || false}});
    return route.fulfill({json:path === '/api/auth/me' ? {user:null} : {}});
  });
  return state;
}
const day = (page,value) => page.locator(`.events-calendar-grid button[data-day="${value}"]`);

test('visible calendar supports single days, inclusive ranges, keyboard navigation and cancellation',async({page})=>{
  const state=await api(page);await page.goto('/events');
  await expect(page.locator('.events-card')).toHaveCount(1);
  await expect(page.locator('.events-event-date')).toContainText('24 октября');
  const trigger=page.getByRole('button',{name:'Выбрать даты',exact:true});await trigger.click();
  const dialog=page.getByRole('dialog',{name:'Дата или диапазон'});await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('grid')).toBeVisible();await expect(dialog.getByRole('gridcell')).toHaveCount(42);
  await day(page,'2026-10-22').click();await expect(dialog.locator('.events-date-preview')).toContainText('22 октября');
  await dialog.getByRole('button',{name:'Применить',exact:true}).click();
  await expect.poll(()=>state.queries.at(-1)?.date_from).toBe('2026-10-22');expect(state.queries.at(-1).date_to).toBe('2026-10-22');
  await expect(page.getByRole('button',{name:'22 октября',exact:true})).toBeFocused();
  await page.getByRole('button',{name:'22 октября',exact:true}).click();
  await dialog.getByRole('button',{name:'Диапазон',exact:true}).click();
  await day(page,'2026-10-24').click();await day(page,'2026-10-26').click();
  await expect(dialog.getByRole('gridcell',{selected:true})).toHaveCount(3);
  await expect(dialog.locator('.events-date-preview')).toContainText('24 октября – 26 октября');
  await dialog.getByRole('button',{name:'Применить',exact:true}).click();
  await expect.poll(()=>state.queries.at(-1)?.date_to).toBe('2026-10-26');
  await page.locator('.events-custom-dates .events-quick-button').click();
  await day(page,'2026-10-24').focus();await page.keyboard.press('PageDown');
  await expect(day(page,'2026-11-24')).toBeFocused();
  await page.keyboard.press('ArrowRight');await expect(day(page,'2026-11-25')).toBeFocused();
  await page.keyboard.press('Escape');await expect(dialog).toHaveCount(0);
  expect(state.queries.at(-1).date_from).toBe('2026-10-24');
});

test('detailed filter drafts apply once and reset together',async({page})=>{
  const state=await api(page);await page.goto('/events');await expect(page.locator('.events-card')).toHaveCount(1);
  await page.getByRole('button',{name:'Фильтры',exact:true}).click();const dialog=page.getByRole('dialog',{name:'Фильтры'});
  await dialog.getByRole('combobox',{name:'Категория',exact:true}).selectOption('music');
  await dialog.getByRole('combobox',{name:'Стоимость',exact:true}).selectOption('free');await dialog.getByRole('combobox',{name:'Источник',exact:true}).selectOption('sxodim');
  expect(state.queries).toHaveLength(1);
  await dialog.getByRole('button',{name:'Применить',exact:true}).click();
  await expect.poll(()=>state.queries.at(-1)?.source).toBe('sxodim');
  expect(state.queries.at(-1)).toMatchObject({price:'free',category:'music'});
  await page.locator('.events-filters-trigger').click();
  await dialog.getByRole('button',{name:'Сбросить',exact:true}).click();
  await dialog.getByRole('button',{name:'Применить',exact:true}).click();
  await expect.poll(()=>state.queries.length).toBe(3);
  expect(state.queries.at(-1)).not.toHaveProperty('category');expect(state.queries.at(-1)).not.toHaveProperty('source');
});

test('archive filters are independent and detail links survive direct navigation',async({page})=>{
  const state=await api(page);await page.goto('/events');await expect(page.locator('.events-card')).toHaveCount(1);
  await page.getByRole('button',{name:'Сегодня',exact:true}).click();await expect.poll(()=>state.queries.at(-1)?.date_from).toBe('2026-10-20');
  await page.locator('.events-tabs').getByRole('link',{name:'Архив',exact:true}).click();
  await expect.poll(()=>state.queries.at(-1)?.view).toBe('archive');
  await page.getByLabel('Месяц',{exact:true}).selectOption('2026-09');await page.getByLabel('Категория',{exact:true}).selectOption('music');
  await page.getByRole('searchbox',{name:'Поиск в архиве'}).fill('концерт');await expect.poll(()=>state.queries.at(-1)?.q).toBe('концерт');
  expect(state.queries.at(-1)).toMatchObject({month:'2026-09',category:'music'});expect(state.queries.at(-1)).not.toHaveProperty('date_from');
  await page.locator('.events-tabs').getByRole('link',{name:'События',exact:true}).click();await expect(page.getByRole('button',{name:'Сегодня',exact:true})).toHaveAttribute('aria-pressed','true');
  await page.goto('/events/sxodim%3Afixture-1');await expect(page.getByRole('heading',{name:event.title,exact:true})).toBeVisible();
  const links=page.locator('.events-original-sources a');await expect(links).toHaveCount(2);
  await expect(links.first()).toHaveAttribute('rel','noopener noreferrer');await expect(links.first()).toHaveAttribute('target','_blank');
  await expect(page.locator('.events-detail-cover .events-category-cover')).toBeVisible();
});

test('failed requests retry, pagination appends and mobile calendar stays inside the viewport',async({page})=>{
  const state=await api(page,{fail:true,total:2});await page.goto('/events');
  await expect(page.getByRole('heading',{name:'Не удалось загрузить события'})).toBeVisible();
  state.fail=false;await page.getByRole('button',{name:'Повторить',exact:true}).click();await expect(page.locator('.events-card')).toHaveCount(1);
  await page.getByRole('button',{name:'Показать ещё',exact:true}).click();await expect(page.locator('.events-card')).toHaveCount(2);expect(state.queries.at(-1).offset).toBe('1');
  await page.screenshot({path:'/tmp/events-front-desktop.png',fullPage:true});
  await page.setViewportSize({width:320,height:780});await page.getByRole('button',{name:'Выбрать даты',exact:true}).click();
  await expect(page.getByRole('dialog')).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const box=await page.getByRole('dialog').boundingBox();expect(box.x).toBeGreaterThanOrEqual(0);expect(box.x+box.width).toBeLessThanOrEqual(320);
  await page.getByRole('button',{name:'Следующий месяц',exact:true}).click();await day(page,'2026-11-10').click();
  await page.screenshot({path:'/tmp/events-front-mobile-calendar.png',fullPage:true});
  await page.getByRole('button',{name:'Отмена',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0);
});


test('a slow previous search cannot replace a newer response',async({page})=>{
  await api(page);let release, started=false;const gate=new Promise(resolve=>{release=resolve});
  await page.route('**/api/events?**',async route=>{
    const q=new URL(route.request().url()).searchParams.get('q');
    if(q !== 'slow') return route.fallback();
    started=true;await gate;await route.fulfill({json:{items:[{...event,title:'Устаревший ответ'}],total:1,today:'2026-10-20',categories:[],months:[]}}).catch(()=>{});
  });
  await page.goto('/events');await expect(page.locator('.events-card')).toHaveCount(1);
  await page.getByRole('searchbox',{name:'Поиск событий'}).fill('slow');await expect.poll(()=>started).toBe(true);
  await page.getByRole('searchbox',{name:'Поиск событий'}).fill('latest');await expect(page.getByRole('heading',{name:event.title,exact:true})).toBeVisible();
  release();await expect(page.getByRole('heading',{name:'Устаревший ответ',exact:true})).toHaveCount(0);
});


test('continuous multi-day cards show both dates and duplicate-only pages advance the server cursor',async({page})=>{
  const state=await api(page);const offsets=[];
  await page.route('**/api/events?**',async route=>{
    const offset=Number(new URL(route.request().url()).searchParams.get('offset') || 0);offsets.push(offset);
    const first=offset === 40 ? 40 : 0;
    const items=Array.from({length:20},(_,index)=>({...event,id:`continuous-${first+index}`,title:`Непрерывное событие ${first+index}`,start:'2026-11-02T10:00:00+05:00',end:'2026-11-04T20:00:00+05:00',schedule_kind:'continuous',sessions:['2026-11-02T10:00:00+05:00']}));
    await route.fulfill({json:{items,total:60,offset,limit:20,today:'2026-10-20',categories:[],months:[]}});
  });
  await page.goto('/events');await expect(page.locator('.events-card')).toHaveCount(20);
  await expect(page.locator('.events-event-date').first()).toContainText('2 ноября');await expect(page.locator('.events-event-date').first()).toContainText('4 ноября');
  await page.getByRole('button',{name:'Показать ещё',exact:true}).click();await expect.poll(()=>offsets.at(-1)).toBe(20);
  await expect(page.getByRole('button',{name:'Показать ещё',exact:true})).toBeEnabled();await expect(page.locator('.events-card')).toHaveCount(20);
  await page.getByRole('button',{name:'Показать ещё',exact:true}).click();await expect(page.locator('.events-card')).toHaveCount(40);
  expect(offsets).toEqual([0,20,40]);await expect(page.getByRole('button',{name:'Показать ещё',exact:true})).toHaveCount(0);
});
