/** Synthetic pages only; stdin lifetime owns both private browser sessions. */
import {createInterface} from 'node:readline';
import {SandboxBrowser} from '/opt/betterwright/browser.mjs';
const popup=`<title>Popup fixture</title><style>body{font:24px sans-serif;padding:30px}input,button{font:inherit}</style><h1>Sign in</h1><label>Username <input id="username"></label><button id="next" onclick="opener.postMessage(document.querySelector('input').value,'*');window.close()">Next</button>`;
const form=`<title>Tab fixture</title><style>body{font:24px sans-serif;padding:30px;background:#eef4fa}input,button{font:inherit;margin:12px}#block{background:#008866;width:160px;height:100px}</style><h1>Browser handoff</h1><div id="block"></div><label>Text <input id="text"></label><button id="next" onclick="document.querySelector('#result').textContent='Next worked'">Next</button><button id="popup">Sign in</button><button id="newtab">New tab</button><p id="result">Ready</p>`;
const browsers=[new SandboxBrowser(),new SandboxBrowser()];
const results=[];
let closing=false;
async function close(code=0){
  if(closing)return;closing=true;
  for(const browser of browsers)await browser.close();
  process.exit(code);
}
const input=createInterface({input:process.stdin});
process.on('SIGTERM',()=>close());process.on('SIGINT',()=>close());
try {
  for(const [index,browser] of browsers.entries()){
    const result=await browser.run(`await page.setContent(${JSON.stringify(form)});
      await page.evaluate(({index,form,popup})=>{
        document.title='VIEWER_'+index;
        document.querySelector('#popup').onclick=()=>{const p=window.open('about:blank','login','width=640,height=480');p.document.write(popup);p.document.close()};
        document.querySelector('#newtab').onclick=()=>{const p=window.open('about:blank','_blank');p.document.write(form);p.document.close()};
        window.addEventListener('message',event=>document.querySelector('#result').textContent='Signed in: '+event.data);
      },${JSON.stringify({index,form,popup})});return await page.title()`);
    if(!result.ok)throw Error(JSON.stringify(result));
    results.push({url:await browser.viewerLink()});
  }
  console.log(JSON.stringify({ownerPid:process.pid,browsers:results}));
  for await(const line of input){
    const request=JSON.parse(line);
    console.log(JSON.stringify(await browsers[request.index??0].run(request.code)));
  }
  await close();
} catch(error){console.error(error);await close(1);}
