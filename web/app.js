// Saqi farm page. Every number shown comes from the API (engine/); this file only formats.
"use strict";

const T = {
  en: {
    chatTitle: "Ask Saqi", chatHint: "Ask about today's advice, or tell Saqi what you irrigated and it will log it.",
    send: "Send", thinking: "Thinking…", loggedNote: (rt, d) => `Logged: ${rt} on ${d}`,
    chatError: "Saqi couldn't answer.",
    chips: ["Why this amount today?", "I irrigated 2 hours today", "Is rain coming this week?"],
    farm: "Farm", loading: "Loading today's plan…", why: "How this was worked out",
    logOpen: "Log irrigation", date: "Date", howMuch: "How much did you run?",
    byTime: "Hours", byMm: "Millimetres", h: "h", min: "min", note: "Note (optional)",
    save: "Save irrigation", cancel: "Cancel", pastWeek: "Last 7 days: planned and done",
    day: "Day", planned: "Planned", done: "Done",
    pastNote: "Days without a log are counted as if the plan was followed.",
    today: "Today", irrigateToday: "Irrigate today", noIrrigation: "No irrigation",
    withSystem: (mm, sys) => `${mm} mm with ${sys}`,
    nextOn: (day, rt) => `Next: ${day}, about ${rt}`,
    noneSoon: "None needed in the next 6 days.",
    carry: (max) => `That's longer than a ${max} set, so the rest continues tomorrow.`,
    continuing: "Finishing yesterday's refill.",
    waterLeft: (pct) => `Water left in the root zone: ${pct}%`,
    triggerLabel: "irrigate",
    meta: (crop, soil, sys, ha) => `${crop} on ${soil}, ${sys}, ${ha} ha`,
    why1: (et0, kc, etc, crop) => `Today the weather pulls about <span class="num">${et0} mm</span> from a reference crop. Your ${crop} at this stage uses <span class="num">${kc}%</span> of that, so <span class="num">${etc} mm</span>.`,
    whyRain: (peff, rain) => peff > 0 ? `Rain counted today: <span class="num">${peff} mm</span> of ${rain} mm forecast.` : (rain > 0 ? `${rain} mm of rain is forecast, too light to count (under 5 mm).` : "No rain is forecast today."),
    why2: (dr, raw, taw) => `The soil has given up <span class="num">${dr} mm</span>. Roots can reach <span class="num">${taw} mm</span> in total, and the crop starts to stress after <span class="num">${raw} mm</span>.`,
    why3go: (net, gross, eff, rt, rate) => `So refill <span class="num">${net} mm</span>. Some water is lost on the way (efficiency ${eff}%), so apply <span class="num">${gross} mm</span>: <span class="num">${rt}</span> at ${rate} mm/h.`,
    why3no: (left) => `That's below the stress line, so no water today. About <span class="num">${left} mm</span> to go before it's needed.`,
    whySource: "Weather: Open-Meteo. Method: FAO\u201156 water balance.",
    caveat: "Crop, soil and system values are textbook FAO\u201156 defaults until checked for this farm.",
    logged: "logged", assumed: "not logged", none: "—",
    saved: "Irrigation saved", errAmount: "Enter how long you ran, or how many mm.",
    errLoad: "Couldn't load the plan.", errSave: "Couldn't save.",
    crops: { potato: "potato", tomato: "tomato", wheat: "wheat", table_grapes: "table grapes", citrus: "citrus", olive: "olive", avocado: "avocado", apple: "apple" },
    soils: { sand: "sand", loamy_sand: "loamy sand", sandy_loam: "sandy loam", loam: "loam", silt_loam: "silt loam", clay_loam: "clay loam", clay: "clay" },
    systems: { drip: "drip", micro_sprinkler: "micro-sprinklers", sprinkler: "sprinklers", pivot: "pivot", surface: "surface irrigation" },
    hm: (h, m) => h && m ? `${h} h ${m} min` : h ? `${h} h` : `${m} min`,
  },
  fr: {
    chatTitle: "Demander à Saqi", chatHint: "Posez une question sur le conseil du jour, ou dites à Saqi ce que vous avez arrosé et il le notera.",
    send: "Envoyer", thinking: "Réflexion…", loggedNote: (rt, d) => `Noté : ${rt} le ${d}`,
    chatError: "Saqi n'a pas pu répondre.",
    chips: ["Pourquoi cette quantité ?", "J'ai arrosé 2 h aujourd'hui", "Va-t-il pleuvoir cette semaine ?"],
    farm: "Ferme", loading: "Chargement du plan du jour…", why: "Comment c'est calculé",
    logOpen: "Noter une irrigation", date: "Date", howMuch: "Combien avez-vous irrigué ?",
    byTime: "Heures", byMm: "Millimètres", h: "h", min: "min", note: "Remarque (facultatif)",
    save: "Enregistrer l'irrigation", cancel: "Annuler", pastWeek: "7 derniers jours : prévu et fait",
    day: "Jour", planned: "Prévu", done: "Fait",
    pastNote: "Les jours sans note sont comptés comme si le plan avait été suivi.",
    today: "Aujourd'hui", irrigateToday: "Irriguer aujourd'hui", noIrrigation: "Pas d'irrigation",
    withSystem: (mm, sys) => `${mm} mm en ${sys}`,
    nextOn: (day, rt) => `Prochaine : ${day}, environ ${rt}`,
    noneSoon: "Rien à prévoir dans les 6 prochains jours.",
    carry: (max) => `C'est plus long qu'un poste de ${max} : le reste continue demain.`,
    continuing: "Suite du remplissage d'hier.",
    waterLeft: (pct) => `Eau restante dans la zone racinaire : ${pct} %`,
    triggerLabel: "irriguer",
    meta: (crop, soil, sys, ha) => `${crop} sur ${soil}, ${sys}, ${ha} ha`,
    why1: (et0, kc, etc, crop) => `Aujourd'hui, le climat évapore environ <span class="num">${et0} mm</span> sur une culture de référence. À ce stade, votre culture (${crop}) en consomme <span class="num">${kc} %</span>, soit <span class="num">${etc} mm</span>.`,
    whyRain: (peff, rain) => peff > 0 ? `Pluie prise en compte : <span class="num">${peff} mm</span> sur ${rain} mm prévus.` : (rain > 0 ? `${rain} mm de pluie prévus, trop peu pour compter (moins de 5 mm).` : "Pas de pluie prévue aujourd'hui."),
    why2: (dr, raw, taw) => `Le sol a perdu <span class="num">${dr} mm</span>. Les racines disposent de <span class="num">${taw} mm</span> au total, et la culture commence à souffrir au-delà de <span class="num">${raw} mm</span>.`,
    why3go: (net, gross, eff, rt, rate) => `Il faut donc rendre <span class="num">${net} mm</span>. Une partie se perd en route (efficience ${eff} %), donc apportez <span class="num">${gross} mm</span> : <span class="num">${rt}</span> à ${rate} mm/h.`,
    why3no: (left) => `C'est en dessous du seuil de stress : pas d'eau aujourd'hui. Encore environ <span class="num">${left} mm</span> avant d'irriguer.`,
    whySource: "Météo : Open-Meteo. Méthode : bilan hydrique FAO\u201156.",
    caveat: "Les valeurs de culture, de sol et de système sont les valeurs FAO\u201156 par défaut, à vérifier pour cette ferme.",
    logged: "noté", assumed: "non noté", none: "—",
    saved: "Irrigation enregistrée", errAmount: "Indiquez la durée ou les millimètres.",
    errLoad: "Impossible de charger le plan.", errSave: "Échec de l'enregistrement.",
    crops: { potato: "pomme de terre", tomato: "tomate", wheat: "blé", table_grapes: "raisin de table", citrus: "agrumes", olive: "olivier", avocado: "avocatier", apple: "pommier" },
    soils: { sand: "sable", loamy_sand: "sable limoneux", sandy_loam: "limon sableux", loam: "limon", silt_loam: "limon silteux", clay_loam: "limon argileux", clay: "argile" },
    systems: { drip: "goutte-à-goutte", micro_sprinkler: "micro-aspersion", sprinkler: "aspersion", pivot: "pivot", surface: "irrigation gravitaire" },
    hm: (h, m) => h && m ? `${h} h ${m} min` : h ? `${h} h` : `${m} min`,
  },
  ar: {
    chatTitle: "اسأل ساقي", chatHint: "اسأل عن توصية اليوم، أو أخبر ساقي كم سقيت وهو يسجّلها.",
    send: "إرسال", thinking: "عم فكّر…", loggedNote: (rt, d) => `تم التسجيل: ${rt} بتاريخ ${d}`,
    chatError: "ما قدر ساقي يجاوب.",
    chips: ["ليش هالكمية اليوم؟", "سقيت ساعتين اليوم", "في شتي هالجمعة؟"],
    farm: "المزرعة", loading: "جارٍ تحميل خطة اليوم…", why: "كيف حُسبت هذه التوصية",
    logOpen: "سجّل الري", date: "التاريخ", howMuch: "كم شغّلت الري؟",
    byTime: "بالساعات", byMm: "بالمليمتر", h: "س", min: "د", note: "ملاحظة (اختياري)",
    save: "احفظ الري", cancel: "إلغاء", pastWeek: "آخر ٧ أيام: المخطط والمنفّذ",
    day: "اليوم", planned: "المخطط", done: "المنفّذ",
    pastNote: "الأيام غير المسجّلة تُحسب كأن الخطة نُفّذت.",
    today: "اليوم", irrigateToday: "اسقِ اليوم", noIrrigation: "لا ري اليوم",
    withSystem: (mm, sys) => `${mm} ملم عبر ${sys}`,
    nextOn: (day, rt) => `الري التالي: ${day}، حوالي ${rt}`,
    noneSoon: "لا حاجة للري في الأيام الستة القادمة.",
    carry: (max) => `المدة أطول من ${max} في المرة الواحدة، فيُكمَل الباقي غداً.`,
    continuing: "إكمال ري الأمس.",
    waterLeft: (pct) => `الماء المتبقي في منطقة الجذور: ${pct}٪`,
    triggerLabel: "اسقِ",
    meta: (crop, soil, sys, ha) => `${crop} في تربة ${soil}، الري: ${sys}، ${ha} هكتار`,
    why1: (et0, kc, etc, crop) => `الطقس اليوم يبخّر حوالي <span class="num">${et0} ملم</span> من محصول مرجعي. محصولك (${crop}) في هذه المرحلة يستهلك <span class="num">${kc}٪</span> من ذلك، أي <span class="num">${etc} ملم</span>.`,
    whyRain: (peff, rain) => peff > 0 ? `المطر المحسوب اليوم: <span class="num">${peff} ملم</span> من أصل ${rain} ملم متوقعة.` : (rain > 0 ? `${rain} ملم مطر متوقعة، وهي أقل من ٥ ملم فلا تُحسب.` : "لا مطر متوقع اليوم."),
    why2: (dr, raw, taw) => `فقدت التربة <span class="num">${dr} ملم</span>. تصل الجذور إلى <span class="num">${taw} ملم</span> في المجموع، ويبدأ الإجهاد بعد <span class="num">${raw} ملم</span>.`,
    why3go: (net, gross, eff, rt, rate) => `لذلك يجب تعويض <span class="num">${net} ملم</span>. يضيع جزء من الماء في الطريق (الكفاءة ${eff}٪)، فأضف <span class="num">${gross} ملم</span>: <span class="num">${rt}</span> بمعدل ${rate} ملم/ساعة.`,
    why3no: (left) => `هذا دون حدّ الإجهاد، فلا ري اليوم. بقي حوالي <span class="num">${left} ملم</span> قبل الحاجة للري.`,
    whySource: "الطقس: \u2066Open-Meteo\u2069. الطريقة: الموازنة المائية \u2066FAO\u201156\u2069.",
    caveat: "قيم المحصول والتربة ونظام الري هي القيم الافتراضية لـ \u2066FAO\u201156\u2069 إلى أن يتم التحقق منها لهذه المزرعة.",
    logged: "مسجّل", assumed: "غير مسجّل", none: "—",
    saved: "تم حفظ الري", errAmount: "أدخل مدة التشغيل أو الكمية بالمليمتر.",
    errLoad: "تعذّر تحميل الخطة.", errSave: "تعذّر الحفظ.",
    crops: { potato: "بطاطا", tomato: "بندورة", wheat: "قمح", table_grapes: "عنب المائدة", citrus: "حمضيات", olive: "زيتون", avocado: "أفوكادو", apple: "تفاح" },
    soils: { sand: "رملية", loamy_sand: "رملية طميية", sandy_loam: "طميية رملية", loam: "طميية", silt_loam: "طميية غرينية", clay_loam: "طميية طينية", clay: "طينية" },
    systems: { drip: "التنقيط", micro_sprinkler: "الرشاشات الصغيرة", sprinkler: "الرش", pivot: "الري المحوري", surface: "الري السطحي" },
    hm: (h, m) => h && m ? `${h} س ${m} د` : h ? `${h} س` : `${m} د`,
  },
};
const LOCALES = { en: "en-GB", fr: "fr-FR", ar: "ar-LB-u-nu-latn" };

let lang = pickLang();
let farms = [];
let current = null;
let chatOn = false;
const chats = {};
const $ = (sel, root = document) => root.querySelector(sel);

function pickLang() {
  try {
    const saved = localStorage.getItem("saqi.lang");
    if (saved && T[saved]) return saved;
  } catch (_) { /* storage blocked */ }
  const nav = (navigator.language || "en").slice(0, 2);
  return T[nav] ? nav : "en";
}
function t() { return T[lang]; }
function mm(x) { return (Math.round(x * 10) / 10).toFixed(1); }
function nf(x, d = 0) { return Number(x).toLocaleString(lang === "ar" ? "en-US" : LOCALES[lang], { maximumFractionDigits: d, minimumFractionDigits: d }); }
// Runtime to the nearest 5 minutes (a farmer can't set 3 h 17 min). Never round a real set to zero.
function hm(hours) {
  let mins = Math.round((hours * 60) / 5) * 5;
  if (hours > 0 && mins === 0) mins = 5;
  return t().hm(Math.floor(mins / 60), mins % 60);
}
function hmShort(hours) {
  let mins = Math.round((hours * 60) / 5) * 5;
  if (hours > 0 && mins === 0) mins = 5;
  return `${Math.floor(mins / 60)}:${String(mins % 60).padStart(2, "0")}`;
}
function parseDate(iso) { const [y, m, d] = iso.split("-").map(Number); return new Date(Date.UTC(y, m - 1, d)); }
function weekday(iso, style = "short") {
  return new Intl.DateTimeFormat(LOCALES[lang], { weekday: style, timeZone: "UTC" }).format(parseDate(iso));
}
function dayLabel(iso) {
  return new Intl.DateTimeFormat(LOCALES[lang], { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }).format(parseDate(iso));
}

function applyStatic() {
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const v = t()[el.dataset.i18n];
    if (typeof v === "string") el.textContent = v;
  });
  document.querySelectorAll(".lang button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === lang)));
}

async function api(path, opts) {
  const res = await fetch(`/api${path}`, opts);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail ? (typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail)) : res.statusText);
  return body;
}

function setStatus(text, isError = false) {
  const main = $("#main");
  main.innerHTML = "";
  const p = document.createElement("p");
  p.className = "status" + (isError ? " error" : "");
  p.textContent = text;
  main.append(p);
}

async function init() {
  applyStatic();
  document.querySelectorAll(".lang button").forEach((b) => b.addEventListener("click", () => {
    lang = b.dataset.lang;
    try { localStorage.setItem("saqi.lang", lang); } catch (_) { /* ignore */ }
    applyStatic();
    if (current) render(current);
  }));
  try {
    chatOn = (await api("/assistant")).enabled;
  } catch (_) { chatOn = false; }
  wireChat();
  try {
    farms = await api("/farms");
  } catch (e) {
    setStatus(`${t().errLoad} ${e.message}`, true);
    return;
  }
  const sel = $("#farm");
  sel.innerHTML = "";
  farms.forEach((f) => sel.add(new Option(f.name, f.id)));
  let chosen = new URLSearchParams(location.search).get("farm");
  if (!farms.some((f) => f.id === chosen)) {
    try { chosen = localStorage.getItem("saqi.farm"); } catch (_) { chosen = null; }
  }
  if (!farms.some((f) => f.id === chosen)) chosen = farms[0] && farms[0].id;
  sel.value = chosen;
  sel.addEventListener("change", () => load(sel.value));
  if (chosen) load(chosen);
}

async function load(farmId) {
  try { localStorage.setItem("saqi.farm", farmId); } catch (_) { /* ignore */ }
  setStatus(t().loading);
  try {
    current = await api(`/farms/${encodeURIComponent(farmId)}/plan`);
    render(current);
  } catch (e) {
    setStatus(`${t().errLoad} ${e.message}`, true);
  }
}

function render(plan) {
  const main = $("#main");
  main.innerHTML = "";
  plan.blocks.forEach((b) => main.append(renderBlock(plan, b)));
  const unverified = plan.blocks.some((b) => b.unverified.length);
  renderChat();
  const cav = $("#caveat");
  cav.hidden = !unverified;
  cav.textContent = t().caveat;
}

function renderBlock(plan, b) {
  const L = t();
  const node = $("#block-tpl").content.firstElementChild.cloneNode(true);
  node.querySelectorAll("[data-i18n]").forEach((el) => { const v = L[el.dataset.i18n]; if (typeof v === "string") el.textContent = v; });
  const crop = L.crops[b.crop] || b.crop;
  const soil = L.soils[b.soil_type] || b.soil_type;
  const sys = L.systems[b.system] || b.system;
  $(".block-name", node).textContent = b.name;
  $(".block-meta", node).textContent = L.meta(crop, soil, sys, nf(b.area_ha, 1));

  const d = b.today;
  const answer = $(".answer", node);
  if (d.irrigate) {
    $(".when", node).textContent = L.irrigateToday;
    answer.textContent = hm(d.runtime_h);
    answer.classList.add("go");
    $(".detail", node).textContent = L.withSystem(mm(d.gross_mm), sys);
    const prev = b.past[b.past.length - 1];
    const carry = $(".carry", node);
    if (d.capped) { carry.hidden = false; carry.textContent = L.carry(hm(b.max_runtime_h)); }
    else if (prev && prev.capped) { carry.hidden = false; carry.textContent = L.continuing; }
  } else {
    $(".when", node).textContent = L.today;
    answer.textContent = L.noIrrigation;
    const next = b.forecast.find((f) => f.irrigate);
    $(".detail", node).textContent = next ? L.nextOn(weekday(next.date, "long"), hm(next.runtime_h)) : L.noneSoon;
  }

  drawProfile($(".profile", node), d);

  const week = $(".week", node);
  [d, ...b.forecast].slice(0, 7).forEach((day, i) => {
    const li = document.createElement("li");
    if (i === 0) li.classList.add("is-today");
    if (day.irrigate) li.classList.add("go");
    li.innerHTML = `<span class="dname"></span><svg class="drop" viewBox="0 0 24 28" aria-hidden="true"><path d="M12 2c4 5 8 9.6 8 14.2A8 8 0 0 1 4 16.2C4 11.6 8 7 12 2Z"/></svg><span class="rt"></span>`;
    $(".dname", li).textContent = weekday(day.date);
    $(".rt", li).textContent = day.irrigate ? hmShort(day.runtime_h) : "";
    li.setAttribute("aria-label", `${dayLabel(day.date)}: ${day.irrigate ? hm(day.runtime_h) : L.noIrrigation}`);
    week.append(li);
  });

  const why = $(".why-body", node);
  const paras = [
    L.why1(mm(d.et0_mm), Math.round(d.kc * 100), mm(d.etc_mm), crop),
    L.whyRain(Number(mm(d.peff_mm)), mm(d.rain_mm)),
    L.why2(mm(d.dr_mm), mm(d.raw_mm), mm(d.taw_mm)),
    d.irrigate
      ? L.why3go(mm(d.net_mm), mm(d.gross_mm), Math.round(b.efficiency * 100), hm(d.runtime_h), nf(b.application_rate_mm_h, 1))
      : L.why3no(mm(d.raw_mm - d.dr_mm)),
  ];
  why.innerHTML = paras.map((p) => `<p>${p}</p>`).join("") + `<p class="source">${L.whySource}</p>`;

  const tbody = $(".past tbody", node);
  b.past.slice().reverse().forEach((day) => {
    const tr = document.createElement("tr");
    const planned = day.irrigate ? hm(day.runtime_h) : L.none;
    let done, cls;
    if (day.applied_source === "logged") { done = `${hm(day.logged_runtime_h)} (${L.logged})`; cls = "logged"; }
    else { done = L.assumed; cls = "assumed"; }
    tr.innerHTML = `<td></td><td></td><td class="${cls}"></td>`;
    tr.children[0].textContent = dayLabel(day.date);
    tr.children[1].textContent = planned;
    tr.children[2].textContent = done;
    tbody.append(tr);
  });

  wireLog(node, plan, b);
  return node;
}

function drawProfile(fig, d) {
  // Root zone as a soil column. Top = surface. Brown = water already used (Dr), blue = water left.
  const H = 180, W = 72, x = 8, y = 10;
  const taw = Math.max(d.taw_mm, 0.001);
  const used = Math.min(Math.max(d.dr_mm / taw, 0), 1);
  const trig = Math.min(Math.max(d.raw_mm / taw, 0), 1);
  const usedH = used * H;
  const trigY = y + trig * H;
  let grains = "";
  for (let i = 0; i < 26; i++) {
    const gx = x + 6 + ((i * 37) % (W - 12));
    const gy = y + 4 + ((i * 53) % Math.max(usedH - 6, 1));
    if (usedH > 8) grains += `<circle class="soil-grain" cx="${gx}" cy="${gy}" r="1.6"/>`;
  }
  const svg = fig.querySelector("svg");
  svg.innerHTML = `
    <rect class="soil" x="${x}" y="${y}" width="${W}" height="${H}" rx="6"/>
    ${grains}
    <rect class="water" x="${x}" y="${y + usedH}" width="${W}" height="${H - usedH}" rx="${usedH > H - 6 ? 0 : 6}"/>
    <line class="surface-line" x1="${x + 4}" y1="${y}" x2="${x + W - 4}" y2="${y}"/>
    <line class="trigger" x1="${x - 4}" y1="${trigY}" x2="${x + W + 4}" y2="${trigY}"/>
    <text class="trigger-label" x="${x + W + 7}" y="${trigY + 4}" text-anchor="start"></text>
    <rect class="frame" x="${x}" y="${y}" width="${W}" height="${H}" rx="6"/>`;
  svg.setAttribute("viewBox", `0 0 ${x + W + 52} ${H + 20}`);
  svg.querySelector(".trigger-label").textContent = t().triggerLabel;
  const pct = Math.round((1 - used) * 100);
  svg.setAttribute("aria-label", t().waterLeft(pct));
  fig.querySelector("figcaption").textContent = t().waterLeft(pct);
}

function wireLog(node, plan, b) {
  const L = t();
  const open = $(".log-open", node);
  const form = $(".log-form", node);
  const err = $(".form-error", node);
  form.elements.date.value = plan.today;
  form.elements.date.max = plan.today;
  form.elements.date.min = b.planting_date;
  if (b.today.irrigate) {
    let mins = Math.round((b.today.runtime_h * 60) / 5) * 5;
    form.elements.hours.value = Math.floor(mins / 60);
    form.elements.minutes.value = mins % 60;
  }
  open.addEventListener("click", () => { form.hidden = false; open.hidden = true; form.elements.date.focus(); });
  $(".log-cancel", node).addEventListener("click", () => { form.hidden = true; open.hidden = false; err.hidden = true; });
  form.querySelectorAll('input[name="unit"]').forEach((r) => r.addEventListener("change", () => {
    const byMm = form.elements.unit.value === "mm";
    $(".by-mm", form).hidden = !byMm;
    $(".by-time", form).hidden = byMm;
  }));
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    err.hidden = true;
    const f = form.elements;
    const body = { date: f.date.value, note: f.note.value };
    if (f.unit.value === "mm") {
      const v = parseFloat(f.mm.value);
      if (!(v > 0)) { err.textContent = L.errAmount; err.hidden = false; return; }
      body.gross_mm = v;
    } else {
      const hrs = (parseInt(f.hours.value || "0", 10) || 0) + (parseInt(f.minutes.value || "0", 10) || 0) / 60;
      if (!(hrs > 0)) { err.textContent = L.errAmount; err.hidden = false; return; }
      body.runtime_h = hrs;
    }
    const btn = form.querySelector(".primary");
    btn.disabled = true;
    try {
      await api(`/farms/${encodeURIComponent(plan.farm.id)}/blocks/${encodeURIComponent(b.id)}/log`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      toast(L.saved);
      await load(plan.farm.id);
    } catch (e) {
      err.textContent = `${L.errSave} ${e.message}`;
      err.hidden = false;
      btn.disabled = false;
    }
  });
}

function farmChat() {
  const id = current && current.farm.id;
  if (!id) return [];
  if (!chats[id]) chats[id] = [];
  return chats[id];
}

function renderChat() {
  const box = $("#chat");
  box.hidden = !chatOn || !current;
  if (box.hidden) return;
  const L = t();
  box.querySelectorAll("[data-i18n]").forEach((el) => { const v = L[el.dataset.i18n]; if (typeof v === "string") el.textContent = v; });
  const log = $("#chat-log");
  log.innerHTML = "";
  farmChat().forEach((m) => {
    const li = document.createElement("li");
    li.className = m.kind || m.role;
    li.dir = "auto";
    li.textContent = m.content;
    log.append(li);
  });
  const chips = $("#chips");
  chips.innerHTML = "";
  if (!farmChat().some((m) => m.role === "user")) {
    L.chips.forEach((c) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = c;
      b.addEventListener("click", () => { const i = $("#chat-input"); i.value = c; i.focus(); });
      chips.append(b);
    });
  }
}

function wireChat() {
  const form = $("#chat-form");
  const input = $("#chat-input");
  input.addEventListener("input", () => { input.style.height = "auto"; input.style.height = `${input.scrollHeight}px`; });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
  });
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const text = input.value.trim();
    if (!text || !current) return;
    const L = t();
    const farmId = current.farm.id;
    const thread = farmChat();
    thread.push({ role: "user", content: text });
    input.value = "";
    input.style.height = "auto";
    renderChat();
    const typing = document.createElement("li");
    typing.className = "assistant typing";
    typing.textContent = L.thinking;
    $("#chat-log").append(typing);
    const send = form.querySelector(".send");
    send.disabled = true;
    try {
      const history = thread.filter((m) => !m.kind).map(({ role, content }) => ({ role, content })).slice(-20);
      const res = await api(`/farms/${encodeURIComponent(farmId)}/chat`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: history, lang }),
      });
      thread.push({ role: "assistant", content: res.reply });
      (res.logged || []).forEach((row) => {
        thread.push({ role: "assistant", kind: "logged", content: L.loggedNote(hm(Number(row.runtime_h)), dayLabel(row.date)) });
      });
      if ((res.logged || []).length) await load(farmId);
    } catch (e) {
      thread.push({ role: "assistant", kind: "error", content: `${L.chatError} ${e.message}` });
    } finally {
      send.disabled = false;
      renderChat();
      const last = $("#chat-log").lastElementChild;
      if (last) last.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  });
}

function toast(text) {
  const el = document.createElement("div");
  el.className = "toast";
  el.setAttribute("role", "status");
  el.textContent = text;
  document.body.append(el);
  setTimeout(() => el.remove(), 2600);
}

init();
