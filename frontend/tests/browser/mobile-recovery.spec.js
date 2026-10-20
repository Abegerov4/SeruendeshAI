import {test, expect} from '@playwright/test';

async function guestApi(page, language = 'ru') {
  await page.addInitScript(lang => localStorage.setItem('seruendesh.language', lang), language);
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/auth/me') return route.fulfill({json: {user: null}});
    if (path === '/api/meta') return route.fulfill({json: {features: {photo: false, password_reset_email: false}}});
    return route.fulfill({json: {}});
  });
}

for (const [language, backName] of [['ru', 'Назад к городу'], ['kk', 'Қалаға оралу'], ['en', 'Back to the city']]) {
  test(`mobile auth back link stays named and tappable in ${language}`, async ({page}) => {
    await page.setViewportSize({width: 320, height: 568});
    await guestApi(page, language);
    await page.goto('/login');

    const back = page.getByRole('link', {name: backName, exact: true});
    await expect(back).toBeVisible();
    const box = await back.boundingBox();
    expect(box.width).toBeGreaterThanOrEqual(44);
    expect(box.height).toBeGreaterThanOrEqual(44);
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(320);
    await back.click();
    await expect(page).toHaveURL('/');
    await expect(page.locator('#chat-input')).toBeVisible();
  });
}

test('an empty mobile plan offers a working way back to the chat', async ({page}) => {
  await page.setViewportSize({width: 390, height: 844});
  await guestApi(page);
  await page.goto('/?view=plan');

  const route = page.getByRole('region', {name: 'Твой маршрут', exact: true});
  await expect(route).toBeVisible();
  await route.getByRole('button', {name: 'Спроси Серу', exact: true}).click();
  await expect(route).toBeHidden();
  const composer = page.getByRole('textbox', {name: 'Как хочешь провести время?', exact: true});
  await expect(composer).toBeVisible();
  await composer.fill('Кофе возле Байтерека');
  await expect(page.getByRole('button', {name: 'Подобрать места', exact: true})).toBeEnabled();
});
