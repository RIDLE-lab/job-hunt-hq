/* Job Hunt HQ Assistant – a small helper that floats on job sites and application forms.
   It reads the advert, scores it against YOUR details, fills forms, and suggests answers from your own
   work history. It never presses Submit or Next for you. */
(function () {
  if (window.__jhqAssistant || !window.JHQ_CONFIG) return;
  window.__jhqAssistant = true;
  var BASE = JHQ_CONFIG.base;
  try {
    if ([BASE, JHQ_CONFIG.alt].filter(Boolean).some(function (b) { return location.origin === new URL(b).origin; })) return;
  } catch (e) {}

  /* ---------------------------------------------------------------- only on job sites */
  /* Job boards and the application systems employers use: the assistant appears on these. */
  var JOB_SITES = /(^|\.)(linkedin\.com|indeed\.[a-z.]+|reed\.co\.uk|totaljobs\.com|cv-library\.co\.uk|cwjobs\.co\.uk|caterer\.com|jobsite\.co\.uk|monster\.[a-z.]+|glassdoor\.[a-z.]+|adzuna\.[a-z.]+|guardianjobs\.com|jobs\.theguardian\.com|jobs\.nhs\.uk|healthjobsuk\.com|civilservicejobs\.service\.gov\.uk|findajob\.dwp\.gov\.uk|charityjob\.co\.uk|jobs\.ac\.uk|ziprecruiter\.[a-z.]+|totaljobs\.[a-z]+|hays\.[a-z.]+|michaelpage\.[a-z.]+|roberthalf\.[a-z.]+|randstad\.[a-z.]+|adecco\.[a-z.]+|pertemps\.co\.uk|welcometothejungle\.com|stepstone\.[a-z.]+|nationalevacaturebank\.nl|infojobs\.[a-z.]+|francetravail\.fr|apec\.fr|xing\.com|seek\.com\.au|jora\.com|simplyhired\.[a-z.]+|careerbuilder\.com|dice\.com|wellfound\.com|otta\.com|workable\.com|myworkdayjobs\.com|myworkdaysite\.com|workday\.com|greenhouse\.io|lever\.co|smartrecruiters\.com|taleo\.net|oraclecloud\.com|icims\.com|teamtailor\.com|ashbyhq\.com|bamboohr\.com|jobvite\.com|successfactors\.[a-z.]+|recruitee\.com|personio\.[a-z]+|pinpointhq\.com|applytojob\.com|breezy\.hr|jazzhr\.com|tribepad\.com|eploy\.net|eploy\.co\.uk|hireful\.co\.uk|networx\.uk|webrecruit\.co|cezanneondemand\.com|beapplied\.com|tal\.net|ciphr\.com|jobtrain\.co\.uk|trac\.jobs|recruitmentplatform\.com|hirehive\.com|comeet\.com|rippling\.com|dayforcehcm\.com|ultipro\.com|paylocity\.com|jobs\.[a-z0-9-]+\.[a-z.]+|careers\.[a-z0-9-]+\.[a-z.]+)$/i;
  /* Everyday sites where a job helper is never wanted. */
  var NEVER = /(^|\.)(youtube\.com|youtu\.be|google\.[a-z.]+|bing\.com|duckduckgo\.com|facebook\.com|instagram\.com|threads\.net|x\.com|twitter\.com|tiktok\.com|reddit\.com|pinterest\.[a-z.]+|snapchat\.com|whatsapp\.com|discord\.com|telegram\.org|twitch\.tv|netflix\.com|disneyplus\.com|primevideo\.com|spotify\.com|soundcloud\.com|amazon\.[a-z.]+|ebay\.[a-z.]+|etsy\.com|aliexpress\.com|wikipedia\.org|bbc\.co\.uk|bbc\.com|chatgpt\.com|openai\.com|claude\.ai|anthropic\.com|github\.com|stackoverflow\.com|outlook\.(live|office)\.com|office\.com|live\.com|yahoo\.com|icloud\.com|apple\.com|microsoft\.com|steampowered\.com|steamcommunity\.com|epicgames\.com|xbox\.com|playstation\.com|paypal\.com|onrender\.com|names\.co\.uk)$/i;
  var HOST = location.hostname.replace(/^www\./, "");
  var siteKind = NEVER.test(HOST) ? "never" : JOB_SITES.test(HOST) ? "job" : "other";
  if (siteKind === "never") return;          /* not even the button – and nothing is sent anywhere */
  /* Inside a frame (a company's careers page showing a Greenhouse, Lever or Workday form): only for those systems,
     and only when the frame is big enough to be the form itself. */
  if (window.top !== window && (siteKind !== "job" || innerWidth < 480 || innerHeight < 300)) return;
  function strongJobSignals() {
    /* For other websites (a company's own careers page): only a real advert or application form counts. */
    var ld = Array.prototype.some.call(document.querySelectorAll('script[type="application/ld+json"]'), function (s) { return /"JobPosting"/.test(s.textContent); });
    var urlish = /\/(jobs?|careers?|vacanc(y|ies)|apply|application|recruit(ment)?|opportunit(y|ies)|positions?|openings?)(\/|\?|-|$)/i.test(location.pathname + location.search);
    return { ld: ld, urlish: urlish };
  }

  /* ---------------------------------------------------------------- talking to Job Hunt HQ */
  function api(body) {
    return new Promise(function (resolve, reject) {
      chrome.runtime.sendMessage({ type: "api", body: body }, function (r) {
        if (chrome.runtime.lastError) return reject(new Error("The assistant was updated – reload this page."));
        r && r.ok ? resolve(r.data) : reject(new Error((r && r.error) || "No answer from Job Hunt HQ"));
      });
    });
  }
  function getFile(path) {
    return new Promise(function (resolve) {
      chrome.runtime.sendMessage({ type: "file", path: path }, function (r) {
        if (!r || !r.ok || !r.data) return resolve(null);
        var bin = atob(r.data.b64), arr = new Uint8Array(bin.length);
        for (var i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
        resolve({ blob: new Blob([arr], { type: r.data.type }), name: r.data.name });
      });
    });
  }
  var store = {
    get: function (k) { return new Promise(function (res) { chrome.storage.local.get(k, function (v) { res(v[k]); }); }); },
    set: function (k, v) { var o = {}; o[k] = v; chrome.storage.local.set(o); }
  };

  /* ---------------------------------------------------------------- reading the page */
  function txt(sel) {
    for (var i = 0; i < sel.length; i++) {
      var el = document.querySelector(sel[i]);
      if (el && el.innerText && el.innerText.trim()) return el.innerText.trim();
    }
    return "";
  }
  function readJob() {
    var job = { url: location.href, title: "", company: "", location: "", salary: "", description: "" };
    try {
      document.querySelectorAll('script[type="application/ld+json"]').forEach(function (s) {
        var data = JSON.parse(s.textContent);
        (Array.isArray(data) ? data : (data["@graph"] || [data])).forEach(function (d) {
          if (!d || d["@type"] !== "JobPosting") return;
          job.title = job.title || d.title || "";
          job.company = job.company || (d.hiringOrganization && d.hiringOrganization.name) || "";
          var a = ([].concat(d.jobLocation || [])[0] || {}).address;
          if (a && !job.location) job.location = [a.addressLocality, a.postalCode].filter(Boolean).join(", ");
          if (d.description && !job.description) { var t = document.createElement("div"); t.innerHTML = d.description; job.description = t.innerText; }
        });
      });
    } catch (e) {}
    var h = location.hostname;
    if (/linkedin\.com$/.test(h)) {
      var id = (location.href.match(/currentJobId=(\d+)/) || location.href.match(/jobs\/view\/(\d+)/) || [])[1];
      if (id) job.url = "https://www.linkedin.com/jobs/view/" + id + "/";
      job.title = txt([".job-details-jobs-unified-top-card__job-title", ".jobs-unified-top-card__job-title", ".top-card-layout__title"]) || job.title;
      job.company = txt([".job-details-jobs-unified-top-card__company-name", ".jobs-unified-top-card__company-name", ".topcard__org-name-link"]) || job.company;
      job.description = txt(["#job-details", ".jobs-description__content", ".description__text"]) || job.description;
    } else if (/indeed\./.test(h)) {
      var jk = (location.href.match(/[?&](?:vjk|jk)=([0-9a-f]{16})/) || [])[1];
      if (jk) job.url = "https://uk.indeed.com/viewjob?jk=" + jk;
      job.title = (txt(['[data-testid="jobsearch-JobInfoHeader-title"]', ".jobsearch-JobInfoHeader-title"]) || job.title).replace(/\s*-\s*job post\s*$/i, "");
      job.company = txt(['[data-testid="inlineHeader-companyName"]', '[data-company-name="true"]']) || job.company;
      job.location = txt(['[data-testid="inlineHeader-companyLocation"]', '[data-testid="job-location"]']) || job.location;
      job.description = txt(["#jobDescriptionText"]) || job.description;
    } else if (/reed\.co\.uk|totaljobs|cv-library|cwjobs|caterer|guardian|jobs\.nhs|civilservicejobs|charityjob|adzuna|glassdoor/.test(h)) {
      job.title = job.title || txt(["h1"]);
      job.description = job.description || txt(['[itemprop="description"]', ".job-description", "#job-description", ".description", "article"]);
    }
    if (!job.description) {
      /* any site: the biggest block of text that reads like an advert */
      var best = null;
      document.querySelectorAll("article, section, main, div").forEach(function (e) {
        var t = e.innerText || "";
        if (t.length < 300 || t.length > 25000) return;
        if (!/responsibilit|requirement|about the (role|job)|you will|we are looking|duties|what you'll|skills/i.test(t)) return;
        if (!best || t.length < best.innerText.length) best = e;
      });
      if (best) job.description = best.innerText.trim();
    }
    if (!job.title) {
      var og = document.querySelector('meta[property="og:title"]');
      job.title = (og && og.content) || txt(["h1"]) || "";
    }
    /* Application pages (Indeed's "smartapply", Workday…) show the job as "HR Advisor" then "Burger and Beyond - London". */
    if (!job.company || /^(answer|apply|application|questions|review|upload|add|your|contact|relevant|resume|cv)\b/i.test(job.title)) {
      var lines = (document.body.innerText || "").split("\n").map(function (l) { return l.trim(); }).filter(Boolean).slice(0, 400);
      for (var i = 0; i < lines.length - 1; i++) {
        var a = lines[i], m = lines[i + 1].match(/^([^\-–|]{2,70})\s[-–]\s([^\-–|]{2,60})$/);
        if (m && a.length <= 90 && a.length >= 3 && !/[.?!:]$/.test(a) && !/^(fields|answer|apply|step|\d+%)/i.test(a)) {
          if (!job.company || job.title.toLowerCase() === a.toLowerCase() || /^(answer|apply|application|questions|review)/i.test(job.title)) {
            job.title = a; job.company = m[1].trim(); job.location = job.location || m[2].trim();
          }
          break;
        }
      }
    }
    if (!job.company) {
      var parts = document.title.split(/\s[|–-]\s/);
      if (parts.length >= 2 && !/indeed|linkedin|apply|application/i.test(parts[1])) job.company = parts[1].trim();
    }
    job.title = job.title.split(/\s[|–-]\s/)[0].trim().slice(0, 150);
    return job;
  }
  function looksLikeJob(job) {
    return !!(job.title && job.description && job.description.length > 250 &&
              /responsibilit|requirement|experience|role|apply|salary|skills|duties/i.test(job.description));
  }
  function formInfo() {
    var s = { questions: [], fields: 0 };
    try { s = JHQ.scan(); } catch (e) {}
    var hasUpload = !!document.querySelector("input[type=file]");
    var heads = Array.prototype.map.call(document.querySelectorAll("h1, h2, h3, legend"), function (h) { return h.innerText || ""; }).join(" ");
    var applyWords = /apply|application|candidate|career|vacanc|recruit|job|workday|greenhouse|lever\.co|smartrecruiters|taleo|icims|teamtailor|ashby|bamboohr|jobvite/i.test(location.href) ||
                     /apply|application|candidate|résumé|resume|cover letter|employer questions|screening|work experience|your cv/i.test(document.title + " " + heads);
    var qs = s.questions || [];
    /* the button at the bottom of an application form ("Submit application", "Apply now", "Send application") */
    var submitBtn = Array.prototype.some.call(document.querySelectorAll("button, input[type=submit], [role=button]"), function (b) {
      return /^\s*(submit|send|complete)( my| your)? application|^\s*apply( now| for this (job|role|position))?\s*$/i.test(b.innerText || b.value || "");
    });
    return { form: (s.fields >= 3 && (applyWords || hasUpload)) || (qs.length >= 1 && applyWords) ||
                   (submitBtn && (s.fields >= 1 || hasUpload) && siteKind === "job"), questions: qs };
  }

  /* ---------------------------------------------------------------- the floating helper */
  var host = document.createElement("div");
  host.id = "jhq-assistant";
  host.style.cssText = "all:initial;position:fixed;z-index:2147483646;right:18px;bottom:18px;display:none";
  var root = host.attachShadow({ mode: "open" });
  root.innerHTML =
    "<style>" +
    ":host{all:initial}*{box-sizing:border-box;font-family:'Segoe UI',system-ui,-apple-system,Arial,sans-serif}" +
    ".bub{width:56px;height:56px;border-radius:50%;border:0;cursor:grab;background:#0b1240;color:#fff;box-shadow:0 8px 24px rgba(11,18,64,.35);display:grid;place-items:center;position:relative}" +
    ".bub:hover{background:#2443e0}.bub svg{width:30px;height:30px}" +
    ".bub.mini{width:30px;height:30px;opacity:.55;box-shadow:0 4px 12px rgba(11,18,64,.3);transition:opacity .15s,width .15s,height .15s}" +
    ".bub.mini:hover,.bub.mini:focus-visible{opacity:1}.bub.mini svg{width:18px;height:18px}.bub.mini .badge{display:none}" +
    ".hd .x{padding:0 4px;line-height:1}.hd .mn{font-size:22px;margin-top:-4px}" +
    ".badge{position:absolute;top:-6px;right:-6px;min-width:26px;height:22px;padding:0 6px;border-radius:999px;background:#3be3cc;color:#0b1240;font:700 12px/22px Arial;text-align:center}" +
    ".badge.mid{background:#ffd166}.badge.low{background:#e6e8f0}" +
    ".pulse{animation:p 1.6s ease-out 3}@keyframes p{0%{box-shadow:0 0 0 0 rgba(59,227,204,.7)}100%{box-shadow:0 0 0 18px rgba(59,227,204,0)}}" +
    ".panel{position:absolute;right:0;bottom:68px;width:370px;max-width:calc(100vw - 36px);max-height:calc(100vh - 110px);overflow:auto;background:#fff;color:#10153a;border-radius:14px;box-shadow:0 18px 50px rgba(11,18,64,.35);font-size:14px;line-height:1.45}" +
    ".hd{background:#0b1240;color:#fff;padding:12px 14px;display:flex;align-items:center;gap:8px;position:sticky;top:0;z-index:2;border-radius:14px 14px 0 0}" +
    ".hd b{flex:1}.x{background:none;border:0;color:#c9d1f5;font-size:18px;cursor:pointer}" +
    ".sec{padding:12px 14px;border-top:1px solid #e9ecf5}.sec:first-of-type{border-top:0}" +
    ".muted{color:#5a6283;font-size:12.5px}.h{font-weight:700;margin:0 0 6px}" +
    ".job{display:flex;gap:12px;align-items:center}.ring{width:54px;height:54px;border-radius:50%;display:grid;place-items:center;font:700 16px Arial;flex:none;background:conic-gradient(var(--c) calc(var(--v)*1%),#e9ecf5 0)}" +
    ".ring span{width:42px;height:42px;border-radius:50%;background:#fff;display:grid;place-items:center}" +
    "ul{margin:6px 0 0;padding-left:18px}li{margin:2px 0}" +
    "button.b{display:block;width:100%;margin-top:8px;padding:9px;border-radius:8px;border:1px solid #0b1240;background:#0b1240;color:#fff;font-weight:600;font-size:14px;cursor:pointer}" +
    "button.b:hover{background:#2443e0;border-color:#2443e0}button.g{background:#fff;color:#0b1240}button.g:hover{color:#fff}" +
    "button.s{display:inline-block;width:auto;margin:6px 6px 0 0;padding:5px 10px;font-size:12.5px}" +
    ".q{border:1px solid #e9ecf5;border-radius:10px;padding:8px 10px;margin-top:8px}.q p{margin:0}" +
    "textarea{width:100%;min-height:90px;margin-top:6px;border:1px solid #dce1ee;border-radius:8px;padding:8px;font-size:13.5px;color:#10153a;resize:vertical}" +
    ".ok{background:#dcf4ea;color:#0f7a55;border-radius:8px;padding:8px 10px;margin-top:8px;font-size:13px}" +
    ".err{background:#fde5ea;color:#c0263d;border-radius:8px;padding:8px 10px;margin-top:8px;font-size:13px}" +
    "a{color:#2443e0}" +
    "</style>" +
    "<div class='panel' hidden></div>" +
    "<button class='bub' title='Job Hunt HQ Assistant' aria-label='Open Job Hunt HQ Assistant'>" +
    "<svg viewBox='0 0 40 40' fill='none' stroke='#3be3cc' stroke-width='3'><circle cx='20' cy='20' r='15'/><circle cx='20' cy='20' r='8'/><circle cx='20' cy='20' r='2.5' fill='#fff' stroke='none'/><circle cx='30' cy='10' r='3' fill='#ff5c8a' stroke='none'/></svg>" +
    "<span class='badge' hidden></span></button>";
  document.documentElement.appendChild(host);
  var bub = root.querySelector(".bub"), badge = root.querySelector(".badge"), panel = root.querySelector(".panel");

  /* drag the bubble anywhere; it remembers where you put it */
  store.get("pos").then(function (p) { if (p) { host.style.right = p.r + "px"; host.style.bottom = p.b + "px"; } });
  var drag = null;
  bub.addEventListener("pointerdown", function (e) { drag = { x: e.clientX, y: e.clientY, r: parseInt(host.style.right), b: parseInt(host.style.bottom), moved: false }; bub.setPointerCapture(e.pointerId); });
  bub.addEventListener("pointermove", function (e) {
    if (!drag) return;
    var dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 4) drag.moved = true;
    if (!drag.moved) return;
    host.style.right = Math.max(4, Math.min(innerWidth - 64, drag.r - dx)) + "px";
    host.style.bottom = Math.max(4, Math.min(innerHeight - 64, drag.b - dy)) + "px";
  });
  bub.addEventListener("pointerup", function () {
    if (drag && drag.moved) store.set("pos", { r: parseInt(host.style.right), b: parseInt(host.style.bottom) });
    else if (bub.classList.contains("mini")) { minimise(false); toggle(true); }
    else toggle();
    drag = null;
  });
  chrome.runtime.onMessage.addListener(function (m) { if (m.type === "toggle") { show(true); hello(); toggle(); } });   /* the toolbar button opens it anywhere */
  var shown = false, hidden = {};
  function show(on) { shown = on; host.style.display = on ? "block" : "none"; }
  /* minimise: the helper shrinks to a small dot (on every page) until you click it again */
  function minimise(on) {
    bub.classList.toggle("mini", on);
    bub.title = on ? "Job Hunt HQ Assistant (minimised) – click to open" : "Job Hunt HQ Assistant";
    store.set("mini", on);
    if (on) { panel.hidden = true; bub.classList.remove("pulse"); }
  }
  store.get("mini").then(function (m) { if (m) minimise(true); });
  root.addEventListener("keydown", function (e) { if (e.key === "Escape" && !panel.hidden) { toggle(false); bub.focus(); } });
  store.get("hiddenSites").then(function (h) { hidden = h || {}; });

  var state = { me: null, job: null, page: null, form: null, pack: null, answers: {}, msg: "", letter: null, lmsg: "" };
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return "&#" + c.charCodeAt(0) + ";"; }); }
  function toggle(open) {
    var show = open === undefined ? panel.hidden : open;
    panel.hidden = !show;
    if (show) { bub.classList.remove("pulse"); render(); }
  }

  /* ---------------------------------------------------------------- what's on this page */
  function look() {
    var job = readJob(), form = formInfo();
    state.page = job;
    state.form = form;
    var isJob = looksLikeJob(job);
    var sig = siteKind === "other" ? strongJobSignals() : null;
    /* On job boards: any advert or form. Elsewhere: only a real job advert (JobPosting data, or a careers/jobs address)
       or an application form on a careers/jobs address. */
    var qualifies = siteKind === "job" ? (isJob || form.form)
                  : (sig.ld && isJob) || (sig.urlish && (isJob || form.form));
    if (hidden[HOST]) qualifies = false;
    if (!qualifies) { badge.hidden = true; if (panel.hidden) show(false); return Promise.resolve(); }
    show(true); hello();
    if (!isJob && form.form && job.title && job.company) isJob = true;    /* the application page for a job */
    var p = isJob ? api({ action: "job", url: job.url, title: job.title, company: job.company, location: job.location, description: job.description })
                  : store.get("lastJob").then(function (j) { return { job: j && Date.now() - j.at < 6 * 3600e3 ? j : null }; });
    return p.then(function (r) {
      state.job = r.job;
      if (r.job && r.job.id) store.set("lastJob", Object.assign({}, r.job, { at: Date.now() }));
      if (r.job && r.job.score != null) {
        badge.hidden = false; badge.textContent = r.job.score;
        badge.className = "badge" + (r.job.score >= 70 ? "" : r.job.score >= 50 ? " mid" : " low");
      } else if (form.form) { badge.hidden = false; badge.textContent = "✎"; badge.className = "badge"; }
      if (!bub.classList.contains("mini")) bub.classList.add("pulse");
      if (!panel.hidden) render();
    }).catch(function (e) { state.msg = e.message; });
  }

  /* ---------------------------------------------------------------- the cover letter on the page */
  var lastField = null;
  document.addEventListener("focusin", function (e) {
    var el = e.target;
    if (el && (el.tagName === "TEXTAREA" || el.isContentEditable) && !host.contains(el)) lastField = el;
  }, true);
  function labelOf(el) {
    var t = "";
    if (el.labels && el.labels[0]) t = el.labels[0].innerText;
    t += " " + (el.getAttribute("aria-label") || "") + " " + (el.getAttribute("placeholder") || "") + " " + (el.name || "") + " " + (el.id || "");
    var box = el.closest("[class*=question], [class*=field], .form-group, fieldset, li, div");
    if (box) t += " " + (box.innerText || "").slice(0, 200);
    return t.toLowerCase();
  }
  var LETTER = /cover(ing)?\s*letter|supporting (statement|information)|personal statement|letter of (application|motivation)|motivation/;
  function letterBox() {
    var boxes = Array.prototype.filter.call(document.querySelectorAll("textarea, [contenteditable=true]"), function (el) {
      return !host.contains(el) && el.offsetParent !== null;
    });
    return boxes.find(function (el) { return LETTER.test(labelOf(el)); }) || lastField ||
           (boxes.length === 1 ? boxes[0] : null);
  }
  function letterUpload() {
    var files = Array.prototype.filter.call(document.querySelectorAll("input[type=file]"), function (el) { return !el.disabled; });
    return files.find(function (el) { return LETTER.test(labelOf(el)) || /letter/.test(labelOf(el)); }) ||
           (files.length >= 2 ? files[1] : null);
  }
  function setField(el, value) {
    if (el.isContentEditable) { el.focus(); el.innerText = value; el.dispatchEvent(new Event("input", { bubbles: true })); return; }
    var proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.style.outline = "3px solid #3be3cc";
  }

  /* ---------------------------------------------------------------- the panel */
  function render() {
    var h = "<div class='hd'><b>Job Hunt HQ" + (state.me && state.me.first ? " · Hi " + esc(state.me.first) : "") + "</b>" +
            "<button class='x mn' data-a='mini' aria-label='Minimise' title='Minimise – shrink to a small dot until you need it'>–</button>" +
            "<button class='x' data-a='close' aria-label='Close' title='Close'>✕</button></div>";
    var j = state.job;
    if (j) {
      var col = j.score >= 70 ? "#0f7a55" : j.score >= 50 ? "#c08a00" : "#8a93a0";
      h += "<div class='sec'><div class='job'>" +
           (j.score != null ? "<div class='ring' style='--v:" + j.score + ";--c:" + col + "'><span>" + j.score + "</span></div>" : "") +
           "<div><div class='h'>" + esc(j.title) + "</div><div class='muted'>" + esc(j.company) + (j.fit ? " · " + esc(j.fit) : "") + "</div></div></div>" +
           (j.reasons && j.reasons.length ? "<ul class='muted'>" + j.reasons.map(function (r) { return "<li>" + esc(r) + "</li>"; }).join("") + "</ul>" : "") +
           (j.id ? "<p class='muted' style='margin:8px 0 0'>Saved in your jobs" + (j.has_letter ? " · cover letter ready" : "") +
                   " · <a href='" + esc(j.link) + "' target='_blank' rel='noopener'>open</a></p>"
                 : "<button class='b' data-a='save'>Save it and write my cover letter</button>") + "</div>";
    } else if (state.page && looksLikeJob(state.page)) {
      h += "<div class='sec'><p class='h'>" + esc(state.page.title) + "</p><button class='b' data-a='save'>Save it and score it</button></div>";
    }
    if (j && j.id) {
      h += "<div class='sec'><p class='h'>Cover letter</p>";
      if (state.letter == null) {
        h += "<button class='b g' data-a='letter'>Show my cover letter for this job</button>";
      } else {
        h += "<textarea data-letter style='min-height:180px'>" + esc(state.letter) + "</textarea>" +
             "<div><button class='b s' data-a='lcopy'>Copy</button>" +
             "<button class='b s' data-a='lput'>Put it in the letter box</button>" +
             "<button class='b s' data-a='lattach'>Attach as PDF</button></div>" +
             "<div><button class='b g s' data-a='ldl' data-f='pdf'>Download PDF</button>" +
             "<button class='b g s' data-a='ldl' data-f='docx'>Download Word</button>" +
             "<button class='b g s' data-a='lsave'>Save my edits</button>" +
             "<button class='b g s' data-a='lnew'>Write it again</button></div>" +
             (state.lmsg ? "<div class='ok'>" + esc(state.lmsg) + "</div>" : "") +
             "<p class='muted'>Edit it here first if you like – your changes are used everywhere.</p>";
      }
      h += "</div>";
    }
    if (!j || !j.id) {
      h += "<div class='sec'><details" + (state.pasteOpen ? " open" : "") + "><summary class='h' style='cursor:pointer'>Paste a job description</summary>" +
           "<p class='muted'>From anywhere – an email, a PDF, a website. I'll score it and write your cover letter.</p>" +
           "<input data-pt placeholder='Job title' value='" + esc((state.page && state.page.title) || "") + "' style='width:100%;margin-top:6px;padding:7px;border:1px solid #dce1ee;border-radius:8px'>" +
           "<input data-pc placeholder='Employer' value='" + esc((state.page && state.page.company) || "") + "' style='width:100%;margin-top:6px;padding:7px;border:1px solid #dce1ee;border-radius:8px'>" +
           "<textarea data-pd placeholder='Paste the job description here'></textarea>" +
           "<button class='b' data-a='paste'>Save it and write my cover letter</button></details></div>";
    }
    if (state.form && state.form.form) {
      var qs = state.form.questions;
      h += "<div class='sec'><p class='h'>This application</p>" +
           "<button class='b' data-a='fill'>Fill this page for me</button>" +
           (qs.length ? "<button class='b g' data-a='suggestall'>Suggest answers for all " + qs.length + " questions</button>" : "") +
           qs.slice(0, 15).map(function (q) {
             var a = state.answers[q.id];
             return "<div class='q'><p><b>" + esc(q.label || "Question") + "</b></p>" +
               (a ? (a.answer ? "<textarea data-q='" + q.id + "'>" + esc(a.answer) + "</textarea>" +
                                "<button class='b s' data-a='use' data-q='" + q.id + "'>Put it in the form</button>" : "") +
                    "<p class='muted'>" + esc(a.note) + "</p>"
                  : "<button class='b g s' data-a='suggest' data-q='" + q.id + "'>Suggest an answer</button>") + "</div>";
           }).join("") +
           (state.filled ? "<div class='ok'>" + esc(state.filled) + "</div>" : "") +
           "<button class='b g' data-a='applied'" + (j && j.id ? "" : " disabled title='Save the job first'") + ">I've submitted – mark as applied</button>" +
           "<p class='muted'>Check everything before you press the site's Submit – you always do that part.</p></div>";
    }
    h += "<div class='sec'><p class='h'>Ask your assistant</p>" +
         "<textarea data-ask placeholder='e.g. Which of my experiences best fits this role?'></textarea>" +
         "<button class='b g s' data-a='ask'>Ask</button><div data-askout></div></div>";
    if (!j && !(state.form && state.form.form) && !(state.page && looksLikeJob(state.page))) {
      h += "<div class='sec muted'>Open a job advert or an application form and I'll score it against your details, fill it in and suggest answers.</div>";
    }
    if (state.msg) h += "<div class='sec'><div class='err'>" + esc(state.msg) + "</div></div>";
    h += "<div class='sec muted'>Not a job site? <a href='#' data-a='hidesite'>Don't show on " + esc(HOST) + "</a></div>";
    panel.innerHTML = h;
  }

  panel.addEventListener("click", function (e) {
    var b = e.target.closest("[data-a]");
    if (!b) return;
    var a = b.getAttribute("data-a"), qid = b.getAttribute("data-q");
    state.msg = "";
    if (a === "close") return toggle(false);
    if (a === "mini") return minimise(true);
    if (a === "hidesite") { e.preventDefault(); hidden[HOST] = true; store.set("hiddenSites", hidden); toggle(false); show(false); return; }
    if (a === "save") {
      b.textContent = "Saving…";
      var p = state.page;
      return api({ action: "job", save: true, url: p.url, title: p.title, company: p.company, location: p.location, description: p.description })
        .then(function (r) { state.job = r.job; if (r.job) store.set("lastJob", Object.assign({}, r.job, { at: Date.now() })); render(); })
        .catch(function (err) { state.msg = err.message; render(); });
    }
    if (a === "fill") {
      b.textContent = "Filling…";
      return api({ action: "pack", job_id: state.job && state.job.id, page: location.href }).then(function (pack) {
        var want = [];
        if (pack.files && pack.files.cv) want.push(getFile(pack.files.cv).then(function (f) { return ["cv", f]; }));
        if (pack.files && pack.files.letter) want.push(getFile(pack.files.letter).then(function (f) { return ["letter", f]; }));
        return Promise.all(want).then(function (pairs) {
          pack.blobs = {};
          pairs.forEach(function (p) { if (p[1]) pack.blobs[p[0]] = p[1]; });
          return JHQ.fill(pack);
        });
      }).then(function (res) {
        state.filled = res.filled.length ? "Filled: " + res.filled.join(", ") + "." : "Nothing on this page matched your details – try Suggest on each question.";
        state.form = formInfo();
        render();
      }).catch(function (err) { state.msg = err.message; render(); });
    }
    if (a === "suggest" || a === "suggestall") {
      var list = a === "suggest" ? state.form.questions.filter(function (q) { return q.id === qid; }) : state.form.questions.slice(0, 15);
      b.textContent = "Thinking…";
      return list.reduce(function (chain, q) {
        return chain.then(function () {
          return api({ action: "answer", job_id: state.job && state.job.id, question: q.label, kind: q.kind, options: q.options, hint: q.hint,
                       page_text: state.job && state.job.id ? "" : (document.body.innerText || "").slice(0, 6000) })
            .then(function (r) { state.answers[q.id] = r; });
        });
      }, Promise.resolve()).then(render).catch(function (err) { state.msg = err.message; render(); });
    }
    if (a === "use") {
      var box = panel.querySelector("textarea[data-q='" + qid + "']");
      var res = JHQ.answer(qid, box ? box.value : "");
      b.textContent = res === "ok" ? "✓ In the form" : res === "robot" ? "Pick it from the list on the page" : "Couldn't find that box – copy it in";
      return;
    }
    if (a === "letter" || a === "lnew") {
      b.textContent = a === "lnew" ? "Writing…" : "Loading…";
      return api({ action: "letter", job_id: state.job.id, rewrite: a === "lnew" })
        .then(function (r) { state.letter = r.text; state.lmsg = a === "lnew" ? "Written again from your details." : ""; render(); })
        .catch(function (err) { state.msg = err.message; render(); });
    }
    var box = panel.querySelector("[data-letter]");
    var text = box ? box.value : (state.letter || "");
    if (a === "lcopy") {
      navigator.clipboard.writeText(text).then(function () { b.textContent = "✓ Copied"; }, function () { box.select(); document.execCommand("copy"); b.textContent = "✓ Copied"; });
      return;
    }
    if (a === "lsave") {
      return api({ action: "letter_save", job_id: state.job.id, text: text })
        .then(function () { state.letter = text; state.lmsg = "Saved."; render(); });
    }
    if (a === "lput") {
      var target = letterBox();
      if (!target) { state.letter = text; state.lmsg = "Click inside the form's cover-letter box first, then press this again."; return render(); }
      setField(target, text);
      state.letter = text; state.lmsg = "✓ Put in the form – check it reads right.";
      return render();
    }
    if (a === "lattach" || a === "ldl") {
      b.textContent = "Preparing…";
      var fmt = a === "lattach" ? "pdf" : b.getAttribute("data-f");
      return api({ action: "letter_file", job_id: state.job.id, text: text, fmt: fmt }).then(function (r) {
        var bin = atob(r.b64), arr = new Uint8Array(bin.length);
        for (var i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
        var blob = new Blob([arr], { type: r.type });
        state.letter = text;
        if (a === "ldl") {
          var url = URL.createObjectURL(blob), link = document.createElement("a");
          link.href = url; link.download = r.name; document.body.appendChild(link); link.click(); link.remove();
          setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
          state.lmsg = "✓ Downloaded " + r.name;
        } else {
          var input = letterUpload();
          if (!input) { state.lmsg = "There's no upload box for a cover letter on this page – use Download PDF instead."; return render(); }
          var dt = new DataTransfer();
          dt.items.add(new File([blob], r.name, { type: r.type }));
          input.files = dt.files;
          input.dispatchEvent(new Event("input", { bubbles: true }));
          input.dispatchEvent(new Event("change", { bubbles: true }));
          state.lmsg = "✓ Attached " + r.name + " to the form.";
        }
        render();
      }).catch(function (err) { state.msg = err.message; render(); });
    }
    if (a === "paste") {
      var t = panel.querySelector("[data-pt]").value.trim(), co = panel.querySelector("[data-pc]").value.trim(),
          ds = panel.querySelector("[data-pd]").value.trim();
      if (!t || ds.length < 80) { state.pasteOpen = true; state.msg = "Add the job title and paste the full description."; return render(); }
      b.textContent = "Writing your letter…";
      return api({ action: "job", save: true, url: location.href, title: t, company: co, description: ds }).then(function (r) {
        state.job = r.job; state.letter = null;
        if (r.job) store.set("lastJob", Object.assign({}, r.job, { at: Date.now() }));
        return api({ action: "letter", job_id: r.job.id });
      }).then(function (r) { state.letter = r.text; state.lmsg = "Here's your cover letter."; render(); })
        .catch(function (err) { state.msg = err.message; render(); });
    }
    if (a === "applied") {
      b.textContent = "Saving…";
      return api({ action: "applied", job_id: state.job.id, page: location.href })
        .then(function () { b.textContent = "✓ Marked as applied – good luck!"; b.disabled = true; })
        .catch(function (err) { state.msg = err.message; render(); });
    }
    if (a === "ask") {
      var q = panel.querySelector("[data-ask]").value.trim(), out = panel.querySelector("[data-askout]");
      if (!q) return;
      b.textContent = "Thinking…";
      return api({ action: "ask", question: q, job_id: state.job && state.job.id }).then(function (r) {
        out.innerHTML = r.answer ? "<div class='ok' style='white-space:pre-wrap;color:#10153a;background:#f6f8fd'>" + esc(r.answer) + "</div><p class='muted'>" + esc(r.note) + "</p>"
                                 : "<p class='muted'>" + esc(r.note) + "</p>";
        b.textContent = "Ask";
      }).catch(function (err) { out.innerHTML = "<div class='err'>" + esc(err.message) + "</div>"; b.textContent = "Ask"; });
    }
  });

  /* ---------------------------------------------------------------- start, and follow single-page sites */
  var said = false;
  function hello() {             /* only once the assistant is actually needed on this page */
    if (said) return; said = true;
    api({ action: "hello" }).then(function (me) { state.me = me; if (!panel.hidden) render(); }).catch(function (e) { state.msg = e.message; });
  }
  setTimeout(look, 1200);
  var lastUrl = location.href, lastLen = 0;
  setInterval(function () {
    var len = (document.body && document.body.innerText || "").length;
    if (location.href !== lastUrl || Math.abs(len - lastLen) > 2000) {
      lastUrl = location.href; lastLen = len;
      state.answers = {}; state.filled = ""; state.letter = null; state.lmsg = "";
      look();
    }
  }, 2000);
})();
