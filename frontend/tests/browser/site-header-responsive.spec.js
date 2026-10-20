import {test, expect} from '@playwright/test';
import {readFileSync} from 'node:fs';

const walk = JSON.parse(readFileSync(new URL('../../../backend/docs/api/examples/walk.json', import.meta.url)));

async function guestApi(page, language) {
  await page.addInitScript(lang => localStorage.setItem('seruendesh.language',lang), language);
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/recommend') {
      const response = structuredClone(walk);
      response.route = null;
      response.recommendations = response.recommendations.slice(0,3);
      return route.fulfill({json:response});
    }
    return route.fulfill({json:path === '/api/auth/me' ? {user:null} : {features:{photo:false}}});
  });
}

for (const language of ['ru','kk','en']) {
  for (const width of [1024,1100,1250,1251,1280,1366,1399,1400,1440]) {
    test(`desktop header keeps every destination and action clear at ${width}px in ${language}`, async ({page}) => {
      await page.setViewportSize({width,height:768});
      await guestApi(page, language);
      await page.goto('/');
      const header = page.locator('.site-header');
      await expect(header.locator('nav > a')).toHaveCount(4);
      for (const selector of ['.brand','nav','.app-install-trigger','.lang-trigger','.login-link']) {
        await expect(header.locator(selector)).toBeVisible();
      }
      await page.evaluate(() => document.fonts.ready);

      const expectClearHeader = async () => {
        const geometry = await header.evaluate(element => {
          const bounds = node => {
            const {left,top,right,bottom,width,height} = node.getBoundingClientRect();
            return {left,top,right,bottom,width,height};
          };
          // The flex item can shrink while its logo text overflows its own box.
          const brand = element.querySelector('.brand');
          const brandParts = [brand,...brand.children].map(bounds);
          const parts = [{name:'brand artwork and text',
            left:Math.min(...brandParts.map(part => part.left)),
            top:Math.min(...brandParts.map(part => part.top)),
            right:Math.max(...brandParts.map(part => part.right)),
            bottom:Math.max(...brandParts.map(part => part.bottom)),
          }];
          for (const control of element.querySelectorAll('.nearby-trigger, nav > a, .app-install-trigger, .lang-trigger, .header-actions .login-link')) {
            const box = bounds(control);
            if (box.width && box.height && getComputedStyle(control).visibility !== 'hidden') {
              parts.push({name:control.getAttribute('aria-label') || control.textContent.trim(),...box});
            }
          }
          return {header:bounds(element),parts:parts.sort((a,b) => a.left - b.left)};
        });

        for (const part of geometry.parts) {
          expect.soft(part.left, `${part.name} begins inside the header`).toBeGreaterThanOrEqual(geometry.header.left);
          expect.soft(part.right, `${part.name} ends inside the header`).toBeLessThanOrEqual(geometry.header.right);
          expect.soft(part.top, `${part.name} begins below the header's top`).toBeGreaterThanOrEqual(geometry.header.top);
          expect.soft(part.bottom, `${part.name} ends above the header's bottom`).toBeLessThanOrEqual(geometry.header.bottom);
        }
        for (let index = 1; index < geometry.parts.length; index++) {
          const previous = geometry.parts[index - 1], current = geometry.parts[index];
          expect.soft(previous.right, `${previous.name} does not overlap ${current.name}`).toBeLessThanOrEqual(current.left);
        }
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      };
      await expectClearHeader();
      await page.locator('.start-landmarks button').filter({hasText:'Mega Silk Way'}).first().click();
      await expect(page.locator('.nearby-trigger .nav-count')).toHaveText('3');
      await expectClearHeader();
    });
  }
}
