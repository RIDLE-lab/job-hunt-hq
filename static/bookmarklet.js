/* "Send to Job Hunt HQ" – runs on the job page you are looking at (LinkedIn, Indeed or any site),
   reads the advert from the page and opens Job Hunt HQ with it. Nothing is sent anywhere else. */
(function () {
  var PORT = __PORT__, BASE = "__BASE__";
  var q = function (sels) {
    for (var i = 0; i < sels.length; i++) {
      var el = document.querySelector(sels[i]);
      if (el && el.innerText && el.innerText.trim()) return el.innerText.trim();
    }
    return "";
  };
  var job = { url: location.href, title: "", company: "", location: "", salary: "", description: "", closes: "", site: location.hostname, apply_url: "", posted: "" };

  /* 1. Structured data that many job sites include (schema.org JobPosting). */
  try {
    document.querySelectorAll('script[type="application/ld+json"]').forEach(function (s) {
      var data = JSON.parse(s.textContent);
      (Array.isArray(data) ? data : (data["@graph"] || [data])).forEach(function (d) {
        if (!d || d["@type"] !== "JobPosting") return;
        job.title = job.title || d.title || "";
        job.company = job.company || (d.hiringOrganization && d.hiringOrganization.name) || "";
        var loc = [].concat(d.jobLocation || [])[0];
        var a = loc && loc.address;
        if (a && !job.location) job.location = [a.addressLocality, a.addressRegion, a.postalCode].filter(Boolean).join(", ");
        if (d.description && !job.description) { var t = document.createElement("div"); t.innerHTML = d.description; job.description = t.innerText; }
        if (d.validThrough) job.closes = String(d.validThrough).slice(0, 10);
        if (d.datePosted) job.posted = String(d.datePosted).slice(0, 10);
        var b = d.baseSalary && d.baseSalary.value;
        if (b && (b.minValue || b.value)) job.salary = "£" + (b.minValue || b.value) + (b.maxValue ? " – £" + b.maxValue : "") + (b.unitText ? " per " + String(b.unitText).toLowerCase() : "");
      });
    });
  } catch (e) {}

  var host = location.hostname;
  /* "Posted 3 days ago" style text near the top of LinkedIn and Indeed adverts. */
  try {
    var top = q([".job-details-jobs-unified-top-card__primary-description-container", ".job-details-jobs-unified-top-card__tertiary-description-container",
                 ".posted-time-ago__text", ".jobs-unified-top-card__posted-date", '[data-testid="myJobsStateDate"]', ".jobsearch-JobMetadataFooter"]);
    var ago = top.match(/(just posted|today|yesterday|\d+\+?\s*(minute|hour|day|week|month)s?\s*ago|an?\s+(day|week|month)\s+ago)/i);
    if (ago && !job.posted) job.posted = ago[0];
  } catch (e) {}
  if (/linkedin\.com$/.test(host)) {
    var id = (location.href.match(/currentJobId=(\d+)/) || location.href.match(/jobs\/view\/(\d+)/) || [])[1];
    if (id) job.url = "https://www.linkedin.com/jobs/view/" + id + "/";
    job.title = q([".job-details-jobs-unified-top-card__job-title", ".jobs-unified-top-card__job-title", ".top-card-layout__title", "h1"]) || job.title;
    job.company = q([".job-details-jobs-unified-top-card__company-name", ".jobs-unified-top-card__company-name", ".topcard__org-name-link", ".top-card-layout__second-subline a"]) || job.company;
    job.location = q([".job-details-jobs-unified-top-card__primary-description-container .tvm__text", ".job-details-jobs-unified-top-card__bullet", ".jobs-unified-top-card__bullet", ".topcard__flavor--bullet"]) || job.location;
    job.salary = q([".job-details-jobs-unified-top-card__job-insight--highlight", ".compensation__salary"]) || job.salary;
    job.description = q(["#job-details", ".jobs-description__content", ".jobs-box__html-content", ".description__text", ".show-more-less-html__markup"]) || job.description;
    /* LinkedIn's newer layout: "Recruitment Advisor | BCLP | LinkedIn" in the tab title; the advert under "About the job". */
    var tparts = document.title.replace(/^\(\d+\)\s*/, "").split(" | ");
    if (tparts.length >= 3 && /linkedin/i.test(tparts[tparts.length - 1])) {
      if (!job.title || job.title === document.title) job.title = tparts[0];
      if (!job.company) job.company = tparts[1];
    }
    if (!job.description) {
      var about = Array.prototype.filter.call(document.querySelectorAll("section, article, div"), function (e) {
        var t = e.innerText || ""; return t.indexOf("About the job") >= 0 && t.length > 300 && t.length < 20000;
      }).sort(function (a, b) { return a.innerText.length - b.innerText.length; })[0];
      if (about) job.description = about.innerText.split("About the job").pop().trim();
    }
  } else if (/indeed\./.test(host)) {
    var jk = (location.href.match(/[?&](?:vjk|jk)=([0-9a-f]{16})/) || [])[1];
    if (jk) job.url = "https://" + host + "/viewjob?jk=" + jk;
    job.title = q(['[data-testid="jobsearch-JobInfoHeader-title"]', ".jobsearch-JobInfoHeader-title", "h1"]) || job.title;
    job.title = job.title.replace(/\s*-\s*job post\s*$/i, "");
    job.company = q(['[data-testid="inlineHeader-companyName"]', '[data-company-name="true"]', ".jobsearch-CompanyInfoContainer a"]) || job.company;
    job.location = q(['[data-testid="inlineHeader-companyLocation"]', '[data-testid="job-location"]', '[data-testid="jobsearch-JobInfoHeader-companyLocation"]']) || job.location;
    job.salary = q(["#salaryInfoAndJobType", '[data-testid="jobsearch-OtherJobDetailsContainer"] [aria-label*="Pay"]']) || job.salary;
    job.description = q(["#jobDescriptionText", ".jobsearch-JobComponent-description"]) || job.description;
  }

  /* The employer's own application link, when the page shows one (Indeed "Apply on company site",
     The Talent World "Apply directly", LinkedIn public pages…). */
  try {
    var links = Array.prototype.slice.call(document.querySelectorAll("a[href]"));
    var wrapped = links.find(function (a) { return /linkedin\.com\/safety\/go\/?\?/.test(a.href) && /apply/i.test(a.innerText || a.getAttribute("aria-label") || ""); });
    if (wrapped) {
      try { job.apply_url = new URL(wrapped.href).searchParams.get("url") || ""; } catch (e) {}
    }
    var ext = job.apply_url ? null : links.find(function (a) {
      var t = (a.innerText || a.getAttribute("aria-label") || "").trim();
      return /apply (on company site|directly|on employer|now|for this job)|company website/i.test(t) &&
             a.href.indexOf("http") === 0 && a.hostname !== location.hostname;
    });
    if (ext) job.apply_url = ext.href;
  } catch (e) {}

  /* 2. Anything else: the heading, plus the text you selected or the whole page. */
  var sel = String(window.getSelection ? window.getSelection() : "").trim();
  if (sel.length > 200) job.description = sel;
  job.title = job.title || q(["h1"]) || document.title;
  if (!job.description) job.description = (document.querySelector("main") || document.body).innerText;
  job.description = job.description.slice(0, 20000);

  /* 3. A page of search results (your LinkedIn or Indeed search): offer to send every job in the list. */
  var AGO = /(just posted|today|yesterday|\d+\+?\s*(minute|hour|day|week|month)s?\s*ago|an?\s+(day|week|month)\s+ago)/i;
  var NOISE = /^(promoted|viewed|saved|easy apply|be an early applicant|actively reviewing applicants|verified|new|applied|\d+ connections? works? here|.*school alumni.*|.*with verification|.*\(verified job\)|selected,.*|·)$/i;
  function txt(el, sel) { var e = el.querySelector(sel); return e ? (e.getAttribute("title") || e.innerText || "").trim() : ""; }
  function collect() {
  var list = [];
  try {
    if (/linkedin\.com$/.test(host)) {
      var cards = [];
      document.querySelectorAll("li[data-occludable-job-id], [data-job-id], [componentkey^='job-card-component-ref-']").forEach(function (card) {
        var key = card.getAttribute("componentkey");
        cards.push([card, card.getAttribute("data-occludable-job-id") || card.getAttribute("data-job-id") ||
                          (key ? key.replace("job-card-component-ref-", "") : "")]);
      });
      /* LinkedIn's job tracker (Saved, In progress…): each saved job is one link holding title, "Company · Place" and "Posted 3d ago". */
      if (/jobs-tracker|my-items/.test(location.pathname)) {
        document.querySelectorAll("a[href*='/jobs/view/']").forEach(function (a) {
          var m = a.href.match(/jobs\/view\/(?:[^\/?]*-)?(\d{6,})/);
          if (!m || list.some(function (j) { return j.url.indexOf("/" + m[1] + "/") > 0; })) return;
          var leaves = Array.prototype.filter.call(a.querySelectorAll("*"), function (e) { return !e.children.length; })
            .map(function (e) { return (e.textContent || "").trim(); }).filter(Boolean);
          var postedLine = leaves.find(function (l) { return /ago/.test(l); }) || "";
          var compLine = leaves.find(function (l) { return / · /.test(l) && l !== postedLine; }) || "";
          var full = (a.textContent || "").replace(/\s+/g, " ").trim();
          var title = (compLine ? full.split(compLine)[0] : leaves[0] || "").replace(/\s*(Verified|with verification)\s*$/i, "").trim();
          var parts = compLine.split(" · ");
          if (title) list.push({ url: "https://www.linkedin.com/jobs/view/" + m[1] + "/", title: title, company: parts[0] || "",
                                 location: parts.slice(1).join(" · "), salary: "", site: host, description: compLine,
                                 posted: (postedLine.match(/\d+\s*(mo|m|h|d|w)\w*\s*ago/) || [""])[0] });
        });
        return list;
      }
      /* Backup if LinkedIn changes its layout: every link to a job in the list. */
      if (cards.length < 3) document.querySelectorAll("a[href*='/jobs/view/'], a[href*='currentJobId=']").forEach(function (a) {
        var m = a.href.match(/jobs\/view\/(?:[^\/?]*-)?(\d{6,})/) || a.href.match(/currentJobId=(\d{6,})/);
        var card = a.closest("li") || (a.parentElement && a.parentElement.parentElement);
        if (m && card && card.innerText.length < 1200) cards.push([card, m[1]]);
      });
      cards.forEach(function (pair) {
        var card = pair[0], id = pair[1];
        var lines = card.innerText.split("\n").map(function (l) { return l.trim(); }).filter(function (l) { return l && !NOISE.test(l); });
        lines = lines.filter(function (l, i) { return i === 0 || l !== lines[i - 1]; });
        if (!id || lines.length < 2 || list.some(function (j) { return j.url.indexOf("/" + id + "/") > 0; })) return;
        var title = txt(card, "a[href*='/jobs/view/'] strong") || txt(card, ".job-card-list__title--link") || lines[0];
        title = title.split("\n")[0].replace(/\s+with verification$/i, "");
        var rest = lines.filter(function (l) { return l !== title; });
        var c = txt(card, ".artdeco-entity-lockup__subtitle") || rest[0] || "";
        var place = txt(card, ".artdeco-entity-lockup__caption") || rest.find(function (l) { return l !== c && !/GBP|£|ago|applicant/i.test(l); }) || "";
        var when = card.querySelector("time");
        var posted = when ? (when.getAttribute("datetime") || when.innerText) : (card.innerText.match(AGO) || [""])[0];
        /* A "Past 24 hours" search: every job in it is from today, even where LinkedIn shows "Viewed" instead. */
        if (!posted && +((location.href.match(/f_TPR=r(\d+)/) || [])[1] || 0) <= 86400 && /f_TPR=r/.test(location.href)) posted = "today";
        list.push({ url: "https://www.linkedin.com/jobs/view/" + id + "/", title: title, company: c, location: place,
                    salary: rest.find(function (l) { return /GBP|£/.test(l); }) || "", posted: posted, site: host,
                    description: id === (location.href.match(/currentJobId=(\d+)/) || [])[1] ? job.description : rest.join(" · ") });
      });
    } else if (/indeed\./.test(host)) {
      document.querySelectorAll("a[data-jk]").forEach(function (a) {
        var card = a.closest(".job_seen_beacon, li, td") || a.parentElement;
        var jk = a.getAttribute("data-jk");
        if (!jk || list.some(function (j) { return j.jk === jk; })) return;
        var posted = (card.innerText.match(AGO) || [""])[0];
        list.push({ jk: jk, url: "https://" + host + "/viewjob?jk=" + jk, title: txt(card, "h2 span[title]") || txt(card, "h2") || a.innerText.trim(),
                    company: txt(card, "[data-testid='company-name']"), location: txt(card, "[data-testid='text-location']"),
                    salary: (card.innerText.match(/£[\d,.]+[^\n]*/) || [""])[0], posted: posted, site: host,
                    description: txt(card, ".job-snippet") || txt(card, "[data-testid='jobsnippet_footer']") || card.innerText.slice(0, 600) });
      });
    }
  } catch (e) { list = []; }
  return list;
  }

  /* LinkedIn only fills in the jobs you've scrolled past, so scroll the list to the bottom first. */
  function scrollAll(done) {
    var first = document.querySelector("li[data-occludable-job-id], [componentkey^='job-card-component-ref-'], a[href*='/jobs/view/'], a[data-jk]");
    var box = first;
    while (box && box !== document.body) {
      var st = getComputedStyle(box);
      if (box.scrollHeight > box.clientHeight + 50 && /(auto|scroll)/.test(st.overflowY)) break;
      box = box.parentElement;
    }
    var win = !box || box === document.body;
    var steps = 0;
    (function step() {
      var top = win ? window.scrollY : box.scrollTop, h = win ? window.innerHeight : box.clientHeight;
      var full = win ? document.body.scrollHeight : box.scrollHeight;
      if (top + h >= full - 5 || steps++ > 40) { setTimeout(function () { if (win) window.scrollTo(0, 0); else box.scrollTop = 0; done(); }, 700); return; }
      if (win) window.scrollBy(0, h * 0.8); else box.scrollTop = top + h * 0.8;
      setTimeout(step, 350);
    })();
  }
  var found = collect();
  var slots = Math.max(found.length, document.querySelectorAll("li[data-occludable-job-id], [componentkey^='job-card-component-ref-']").length);
  var tracker = /jobs-tracker|my-items/.test(location.pathname);
  if (slots >= 3 && confirm("Job Hunt HQ: send every job in this list?\n\nOK = all of them" + (tracker ? " on this page (LinkedIn shows 10 at a time – press Next and click again for the rest)" : " (the list scrolls by itself for a few seconds to load them)") + "\nCancel = just the job that's open")) {
    var wl = window.open("", "_blank");   /* opened now, so the pop-up isn't blocked; filled in once the list has loaded */
    if (!wl) { alert("Job Hunt HQ: allow pop-ups for this site, then click the button again. Is the app running (run.bat)?"); return; }
    try { wl.document.write("<p style='font:16px Segoe UI,sans-serif;padding:24px'>Job Hunt HQ: loading the jobs in your list…</p>"); } catch (e) {}
    scrollAll(function () {
      var list = collect();
      if (list.length < found.length) list = found;
      var payload = { jobs: list.slice(0, 100).map(function (j) { j.description = String(j.description || "").slice(0, 1200); delete j.jk; return j; }),
                      recent: list.every(function (j) { return /hour|minute|just|today/i.test(j.posted || ""); }) };
      wl.location.href = BASE + "/import#" + encodeURIComponent(JSON.stringify(payload));
    });
    return;
  }

  var w = window.open(BASE + "/import#" + encodeURIComponent(JSON.stringify(job)), "_blank");
  if (!w) alert("Job Hunt HQ: allow pop-ups for this site, then click the button again. Is the app running (run.bat)?");
})();
