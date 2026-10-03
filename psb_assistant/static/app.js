"use strict";
const $ = id => document.getElementById(id);
const labels = {deposits:"Вклад / счет",loans:"Кредит",cards:"Банковская карта"};
let products = [], category = "all", selected = new Set();
let startupPolling = null;
const node = (tag, text, className) => {const e=document.createElement(tag); if(text!==undefined)e.textContent=text;if(className)e.className=className;return e;};
function source(url, title="Источник ПСБ ↗") {
  const a=node("a",title); const u=new URL(url);
  if(u.protocol!=="https:"||u.hostname!=="www.psbank.ru")throw new Error("Неверный источник");
  a.href=u.href;a.target="_blank";a.rel="noopener noreferrer";return a;
}
async function api(path, body) {
  const response=await fetch(path,body===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  if(!response.ok)throw new Error(response.status===409?"Обновление уже выполняется":"Не удалось выполнить запрос. Попробуйте еще раз.");
  return response.json();
}
function addFact(parent,key,fact) {const block=node("div",undefined,"fact");block.append(node("span",key,"fact-label"),node("div",fact.value),source(fact.source_url));parent.append(block);}
function card(product, selectable=false, date=null) {
  const e=node("article",undefined,"card");if(selected.has(product.source_url)&&selectable)e.classList.add("selected");
  if(product.category)e.append(node("div",labels[product.category],"category"));
  e.append(node("h3",product.product_name));
  const summary=node("p",product.summary.value,"summary");summary.append(document.createTextNode(" "),source(product.summary.source_url,"↗"));e.append(summary);
  const entries=Object.entries(product.params);entries.slice(0,2).forEach(([key,fact])=>addFact(e,key,fact));
  if(entries.length>2){const details=node("details");details.append(node("summary","Все условия ("+entries.length+")"));entries.slice(2).forEach(([key,fact])=>addFact(details,key,fact));e.append(details);}
  const timestamp=date||product.fetched_at;if(timestamp)e.append(node("div","Загружено: "+new Date(timestamp).toLocaleString("ru-RU"),"date"));
  const footer=node("div",undefined,"card-footer");footer.append(source(product.source_url,"Полные условия ↗"));
  if(selectable){const label=node("label",undefined,"select-product");const checkbox=node("input");checkbox.type="checkbox";checkbox.checked=selected.has(product.source_url);checkbox.addEventListener("change",()=>{if(checkbox.checked&&selected.size>=3){checkbox.checked=false;alert("Можно сравнить максимум 3 продукта.");return;}checkbox.checked?selected.add(product.source_url):selected.delete(product.source_url);renderCatalog();});label.append(checkbox,document.createTextNode("Сравнить"));footer.append(label);}
  e.append(footer);return e;
}
function renderCatalog() {
  $("catalog").replaceChildren();const visible=products.filter(p=>category==="all"||p.category===category);
  if(!visible.length){const empty=node("div",undefined,"empty");empty.append(node("h3",products.length?"В этой категории пока нет продуктов":"Каталог пока пуст"),node("p","Нажмите «Обновить каталог». Ассистент загрузит публичные страницы ПСБ, если сайт доступен и robots.txt разрешает обход."));$("catalog").append(empty);}
  visible.forEach(p=>$("catalog").append(card(p,true)));
  $("compare-bar").classList.toggle("hidden",selected.size===0);$("selected-count").textContent="Выбрано продуктов: "+selected.size+" / 3";$("compare").disabled=selected.size<2;
}
async function load() {
  try {const health=await api("/api/health");products=await api("/api/products");renderCatalog();
    $("status").textContent=health.running?"Загружаем страницы ПСБ…":health.products+" продуктов · "+(health.ready?"все категории доступны":"база заполнена не полностью");
    if(health.running){if(!startupPolling)startupPolling=setInterval(load,5000);}else{clearInterval(startupPolling);startupPolling=null;}
    if(!health.running&&health.last_report?.errors?.length)$("status").textContent="Часть страниц не загрузилась. Сохраненные данные доступны.";
  }catch(error){$("status").textContent=error.message;}
}
function showAnswer(answer) {
  const root=$("answer");root.classList.remove("hidden");root.replaceChildren(node("h2",answer.mode==="compare"?"Сравнение условий":"Ответ по источникам"),node("p",answer.message));
  answer.warnings.forEach(w=>root.append(node("p",w,"warning")));
  if(answer.mode==="compare"&&answer.insights?.length){
    const section=node("section",undefined,"comparison-insights");section.append(node("h3","Что отличается"));
    answer.insights.forEach(insight=>{const item=node("article",undefined,"insight");item.append(node("h4",insight.title),node("p",insight.explanation));Object.entries(insight.evidence||{}).forEach(([name,fact])=>{const p=node("p",undefined,"evidence");p.append(node("strong",name+": "),node("span",fact.value),source(fact.source_url," ↗"));item.append(p);});section.append(item);});root.append(section);
  }
  if(answer.mode==="compare"&&answer.clarifications?.length){const section=node("section",undefined,"clarifications");section.append(node("h3","Чтобы определить, что выгоднее"));const list=node("ul");answer.clarifications.forEach(q=>list.append(node("li",q)));section.append(list);root.append(section);}
  if(answer.mode==="compare"&&answer.products.length>=2){
    const wrap=node("div",undefined,"table-wrap"),table=node("table"),head=node("thead"),hr=node("tr");hr.append(node("th","Параметр"));answer.products.forEach(p=>{const cell=node("th",p.product_name);cell.append(source(p.source_url));hr.append(cell);});head.append(hr);table.append(head);
    const body=node("tbody"),keys=[...new Set(answer.products.flatMap(p=>Object.keys(p.params)))];keys.forEach(key=>{const row=node("tr");row.append(node("th",key));answer.products.forEach(p=>{const fact=p.params[key];const cell=node("td",fact?fact.value:"Не найдено в сохраненной странице");if(fact)cell.append(source(fact.source_url));row.append(cell);});body.append(row);});
    const dates=node("tr");dates.append(node("th","Дата загрузки"));answer.products.forEach(p=>dates.append(node("td",answer.fetched_at[p.source_url]?new Date(answer.fetched_at[p.source_url]).toLocaleString("ru-RU"):"—")));body.append(dates);table.append(body);wrap.append(table);root.append(wrap);
  }else{const grid=node("div",undefined,"grid");answer.products.forEach(p=>grid.append(card(p,false,answer.fetched_at[p.source_url])));root.append(grid);}
  root.scrollIntoView({behavior:"smooth",block:"start"});
}
function showError(error) {showAnswer({mode:"search",message:error.message,products:[],warnings:[],fetched_at:{}});}
$("ask-form").addEventListener("submit",async event=>{event.preventDefault();$("ask-button").disabled=true;try{showAnswer(await api("/api/ask",{query:$("query").value.trim()}));}catch(error){showError(error);}finally{$("ask-button").disabled=false;}});
document.querySelectorAll("[data-query]").forEach(b=>b.addEventListener("click",()=>{$("query").value=b.dataset.query;$("ask-form").requestSubmit();}));
document.querySelectorAll("[data-category]").forEach(b=>b.addEventListener("click",()=>{category=b.dataset.category;document.querySelectorAll("[data-category]").forEach(e=>e.classList.toggle("active",e===b));renderCatalog();}));
$("refresh").addEventListener("click",async()=>{$("refresh").disabled=true;$("status").textContent="Обновляем каталог с учетом кеша…";try{const report=await api("/api/refresh",{force:false});await load();if(report.errors.length)showAnswer({mode:"search",message:"Некоторые страницы не удалось обновить.",products:[],warnings:report.errors,fetched_at:{}});}catch(error){showError(error);}finally{$("refresh").disabled=false;}});
$("compare").addEventListener("click",async()=>{$("compare").disabled=true;try{showAnswer(await api("/api/compare",{urls:[...selected]}));}catch(error){showError(error);}finally{$("compare").disabled=selected.size<2;}});
$("clear-selection").addEventListener("click",()=>{selected.clear();renderCatalog();});
load();
