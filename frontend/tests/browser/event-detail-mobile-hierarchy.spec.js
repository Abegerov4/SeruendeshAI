import {test, expect} from '@playwright/test';

const posterSizes = {portrait:[900,1600],square:[900,900],landscape:[1600,900]};
const event = {
  id:'mobile-poster', title:'Вечер музыки в Астане',
  description:'Концерт артистов и приглашённых музыкантов.',
  venue:'Городской концертный зал', address:'проспект Республики, 32',
  start:'2026-10-24T19:00:00+05:00', end:null, sessions:[],
  price_from:4000,currency:'KZT',category:'music',category_label:'Музыка',
  announced_at:'2026-10-19T09:00:00+05:00',first_seen_at:'2026-10-20T09:00:00+05:00',
  sources:[{name:'ticketon',url:'https://ticketon.kz/event/concert'}],is_archived:false,
};

for (const width of [320,390,430]) {
  test(`event essentials precede complete posters at ${width}px`, async({page}, testInfo) => {
    const state = {...event};
    await page.setViewportSize({width,height:700});
    await page.addInitScript(()=>localStorage.setItem('seruendesh.language','ru'));
    await page.route('**/api/**',route=>{
      const path=new URL(route.request().url()).pathname;
      if(path.startsWith('/api/events/')) return route.fulfill({json:state});
      return route.fulfill({json:path === '/api/auth/me' ? {user:null} : {}});
    });
    await page.route('https://mobile-posters.test/**',route=>{
      const format=new URL(route.request().url()).pathname.slice(1).replace('.svg','');
      const [w,h]=posterSizes[format];
      return route.fulfill({contentType:'image/svg+xml',body:`<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><rect width="${w}" height="${h}" fill="#dce9d6"/><rect x="10" y="10" width="${w-20}" height="${h-20}" fill="none" stroke="#123f31" stroke-width="20"/><text x="50%" y="50%" text-anchor="middle" fill="#123f31" font-size="70">${format}</text></svg>`});
    });
    for (const format of Object.keys(posterSizes)) {
      state.image_url=`https://mobile-posters.test/${format}.svg`;
      await page.goto('/events/mobile-poster');
      const cover=page.locator('.events-detail-cover'),image=cover.locator('img');
      await expect(cover).toHaveAttribute('data-orientation',format);
      await expect(image).toHaveCSS('object-fit','contain');
      await expect(page.locator('.events-detail-content h1')).toHaveText(event.title);
      await expect(page.locator('.events-detail-place')).toContainText(event.venue);
      await expect(page.locator('.events-detail-timing')).toContainText('24 октября');
      await expect(page.locator('.events-detail-price')).toContainText('4');
      const summary=await page.locator('.events-detail-content').boundingBox();
      const poster=await cover.boundingBox();
      const action=await page.locator('.events-detail-action').boundingBox();
      const navigation=await page.locator('.mobile-app-nav').boundingBox();
      expect(summary.y+summary.height).toBeLessThan(poster.y);
      expect(action.y+action.height).toBeLessThanOrEqual(navigation.y);
      expect(poster.height).toBeLessThanOrEqual(page.viewportSize().height/2);
      const [w,h]=posterSizes[format];
      expect(poster.width/poster.height).toBeCloseTo(w/h,2);
      expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
      await page.screenshot({path:testInfo.outputPath(`${format}-${width}.png`)});
      await cover.evaluate(element=>element.scrollIntoView({block:'center',behavior:'instant'}));
      await cover.screenshot({path:testInfo.outputPath(`${format}-${width}-complete.png`)});
    }
  });
}
