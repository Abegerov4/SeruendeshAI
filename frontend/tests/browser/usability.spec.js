import {test, expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
const fixture = JSON.parse(readFileSync(new URL('../../../backend/docs/api/examples/walk.json', import.meta.url)));
const aPlace = {poi_id: 'saved-a', data: {name: 'Private place A', categoryKey: 'park', category: 'Парк', travel: 5, visit: 20}};
async function mockApi(page, {account=null, saved=[], failSave=false, failSearch=false}={}) {
  const state = {account, saved, failSave, failSearch, requests: [], writes: [], geo: 0};
  await page.addInitScript(() => {window.geoCalls=0; navigator.geolocation.getCurrentPosition=()=>{window.geoCalls++};});
  await page.route('**/api/**', async r => {
    const path = new URL(r.request().url()).pathname, method=r.request().method();
    let json={};
    if(path==='/api/auth/me'||path==='/api/auth/login') json=state.account?{id:state.account,name:state.account,email:state.account+'@example.com'}:{user:null};
    if(path==='/api/me/saved') json=state.saved;
    if(path.startsWith('/api/me/saved/')&&method==='PUT') {
      state.writes.push(r.request().postDataJSON());
      if(state.failSave) return r.fulfill({status:503,json:{detail:'unavailable'}});
      json={poi_id:decodeURIComponent(path.split('/').at(-1)),data:r.request().postDataJSON().data};state.saved.push(json);
    }
    if(path==='/api/meta') json={features:{photo:false}};
    if(path==='/api/recommend') {
      state.requests.push(r.request().postDataJSON());
      if(state.failSearch) return r.fulfill({status:503,json:{detail:'unavailable'}});
      json=structuredClone(fixture);json.route=null;
      json.recommendations=json.recommendations.slice(0,2);
      json.recommendations[0].travel_min=10;json.recommendations[0].visit_suggested_min=20;
      json.recommendations[1].travel_min=8;json.recommendations[1].visit_suggested_min=45;
    }
    await r.fulfill({json});
  });
  return state;
}
async function chooseStart(page) {
  await page.locator('.start-landmarks button').filter({hasText:'Mega Silk Way'}).first().click();
  await expect(page.locator('.chat-place')).toHaveCount(2);
}

test('first visit asks for a start without GPS prompt or recommendation request',async({page})=>{
 const state=await mockApi(page);await page.goto('/');
 await expect(page.locator('.start-chooser').first()).toBeVisible();
 expect(state.requests).toHaveLength(0);expect(await page.evaluate(()=>window.geoCalls)).toBe(0);
 await expect(page.getByText('Подходящих мест пока нет',{exact:true})).toHaveCount(0);
 await chooseStart(page);expect(state.requests).toHaveLength(1);expect(state.requests[0].landmark).toBe('mega_silk_way');
 await page.locator('.nearby-trigger').click();await expect(page.locator('.places-section .place-card')).toHaveCount(2);
 await page.locator('.nearby-trigger').click();await expect(page.locator('.places-section .place-card').first()).toBeHidden();
});

test('duration, transport and conditions live behind one button in the composer',async({page})=>{
 const state=await mockApi(page);await page.goto('/');await chooseStart(page);
 await expect(page.locator('.time-selector')).toHaveCount(0);
 await page.locator('.filter-trigger').click();
 await page.locator('.filter-popover button').filter({hasText:'120'}).click();
 await page.locator('.filter-popover button').filter({hasText:'С ребёнком'}).click();
 await page.getByRole('button',{name:'Найти с этими условиями',exact:true}).click();
 await expect(page.locator('.filter-popover')).toHaveCount(0);
 await expect.poll(()=>state.requests.length).toBe(2);expect(state.requests[1].time_budget_min).toBe(120);
});

test('logout and account switch cannot expose or upload the previous saved places',async({page})=>{
 const state=await mockApi(page,{account:'A',saved:[aPlace]});await page.goto('/saved');
 await expect(page.getByText('Private place A',{exact:true})).toBeVisible();
 await page.locator('.account-button').click();await page.getByRole('menuitem',{name:'Выйти',exact:true}).click();
 await expect(page.getByText('Private place A',{exact:true})).toHaveCount(0);
 state.account='B';state.saved=[];
 await page.evaluate(async()=>{const {login}=await import('/src/auth.js');await login('b@example.com','password')});
 await expect(page.locator('.account-button')).toContainText('B');
 await expect(page.getByText('Private place A',{exact:true})).toHaveCount(0);expect(state.writes).toHaveLength(0);
});

test('failed save rolls back and offers a working retry',async({page})=>{
 const state=await mockApi(page,{account:'A',failSave:true});await page.goto('/');await chooseStart(page);
 await page.locator('.reference-more').click();const save=page.locator('.detail-save');
 await save.click();await expect(page.locator('.detail-save-error')).toContainText('Изменение отменено');
 await expect(save).toHaveAttribute('aria-pressed','false');
 state.failSave=false;await page.locator('.detail-save-error').getByRole('button',{name:'Повторить',exact:true}).click();
 await expect(save).toHaveAttribute('aria-pressed','true');await expect(page.locator('.saved-feedback')).toHaveCount(0);
 await page.keyboard.press('Escape');await page.goto('/saved');
 await expect(page.locator('.place-card')).toHaveCount(1);expect(state.writes).toHaveLength(2);
});

test('a failed search can be retried without retyping',async({page})=>{
 const state=await mockApi(page,{failSearch:true});await page.goto('/');await page.locator('#chat-input').fill('кофе возле Байтерека');await page.locator('.send-button').click();
 await expect(page.getByRole('button',{name:'Повторить запрос',exact:true})).toBeVisible();
 state.failSearch=false;await page.getByRole('button',{name:'Повторить запрос',exact:true}).click();
 await expect(page.locator('.chat-place')).toHaveCount(2);expect(state.requests).toHaveLength(2);expect(state.requests[0].query).toBe(state.requests[1].query);
});

test('mobile start, composer, tabs and cards remain usable at narrow widths',async({page})=>{
 await page.setViewportSize({width:390,height:844});await mockApi(page);await page.goto('/');
 await expect(page.locator('#chat-input')).toBeVisible();await chooseStart(page);
 for(const width of [320,390,768]){
  await page.setViewportSize({width,height:844});
  for(let i=0;i<4;i++){await page.locator('.mobile-app-nav button').nth(i).click();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);}
 }
 await page.locator('.mobile-app-nav button').first().click();await page.locator('#chat-input').fill('ещё кофе');
 await page.setViewportSize({width:390,height:440});await page.waitForTimeout(300);
 const box=await page.locator('.chat-composer').boundingBox();expect(box.y+box.height).toBeLessThanOrEqual(441);
});

test('late account response is discarded after logout',async({page})=>{
 await mockApi(page,{account:'A'});
 let release;const gate=new Promise(resolve=>{release=resolve});let started=false;
 await page.route('**/api/me/saved',async r=>{started=true;await gate;await r.fulfill({json:[aPlace]}).catch(()=>{});});
 await page.goto('/saved');await expect.poll(()=>started).toBe(true);
 await page.locator('.account-button').click();await page.getByRole('menuitem',{name:'Выйти',exact:true}).click();
 release();await expect(page.locator('.login-link')).toContainText('Войти');
 await expect(page.getByText('Private place A',{exact:true})).toHaveCount(0);
});

test('address entry also hides the mobile bar when the keyboard opens',async({page})=>{
 await page.setViewportSize({width:390,height:844});await mockApi(page);await page.goto('/');
 await page.locator('.chat-body [data-start-input]').fill('Кенесары 40');await page.setViewportSize({width:390,height:440});
 await expect(page.locator('.mobile-app-nav')).toHaveAttribute('aria-hidden','true');
 await expect(page.locator('.chat-body [data-start-input]')).toBeVisible();
 await page.locator('.chat-body [data-start-input]').press('Enter');await expect(page.locator('.chat-places')).toBeVisible();
});

test('denied geolocation keeps a working landmark fallback',async({page})=>{
 const state=await mockApi(page);
 await page.addInitScript(()=>{navigator.geolocation.getCurrentPosition=(_,reject)=>reject({code:1})});
 await page.goto('/');await page.locator('.start-geo').first().click();
 await expect(page.locator('.geo-denied')).toBeVisible();expect(state.requests).toHaveLength(0);
 await chooseStart(page);expect(state.requests[0].landmark).toBe('mega_silk_way');
});
