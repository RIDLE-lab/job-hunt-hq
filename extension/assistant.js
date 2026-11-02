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
    return { form: (s.fields >= 3 && (applyWords || hasUpload)) || (qs.length >= 1 && applyWords), questions: qs };
  }

  /* ---------------------------------------------------------------- the floating helper */
  var host = document.createElement("div");
  host.id = "jhq-assistant";
  host.style.cssText = "all:initial;position:fixed;z-index:2147483646;right:18px;bottom:18px";
  var root = host.attachShadow({ mode: "open" });
  root.innerHTML =
    "<style>" +
    ":host{all:initial}*{box-sizing:border-box;font-family:'Segoe UI',system-ui,-apple-system,Arial,sans-serif}" +
    ".bub{width:56px;height:56px;border-radius:50%;border:0;cursor:grab;background:#0b1240;color:#fff;box-shadow:0 8px 24px rgba(11,18,64,.35);display:grid;place-items:center;position:relative}" +
    ".bub:hover{background:#2443e0}.bub svg{width:30px;height:30px}" +
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
    else toggle();
    drag = null;
  });
  chrome.runtime.onMessage.addListener(function (m) { if (m.type === "toggle") toggle(); });

  var state = { me: null, job: null, page: null, form: null, pack: null, answers: {}, msg: "" };
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
    if (!isJob && !form.form) { badge.hidden = true; return Promise.resolve(); }
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
      bub.classList.add("pulse");
      if (!panel.hidden) render();
    }).catch(function (e) { state.msg = e.message; });
  }

  /* ---------------------------------------------------------------- the panel */
  function render() {
    var h = "<div class='hd'><b>Job Hunt HQ" + (state.me && state.me.first ? " · Hi " + esc(state.me.first) : "") + "</b>" +
            "<button class='x' data-a='close' aria-label='Close'>✕</button></div>";
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
    panel.innerHTML = h;
  }

  panel.addEventListener("click", function (e) {
    var b = e.target.closest("[data-a]");
    if (!b) return;
    var a = b.getAttribute("data-a"), qid = b.getAttribute("data-q");
    state.msg = "";
    if (a === "close") return toggle(false);
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
  api({ action: "hello" }).then(function (me) { state.me = me; }).catch(function (e) { state.msg = e.message; });
  setTimeout(look, 1200);
  var lastUrl = location.href, lastLen = 0;
  setInterval(function () {
    var len = (document.body && document.body.innerText || "").length;
    if (location.href !== lastUrl || Math.abs(len - lastLen) > 2000) {
      lastUrl = location.href; lastLen = len;
      state.answers = {}; state.filled = "";
      look();
    }
  }, 2000);
})();
