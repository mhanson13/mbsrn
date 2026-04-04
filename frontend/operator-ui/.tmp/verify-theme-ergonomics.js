const { chromium } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const OUTPUT_DIR = process.argv[2];
const BASE_URL = 'http://127.0.0.1:3201';

const BUSINESS_ID = 'biz-1';
const SITE_ID = 'site-1';

const recommendations = [
  {
    id: 'rec-1',
    business_id: BUSINESS_ID,
    site_id: SITE_ID,
    recommendation_run_id: 'rec-run-1',
    audit_run_id: null,
    comparison_run_id: null,
    status: 'open',
    category: 'SEO',
    severity: 'warning',
    priority_score: 88,
    priority_band: 'high',
    effort_bucket: 'small',
    title: 'Fix title tag duplication on service pages',
    rationale: 'Consolidate duplicate title tags so search engines can better distinguish each service page intent and improve click-through quality for local prospects.',
    created_at: '2026-04-03T15:00:00Z',
    updated_at: '2026-04-03T15:00:00Z',
  },
  {
    id: 'rec-2',
    business_id: BUSINESS_ID,
    site_id: SITE_ID,
    recommendation_run_id: 'rec-run-1',
    audit_run_id: null,
    comparison_run_id: null,
    status: 'open',
    category: 'CONTENT',
    severity: 'warning',
    priority_score: 72,
    priority_band: 'medium',
    effort_bucket: 'moderate',
    title: 'Improve internal linking for conversion paths',
    rationale: 'Add directional links between core service pages and supporting FAQ content so operators can preserve a clear crawl path and conversion journey.',
    created_at: '2026-04-03T15:00:00Z',
    updated_at: '2026-04-03T15:00:00Z',
  },
];

function recommendationListResponse() {
  return {
    items: recommendations,
    total: recommendations.length,
    filtered_summary: {
      total: recommendations.length,
      open: recommendations.filter((r) => r.status === 'open').length,
      accepted: recommendations.filter((r) => r.status === 'accepted').length,
      dismissed: recommendations.filter((r) => r.status === 'dismissed').length,
      high_priority: recommendations.filter((r) => ['high', 'critical'].includes(r.priority_band)).length,
    },
  };
}

(async () => {
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();

  const consoleMessages = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error' || /hydration|mismatch/i.test(msg.text())) {
      consoleMessages.push({ type: msg.type(), text: msg.text() });
    }
  });

  await page.addInitScript(({ businessId, siteId }) => {
    window.sessionStorage.setItem('mbsrn.operator.access_token', 'manual-verify-token');
    window.sessionStorage.setItem('mbsrn.operator.refresh_token', 'manual-verify-refresh');
    window.sessionStorage.setItem('mbsrn.operator.principal', JSON.stringify({
      business_id: businessId,
      principal_id: 'manual-verify-principal',
      display_name: 'Manual Verify',
      role: 'admin',
      is_active: true,
    }));
    window.localStorage.setItem('operator-ui-theme', 'light');
    window.localStorage.setItem('mbsrn.operator.selected_site_id', siteId);
  }, { businessId: BUSINESS_ID, siteId: SITE_ID });

  let patchCount = 0;

  await page.route('http://127.0.0.1:8000/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const pathname = url.pathname;
    const method = request.method();

    if (pathname === `/api/businesses/${BUSINESS_ID}/seo/sites` && method === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [
            {
              id: SITE_ID,
              business_id: BUSINESS_ID,
              display_name: 'Alpha Plumbing',
              base_url: 'https://example.com',
              normalized_domain: 'example.com',
              is_active: true,
              is_primary: true,
              last_audit_run_id: null,
              last_audit_status: null,
              last_audit_completed_at: null,
            },
          ],
          total: 1,
        }),
      });
      return;
    }

    if (pathname === `/api/businesses/${BUSINESS_ID}/seo/sites/${SITE_ID}/recommendations` && method === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(recommendationListResponse()),
      });
      return;
    }

    if (pathname === `/api/businesses/${BUSINESS_ID}/seo/sites/${SITE_ID}/automation/runs` && method === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [], total: 0 }),
      });
      return;
    }

    if (pathname.startsWith(`/api/businesses/${BUSINESS_ID}/seo/sites/${SITE_ID}/recommendations/`) && method === 'PATCH') {
      patchCount += 1;
      if (patchCount % 2 === 0) {
        await route.fulfill({
          status: 422,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'state invalid' }),
        });
      } else {
        const recId = pathname.split('/').pop();
        const rec = recommendations.find((r) => r.id === recId) || recommendations[0];
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ ...rec, status: 'dismissed', updated_at: '2026-04-03T16:00:00Z' }),
        });
      }
      return;
    }

    if (pathname === '/api/auth/logout' && method === 'POST') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
      return;
    }

    await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'not mocked' }) });
  });

  await page.goto(`${BASE_URL}/recommendations`, { waitUntil: 'networkidle' });
  await page.waitForSelector('text=Recommendation Workflow');

  const themeToggle = page.getByTestId('topnav-theme-toggle');

  await page.screenshot({ path: path.join(OUTPUT_DIR, 'recommendations-light-1280.png'), fullPage: true });

  await themeToggle.click();
  await page.waitForTimeout(150);
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForTimeout(150);
  await page.screenshot({ path: path.join(OUTPUT_DIR, 'recommendations-dark-1280.png'), fullPage: true });

  await themeToggle.click();
  await page.waitForTimeout(150);
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForTimeout(150);
  await page.screenshot({ path: path.join(OUTPUT_DIR, 'recommendations-light-reloaded-1280.png'), fullPage: true });

  const localTheme = await page.evaluate(() => window.localStorage.getItem('operator-ui-theme'));
  const rootTheme = await page.evaluate(() => document.documentElement.dataset.theme || null);

  for (const width of [1100, 1280, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.waitForTimeout(120);
    await page.screenshot({ path: path.join(OUTPUT_DIR, `recommendations-light-${width}.png`), fullPage: true });
    const widths = await page.evaluate(() => {
      const firstRow = document.querySelector('.recommendations-table tbody tr');
      if (!firstRow) return null;
      const titleCell = firstRow.querySelector('.recommendation-title-cell');
      const summaryCell = firstRow.querySelector('.recommendation-summary-cell');
      if (!titleCell || !summaryCell) return null;
      const titleRect = titleCell.getBoundingClientRect();
      const summaryRect = summaryCell.getBoundingClientRect();
      return { titleWidth: titleRect.width, summaryWidth: summaryRect.width, overflow: document.documentElement.scrollWidth > window.innerWidth };
    });
    fs.writeFileSync(path.join(OUTPUT_DIR, `width-metrics-${width}.json`), JSON.stringify(widths, null, 2));
  }

  await page.setViewportSize({ width: 1280, height: 900 });
  await page.getByLabel('Select all displayed recommendations').click();
  await page.getByRole('button', { name: 'Dismiss Selected' }).click();
  await page.waitForSelector('[data-testid="recommendation-error-toast"]');
  await page.screenshot({ path: path.join(OUTPUT_DIR, 'recommendations-toast-error-1280.png'), fullPage: true });

  const overlap = await page.evaluate(() => {
    const toast = document.querySelector('[data-testid="recommendation-error-toast"]');
    const table = document.querySelector('.recommendations-table');
    if (!toast || !table) return null;
    const t = toast.getBoundingClientRect();
    const tr = table.getBoundingClientRect();
    const intersects = !(t.right < tr.left || t.left > tr.right || t.bottom < tr.top || t.top > tr.bottom);
    return { intersectsTableViewportBounds: intersects, toast: { left: t.left, top: t.top, right: t.right, bottom: t.bottom }, table: { left: tr.left, top: tr.top, right: tr.right, bottom: tr.bottom } };
  });
  fs.writeFileSync(path.join(OUTPUT_DIR, 'toast-overlap.json'), JSON.stringify(overlap, null, 2));

  await page.getByRole('button', { name: 'Dismiss' }).click();

  await page.goto(`${BASE_URL}/dashboard`, { waitUntil: 'networkidle' });
  await page.waitForSelector('text=Operator Focus');
  await page.screenshot({ path: path.join(OUTPUT_DIR, 'dashboard-light-1280.png'), fullPage: true });
  await themeToggle.click();
  await page.waitForTimeout(150);
  await page.screenshot({ path: path.join(OUTPUT_DIR, 'dashboard-dark-1280.png'), fullPage: true });

  const headerGrouping = await page.evaluate(() => {
    const selector = document.querySelector('#global-workflow-site-selector');
    const meta = document.querySelector('[data-testid="topnav-context-identifiers"]');
    if (!selector || !meta) return null;
    const s = selector.getBoundingClientRect();
    const m = meta.getBoundingClientRect();
    return {
      selectorTop: s.top,
      selectorBottom: s.bottom,
      metaTop: m.top,
      metaBottom: m.bottom,
      verticalDistance: Math.abs(s.top - m.top),
    };
  });
  fs.writeFileSync(path.join(OUTPUT_DIR, 'header-grouping.json'), JSON.stringify(headerGrouping, null, 2));

  fs.writeFileSync(
    path.join(OUTPUT_DIR, 'verification-summary.json'),
    JSON.stringify(
      {
        localTheme,
        rootTheme,
        consoleMessages,
      },
      null,
      2,
    ),
  );

  await browser.close();
})();
