import RFB from '@novnc/novnc';

const screen=document.querySelector('#screen');
const status=document.querySelector('#status');
const observe=document.querySelector('#observe');
const paste=document.querySelector('#paste');
const copy=document.querySelector('#copy');
const dialog=document.querySelector('#clipboard');
const text=dialog.querySelector('textarea');
const send=dialog.querySelector('#send');
let rfb,timer,delay=500,failures=0,stopped=false,clipboard='';

function layout() {
  if(!rfb)return;
  // Small windows observe a scaled desktop instead of shrinking browser dialogs.
  rfb.scaleViewport=screen.clientWidth<800 || screen.clientHeight<600;
  rfb.resizeSession=!rfb.scaleViewport;
}
function controls() {
  if(!rfb)return;
  rfb.viewOnly=observe.checked;
  paste.disabled=observe.checked;copy.disabled=observe.checked || !clipboard;
  layout();
}
function connect() {
  clearTimeout(timer);
  if(stopped)return;
  screen.replaceChildren();
  status.textContent='Connecting';
  const url=new URL('vnc',location.href);
  url.protocol=location.protocol==='https:'?'wss:':'ws:';
  const connection=new RFB(screen,url.href,{shared:true});
  rfb=connection;
  rfb.background='#1b1d21';
  rfb.qualityLevel=9;
  controls();
  rfb.addEventListener('connect',()=>{
    if(connection!==rfb)return;
    delay=500;failures=0;status.textContent=observe.checked?'Observing':'Connected';
    screen.dataset.connected='true';
  });
  rfb.addEventListener('disconnect',()=>{
    if(connection!==rfb)return;
    screen.dataset.connected='false';
    if(stopped)return;
    if(++failures>6){status.textContent='Disconnected — reconnect or request a fresh link.';return;}
    status.textContent='Reconnecting…';
    timer=setTimeout(connect,delay);delay=Math.min(delay*2,10000);
  });
  rfb.addEventListener('clipboard',event=>{
    if(connection!==rfb)return;
    clipboard=event.detail.text;copy.disabled=observe.checked || !clipboard;
  });
}
observe.addEventListener('change',()=>{
  controls();status.textContent=observe.checked?'Observing':'Connected';
});
document.querySelector('#reconnect').addEventListener('click',()=>{
  stopped=true;rfb?.disconnect();clearTimeout(timer);stopped=false;failures=0;delay=500;connect();
});
document.querySelector('#fullscreen').addEventListener('click',async()=>{
  try {
    if(document.fullscreenElement)await document.exitFullscreen();
    else await document.documentElement.requestFullscreen();
  } catch {status.textContent='Fullscreen unavailable';}
});
paste.addEventListener('click',()=>{
  text.value='';text.readOnly=false;send.hidden=false;
  dialog.querySelector('h2').textContent='Paste into the browser';
  dialog.showModal();text.focus();
});
send.addEventListener('click',()=>{
  if(!rfb || observe.checked)return;
  if(new TextEncoder().encode(text.value).length>256*1024){
    dialog.querySelector('h2').textContent='Text is too large (maximum 256 KiB)';return;
  }
  rfb.clipboardPasteFrom(text.value);
  dialog.close();rfb.focus();
  rfb.sendKey(0xffe3,'ControlLeft',true);
  rfb.sendKey(0x76,'KeyV',true);rfb.sendKey(0x76,'KeyV',false);
  rfb.sendKey(0xffe3,'ControlLeft',false);
  text.value='';
});
copy.addEventListener('click',async()=>{
  try {await navigator.clipboard.writeText(clipboard);status.textContent='Copied';}
  catch {
    text.value=clipboard;text.readOnly=true;send.hidden=true;
    dialog.querySelector('h2').textContent='Copy from the browser';
    dialog.showModal();text.focus();text.select();
  }
});
dialog.querySelector('#cancel').addEventListener('click',()=>dialog.close());
dialog.addEventListener('close',()=>{text.value='';});
new ResizeObserver(layout).observe(screen);
window.addEventListener('pageshow',event=>{if(event.persisted){stopped=false;connect();}});
window.addEventListener('pagehide',()=>{stopped=true;clearTimeout(timer);rfb?.disconnect();});
connect();
