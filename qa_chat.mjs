export default async function run(page) {
  const box = page.getByPlaceholder(/Describe technical task/i);
  await box.waitFor({ state: 'visible', timeout: 10000 });
  await box.fill('Reply with exactly: QA-OK');
  await page.keyboard.press('Enter');
  await page.waitForFunction(
    () => document.body.innerText.includes('QA-OK'),
    null,
    { timeout: 45000 }
  );
  return { replySeen: true };
}
