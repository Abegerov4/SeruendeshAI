import {test, expect} from '@playwright/test';
import {readFileSync} from 'node:fs';

const walk = JSON.parse(readFileSync(new URL('../../../backend/docs/api/examples/walk.json', import.meta.url)));
const event = {id:'mobile-event',title:'Вечер в Астане',start:'2026-10-24T19:00:00+05:00',venue:'Городской зал',price_from:2000,currency:'KZT',category:'music',category_label:'Музыка',sources:[],sessions:[],is_archived:false};

async function api(page) {
  const requests = [];
  await page.addInitScript(() => {
    localStorage.setItem('seruendesh.language','ru');
    window.geoCalls = 0;
    navigator.geolocation.getCurrentPosition = (_, reject) => {window.geoCalls++;reject({code:1});};
  });
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/recommend') {
      requests.push(route.request().postDataJSON());
      const response = structuredClone(walk);
      response.route = null;
      response.recommendations = response.recommendations.slice(0,2);
      return route.fulfill({json:response});
    }
    if (url.pathname === '/api/geocode') return route.fulfill({json:{results:[]}});
    if (url.pathname === '/api/events') return route.fulfill({json:{items:[event],total:1,offset:0,limit:20,today:'2026-10-20',categories:[],months:[]}});
    if (url.pathname.startsWith('/api/events/')) return route.fulfill({json:event});
    return route.fulfill({json:url.pathname === '/api/auth/me' ? {user:null} : {features:{photo:false}}});
  });
  return requests;
}

test('mobile start is a dismissible dialog without automatic GPS or recommendation requests', async ({page}) => {
  await page.setViewportSize({width:320,height:568});
  const requests = await api(page);
  await page.goto('/');
  const dialog = page.getByRole('dialog',{name:'Откуда начнём?',exact:true});
  await expect(dialog).toBeVisible();
  expect(requests).toHaveLength(0);
  expect(await page.evaluate(() => window.geoCalls)).toBe(0);
  await dialog.getByRole('textbox',{name:'Или адрес / ориентир'}).fill('Несуществующий адрес');
  await dialog.getByRole('button',{name:'Найти места',exact:true}).click();
  await expect(dialog.getByRole('alert')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await expect(page.locator('#chat-input')).toBeEditable();
  await expect(page.locator('.mobile-app-nav')).toBeVisible();
  expect(requests).toHaveLength(0);
});

test('the start address and lookup error stay reachable above a small mobile keyboard', async ({page}) => {
  await page.setViewportSize({width:320,height:568});
  await api(page);
  await page.goto('/');
  const dialog = page.getByRole('dialog',{name:'Откуда начнём?',exact:true});
  const address = dialog.getByRole('textbox',{name:'Или адрес / ориентир'});
  await address.fill('Неизвестный адрес');
  await page.evaluate(() => {
    Object.defineProperty(visualViewport,'height',{configurable:true,value:300});
    visualViewport.dispatchEvent(new Event('resize'));
  });
  await expect.poll(async () => {
    const field = await address.boundingBox(), sheet = await dialog.boundingBox();
    return field.y >= sheet.y && field.y + field.height <= sheet.y + sheet.height;
  }).toBe(true);
  const submit = dialog.getByRole('button',{name:'Найти места',exact:true});
  const button = await submit.boundingBox();
  expect(button.y + button.height).toBeLessThanOrEqual(300);
  await submit.click();
  const error = dialog.getByRole('alert');
  await expect(error).toBeVisible();
  await expect.poll(async () => {
    const message = await error.boundingBox();
    return message.y >= 16 && message.y + message.height <= 300;
  }).toBe(true);
});

test('bottom navigation is available on direct event and saved routes and returns to chat', async ({page}) => {
  await page.setViewportSize({width:390,height:844});
  await api(page);
  for (const path of ['/events','/events/archive','/events/mobile-event','/saved']) {
    await page.goto(path);
    const nav = page.locator('.mobile-app-nav');
    await expect(nav).toBeVisible();
    await expect(nav.getByRole('button',{name:'Чат',exact:true})).toBeVisible();
    if (path.startsWith('/events')) await expect(nav.getByRole('link',{name:'События',exact:true})).toHaveAttribute('aria-current','page');
    await nav.getByRole('button',{name:'Чат',exact:true}).click();
    await expect(page).toHaveURL(/\/$/);
    const chooser = page.getByRole('dialog',{name:'Откуда начнём?',exact:true});
    await chooser.getByRole('button',{name:'Закрыть',exact:true}).click();
    await expect(page.locator('#chat-input')).toBeEditable();
  }
});

test('a walking result and unsent message survive events and return through the bottom bar', async ({page}) => {
  await page.setViewportSize({width:390,height:844});
  const requests = await api(page);
  await page.goto('/');
  await page.getByRole('button',{name:'Mega Silk Way',exact:true}).first().click();
  await expect(page.locator('.chat-place')).toHaveCount(2);
  const firstPlace = await page.locator('.chat-place-text b').first().textContent();
  await page.locator('#chat-input').fill('После афиши хочу кофе');
  await page.locator('.chat-heading h2').click();
  await page.locator('.mobile-app-nav').getByRole('link',{name:'События',exact:true}).click();
  await expect(page.getByRole('heading',{name:event.title,exact:true})).toBeVisible();
  await page.goBack();
  await expect(page.locator('.chat-place')).toHaveCount(2);
  await page.locator('.mobile-app-nav').getByRole('link',{name:'События',exact:true}).click();
  await expect(page.locator('.mobile-app-nav')).toBeVisible();
  await page.locator('.mobile-app-nav').getByRole('button',{name:'Чат',exact:true}).click();
  await expect(page.locator('.chat-place')).toHaveCount(2);
  await expect(page.locator('.chat-place-text b').first()).toHaveText(firstPlace);
  await expect(page.locator('#chat-input')).toHaveValue('После афиши хочу кофе');
  await expect(page.getByRole('dialog',{name:'Откуда начнём?',exact:true})).toHaveCount(0);
  expect(requests).toHaveLength(1);
});

test('a guest can open the saved collection from mobile places and return to the same result', async ({page}) => {
  await page.setViewportSize({width:320,height:700});
  await api(page);
  await page.goto('/');
  await page.getByRole('button',{name:'Mega Silk Way',exact:true}).first().click();
  await expect(page.locator('.chat-place')).toHaveCount(2);
  await page.locator('.mobile-app-nav').getByRole('button',{name:'Места 2',exact:true}).click();
  await page.locator('.places-section .save-button').first().click();
  await page.locator('.places-section').getByRole('link',{name:/Избранное/}).click();
  await expect(page).toHaveURL(/\/saved$/);
  await expect(page.locator('.saved-grid .place-card')).toHaveCount(1);
  await page.locator('.mobile-app-nav').getByRole('button',{name:'Места 2',exact:true}).click();
  await expect(page.locator('.places-section .place-card')).toHaveCount(2);
  await expect(page.locator('.places-section .save-button').first()).toHaveAttribute('aria-pressed','true');
});
