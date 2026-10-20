import {test, expect} from '@playwright/test';

const event = index => ({
  id:`navigation-${index}`, title:`Концерт ${index + 1}`, description:'Описание события.',
  venue:'Городской концертный зал', address:'проспект Республики, 32',
  start:'2026-11-01T19:00:00+05:00', end:null, sessions:['2026-11-01T19:00:00+05:00'],
  price_from:4000, currency:'KZT', category:'music', category_label:'Музыка', image_url:null,
  announced_at:null, first_seen_at:'2026-10-20T09:00:00+05:00',
  sources:[{name:'sxodim',url:'https://sxodim.com/astana/event/navigation'}], is_archived:false,
});

async function api(page, detailStatus = 200) {
  await page.addInitScript(() => localStorage.setItem('seruendesh.language','ru'));
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/events') {
      const offset = Number(url.searchParams.get('offset') || 0), archived = url.searchParams.get('view') === 'archive';
      return route.fulfill({json:{items:Array.from({length:8}, (_, index) => ({...event(offset + index),is_archived:archived})),total:16,offset,limit:8,today:'2026-10-20',categories:[{value:'music',label:'Музыка'}],months:['2026-09']}});
    }
    if (url.pathname.startsWith('/api/events/')) {
      const index = Number(decodeURIComponent(url.pathname.split('/').at(-1)).replace('navigation-',''));
      return route.fulfill({status:detailStatus,json:detailStatus === 200 ? event(index) : {detail:'Unavailable'}});
    }
    return route.fulfill({json:url.pathname === '/api/auth/me' ? {user:null} : {}});
  });
}

for (const returnMethod of ['link','browser Back']) {
  test(`returning by ${returnMethod} restores loaded event pages, filters and scroll`,async({page}) => {
    await api(page); await page.setViewportSize({width:390,height:844}); await page.goto('/events');
    await expect(page.locator('.events-card:visible')).toHaveCount(8);
    await page.getByRole('searchbox',{name:'Поиск событий',exact:true}).fill('концерт');
    await page.getByRole('button',{name:'Сегодня',exact:true}).click();
    await expect(page.locator('.events-list[aria-busy="false"]')).toBeVisible();
    await page.getByRole('button',{name:'Показать ещё',exact:true}).click();
    await expect(page.locator('.events-card:visible')).toHaveCount(16);
    const link = page.locator('.events-details-link').nth(12);
    await link.scrollIntoViewIfNeeded();
    const originalScroll = await page.evaluate(() => scrollY);
    expect(originalScroll).toBeGreaterThan(1000);
    await link.click(); await expect(page).toHaveURL(/\/events\/navigation-12$/);
    await expect(page.getByRole('heading',{name:'Концерт 13',level:1,exact:true})).toBeVisible();
    if (returnMethod === 'link') await page.locator('.events-back').click();
    else await page.goBack();
    await expect(page).toHaveURL(/\/events$/);
    await expect(page.locator('.events-card:visible')).toHaveCount(16);
    await expect(page.getByRole('searchbox',{name:'Поиск событий',exact:true})).toHaveValue('концерт');
    await expect(page.getByRole('button',{name:'Сегодня',exact:true})).toHaveAttribute('aria-pressed','true');
    await expect.poll(async() => Math.abs(await page.evaluate(() => scrollY) - originalScroll)).toBeLessThan(8);
    await expect(link).toBeInViewport();
  });
}

for (const status of [503,404]) {
  test(`an archive detail ${status} keeps its archive return destination`,async({page}) => {
    await api(page,status); await page.setViewportSize({width:390,height:844}); await page.goto('/events/archive');
    await expect(page.locator('.events-card:visible')).toHaveCount(8);
    await page.getByRole('searchbox',{name:'Поиск в архиве',exact:true}).fill('концерт');
    await expect(page.locator('.events-list[aria-busy="false"]')).toBeVisible();
    await page.locator('.events-details-link').first().click();
    await expect(page.getByRole('heading',{name:status === 404 ? 'Событие не найдено' : 'Не удалось загрузить события',exact:true})).toBeVisible();
    await expect(page.locator('.events-back')).toHaveAttribute('href','/events/archive');
    await expect(page.locator('.events-tabs a[href="/events/archive"]')).toHaveAttribute('aria-current','page');
    if (status === 404) await expect(page.locator('.events-detail .events-primary')).toHaveAttribute('href','/events/archive');
    await page.locator('.events-back').click();
    await expect(page).toHaveURL(/\/events\/archive$/);
    await expect(page.getByRole('searchbox',{name:'Поиск в архиве',exact:true})).toHaveValue('концерт');
    await expect(page.locator('.events-card:visible')).toHaveCount(8);
  });
}

test('a direct failed detail link still returns to upcoming events',async({page}) => {
  await api(page,404); await page.goto('/events/navigation-1');
  await expect(page.getByRole('heading',{name:'Событие не найдено',exact:true})).toBeVisible();
  await expect(page.locator('.events-back')).toHaveAttribute('href','/events');
  await expect(page.locator('.events-detail .events-primary')).toHaveAttribute('href','/events');
});

test('browser Back to a detail closes a picker from the retained feed',async({page}) => {
  await api(page); await page.goto('/events');
  await page.locator('.events-details-link').first().click();
  await expect(page.getByRole('heading',{name:'Концерт 1',level:1,exact:true})).toBeVisible();
  await page.locator('.events-back').click();
  await page.getByRole('button',{name:'Выбрать даты',exact:true}).click();
  await expect(page.getByRole('dialog',{name:'Дата или диапазон',exact:true})).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(/\/events\/navigation-0$/);
  await expect(page.locator('.events-dialog[open]')).toHaveCount(0);
  await expect(page.getByRole('heading',{name:'Концерт 1',level:1,exact:true})).toBeVisible();
  await expect(page.locator('body')).not.toHaveCSS('overflow','hidden');
});

test('history revisits restore the latest feed scroll after further browsing',async({page}) => {
  await api(page); await page.setViewportSize({width:390,height:844}); await page.goto('/events');
  await page.getByRole('button',{name:'Показать ещё',exact:true}).click();
  await expect(page.locator('.events-card:visible')).toHaveCount(16);
  const link = page.locator('.events-details-link').nth(12);
  await link.scrollIntoViewIfNeeded(); await link.click();
  await expect(page).toHaveURL(/\/events\/navigation-12$/);
  await page.goBack(); await expect(page).toHaveURL(/\/events$/);
  await expect(link).toBeInViewport();
  const latestScroll = await page.evaluate(async() => {
    window.scrollTo({top:scrollY + 300,behavior:'instant'});
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    return scrollY;
  });
  await page.goForward(); await expect(page).toHaveURL(/\/events\/navigation-12$/);
  await page.goBack(); await expect(page).toHaveURL(/\/events$/);
  await expect.poll(async() => Math.abs(await page.evaluate(() => scrollY) - latestScroll)).toBeLessThan(8);
});
