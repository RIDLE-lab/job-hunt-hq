/* "Fill this application" – run on an employer's application form. It asks Job Hunt HQ (on this PC)
   for your details and the job's cover letter, fills the fields it recognises, attaches your CV and
   cover letter, and highlights everything it filled. It never presses Submit. */
(function () {
  var BASE = "__BASE__", TOKEN = "__TOKEN__";
  var old = document.getElementById("jhq-panel");
  if (old) old.remove();

  var panel = document.createElement("div");
  panel.id = "jhq-panel";
  panel.style.cssText = "position:fixed;z-index:2147483647;right:16px;bottom:16px;width:340px;max-width:calc(100vw - 32px);" +
    "background:#1f3a5f;color:#fff;font:14px/1.45 'Segoe UI',system-ui,sans-serif;border-radius:12px;padding:14px 16px;" +
    "box-shadow:0 8px 30px rgba(0,0,0,.35)";
  panel.innerHTML = "<b>Job Hunt HQ</b><div id='jhq-msg' style='margin-top:6px'>Getting your details…</div>";
  document.body.appendChild(panel);
  var msg = panel.querySelector("#jhq-msg");

  /* Talks to Job Hunt HQ through a small window it opens on 127.0.0.1, which closes itself.
     (Browsers block websites from contacting apps on your PC directly.) */
  function bridge(request) {
    return new Promise(function (resolve, reject) {
      var done = false;
      function onMsg(e) {
        if (e.origin !== BASE || !e.data || !e.data.jhq) return;
        done = true;
        window.removeEventListener("message", onMsg);
        e.data.error ? reject(new Error(e.data.error)) : resolve(e.data);
      }
      window.addEventListener("message", onMsg);
      request.token = TOKEN;
      var w = window.open(BASE + "/bridge#" + encodeURIComponent(JSON.stringify(request)), "jhq_bridge",
                          "width=420,height=220,left=40,top=40");
      if (!w) { window.removeEventListener("message", onMsg); reject(new Error("popup")); return; }
      setTimeout(function () { if (!done) { window.removeEventListener("message", onMsg); reject(new Error("timeout")); } }, 25000);
    });
  }

  function esc(s) { return String(s || "").replace(/[&<>"']/g, function (c) { return "&#" + c.charCodeAt(0) + ";"; }); }

  /* Every pre-written answer with a Copy button – for anything the button can't fill itself. */
  function copyList(pack) {
    var f = pack.fields, rows = [
      ["Full name", f.name], ["First name", f.first_name], ["Last name", f.last_name], ["Email", f.email],
      ["Phone", f.phone], ["Address line 1", f.address_line], ["Town / city", f.city], ["Postcode", f.postcode],
      ["Country", "United Kingdom"], ["LinkedIn", f.linkedin], ["Current employer", f.current_employer],
      ["Current job title", f.current_title], ["Notice period", f.notice_period], ["Salary expectation", f.salary_expectation],
      ["Right to work", f.right_to_work], ["How did you hear about us", "LinkedIn"], ["Short message", pack.message]
    ];
    (pack.answers || []).forEach(function (qa) { rows.push([qa[0], qa[1]]); });
    rows.push(["Cover letter (full)", pack.cover_letter]);
    return rows.filter(function (r) { return r[1]; }).map(function (r, i) {
      return "<div style='padding:6px 0;border-top:1px solid rgba(255,255,255,.15)'>" +
        "<div style='display:flex;justify-content:space-between;gap:8px;align-items:center'><span style='font-size:12px;opacity:.8'>" + esc(r[0]) + "</span>" +
        "<button data-jhq-copy='" + i + "' style='font:12px sans-serif;border:0;border-radius:5px;padding:2px 8px;background:#e0a526;color:#1b1404;cursor:pointer'>Copy</button></div>" +
        "<div data-jhq-text='" + i + "' style='white-space:pre-wrap;max-height:4.5em;overflow:hidden;font-size:12.5px'>" + esc(r[1]) + "</div></div>";
    }).join("");
  }

  function render(pack, result) {
    var opts = pack.recent.map(function (j) {
      return "<option value='" + j.id + "'" + (j.id === pack.job.id ? " selected" : "") + ">" +
        esc(j.title + " · " + j.company) + "</option>";
    }).join("");
    panel.style.maxHeight = "calc(100vh - 32px)";
    panel.style.overflowY = "auto";
    panel.innerHTML =
      "<div style='display:flex;justify-content:space-between;gap:8px'><b>Job Hunt HQ</b>" +
      "<span><a href='#' id='jhq-min' style='color:#fff;text-decoration:none;margin-right:10px' title='Minimise'>–</a>" +
      "<a href='#' id='jhq-x' style='color:#fff;text-decoration:none' title='Close'>✕</a></span></div>" +
      "<div id='jhq-body'>" +
      "<label style='display:block;margin-top:8px;font-size:12px;opacity:.85'>Filling for</label>" +
      "<select id='jhq-job' style='width:100%;margin-top:2px;padding:5px;border-radius:6px;border:0;color:#111'>" + opts + "</select>" +
      "<div style='margin-top:10px'>" + (result.filled.length
        ? "Filled <b>" + result.filled.length + "</b>: " + result.filled.join(", ") + "."
        : "Nothing to fill automatically on this page – use <b>Copy answers</b> below.") +
      (result.skipped ? " Left " + result.skipped + " already-filled field" + (result.skipped > 1 ? "s" : "") + " alone." : "") + "</div>" +
      (result.toEdit ? "<div style='margin-top:8px;padding:6px 8px;border-radius:6px;background:#d93025'>Edit the answer" + (result.toEdit > 1 ? "s" : "") +
        " outlined in <b>red</b>: replace any [bracketed] part with something specific about this employer, and pick list fields (like City) from their drop-down.</div>" : "") +
      "<div style='margin-top:8px;font-size:12.5px;opacity:.9'>Check the highlighted fields and answer anything left blank. " +
      "On forms with several steps (like Workday), press <b>Fill this step</b> on each page.</div>" +
      "<button id='jhq-again' style='margin-top:10px;width:100%;padding:7px;border:1px solid #e0a526;border-radius:8px;background:transparent;color:#fff;cursor:pointer'>Fill this step</button>" +
      "<details style='margin-top:10px'><summary style='cursor:pointer;font-weight:600'>Copy answers</summary>" + copyList(pack) + "</details>" +
      "<button id='jhq-done' style='margin-top:12px;width:100%;padding:8px;border:0;border-radius:8px;background:#e0a526;color:#1b1404;font-weight:600;cursor:pointer'>I've submitted – mark as applied</button>" +
      "</div>";
    panel.querySelector("#jhq-x").onclick = function (e) { e.preventDefault(); panel.remove(); };
    panel.querySelector("#jhq-min").onclick = function (e) {
      e.preventDefault();
      var body = panel.querySelector("#jhq-body");
      body.style.display = body.style.display === "none" ? "" : "none";
    };
    panel.querySelector("#jhq-job").onchange = function () { start(this.value); };
    panel.querySelector("#jhq-again").onclick = function () {
      var b = this;
      JHQ.fill(pack).then(function (res) { render(pack, res); });
      b.textContent = "Filling…";
    };
    panel.querySelectorAll("[data-jhq-copy]").forEach(function (btn) {
      btn.onclick = function () {
        var i = btn.getAttribute("data-jhq-copy");
        var text = panel.querySelector("[data-jhq-text='" + i + "']").textContent;
        var ok = function () { btn.textContent = "Copied"; setTimeout(function () { btn.textContent = "Copy"; }, 1500); };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(ok, function () { fallbackCopy(text); ok(); });
        } else { fallbackCopy(text); ok(); }
      };
    });
    panel.querySelector("#jhq-done").onclick = function () {
      var b = this; b.textContent = "Saving…";
      bridge({ action: "applied", job_id: pack.job.id, page: location.href })
        .then(function () { b.textContent = "✓ Marked as applied in Job Hunt HQ"; b.disabled = true; })
        .catch(function () { b.textContent = "Couldn't reach Job Hunt HQ – is it running?"; });
    };
  }

  function fallbackCopy(text) {
    var t = document.createElement("textarea");
    t.value = text; t.style.position = "fixed"; t.style.opacity = "0";
    document.body.appendChild(t); t.select();
    try { document.execCommand("copy"); } catch (e) {}
    t.remove();
  }

  function start(jobId) {
    msg = panel.querySelector("#jhq-msg") || panel;
    bridge({ action: "fill", job_id: jobId || null, page: location.href })
      .then(function (pack) { return JHQ.fill(pack).then(function (res) { render(pack, res); }); })
      .catch(function (e) {
        var why = e.message === "popup" ? "Your browser blocked the small Job Hunt HQ window. Allow pop-ups for this site, then click the button again."
                : e.message === "timeout" ? "Job Hunt HQ didn't answer. Make sure it's running (run.bat), then click the button again."
                : e.message;
        panel.innerHTML = "<b>Job Hunt HQ</b><div style='margin-top:6px'>" + why.replace(/[<>&]/g, "") + "</div>";
      });
  }
  start();
})();
