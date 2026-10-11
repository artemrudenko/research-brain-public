"""
report_theme.py — the static presentation payload for the browser-grade digest
report: the embedded stylesheet, the self-contained count-up/reveal script, and
the Google Fonts links that `digest_report_html.render_digest_report` stitches
into its document shell.

Split out of `digest_report_html.py` verbatim so the render logic and the theme
payload can evolve separately; `digest_report_html` stays the public facade
(import `render_digest_report` and the `Report*` dataclasses from there). These
strings are pure data — every byte lands in the rendered document, and the
golden pin in `tests/test_digest_report_html.py` holds the combined output
byte-for-byte across refactors.

Adaptivity & accessibility of the stylesheet (one sheet, no forked palettes):

* **Dark mode** — `@media (prefers-color-scheme: dark)` overrides only the CSS
  custom properties (`--bg`, `--surface`, `--ink`, `--line`, the accent tokens,
  the shadows). Because every rule already reads those variables, the whole page
  flips to a warm dark palette while the terracotta/olive/teal/gold accents stay
  readable; a couple of accent-tinted chips (badge/callout) get a dark-safe tweak.
* **Print** — `@media print` flattens the tokens to black-on-white, drops the
  hero gradient, shadows and entrance animations (opacity forced to 1), and adds
  `break-inside:avoid` to cards so the report exports cleanly to PDF.
"""

from __future__ import annotations

# Embedded stylesheet — the tokens/typography from the showcase deck, trimmed
# to what a digest report needs (hero, KPI grid, section cards, callout, lists).
REPORT_STYLE = """
:root{
  --bg:#F4F0E9;--surface:#FFFFFF;--surface-2:#FBF8F2;--ink:#2B2622;--ink-soft:#4A4238;
  --ink-muted:#6E6454;--line:#E6DECF;--terra:#A35E42;--terracotta:#C17B5C;
  --olive:#5D6850;--teal:#174C55;--gold:#B0852F;--radius:14px;
  --shadow:0 1px 2px rgba(43,38,34,.04),0 8px 24px rgba(43,38,34,.05);
  --shadow-hover:0 2px 6px rgba(43,38,34,.06),0 14px 38px rgba(43,38,34,.09);
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:'Manrope',system-ui,-apple-system,sans-serif;font-size:15px;line-height:1.55}
.num{font-family:'JetBrains Mono',ui-monospace,monospace;font-variant-numeric:tabular-nums}
.wrap{max-width:820px;margin:0 auto;padding:34px 22px 64px}
.hero{background:linear-gradient(150deg,#2B2622,#3A332C);color:#fff;border-radius:var(--radius);
  padding:34px 32px;box-shadow:var(--shadow);position:relative;overflow:hidden}
.hero::after{content:"";position:absolute;inset:0 0 auto 0;height:3px;
  background:linear-gradient(90deg,var(--terra),var(--olive),var(--teal),var(--gold))}
.hero h1{margin:0;font-size:27px;font-weight:800;letter-spacing:-.4px}
.hero .sub{margin-top:10px;color:#D9CFC0;font-size:15px}
.hero .rb-prev{display:inline-block;margin-top:12px;font-size:13px;font-weight:700;color:#D9CFC0}
.hero .rb-prev:hover{color:#fff}
.hero .ser{font-family:'Fraunces',Georgia,serif;font-style:italic;font-weight:400}
.rb-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:14px;margin:20px 0 6px}
.rb-kpi{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
  padding:18px 16px;box-shadow:var(--shadow);transition:transform .18s,box-shadow .18s}
.rb-kpi:hover{transform:translateY(-3px);box-shadow:var(--shadow-hover)}
.rb-kpi-num{font-size:30px;font-weight:700;color:var(--terra);line-height:1}
.rb-kpi-lbl{margin-top:6px;color:var(--ink-muted);font-size:12.5px;font-weight:600;
  text-transform:uppercase;letter-spacing:.4px}
.rb-card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
  padding:22px 24px;margin-top:16px;box-shadow:var(--shadow);transition:box-shadow .18s}
.rb-card:hover{box-shadow:var(--shadow-hover)}
.rb-sec{margin:0 0 12px;font-size:19px;font-weight:800;color:var(--ink);letter-spacing:-.2px}
.rb-badge{display:inline-block;font-family:'JetBrains Mono',monospace;font-size:12.5px;font-weight:700;
  color:var(--teal);background:#D6E7EA;border-radius:7px;padding:4px 10px;margin:8px 0 4px}
.rb-callout{background:linear-gradient(150deg,#FBF8F2,#F2ECE1);border:1px solid var(--line);
  border-left:4px solid var(--terra);border-radius:var(--radius);padding:18px 22px;margin-top:16px}
.rb-callout-h{font-weight:800;font-size:16px;margin-bottom:8px;color:var(--terra-deep,var(--terra))}
.rb-list{list-style:none;margin:6px 0;padding:0}
.rb-li{position:relative;padding:5px 0 5px 20px;color:var(--ink-soft)}
.rb-li::before{content:"•";position:absolute;left:2px;color:var(--terra);font-weight:800}
.rb-sub{padding:1px 0 4px 22px;color:var(--ink-muted);font-size:13px;list-style:none}
.rb-p{color:var(--ink-soft);margin:8px 0}
.rb-quote{margin:8px 0;padding:6px 0 6px 16px;border-left:3px solid var(--line);color:var(--ink-muted)}
.tabs{display:flex;gap:8px;margin:18px 0 10px;position:sticky;top:0;z-index:4;
  padding:10px 0;background:color-mix(in srgb,var(--bg) 88%,transparent)}
.tab{appearance:none;border:1px solid var(--line);background:var(--surface);color:var(--ink-soft);
  border-radius:9px;padding:9px 13px;font-weight:800;cursor:pointer;box-shadow:var(--shadow)}
.tab[aria-selected="true"]{background:var(--ink);border-color:var(--ink);color:var(--surface)}
.panel[hidden]{display:none}
/* On narrow screens the tab row scrolls; a right-edge fade hints "more →". */
@media (max-width:640px){
  .rb-tabs-scroll{-webkit-overflow-scrolling:touch;
    -webkit-mask-image:linear-gradient(90deg,#000 86%,transparent);
    mask-image:linear-gradient(90deg,#000 86%,transparent)}
}
.rb-toolrow{display:flex;align-items:center;gap:12px;margin:16px 0}
.rb-search{width:100%;border:1px solid var(--line);border-radius:9px;background:var(--surface);
  color:var(--ink);padding:11px 13px;font:inherit;box-shadow:var(--shadow)}
.rb-count,.rb-mini{color:var(--ink-muted);font-size:12px;white-space:nowrap}
.rb-stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:12px;margin-top:14px}
.rb-stat{background:var(--surface-2);border:1px solid var(--line);border-radius:12px;padding:14px}
.rb-stat-num{font-size:24px;font-weight:800;color:var(--terra)}
.rb-stat-lbl{color:var(--ink-muted);font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.35px}
.rb-subsec{margin-top:22px}.rb-topic-stats{list-style:none;margin:8px 0 0;padding:0}
.rb-topic-stats li{display:grid;grid-template-columns:minmax(90px,.4fr) 1fr auto;align-items:center;
  gap:16px;border-top:1px solid var(--line);padding:9px 0;color:var(--ink-soft)}
.rb-topic-stats li:first-child{border-top:0}.rb-topic-stats strong{color:var(--terra);text-align:right}
.rb-topic-bar{display:block;height:8px;border-radius:999px;background:var(--surface-2);
  border:1px solid var(--line);overflow:hidden}
.rb-topic-bar i{display:block;height:100%;border-radius:inherit;background:var(--terracotta)}
.rb-audit-fold summary{cursor:pointer;font-weight:800;font-size:15px;color:var(--ink);
  letter-spacing:-.2px;padding:2px 0}
.rb-audit-fold summary:focus-visible{outline:3px solid var(--gold);outline-offset:3px}
.rb-audit-fold[open] summary{margin-bottom:8px}
.rb-audit-topic{background:var(--surface-2);border:1px solid var(--line);border-radius:12px;
  padding:15px 16px;margin-top:13px}
.rb-audit-head{display:flex;align-items:center;justify-content:space-between;gap:12px}
.rb-audit-head h3{margin:0;font-size:16px;color:var(--ink)}
.rb-audit-list{list-style:none;margin:8px 0 0;padding:0}
.rb-audit-row{display:grid;grid-template-columns:auto minmax(0,1fr) auto auto minmax(120px,.55fr);
  align-items:center;gap:9px;border-top:1px solid var(--line);padding:9px 0;color:var(--ink-soft)}
.rb-audit-row:first-child{border-top:0}.rb-audit-title{overflow-wrap:anywhere}
.rb-audit-reason{color:var(--ink-muted);font-size:12.5px}
.rb-pill{font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:800;text-transform:uppercase;
  border-radius:999px;padding:3px 7px;border:1px solid var(--line)}
.rb-pill.show{color:var(--teal);background:#D6E7EA}.rb-pill.hide{color:var(--terra);background:#F2E0D7}
.rb-term{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
  padding:17px 18px;margin-top:12px;box-shadow:var(--shadow)}
.rb-term h3{margin:0 0 6px;font-size:16px;color:var(--ink)}
.rb-term p{margin:0;color:var(--ink-soft)}
.rb-vault-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:12px 0 18px}
.rb-vault-cols{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin-top:8px}
.rb-vault-cols h3{font-size:14px;margin:0 0 10px;text-transform:uppercase;letter-spacing:.4px;color:var(--ink-muted)}
.rb-vault-note{background:var(--surface-2);border:1px solid var(--line);border-radius:12px;
  padding:14px;margin-top:10px}
.rb-vault-note h3{margin:4px 0 6px;font-size:16px;color:var(--ink)}
.rb-vault-kind{font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--terra);
  text-transform:uppercase;letter-spacing:.5px;font-weight:800}
.rb-concept{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
  padding:17px 18px;margin-top:12px;box-shadow:var(--shadow)}
.rb-concept-head{width:100%;display:flex;align-items:center;justify-content:space-between;gap:14px;
  appearance:none;border:0;background:transparent;color:var(--ink);padding:0;text-align:left;cursor:pointer}
.rb-concept-head strong{display:block;font-size:16px}.rb-concept-head small{display:block;color:var(--ink-muted);margin-top:2px}
.rb-open{font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--terra);font-weight:800}
.rb-tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.rb-chip{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:3px 8px;
  color:var(--ink-muted);font-size:12px;background:var(--surface-2)}
.rb-concept-body{border-top:1px solid var(--line);margin-top:14px;padding-top:14px}
.rb-obsidian-cta{background:color-mix(in srgb,var(--teal) 8%,transparent);
  border:1px solid color-mix(in srgb,var(--teal) 22%,transparent);border-radius:10px;padding:10px 13px}
.rb-obsidian{font-weight:700;white-space:nowrap}
.rb-tagbar{display:flex;flex-wrap:wrap;gap:7px;margin:10px 0 4px}
.rb-tagfilter{appearance:none;border:1px solid var(--line);background:var(--surface);color:var(--ink-soft);
  border-radius:999px;padding:5px 12px;font-size:12px;font-weight:700;cursor:pointer;min-height:32px}
.rb-tagfilter:hover{border-color:var(--teal)}
.rb-tagfilter.is-on{background:var(--ink);border-color:var(--ink);color:var(--surface)}
.rb-tagfilter:focus-visible{outline:3px solid var(--gold);outline-offset:2px}
.rb-concept-body h3{font-size:13px;margin:12px 0 6px;text-transform:uppercase;letter-spacing:.4px;color:var(--ink-muted)}
.rb-sources{margin:4px 0 10px;padding-left:18px}.rb-sources li{margin:4px 0;color:var(--ink-soft)}
.rb-filebar{margin-bottom:10px}.rb-file{font-weight:800}.rb-empty,.rb-muted{color:var(--ink-muted)}
pre{white-space:pre-wrap;overflow:auto;max-height:420px;background:var(--surface-2);border:1px solid var(--line);
  border-radius:10px;padding:14px;color:var(--ink-soft);font:12px/1.55 'JetBrains Mono',ui-monospace,monospace}
.to-top{position:fixed;right:22px;bottom:22px;z-index:8;width:44px;height:44px;border-radius:50%;
  border:1px solid var(--line);background:var(--ink);color:var(--surface);box-shadow:var(--shadow-hover);
  font-size:22px;font-weight:900;line-height:1;cursor:pointer;opacity:0;pointer-events:none;
  transform:translateY(8px);transition:opacity .18s,transform .18s}
.to-top.show{opacity:1;pointer-events:auto;transform:none}
.to-top:focus-visible{outline:3px solid var(--gold);outline-offset:3px}
a{color:var(--terra);font-weight:600;text-decoration:none}
a:hover{text-decoration:underline}
main code{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:12.5px;
  background:var(--surface-2);border:1px solid var(--line);border-radius:6px;padding:1px 5px;color:var(--ink-soft)}
.rb-mom{font-weight:800;font-size:12px;cursor:default}
.rb-mom.up{color:var(--olive)}.rb-mom.down{color:var(--terra)}
.rb-why{font-size:11.5px;color:var(--ink-muted);background:var(--surface-2);
  border:1px solid var(--line);border-radius:999px;padding:1px 8px;white-space:nowrap}
.rb-today .rb-today-item{display:flex;align-items:center;gap:10px;flex-wrap:wrap;
  padding:8px 0 8px 20px}
.rb-today .rb-today-item .rb-mini{margin-left:auto;font-family:'JetBrains Mono',ui-monospace,monospace}
.rb-progress{float:right;font-family:'JetBrains Mono',ui-monospace,monospace;font-size:12px;
  font-weight:500;color:var(--ink-muted)}
li.seen>a{color:var(--ink-muted)}li.seen{opacity:.72}
.rb-star{appearance:none;border:0;background:none;cursor:pointer;font-size:18px;line-height:1;
  color:var(--ink-muted);min-width:40px;min-height:40px;display:inline-flex;align-items:center;
  justify-content:center;vertical-align:middle;border-radius:8px}
.rb-star.on{color:var(--gold)}
.rb-star:hover{background:color-mix(in srgb,var(--gold) 12%,transparent)}
.rb-star:focus-visible{outline:3px solid var(--gold);outline-offset:2px}
.rb-tier{display:inline-block;font-size:10px;font-weight:800;text-transform:uppercase;
  letter-spacing:.04em;padding:2px 7px;border-radius:999px;margin-left:6px;vertical-align:middle}
.rb-tier-high{background:color-mix(in srgb,var(--teal) 16%,transparent);color:var(--teal)}
.rb-tier-medium{background:color-mix(in srgb,var(--gold) 20%,transparent);color:var(--gold)}
.rb-tier-low{background:color-mix(in srgb,var(--terra) 18%,transparent);color:var(--terra)}
.rb-tier-untiered{background:var(--surface-2);color:var(--ink-muted)}
.rb-tier-note{color:var(--terra);font-weight:600}
.rb-pickbar{position:fixed;left:50%;transform:translateX(-50%);bottom:20px;z-index:9;
  display:flex;align-items:center;gap:12px;padding:10px 16px;border-radius:999px;
  background:var(--ink);color:var(--surface);box-shadow:var(--shadow-hover)}
.rb-pickbar[hidden]{display:none}
.rb-pickbar-count{font-weight:700;font-size:13.5px}
.rb-pickbar button{appearance:none;border:1px solid color-mix(in srgb,var(--surface) 35%,transparent);
  background:none;color:var(--surface);border-radius:999px;padding:5px 12px;font-weight:700;
  font-size:12.5px;cursor:pointer}
.rb-pickbar button:hover{background:color-mix(in srgb,var(--surface) 12%,transparent)}
.rb-pickbar button:focus-visible{outline:3px solid var(--gold);outline-offset:2px}
.rb-md-modal{border:0;padding:0;background:transparent;width:min(780px,92vw)}
.rb-md-modal::backdrop{background:rgba(27,24,21,.55)}
.rb-md-frame{display:flex;flex-direction:column;max-height:86vh;background:var(--surface);
  border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow-hover)}
.rb-md-head{display:flex;align-items:center;justify-content:space-between;gap:14px;
  padding:16px 20px;border-bottom:1px solid var(--line)}
.rb-md-head h2{margin:0;font-size:17px;color:var(--ink)}
.rb-md-tools{display:flex;align-items:center;gap:12px;flex:none;font-size:13px}
.rb-md-close{appearance:none;border:1px solid var(--line);background:var(--surface-2);color:var(--ink);
  border-radius:8px;width:32px;height:32px;font-size:17px;font-weight:800;line-height:1;cursor:pointer}
.rb-md-body{padding:4px 22px 22px;overflow:auto;color:var(--ink-soft)}
.rb-md-body h2,.rb-md-body h3,.rb-md-body h4{color:var(--ink);letter-spacing:-.2px}
.rb-md-body h2{font-size:19px;margin:18px 0 8px}.rb-md-body h3{font-size:16px;margin:14px 0 6px}
.rb-md-body h4{font-size:14px;margin:12px 0 4px}
.rb-md-body code{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:12.5px;
  background:var(--surface-2);border:1px solid var(--line);border-radius:6px;padding:1px 5px;color:var(--ink-soft)}
.rb-md-body pre code{border:0;background:transparent;padding:0}
.rb-md-body blockquote{margin:8px 0;padding:4px 0 4px 14px;border-left:3px solid var(--line);color:var(--ink-muted)}
.rb-md-fm{margin:10px 0}
.rb-md-fm summary{cursor:pointer;color:var(--ink-muted);font-size:12.5px;font-weight:700;
  text-transform:uppercase;letter-spacing:.4px}
.rb-wiki{border:1px solid var(--line);border-radius:999px;padding:1px 8px;background:var(--surface-2);
  color:var(--ink-muted);font-size:13px;white-space:nowrap}
.rb-md-inline{padding:0;overflow:visible;font-size:14px}
.rb-md-inline>:first-child{margin-top:0}
.reveal{opacity:0;animation:rise .6s cubic-bezier(.22,1,.36,1) forwards}
.reveal.pending{opacity:0;animation:none}
.reveal.in{opacity:1}
@keyframes rise{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
@media (max-width:560px){.hero{padding:26px 22px}.hero h1{font-size:22px}.rb-card{padding:18px 18px}
  .tabs{overflow:auto}.tab{white-space:nowrap}.rb-toolrow{align-items:stretch;flex-direction:column}
  .rb-vault-cols{grid-template-columns:1fr}
  .rb-audit-row{grid-template-columns:1fr;gap:4px}
  .to-top{right:14px;bottom:14px;width:40px;height:40px}}
@media (prefers-reduced-motion:reduce){.reveal{animation:none;opacity:1}}
/* Dark mode — override only the tokens; every rule already reads them, so the
   palette flips wholesale while the terracotta/olive/teal/gold accents stay put.
   Accent-tinted chip backgrounds (badge/callout) are nudged to hold contrast. */
@media (prefers-color-scheme: dark){
  :root{
    --bg:#1B1815;--surface:#232019;--surface-2:#2A251E;--ink:#EDE6D8;--ink-soft:#D4C9B6;
    --ink-muted:#A99D88;--line:#3A342B;--terra:#D08A63;--terracotta:#C17B5C;
    --olive:#8FA07A;--teal:#5FA3AE;--gold:#D6AA4E;
    --shadow:0 1px 2px rgba(0,0,0,.30),0 8px 24px rgba(0,0,0,.38);
    --shadow-hover:0 2px 6px rgba(0,0,0,.34),0 14px 38px rgba(0,0,0,.46);
  }
  .rb-badge{color:#BFE3EA;background:#12343B}
  .rb-pill.show{color:#BFE3EA;background:#12343B}
  .rb-pill.hide{color:#F3B99B;background:#3C241B}
  .rb-callout{background:linear-gradient(150deg,#2A251E,#221E18)}
  .tab[aria-selected="true"]{background:#EDE6D8;color:#1B1815}
}
/* Print — flatten to clean black-on-white with no motion or shadows so the page
   exports faithfully to PDF; keep each card intact across page breaks. */
@media print{
  :root{--bg:#fff;--surface:#fff;--surface-2:#fff;--ink:#000;--ink-soft:#000;
    --ink-muted:#333;--line:#ccc;--shadow:none;--shadow-hover:none}
  body{background:#fff;color:#000}
  .hero{background:#fff;color:#000;border:1px solid var(--line);box-shadow:none}
  .hero .sub{color:#333}
  .hero::after{display:none}
  .tabs{position:static}.tab{box-shadow:none}.panel[hidden]{display:block}
  .to-top{display:none}.rb-md-modal{display:none}
  .reveal{opacity:1;animation:none}
  .rb-card,.rb-kpi,.rb-callout{box-shadow:none;break-inside:avoid}
}
"""

# Self-contained script: count each KPI up from 0, and reveal sections as they
# scroll into view. No external dependencies; degrades gracefully without JS.
REPORT_SCRIPT = """
(function(){
  var nums=document.querySelectorAll('.rb-kpi-num');
  nums.forEach(function(el){
    var target=parseInt(el.getAttribute('data-target'),10);
    if(isNaN(target)){return;}
    var start=null,dur=900;
    function step(ts){
      if(!start){start=ts;}
      var p=Math.min((ts-start)/dur,1);
      el.textContent=Math.round(target*(0.2+0.8*p*(2-p)));
      if(p<1){requestAnimationFrame(step);}else{el.textContent=target;}
    }
    requestAnimationFrame(step);
  });
  if('IntersectionObserver' in window){
    var obs=new IntersectionObserver(function(entries){
      entries.forEach(function(e){if(e.isIntersecting){e.target.classList.add('in');obs.unobserve(e.target);}});
    },{threshold:0.08});
    document.querySelectorAll('.reveal').forEach(function(el){obs.observe(el);});
  }
  var tabs=[].slice.call(document.querySelectorAll('.tab'));
  function activateTab(tab,focus){
    tabs.forEach(function(t){t.setAttribute('aria-selected','false');t.tabIndex=-1;});
    document.querySelectorAll('.panel').forEach(function(p){p.hidden=true;});
    tab.setAttribute('aria-selected','true');tab.tabIndex=0;
    var panel=document.getElementById(tab.getAttribute('aria-controls'));
    if(panel){panel.hidden=false;}
    if(focus){tab.focus();}
  }
  tabs.forEach(function(tab,i){
    tab.addEventListener('click',function(){activateTab(tab,false);});
    // Full ARIA tabs keyboard pattern: arrows move + activate, Home/End jump.
    tab.addEventListener('keydown',function(ev){
      var n=null;
      if(ev.key==='ArrowRight'){n=tabs[(i+1)%tabs.length];}
      else if(ev.key==='ArrowLeft'){n=tabs[(i-1+tabs.length)%tabs.length];}
      else if(ev.key==='Home'){n=tabs[0];}
      else if(ev.key==='End'){n=tabs[tabs.length-1];}
      if(n){ev.preventDefault();activateTab(n,true);}
    });
  });
  document.querySelectorAll('.rb-concept-head').forEach(function(btn){
    btn.addEventListener('click',function(){
      var body=btn.parentElement.querySelector('.rb-concept-body');
      var open=body && body.hidden;
      if(body){body.hidden=!open;}
      btn.setAttribute('aria-expanded',open?'true':'false');
      var label=btn.querySelector('.rb-open');
      if(label){label.textContent=open?'Close':'Open';}
    });
  });
  var search=document.getElementById('conceptSearch');
  var activeTag='';
  function applyConceptFilters(){
    var q=search?search.value.trim().toLowerCase():'';
    document.querySelectorAll('.rb-concept').forEach(function(card){
      var matchQ=!q || card.getAttribute('data-search').indexOf(q)!==-1;
      var tags=(card.getAttribute('data-tags')||'').split(' ');
      var matchTag=!activeTag || tags.indexOf(activeTag)!==-1;
      card.hidden=!(matchQ && matchTag);
    });
  }
  if(search){search.addEventListener('input',applyConceptFilters);}
  document.querySelectorAll('.rb-tagfilter').forEach(function(chip){
    chip.addEventListener('click',function(){
      activeTag=chip.getAttribute('data-tag-filter')||'';
      document.querySelectorAll('.rb-tagfilter').forEach(function(c){c.classList.remove('is-on');});
      chip.classList.add('is-on');
      applyConceptFilters();
    });
  });
  var glossarySearch=document.getElementById('glossarySearch');
  if(glossarySearch){
    glossarySearch.addEventListener('input',function(){
      var q=glossarySearch.value.trim().toLowerCase();
      document.querySelectorAll('.rb-term').forEach(function(card){
        card.hidden=q && card.getAttribute('data-search').indexOf(q)===-1;
      });
    });
  }
  var toTop=document.getElementById('toTop');
  if(toTop){
    var toggleTop=function(){toTop.classList.toggle('show',window.scrollY>360);};
    window.addEventListener('scroll',toggleTop,{passive:true});
    toggleTop();
    toTop.addEventListener('click',function(){window.scrollTo({top:0,behavior:'smooth'});});
  }
  /* Vault-file modal: intercept `open concept file` / `open note`, fetch the
     markdown and render it in-page with a small dependency-free renderer.
     Every file line is HTML-escaped BEFORE any markdown transform, so a vault
     note can never inject live markup. Under file:// fetch is origin-blocked,
     and on any fetch failure, the link falls back to plain navigation (the
     pre-modal behavior). */
  var mdModal=document.getElementById('rbMdModal');
  if(mdModal){
    var mdBody=document.getElementById('rbMdBody');
    var mdTitle=document.getElementById('rbMdTitle');
    var mdRaw=document.getElementById('rbMdRaw');
    var mdClose=document.getElementById('rbMdClose');
    function mdEscape(s){
      return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }
    function mdInline(s){
      s=s.replace(/`([^`]+)`/g,'<code>$1</code>');
      s=s.replace(/\\[\\[([^\\]]+)\\]\\]/g,'<span class="rb-wiki">$1</span>');
      s=s.replace(/\\[([^\\]]+)\\]\\(([^()\\s]+)\\)/g,function(m,t,u){
        return /^(https?:|\\.|\\/|#)/.test(u)
          ?'<a href="'+u+'" target="_blank" rel="noopener">'+t+'</a>':t;
      });
      s=s.replace(/\\*\\*([^*]+)\\*\\*/g,'<strong>$1</strong>');
      s=s.replace(/\\*([^*\\n]+)\\*/g,'<em>$1</em>');
      return s;
    }
    function mdRender(text){
      var lines=text.replace(/\\r/g,'').split('\\n');
      var out=[],i=0,fm=[];
      if(lines[0]==='---'){
        var j=1;
        while(j<lines.length&&lines[j]!=='---'){fm.push(lines[j]);j++;}
        if(j<lines.length){i=j+1;}else{fm=[];}
      }
      var inCode=false,inList=null,para=[];
      function flushPara(){
        if(para.length){out.push('<p>'+mdInline(mdEscape(para.join(' ')))+'</p>');para=[];}
      }
      function closeList(){if(inList){out.push('</'+inList+'>');inList=null;}}
      for(;i<lines.length;i++){
        var ln=lines[i];
        if(/^```/.test(ln)){
          flushPara();closeList();
          out.push(inCode?'</code></pre>':'<pre><code>');
          inCode=!inCode;continue;
        }
        if(inCode){out.push(mdEscape(ln)+'\\n');continue;}
        var h=ln.match(/^(#{1,4})\\s+(.*)$/);
        if(h){
          flushPara();closeList();
          var lvl=Math.min(h[1].length+1,6);
          out.push('<h'+lvl+'>'+mdInline(mdEscape(h[2]))+'</h'+lvl+'>');continue;
        }
        if(/^\\s*[-*+]\\s+/.test(ln)){
          flushPara();
          if(inList!=='ul'){closeList();out.push('<ul>');inList='ul';}
          out.push('<li>'+mdInline(mdEscape(ln.replace(/^\\s*[-*+]\\s+/,'')))+'</li>');continue;
        }
        if(/^\\s*\\d+\\.\\s+/.test(ln)){
          flushPara();
          if(inList!=='ol'){closeList();out.push('<ol>');inList='ol';}
          out.push('<li>'+mdInline(mdEscape(ln.replace(/^\\s*\\d+\\.\\s+/,'')))+'</li>');continue;
        }
        if(/^\\s*>\\s?/.test(ln)){
          flushPara();closeList();
          out.push('<blockquote>'+mdInline(mdEscape(ln.replace(/^\\s*>\\s?/,'')))+'</blockquote>');continue;
        }
        if(/^\\s*(---+|\\*\\*\\*+)\\s*$/.test(ln)){flushPara();closeList();out.push('<hr>');continue;}
        if(/^\\s*$/.test(ln)){flushPara();closeList();continue;}
        para.push(ln.trim());
      }
      flushPara();closeList();
      if(inCode){out.push('</code></pre>');}
      var fmHtml=fm.length
        ?'<details class="rb-md-fm"><summary>frontmatter</summary><pre>'+mdEscape(fm.join('\\n'))+'</pre></details>'
        :'';
      return fmHtml+out.join('');
    }
    function closeMd(){if(mdModal.close){mdModal.close();}else{mdModal.removeAttribute('open');}}
    function openMd(link){
      var href=link.getAttribute('href');
      fetch(href).then(function(r){
        if(!r.ok){throw new Error(String(r.status));}
        return r.text();
      }).then(function(text){
        mdTitle.textContent=link.getAttribute('data-md-title')||href.split('/').pop();
        mdBody.innerHTML=mdRender(text);
        mdRaw.setAttribute('href',href);
        if(mdModal.showModal){mdModal.showModal();}else{mdModal.setAttribute('open','');}
        mdBody.scrollTop=0;
      }).catch(function(){window.location.href=href;});
    }
    if(location.protocol!=='file:'){
      document.addEventListener('click',function(e){
        var link=e.target&&e.target.closest?e.target.closest('a.rb-file'):null;
        if(!link){return;}
        e.preventDefault();
        openMd(link);
      });
    }
    mdClose.addEventListener('click',closeMd);
    mdModal.addEventListener('click',function(e){if(e.target===mdModal){closeMd();}});
    /* Upgrade the concept-note previews to rendered markdown with the SAME
       renderer as the modal (the two views can't drift); without JS the raw
       <pre> text stays readable. */
    document.querySelectorAll('pre.rb-note-md').forEach(function(el){
      var div=document.createElement('div');
      div.className='rb-md-body rb-md-inline';
      div.innerHTML=mdRender(el.textContent);
      el.replaceWith(div);
    });
  }
})();
/* Reader state — read-marks and starred picks, per digest, in localStorage.
   Everything degrades gracefully: storage errors are swallowed, and without
   JS the page simply shows no progress counter, stars, or pick bar. */
(function(){
  var id=document.body.getAttribute('data-digest-id')||'digest';
  var SEEN='rb-seen:'+id, STAR='rb-star:'+id;
  function load(key){try{return JSON.parse(localStorage.getItem(key)||'{}')}catch(e){return {}}}
  function save(key,value){try{localStorage.setItem(key,JSON.stringify(value))}catch(e){}}
  var seen=load(SEEN), stars=load(STAR);
  var rows=[].slice.call(document.querySelectorAll('#panel-digest li[data-url]'));
  var sourceUrls={};
  document.querySelectorAll('#panel-digest .rb-list li[data-url]').forEach(function(row){
    sourceUrls[row.getAttribute('data-url')]=1;
  });
  function refresh(){
    rows.forEach(function(row){
      var url=row.getAttribute('data-url');
      row.classList.toggle('seen',!!seen[url]);
      var btn=row.querySelector('.rb-star');
      if(btn){
        var on=!!stars[url];
        btn.setAttribute('aria-pressed',on?'true':'false');
        btn.textContent=on?'★':'☆';
        btn.classList.toggle('on',on);
      }
    });
    var total=Object.keys(sourceUrls).length;
    var read=Object.keys(seen).filter(function(url){return sourceUrls[url];}).length;
    var slot=document.getElementById('readProgress');
    if(slot){slot.textContent=total?read+' of '+total+' read':'';}
    var picked=Object.keys(stars).length;
    var bar=document.getElementById('pickBar');
    if(bar){
      bar.hidden=!picked;
      var count=document.getElementById('pickCount');
      if(count){count.textContent=picked+' pick'+(picked===1?'':'s');}
    }
  }
  document.addEventListener('click',function(ev){
    if(!ev.target.closest){return;}
    var star=ev.target.closest('.rb-star');
    if(star){
      var url=star.getAttribute('data-url');
      if(stars[url]){delete stars[url];}
      else{
        var li=star.closest('li');
        var link=li?li.querySelector('a[href]'):null;
        stars[url]=link?link.textContent.replace(/\\s+/g,' ').trim():url;
      }
      save(STAR,stars);refresh();ev.preventDefault();return;
    }
    var opened=ev.target.closest('#panel-digest li[data-url] a[href]');
    if(opened){
      var row=opened.closest('li[data-url]');
      seen[row.getAttribute('data-url')]=1;
      save(SEEN,seen);refresh();
    }
  });
  function picksMessage(){
    var lines=Object.keys(stars).map(function(url){return '- '+stars[url]+' — '+url;});
    return '⭐ Picks from '+(document.title||'digest')+':\\n'+lines.join('\\n');
  }
  var share=document.getElementById('pickShare');
  if(share){
    share.addEventListener('click',function(){
      var first=Object.keys(stars)[0]||'';
      window.open('https://t.me/share/url?url='+encodeURIComponent(first)
        +'&text='+encodeURIComponent(picksMessage()),'_blank','noopener');
    });
  }
  var copy=document.getElementById('pickCopy');
  if(copy){
    copy.addEventListener('click',function(){
      if(navigator.clipboard&&navigator.clipboard.writeText){
        navigator.clipboard.writeText(picksMessage()).then(function(){
          copy.textContent='Copied!';
          setTimeout(function(){copy.textContent='Copy';},1500);
        });
      }
    });
  }
  refresh();
})();
"""

REPORT_FONT_LINKS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    # css2 variation tuples must carry one value PER axis (ital,opsz,wght → 3):
    # a short `;500` tuple is an HTTP 400 and the fonts silently never load.
    '<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@1,9..144,400'
    ";1,9..144,500&family=Manrope:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500"
    ';600;700&display=swap" rel="stylesheet">'
)


__all__ = [
    "REPORT_FONT_LINKS",
    "REPORT_SCRIPT",
    "REPORT_STYLE",
]
