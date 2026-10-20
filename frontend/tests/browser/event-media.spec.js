import {test, expect} from '@playwright/test';

async function imageHarness(page) {
  await page.goto('/');
  await page.evaluate(async () => {
    const [{default:React},{default:ReactDOM},{EventImage}] = await Promise.all([
      import('/node_modules/.vite/deps/react.js'),
      import('/node_modules/.vite/deps/react-dom_client.js'),
      import('/src/components/EventPrimitives.jsx'),
    ]);
    const host = document.createElement('div');
    document.body.replaceChildren(host);
    const root = ReactDOM.createRoot(host);
    window.renderEventImage = props => root.render(React.createElement(EventImage,props));
  });
}

test('intrinsic orientation resets on failure and a replacement URL loads on the same image component', async ({page}) => {
  await page.route('https://event-media.test/**', route => {
    if (route.request().url().endsWith('broken.svg')) return route.abort();
    // URL names and supplied metadata deliberately disagree with the real image.
    const [width,height] = route.request().url().endsWith('landscape.svg') ? [600,1200] : [1200,450];
    return route.fulfill({contentType:'image/svg+xml',body:`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}"><rect width="100%" height="100%" fill="#dce8db"/></svg>`});
  });
  await imageHarness(page);
  const event = {id:'image-fixture',title:'Image fixture',category_label:'Музыка',image_url:'https://event-media.test/landscape.svg',image_width:1600,image_height:900};
  await page.evaluate(event => window.renderEventImage({event}),event);
  const cover = page.locator('.events-cover');
  await expect(cover).toHaveAttribute('data-orientation','portrait');
  await expect(cover).toHaveAttribute('data-media','photo');
  await expect(cover.locator('img')).toHaveAttribute('alt','');

  // A failure after a portrait has loaded must also clear its layout orientation.
  await cover.locator('img').dispatchEvent('error');
  await expect(cover).toHaveAttribute('data-orientation','unknown');
  await expect(cover).toHaveAttribute('data-media','fallback');
  await expect(cover.locator('.events-category-cover')).toBeVisible();

  const brokenRequest = page.waitForEvent('requestfailed',request => request.url().endsWith('/broken.svg'));
  await page.evaluate(event => window.renderEventImage({event:{...event,image_url:'https://event-media.test/broken.svg'}}),event);
  await brokenRequest;
  await expect(cover).toHaveAttribute('data-media','fallback');
  await expect(cover).toHaveAttribute('data-orientation','unknown');

  await page.evaluate(event => window.renderEventImage({event:{...event,image_url:'https://event-media.test/portrait.svg'},detail:true}),event);
  await expect(cover).toHaveClass(/events-detail-cover/);
  await expect(cover).toHaveAttribute('data-media','photo');
  await expect(cover).toHaveAttribute('data-orientation','landscape');
});

test('a previously decoded image gets its orientation from the cache without relying on another load event', async ({page}) => {
  await imageHarness(page);
  const imageUrl = await page.evaluate(async () => {
    const image = new Image();
    image.src = new URL('/brand/source-sxodim.svg',location.origin).href;
    await image.decode();
    // Keep native complete/natural dimensions while forcing the cached-image ref path.
    document.addEventListener('load',event => {
      if (event.target instanceof HTMLImageElement && event.target.src === image.src) event.stopImmediatePropagation();
    },true);
    return image.src;
  });
  await page.evaluate(image_url => window.renderEventImage({event:{image_url,category_label:'Музыка'},detail:true}),imageUrl);
  await expect(page.locator('.events-cover')).toHaveAttribute('data-orientation','landscape');
  await expect(page.locator('.events-cover')).toHaveAttribute('data-media','photo');
});
