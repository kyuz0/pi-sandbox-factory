import assert from 'node:assert/strict';
import { SandboxBrowser } from './browser.mjs';
const browser = new SandboxBrowser();
try {
  let r = await browser.run("await page.setContent('<title>Browser fixture</title><button>Press me</button><p id=result>Ready</p><script>document.querySelector(\"button\").onclick=()=>document.querySelector(\"p\").textContent=\"Clicked\"</script>'); await page.getByRole('button',{name:'Press me'}).click(); state.marker='persistent'; return {title:await page.title(),text:await page.locator('#result').textContent()}");
  assert.equal(r.ok, true, JSON.stringify(r));
  assert.deepEqual(r.result, {title:'Browser fixture',text:'Clicked'});
  r = await browser.run("return {marker:state.marker, image:await screenshot({kind:'debug',name:'sandbox-browser-check'})}");
  assert.equal(r.ok,true,JSON.stringify(r));assert.equal(r.result.marker,'persistent');
  if (process.argv[2]) {
    r = await browser.run(`await page.goto(${JSON.stringify(process.argv[2])}); return await page.title()`);
    assert.equal(r.ok,true,JSON.stringify(r));assert(r.result);
  }
  if (process.env.SANDBOX_NETWORK_MODE !== 'unrestricted') {
    r = await browser.run("await page.goto('https://unlisted.invalid'); return await page.title()");
    assert.equal(r.ok,false,'Unlisted destination must be blocked');
    assert.match(JSON.stringify(r), /TUNNEL_CONNECTION_FAILED|403|PROXY/i);
  }
  console.log('PASS Betterwright: launch, DOM interaction, persistent state, screenshot, network policy');
} finally { await browser.close(); }
