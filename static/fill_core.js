/* Job Hunt HQ form logic, shared by the "Fill this application" button and the Apply-for-me robot.
   Finds the fields on an application form, fills the ones it recognises, and lists the required
   questions that are still unanswered. It never presses Submit. */
var JHQ = window.JHQ || (function () {
  var seq = 0;
  function tag(el) {
    if (!el.getAttribute("data-jhq")) el.setAttribute("data-jhq", "f" + (++seq) + "-" + Date.now() % 100000);
    return el.getAttribute("data-jhq");
  }
  function clean(t) { return String(t || "").replace(/\s+/g, " ").trim(); }

  /* Find fields everywhere, including inside page components (SmartRecruiters and others hide
     their fields inside these, out of reach of a normal search). */
  function all(sel) {
    var out = [];
    (function walk(root) {
      root.querySelectorAll(sel).forEach(function (e) { out.push(e); });
      root.querySelectorAll("*").forEach(function (e) { if (e.shadowRoot) walk(e.shadowRoot); });
    })(document);
    return out;
  }

  function describe(el) {
    var bits = [el.name, el.id, el.placeholder, el.getAttribute("aria-label"), el.getAttribute("autocomplete"),
                el.getAttribute("data-automation-id"), el.getAttribute("data-qa"),
                (el.getAttribute("data-testid") || "").replace(/[_-]/g, " ")];
    if (el.labels) for (var i = 0; i < el.labels.length; i++) bits.push(el.labels[i].innerText);
    var lb = el.getAttribute("aria-labelledby");
    var root = el.getRootNode ? el.getRootNode() : document;
    if (lb) lb.split(/\s+/).forEach(function (id) {
      var t = (root.getElementById ? root : document).getElementById(id) || document.getElementById(id);
      if (t) bits.push(t.innerText);
    });
    var choice = el.type === "radio" || el.type === "checkbox";
    var box = choice ? el.closest("fieldset, [role=radiogroup], .application-question, li, .form-group, [class*=question], [class*=field]")
                     : el.closest("label, fieldset, li, .field, .form-group, .application-question, [class*=field], [class*=question]");
    if (box) bits.push(box.innerText.slice(0, 250));
    else if (el.parentElement) bits.push(el.parentElement.innerText.slice(0, 160));
    /* Field inside a component: the label usually sits on or around the component itself. */
    var host = root && root.host;
    if (host) {
      bits.push(host.getAttribute("label"), host.getAttribute("aria-label"), host.getAttribute("placeholder"));
      var hb = host.closest("label, fieldset, li, .field, .form-group, [class*=field], [class*=question]");
      bits.push((hb || host.parentElement || host).innerText.slice(0, 250));
    }
    return bits.filter(Boolean).join(" | ").toLowerCase();
  }

  var UPLOAD_NOISE = /^(total )?\d* ?files? (selected|chosen|attached)|no file|drop (or|files)|drag|browse|choose (a )?file|select (a )?file|^upload$|accepted|max(imum)? (file )?size|\.(pdf|docx?)\b/i;

  /* Text just above a field – for drop zones whose label is a separate heading ("Cover letter" over "Drop or select"). */
  function heading(el) {
    var n = el;
    for (var k = 0; k < 6 && n && n !== document.body; k++) {
      for (var p = n.previousElementSibling; p; p = p.previousElementSibling) {
        var t = (p.innerText || "").trim();
        if (UPLOAD_NOISE.test(t)) continue;      /* "Total 0 file selected", "Drop or select (.pdf)" … */
        if (t && t.length < 80) return t;
        if (t) break;
      }
      n = n.parentElement;
    }
    return "";
  }

  function kindOf(d) {
    if (/photo|image|picture|headshot|portfolio|transcript|certificate|passport|video|audio/.test(d)) return "other";
    return /cover|supporting|statement|letter/.test(d) ? "letter" : /\bcv\b|resume|résumé|curriculum/.test(d) ? "cv" :
           /autofill|auto-fill|autocomplete|auto-complete|parse/.test(d) ? "autofill" : null;
  }
  /* The box's own label first; the heading above it only when the box itself says nothing. */
  function classify(el) {
    var own = kindOf(describe(el));
    if (own === null) own = kindOf(heading(el).toLowerCase());
    if (own === "autofill" && /parse|autofill/.test(describe(el)) && kindOf(heading(el).toLowerCase()) === "cv") own = "cv";
    return own === "other" ? "skip" : own;
  }

  /* Decide which file goes in which upload box. Boxes that take documents (.pdf/.doc) but don't say what they're
     for get your CV first, then your cover letter – most forms list them in that order. */
  function assignFiles(files) {
    var hasCv = files.some(function (pair) { return pair[1] === "cv"; });
    files.forEach(function (pair) { if (pair[1] === "autofill") pair[1] = hasCv ? null : "cv"; });
    hasCv = files.some(function (pair) { return pair[1] === "cv"; });
    var hasLetter = files.some(function (pair) { return pair[1] === "letter"; });
    if (files.length === 1 && !files[0][1]) files[0][1] = "cv";
    files.forEach(function (pair) {
      if (pair[1]) return;
      var el = pair[0], d = describe(el) + " " + (el.accept || "");
      if (/portfolio|photo|image|transcript|certificate|passport|\bid\b|video|audio/.test(d)) return;
      if (!/pdf|docx?|document|\.rtf|\.txt/.test(d) && el.accept) return;
      if (!hasCv) { pair[1] = "cv"; hasCv = true; }
      else if (!hasLetter) { pair[1] = "letter"; hasLetter = true; }
    });
    return files.filter(function (pair) { return pair[1] && pair[1] !== "skip"; });
  }

  /* Every empty upload box on the page and what goes in it (for "Attach my CV & cover letter"). */
  function uploads() {
    var files = [];
    all("input[type=file]").forEach(function (el) {
      if (el.closest("#jhq-panel") || el.disabled) return;
      files.push([el, classify(el)]);
    });
    return assignFiles(files).filter(function (pair) { return !(pair[0].files && pair[0].files.length); })
      .map(function (pair) { return { id: tag(pair[0]), which: pair[1] }; });
  }

  function visible(el) {
    if (el.disabled || el.readOnly) return false;
    var r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return (r.width > 0 && r.height > 0 && s.visibility !== "hidden") || el.type === "file";
  }

  function setValue(el, value) {
    var proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype :
                el.tagName === "SELECT" ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, value);
    ["input", "change", "blur"].forEach(function (t) { el.dispatchEvent(new Event(t, { bubbles: true })); });
  }

  /* A letter cut down to a box's character limit: whole paragraphs only, keeping the greeting and sign-off. */
  function fitText(text, max) {
    var paras = String(text).split(/\n\s*\n/), head = paras[0], tail = paras.slice(-2).join("\n\n"), body = paras.slice(1, -2);
    var out = head;
    for (var i = 0; i < body.length; i++) {
      if ((out + "\n\n" + body[i] + "\n\n" + tail).length > max) continue;   /* skip a long paragraph, try the next */
      out += "\n\n" + body[i];
    }
    out += "\n\n" + tail;
    return out.length <= max ? out : String(text).slice(0, max - 1).replace(/\s+\S*$/, "") + "…";
  }

  function mark(el, colour) {
    el.style.outline = "3px solid " + (colour || "#e0a526");
    el.style.outlineOffset = "1px";
  }

  /* Which of your details a text field wants. Order matters: the first match wins. */
  var OWN_WORDS = /own words|without (the use of |using )?(ai|generative|chatgpt)|not (to )?use (ai|chatgpt)|no ai\b|written by you/;
  var RULES = [
    ["skip", /preferred.?(first.?)?name|middle.?name|nickname|referr|recruiter|how did you hear|source|password|captcha|(current|present|last)[^a-z]{0,6}(\w+ )?salary|salary.*current|address.?line.?2|addressline2|\bcounty\b|\bstate\b|\bregion\b|\bextension\b|country.?phone.?code|\bsearch\b/],
    ["first_name", /first.?name|given.?name|forename|given-name/],
    ["last_name", /last.?name|surname|family.?name|family-name/],
    ["full_name", /full.?name|^name\b(?!.*(company|employer|organi[sz]ation|school|university|reference|qualification|establishment|referee))|\bname\b(?!.*(company|employer|organi[sz]ation|school|university|reference|qualification|establishment|referee))/],
    ["email", /e-?mail/],
    ["phone", /phone|mobile|telephone|\btel\b/],
    ["linkedin", /linkedin/],
    ["github", /github|portfolio|personal (web)?site|examples of (your )?work/],
    ["postcode", /post.?code|postal|zip/],
    ["city", /\bcity\b|\btown\b/],
    ["address", /address(?!.*e-?mail)|street/],
    ["employer", /current (company|employer)|present employer|employer|company name|current organi/],
    ["job_title", /current (job )?title|current (position|role)|job title/],
    ["notice", /notice/],
    ["salary", /salary|compensation|pay expectation|expected pay/],
    ["right_to_work", /right to work|eligib|work permit|visa status/],
    ["why_company", /why .*(us|company|organi[sz]ation|join|work (for|at|here))|interest in (us|the company)|what (interests|attracts|excites|appeals to|draws) you/],
    ["why_role", /why .*(role|position|job|apply|applying)|motivat/],
    ["summary", /relevant experience|tell us about (yourself|your experience)|skills and experience|summary/],
    ["cover_letter", /cover.?letter|covering letter|supporting statement|personal statement/],
    ["message", /message|additional information|anything else|comments|note to/]
  ];

  function fill(pack) {
    var p = pack.fields, filled = [], files = [], skipped = 0, toEdit = 0, combos = [];
    var answers = {};
    (pack.answers || []).forEach(function (qa) { answers[qa[0]] = qa[1]; });
    var value = {
      first_name: p.first_name, last_name: p.last_name, full_name: p.name, email: p.email, phone: p.phone,
      linkedin: p.linkedin, github: p.github, postcode: p.postcode, city: p.city, address: p.address_line, employer: p.current_employer,
      job_title: p.current_title, notice: p.notice_period, salary: p.salary_expectation, right_to_work: p.right_to_work,
      why_role: pack.why_role, why_company: pack.why_company, summary: pack.summary,
      cover_letter: pack.cover_letter, message: pack.message
    };
    var entryBoxes = entryForms();
    all("input, textarea, select").forEach(function (el) {
      if (!visible(el) || el.closest("#jhq-panel")) return;
      if (entryBoxes.some(function (b) { return b.contains(el); })) return;   /* "Add Employment"-style entry forms */
      var type = (el.type || "").toLowerCase();
      if (["hidden", "submit", "button", "checkbox", "radio", "password", "search", "image", "reset"].indexOf(type) >= 0) return;
      var d = describe(el);
      if (type === "file") {
        files.push([el, classify(el)]);
        return;
      }
      if (el.tagName === "SELECT") {
        if (/country/.test(d)) {
          var opt = Array.prototype.find.call(el.options, function (o) { return /^(united kingdom|uk|great britain|gb)$/i.test(o.text.trim()); });
          if (opt && el.value !== opt.value) { setValue(el, opt.value); mark(el); filled.push("Country"); }
        }
        return;
      }
      if (el.value && el.value.trim()) { skipped++; return; }
      if (OWN_WORDS.test(d)) return;   /* they asked for your own words – left for you (the robot asks you) */
      if (type === "email") d = "email " + d;
      if (type === "tel") d = "phone " + d;
      for (var i = 0; i < RULES.length; i++) {
        if (!RULES[i][1].test(d)) continue;
        var key = RULES[i][0];
        if (key === "skip") return;
        if ((key === "address" || key === "postcode" || key === "city") && /employer|company name|business name/i.test(prevLabel(el, 3))) return;
        var v = value[key];
        if ((key === "cover_letter" || key === "why_role" || key === "why_company" || key === "summary") && el.tagName !== "TEXTAREA" && v && v.length > 300)
          v = key === "cover_letter" ? pack.message : v;
        if (!v) return;
        if (el.maxLength > 0 && v.length > el.maxLength) v = fitText(v, el.maxLength);
        setValue(el, v);
        var pickList = el.getAttribute("role") === "combobox" || el.getAttribute("aria-autocomplete");
        if (pickList) combos.push(tag(el));
        if (/\[[^\]]+\]/.test(v) || pickList) { mark(el, "#d93025"); toEdit++; } else mark(el);
        filled.push(key.replace(/_/g, " ") + (pickList ? " – pick it from the list" : ""));
        return;
      }
    });

    /* Cover letter / statement boxes that are rich-text editors rather than plain text boxes. */
    all("[contenteditable=true], [contenteditable='']").forEach(function (ed) {
      if (!visible(ed) || ed.closest("#jhq-panel") || clean(ed.innerText)) return;
      if (entryBoxes.some(function (b) { return b.contains(ed); })) return;
      var lab = (heading(ed) + " " + (ed.getAttribute("aria-label") || "") + " " + (ed.getAttribute("data-placeholder") || "")).toLowerCase();
      if (OWN_WORDS.test(lab) || !/cover.?letter|covering letter|supporting statement|personal statement|letter of application/.test(lab)) return;
      if (!pack.cover_letter) return;
      ed.focus();
      var ok = document.execCommand && document.execCommand("insertText", false, pack.cover_letter);
      if (!ok || !clean(ed.innerText)) { ed.innerText = pack.cover_letter; ed.dispatchEvent(new Event("input", { bubbles: true })); }
      mark(ed);
      filled.push("cover letter");
    });

    /* Yes/No questions, read from each question's OWN wording only (never nearby text):
       right to work = Yes; sponsorship / needing a visa = No; and, as you've told us, unspent criminal
       convictions = No and reasonable adjustments = No – only when the form asks you directly, never on
       consent / check / policy questions. Anything else is left for you. */
    var radios = {};
    all("input[type=radio]").forEach(function (r) { if (r.name) (radios[r.name] = radios[r.name] || []).push(r); });
    Object.keys(radios).forEach(function (name) {
      var group = radios[name];
      if (group.length < 2 || group.length > 4 || group.some(function (r) { return r.checked; })) return;
      var lb = group[0].closest("[role=radiogroup]"), lbl = lb && lb.getAttribute("aria-labelledby");
      var d = clean((lbl && document.getElementById(lbl) && document.getElementById(lbl).innerText) ||
                    (lb && lb.getAttribute("aria-label")) || radioQuestion(group[0]) || "").toLowerCase();
      if (!d || d.length > 400) return;
      var asks = /^\W*(do|have|are|is|will|would|did|has)\b/.test(d);
      var notDeclaration = /consent|agree|willing|happy to|prepared to|check\b|checks\b|dbs|disclos|declare|understand|policy|read |aware|confirm|undergo/.test(d);
      var want = null, what = "";
      if (/without[^.?]{0,50}sponsor|no need for[^.?]{0,30}sponsor|not (need|require)[^.?]{0,30}sponsor/.test(d)) { want = /^yes\b/i; what = "right to work without sponsorship: Yes"; }
      else if (/sponsor/.test(d)) { want = /^no\b/i; what = "sponsorship: No"; }
      else if (/\b(require|need)\b[^.?]{0,60}\b(visa|work permit)/.test(d)) { want = /^no\b/i; what = "visa needed: No"; }
      else if (asks && !notDeclaration && /convict|criminal|offen[cs]e|offender|prosecution|\bcaution/.test(d)) { want = /^no\b/i; what = "criminal convictions: No"; }
      else if (asks && !notDeclaration && /adjustments?\b|access (needs|requirements)|additional support/.test(d)) { want = /^no\b/i; what = "reasonable adjustments: No"; }
      else if (/^\W*(do|are|have)\b[^.?]{0,40}(right to work|eligible to work|legally (able|entitled))/.test(d)) { want = /^yes\b/i; what = "right to work: Yes"; }
      if (!want) return;
      var pick = group.find(function (r) { return want.test(clean(optionText(r))); });
      if (pick) { pick.click(); mark(pick.closest("label") || pick); filled.push(what); }
    });

    /* "Autofill from your CV" boxes (SmartRecruiters, Workday) read the CV and overwrite the form, so they
       only get the CV when there is no proper CV box on the page. A single unlabelled box wants the CV. */
    files = assignFiles(files);
    var robotFiles = [];
    files.forEach(function (pair) {
      var el = pair[0], which = pair[1], f = (pack.blobs || {})[which];
      if (el.files && el.files.length) return;
      if (!pack.blobs) { robotFiles.push({ id: tag(el), which: which }); return; }
      if (!f) { filled.push((which === "cv" ? "CV" : "cover letter") + " not found – attach it yourself"); return; }
      try {
        var dt = new DataTransfer();
        dt.items.add(new File([f.blob], f.name, { type: f.blob.type || "application/pdf" }));
        el.files = dt.files;
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
        mark(el.closest("div") || el);
        filled.push((which === "cv" ? "CV" : "cover letter") + " attached");
      } catch (e) { filled.push("couldn't attach " + which + " – attach it yourself"); }
    });
    return Promise.resolve({ filled: filled, skipped: skipped, toEdit: toEdit, files: robotFiles, combos: combos });
  }


  /* The question a field asks, in readable form. */
  function rawLabel(el) {
    var root = el.getRootNode ? el.getRootNode() : document, host = root && root.host, t = "";
    var choice = el.type === "radio" || (el.type === "checkbox" && !/agree|accept|consent|confirm/i.test(el.labels && el.labels[0] ? el.labels[0].innerText : ""));
    if (choice) {
      var fs = el.closest("fieldset, [role=radiogroup], [role=group]");
      var lg = fs && fs.querySelector("legend, [id$=label], [class*=label]:not(label)");
      t = lg ? lg.innerText : fs ? (fs.getAttribute("aria-label") || "") : "";
      if (!t && fs) { var lb0 = fs.getAttribute("aria-labelledby"); var n0 = lb0 && document.getElementById(lb0.split(" ")[0]); if (n0) t = n0.innerText; }
    }
    if (!t && el.labels && el.labels.length) {
      var copy = el.labels[0].cloneNode(true);   /* the label's own words, without the field's options */
      copy.querySelectorAll("select, input, textarea, button").forEach(function (x) { x.remove(); });
      t = copy.textContent;
    }
    if (!t) {
      var lb = el.getAttribute("aria-labelledby");
      if (lb) t = lb.split(/\s+/).map(function (id) { var n = (root.getElementById ? root : document).getElementById(id) || document.getElementById(id); return n ? n.innerText : ""; }).join(" ");
    }
    if (!t) t = el.getAttribute("aria-label") || "";
    if (!t && host) t = host.getAttribute("label") || host.getAttribute("aria-label") || "";
    if (!t) {
      var box = el.closest("[class*=question], [class*=field], .form-group, li, fieldset");
      if (box) t = box.innerText.split("\n")[0];
    }
    if (!t) t = el.placeholder || el.name || "";
    return clean(t).slice(0, 300);
  }
  function display(t) { return clean(t).replace(/\s*\*\s*$/, "").replace(/^\*\s*/, ""); }

  function isRequired(el, raw) {
    if (el.required || el.getAttribute("aria-required") === "true") return true;
    var box = el.closest("[class*=question], [class*=field], .form-group, fieldset, li, label");
    var text = raw + " " + (box ? box.innerText.slice(0, 200) : "");
    return /\*|\brequired\b/i.test(text);
  }

  function optionText(r) {
    var t = (r.labels && r.labels[0] && r.labels[0].innerText) || r.getAttribute("aria-label") || "";
    if (!t && r.parentElement) t = r.parentElement.innerText;
    return clean(t || r.value);
  }

  /* Required questions still unanswered, plus how many form fields the page has. */
  function scan() {
    var qs = [], seen = {}, count = 0;
    all("input, textarea, select, button[aria-haspopup=listbox]").forEach(function (el) {
      if (el.closest("#jhq-panel") || !visible(el)) return;
      var type = (el.type || "").toLowerCase(), tagName = el.tagName;
      if (tagName === "BUTTON") {
        var bt = clean(el.innerText);
        count++;
        if (bt && !/^(select|select one|choose|please select|--)/i.test(bt)) return;
        var lab = rawLabel(el);
        if (isRequired(el, lab)) qs.push({ id: tag(el), label: display(lab), kind: "listbox", options: [] });
        return;
      }
      if (["hidden", "submit", "button", "image", "reset", "search", "password"].indexOf(type) >= 0) return;
      if (type === "file") { count++; return; }
      if (el.closest("header, nav, footer")) return;
      count++;
      if (type === "radio") {
        var key = (el.getRootNode() === document ? "" : "s") + el.name;
        if (seen[key]) return;
        seen[key] = 1;
        var group = all("input[type=radio]").filter(function (r) { return r.name === el.name && r.getRootNode() === el.getRootNode(); });
        if (group.some(function (r) { return r.checked; })) return;
        var lab2 = rawLabel(el);
        if (!isRequired(el, lab2) && !group.some(function (r) { return r.required; })) return;
        qs.push({ id: tag(el), label: display(lab2), kind: "radio", options: group.map(optionText) });
        return;
      }
      if (type === "checkbox") {
        if (el.checked) return;
        var lab3 = rawLabel(el);
        if (isRequired(el, lab3)) qs.push({ id: tag(el), label: display(lab3), kind: "checkbox", options: ["Yes", "No"] });
        return;
      }
      if (tagName === "SELECT") {
        var sel = el.options[el.selectedIndex];
        if (sel && sel.value && !/^(select|choose|please|--)/i.test(sel.text.trim())) return;
        var lab4 = rawLabel(el);
        if (!isRequired(el, lab4)) return;
        qs.push({ id: tag(el), label: display(lab4), kind: "select", options: Array.prototype.map.call(el.options, function (o) { return clean(o.text); })
          .filter(function (o, i) { return o && !(i === 0 && /^(select|choose|please|--)/i.test(o)); }) });
        return;
      }
      if (el.value && el.value.trim()) return;
      var lab5 = rawLabel(el), req = isRequired(el, lab5);
      if (!req && tagName !== "TEXTAREA") return;
      var box5 = el.closest("[class*=question], [class*=field], .form-group, fieldset, li") || el.parentElement;
      var hint = box5 ? clean(box5.innerText).replace(clean(lab5), "").replace(/^\s*\*\s*/, "").slice(0, 240) : "";
      qs.push({ id: tag(el), label: display(lab5), kind: tagName === "TEXTAREA" ? "textarea" : "text", options: [],
                hint: hint, required: req, own_words: OWN_WORDS.test((lab5 + " " + hint).toLowerCase()) });
    });
    return { questions: qs, fields: count };
  }

  function byId(id) { return all('[data-jhq="' + id + '"]')[0]; }
  function same(a, b) { a = clean(a).toLowerCase(); b = clean(b).toLowerCase(); return a === b || (b.length > 1 && a.indexOf(b) === 0); }

  /* Put an answer into a field. Returns "ok", "missing", or "robot" when the robot must click it. */
  function answer(id, value) {
    var el = byId(id);
    if (!el) return "missing";
    if (el.tagName === "BUTTON") return "robot";
    if (el.type === "radio") {
      var group = all("input[type=radio]").filter(function (r) { return r.name === el.name && r.getRootNode() === el.getRootNode(); });
      var pick = group.find(function (r) { return clean(optionText(r)).toLowerCase() === clean(value).toLowerCase(); }) ||
                 group.find(function (r) { return same(optionText(r), value); });
      if (!pick) return "missing";
      pick.click(); mark(pick.closest("label") || pick); return "ok";
    }
    if (el.type === "checkbox") {
      if (/^(yes|true|tick|agree|i agree|accept)/i.test(value) !== el.checked) el.click();
      mark(el.closest("label") || el); return "ok";
    }
    if (el.tagName === "SELECT") {
      var opt = Array.prototype.find.call(el.options, function (o) { return clean(o.text).toLowerCase() === clean(value).toLowerCase(); }) ||
                Array.prototype.find.call(el.options, function (o) { return same(o.text, value); });
      if (!opt) return "missing";
      setValue(el, opt.value); mark(el); return "ok";
    }
    setValue(el, value); mark(el);
    return el.getAttribute("role") === "combobox" || el.getAttribute("aria-autocomplete") ? "robot" : "ok";
  }

  /* A short fingerprint of the page, to tell whether pressing Next moved on. */
  function signature() {
    var h = all("h1, h2, h3").filter(visible).slice(0, 4).map(function (e) { return clean(e.innerText); }).join("|");
    var f = all("input, textarea, select").filter(function (e) { return visible(e) && e.type !== "hidden"; })
      .slice(0, 40).map(function (e) { return e.name || e.id || e.type; }).join(",");
    return location.pathname + "#" + h + "#" + f;
  }

  /* Repeating sections such as "Work Experience 1", "Work Experience 2" or "Education 1": each block's
     fields, with their labels, in page order. */
  function blocks(pattern) {
    var re = new RegExp(pattern, "i");
    var heads = all("h1, h2, h3, h4, h5, h6, legend, [role=heading], div, span").filter(function (h) {
      var t = clean(h.innerText || "");
      return t.length < 40 && re.test(t) && visible(h) &&
             !Array.prototype.some.call(h.children, function (c) { return re.test(clean(c.innerText || "")); });
    });
    var out = [];
    heads.forEach(function (h) {
      /* The block = the nearest container around the heading that holds its fields. */
      var box = h, best = null;
      for (var i = 0; i < 10 && box.parentElement; i++) {
        box = box.parentElement;
        if (box.querySelectorAll("input, textarea, button[aria-haspopup=listbox]").length >= 3) { best = box; break; }
      }
      if (!best || out.some(function (b) { return b.el === best; })) return;
      var fields = Array.prototype.filter.call(best.querySelectorAll("input, textarea, button[aria-haspopup=listbox]"), function (e) {
        return visible(e) && (e.tagName === "BUTTON" || ["hidden", "submit", "button", "file"].indexOf((e.type || "").toLowerCase()) < 0);
      }).map(function (e) {
        return { id: tag(e), label: display(rawLabel(e)), tag: e.tagName, type: (e.type || "").toLowerCase(),
                 role: e.getAttribute("role") || "", value: e.type === "checkbox" ? (e.checked ? "yes" : "") : clean(e.value || e.innerText || "") };
      });
      out.push({ el: best, title: clean(h.innerText), fields: fields });
    });
    return out.map(function (b) { return { title: b.title, fields: b.fields }; });
  }

  /* The "Add" button of a section such as "Work Experience" (Workday: "Add" / "Add Another"). */
  function addButton(section) {
    var re = new RegExp("^" + section + "$", "i");
    var heads = all("h1, h2, h3, h4, h5, h6, legend, [role=heading], div, span").filter(function (h) {
      return visible(h) && re.test(clean(h.innerText || ""));
    });
    /* The first "Add" button after the section's heading (Workday puts it below the section's rows). */
    var adds = all("button, [role=button]").filter(function (b) {
      var t = clean(b.innerText || b.getAttribute("aria-label") || "");
      return visible(b) && (/^add( another)?$/i.test(t) || new RegExp("^add .*" + section, "i").test(t));
    });
    for (var i = 0; i < heads.length; i++) {
      var after = adds.filter(function (b) { return heads[i].compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING; });
      if (after.length) return tag(after[0]);
    }
    return null;
  }

  /* Containers of repeating "add an entry" forms: the fields above an "Add Employment / Add Education" button. */
  var ENTRY_BUTTON = /^\W*add (an? |another |more )?(employment|education|qualification|work|job|position|experience|school)\b/i;
  function entryForms(pattern) {
    var re = pattern ? new RegExp(pattern, "i") : ENTRY_BUTTON;
    var out = [];
    all("button, [role=button], input[type=button], input[type=submit], a").forEach(function (b) {
      if (!visible(b) || !re.test(clean(b.innerText || b.value || ""))) return;
      var box = b;
      for (var i = 0; i < 8 && box.parentElement; i++) {
        box = box.parentElement;
        if (box.querySelectorAll("input:not([type=hidden]):not([type=button]):not([type=submit]), select, textarea").length >= 2) break;
      }
      if (box.querySelectorAll("input:not([type=hidden]), select, textarea").length <= 14) out.push(box);
    });
    return out;
  }

  /* The label of the field before this one – tells "Address" under "Name of present employer" from your own. */
  function prevLabel(el, count) {
    var fields = all("input, textarea, select").filter(function (e) {
      return visible(e) && ["hidden", "submit", "button", "file"].indexOf((e.type || "").toLowerCase()) < 0;
    });
    var i = fields.indexOf(el), out = [];
    for (var k = 1; k <= (count || 1) && i - k >= 0; k++) {
      var lab = labelFor(fields[i - k]);
      if (k > 1 && !/address|post.?code|town|city|county|street/i.test(labelFor(fields[i - k + 1]))) break;
      out.push(lab);
    }
    return out.join(" | ");
  }

  /* A radio button's question ("Are you still employed here?"), skipping the other options' boxes. */
  function radioQuestion(el) {
    var fs = el.closest("fieldset");
    var lg = fs && fs.querySelector("legend");
    if (lg) return clean(lg.innerText);
    var n = el;
    for (var k = 0; k < 6 && n && n !== document.body; k++) {
      for (var p = n.previousElementSibling; p; p = p.previousElementSibling) {
        if (p.querySelector && p.querySelector("input[type=radio]")) continue;
        var t = clean(p.innerText || "");
        if (t && t.length < 160) return t;
        if (t) break;
      }
      n = n.parentElement;
    }
    return "";
  }

  function labelFor(e) {
    var linked = (e.labels && e.labels.length) || e.getAttribute("aria-labelledby") || e.getAttribute("aria-label");
    if (linked || e.type === "radio" || e.type === "checkbox") return display(rawLabel(e));
    var above = heading(e);
    return display(above && !/^(remove|add)\b/i.test(above) ? above : rawLabel(e));
  }

  function fieldInfo(e) {
    var info = { id: tag(e), label: labelFor(e), tag: e.tagName, type: (e.type || "").toLowerCase(),
                 value: e.type === "checkbox" ? (e.checked ? "yes" : "") : clean(e.value || (e.isContentEditable ? e.innerText : "")),
                 placeholder: e.placeholder || "" };
    if (e.isContentEditable) { info.tag = "EDITOR"; info.label = info.label || display(rawLabel(e.closest("[class*=editor], [class*=field], .form-group") || e)); }
    if (e.tagName === "SELECT") info.options = Array.prototype.map.call(e.options, function (o) { return clean(o.text); });
    if (info.type === "radio") { info.option = optionText(e); info.question = radioQuestion(e); info.value = e.checked ? "yes" : ""; }
    return info;
  }

  /* A visible button by its words, e.g. /add more education/ → its tag. */
  function buttonFor(pattern) {
    var re = new RegExp(pattern, "i");
    var b = all("button, [role=button], a.btn, input[type=button], input[type=submit]").find(function (x) {
      return visible(x) && re.test(clean(x.innerText || x.value || x.getAttribute("aria-label") || ""));
    });
    return b ? tag(b) : null;
  }

  /* The open "add an entry" box (a dialog or pop-up with its own Save button) and its fields. */
  function panel(pattern) {
    var re = pattern ? new RegExp(pattern, "i") : /^\W*(save|add|done|ok|confirm)\W*$/i;
    var saves = all("button, [role=button], input[type=submit], input[type=button], a").filter(function (b) {
      return visible(b) && re.test(clean(b.innerText || b.value || ""));
    });
    var dialogs = all("[role=dialog], dialog[open], .modal.show, .modal.in, [class*=popover], [class*=modal], [class*=overlay]").filter(visible);
    var cands = [];
    saves.forEach(function (s) {
      var box = s;
      for (var i = 0; i < 8 && box.parentElement; i++) {
        box = box.parentElement;
        var n = box.querySelectorAll("input:not([type=hidden]):not([type=button]):not([type=submit]), select, textarea, [contenteditable=true]").length;
        if (n >= 3) { if (n <= 16) cands.push({ box: box, save: s, n: n, dialog: dialogs.some(function (d) { return d.contains(box) || box.contains(d); }) }); break; }
      }
    });
    var weak = function (c) { return /^\W*\+?\s*add\W*$/i.test(clean(c.save.innerText || c.save.value || "")) ? 1 : 0; };
    cands.sort(function (a, b) { return (b.dialog - a.dialog) || (weak(a) - weak(b)) || (a.n - b.n); });
    var c = cands[0];
    if (!c) return null;
    var fields = Array.prototype.filter.call(c.box.querySelectorAll("input, select, textarea, [contenteditable=true]"), function (e) {
      return (visible(e) || (e.type || "").toLowerCase() === "radio") && ["hidden", "submit", "button", "file"].indexOf((e.type || "").toLowerCase()) < 0;
    }).map(fieldInfo);
    return { save: tag(c.save), fields: fields, text: clean(c.box.innerText).slice(0, 400) };
  }

  /* Repeating entry blocks, each with its own "Add Employment"-style button (and often "Remove …").
     Each block = the fields since the previous such button (inside the nearest shared container). */
  function entryBlocks(pattern) {
    var re = new RegExp(pattern, "i");
    var adds = all("button, [role=button], input[type=button], input[type=submit], a").filter(function (b) {
      return visible(b) && re.test(clean(b.innerText || b.value || ""));
    });
    var fieldsAll = all("input, select, textarea").filter(function (e) {
      var t = (e.type || "").toLowerCase();
      return (visible(e) || t === "radio") && ["hidden", "submit", "button", "file"].indexOf(t) < 0;
    });
    var blocks = [];
    adds.forEach(function (b, i) {
      var box = b;
      for (var k = 0; k < 8 && box.parentElement; k++) {
        box = box.parentElement;
        if (box.querySelectorAll("input:not([type=hidden]):not([type=button]):not([type=submit]), select, textarea").length >= 2) break;
      }
      var prev = i > 0 ? adds[i - 1] : null;
      var own = fieldsAll.filter(function (f) {
        return box.contains(f) && (b.compareDocumentPosition(f) & Node.DOCUMENT_POSITION_PRECEDING) &&
               (!prev || (prev.compareDocumentPosition(f) & Node.DOCUMENT_POSITION_FOLLOWING));
      });
      if (!own.length || own.length > 16) return;
      var infos = own.map(fieldInfo);
      var empty = own.every(function (f) { return f.type === "radio" || f.type === "checkbox" ? !f.checked : !clean(f.value); });
      var remove = Array.prototype.some.call((b.parentElement || box).querySelectorAll("button, a, input[type=button]"), function (x) {
        return /^\W*remove|^\W*delete/i.test(clean(x.innerText || x.value || ""));
      });
      blocks.push({ add: tag(b), fields: infos, empty: empty, remove: remove,
                    values: own.map(function (f) { return f.value || ""; }).join(" | ") });
    });
    return blocks;
  }

  /* Pick a radio option the way a person would: click its label/box, so styled buttons register it. */
  function pickRadio(id) {
    var r = document.querySelector('[data-jhq="' + id + '"]') || all("input").find(function (e) { return e.getAttribute("data-jhq") === id; });
    if (!r) return false;
    var target = r.closest("label") || (r.labels && r.labels[0]) || r.parentElement || r;
    target.click();
    if (!r.checked) { r.click(); }
    if (!r.checked) { r.checked = true; r.dispatchEvent(new Event("change", { bubbles: true })); r.dispatchEvent(new Event("input", { bubbles: true })); }
    return r.checked;
  }

  /* The "+ Add" button that belongs to a section heading such as "Education (Optional)" or "Experience". */
  function sectionAdd(pattern) {
    var re = new RegExp("^\\W*(" + pattern + ")(\\s+history)?\\s*(\\(optional\\))?\\s*\\*?\\s*$", "i");
    var heads = all("h1, h2, h3, h4, h5, h6, legend, label, [role=heading], div, span, p, strong").filter(function (h) {
      if (!visible(h)) return false;
      var own = clean(Array.prototype.map.call(h.childNodes, function (n) { return n.nodeType === 3 ? n.textContent : (n.innerText || ""); }).join(" "));
      return own.length < 60 && re.test(own) && !Array.prototype.some.call(h.children, function (c) { return re.test(clean(c.innerText || "")); });
    });
    for (var i = 0; i < heads.length; i++) {
      var box = heads[i];
      for (var k = 0; k < 4 && box.parentElement; k++) {
        box = box.parentElement;
        var h = heads[i];
        var b = Array.prototype.find.call(box.querySelectorAll("button, [role=button], a"), function (x) {
          return visible(x) && (h.compareDocumentPosition(x) & Node.DOCUMENT_POSITION_FOLLOWING) &&
                 /^\W*\+?\s*add\b/i.test(clean(x.innerText || x.getAttribute("aria-label") || ""));
        });
        if (b) return tag(b);
      }
    }
    return null;
  }

  /* Visible fields whose label matches, e.g. every "Skill:" box. */
  function labelled(pattern) {
    var re = new RegExp(pattern, "i");
    return all("input, textarea").filter(function (e) {
      return visible(e) && ["hidden", "submit", "button", "file", "checkbox", "radio"].indexOf((e.type || "").toLowerCase()) < 0 &&
             re.test(display(rawLabel(e)));
    }).map(fieldInfo);
  }

  return { fill: fill, scan: scan, answer: answer, signature: signature, all: all, visible: visible,
           blocks: blocks, addButton: addButton, uploads: uploads, panel: panel, buttonFor: buttonFor, labelled: labelled,
           entryBlocks: entryBlocks, pickRadio: pickRadio, sectionAdd: sectionAdd };
})();
window.JHQ = JHQ;
