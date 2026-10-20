import {test,expect} from '@playwright/test';

const event={id:'tour',title:'Обзорная экскурсия по городу «Любимая Астана»',description:'Полное описание экскурсии, которое должно открываться внутри события.',start:'2026-09-27',end:'2026-10-25',sessions:['2026-09-27'],schedule_kind:'continuous',venue:'Место сбора: пр. Кабанбай батыра',address:'Астана',price_from:9000,currency:'KZT',category:'entertainment',category_label:'Развлечения',image_url:null,sources:[{name:'sxodim',url:'https://sxodim.com/astana/event/tour'}],announced_at:'2024-06-05T15:12:00+05:00',first_seen_at:'2026-10-20T16:07:00+05:00',is_archived:false};
async function mock(page){
 await page.addInitScript(()=>localStorage.setItem('seruendesh.language','ru'));
 await page.route('**/api/**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path==='/api/events')return route.fulfill({json:{items:[event],total:1,offset:0,limit:20,today:'2026-10-20',categories:[],months:[]}});
  if(path==='/api/events/tour')return route.fulfill({json:event});
  return route.fulfill({json:path==='/api/auth/me'?{user:null}:{}});
 });
}

test('compact feed separates discovery from publication and keeps price beside its action',async({page})=>{
 await mock(page);
 for(const width of [1440,768,390,320]){
  await page.setViewportSize({width,height:960});await page.goto('/events');
  const card=page.locator('.events-card');await expect(card).toBeVisible();
  await expect(card.getByText(event.description)).toHaveCount(0);
  await expect(card.getByText('Новый анонс',{exact:true})).toHaveCount(0);
  await expect(card.getByText('Новое в ленте',{exact:true})).toBeVisible();
  await expect(card.locator('.events-event-date')).toHaveText('До 25 октября');
  await expect(card.getByText('20 октября в 16:07')).toHaveCount(0);
  const cover=await card.locator('.events-cover').boundingBox();expect(cover.width/cover.height).toBeCloseTo(1,2);
  const footer=card.locator('.events-card-bottom');await expect(footer.locator('.events-price')).toHaveText('от 9\u00a0000 ₸');
  await expect(footer.getByRole('link',{name:/Подробнее/})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:`/tmp/events-compact-${width}.png`,fullPage:true});
 }
 await page.locator('.events-card-bottom a').click();
 await expect(page.locator('.events-detail-description')).toHaveText(event.description);
});
