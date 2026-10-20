import {test, expect} from '@playwright/test';

async function guestApi(page) {
  await page.addInitScript(() => localStorage.setItem('seruendesh.language','ru'));
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    return route.fulfill({json:path === '/api/auth/me' ? {user:null} : path === '/api/events' ? {items:[],total:0,today:'2026-10-20',categories:[],months:[]} : {features:{photo:false}}});
  });
}

async function expectWalkingControls(page) {
  const nav = page.locator('.mobile-app-nav');
  await expect(nav).toBeVisible();
  const chooser = page.getByRole('dialog',{name:'Откуда начнём?',exact:true});
  if (await chooser.count()) await chooser.getByRole('button',{name:'Закрыть',exact:true}).click();
  await expect(page.locator('#chat-input')).toBeEditable();
  await expect.poll(async () => {
    const composer = await page.locator('.chat-composer').boundingBox(), bar = await nav.boundingBox();
    return composer.y >= 0 && composer.y + composer.height <= bar.y;
  }).toBe(true);
  await expect(page.locator('.site-header')).toBeVisible();
  const header = await page.locator('.site-header').boundingBox();
  const brand = await page.locator('.site-header .brand').boundingBox();
  const actions = await page.locator('.header-actions').boundingBox();
  expect(brand.x + brand.width).toBeLessThanOrEqual(actions.x);
  expect(header.height).toBeLessThanOrEqual(62);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
}

test('a large phone in landscape keeps chat, header and navigation within the visible screen', async ({page}) => {
  await page.setViewportSize({width:932,height:430});
  await guestApi(page);
  await page.goto('/');
  await expectWalkingControls(page);
  await page.getByRole('button',{name:'Длительность и фильтры',exact:true}).click();
  const filters = page.getByRole('dialog',{name:'Длительность и фильтры',exact:true});
  const panel = await filters.boundingBox();
  expect(panel.y).toBeGreaterThanOrEqual(0);
  expect(panel.y + panel.height).toBeLessThanOrEqual(430);
  await filters.getByRole('button',{name:/120/}).click();
  await page.getByRole('button',{name:'Длительность и фильтры',exact:true}).click();
  await page.locator('.mobile-app-nav').getByRole('link',{name:'События',exact:true}).click();
  await expect(page.locator('.mobile-app-nav')).toBeVisible();
  await page.locator('.mobile-app-nav').getByRole('button',{name:'Чат',exact:true}).click();
  await expectWalkingControls(page);
});

test('rotating a phone keeps the chosen walking view and a reachable composer', async ({page}) => {
  await page.setViewportSize({width:390,height:844});
  await guestApi(page);
  await page.goto('/');
  await page.getByRole('dialog',{name:'Откуда начнём?',exact:true}).getByRole('button',{name:'Закрыть',exact:true}).click();
  await page.setViewportSize({width:932,height:430});
  await expectWalkingControls(page);
  await expect(page.locator('.mobile-app-nav').getByRole('button',{name:'Чат',exact:true})).toHaveAttribute('aria-current','page');
});
