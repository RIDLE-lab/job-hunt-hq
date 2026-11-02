/* Talks to your Job Hunt HQ account. Runs inside the extension, so job sites never see your key. */
importScripts("config.js");

async function api(body) {
  const r = await fetch(JHQ_CONFIG.base + "/api/assistant", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(Object.assign({ token: JHQ_CONFIG.token }, body))
  });
  if (r.status === 403) throw new Error("Your assistant isn't connected any more – download it again from Job Hunt HQ → Assistant.");
  if (!r.ok) throw new Error("Job Hunt HQ didn't answer (" + r.status + "). Is it running?");
  return r.json();
}

async function file(path) {
  const r = await fetch(JHQ_CONFIG.base + path + (path.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(JHQ_CONFIG.token));
  if (!r.ok) return null;
  const buf = new Uint8Array(await r.arrayBuffer());
  let bin = "";
  for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
  const name = decodeURIComponent(r.headers.get("X-Filename") || "") || (path.includes("letter") ? "Cover letter.pdf" : "CV.pdf");
  return { b64: btoa(bin), type: r.headers.get("Content-Type") || "application/pdf", name };
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  const work = msg.type === "api" ? api(msg.body) : msg.type === "file" ? file(msg.path) : Promise.reject(new Error("?"));
  work.then((data) => reply({ ok: true, data }), (e) => reply({ ok: false, error: e.message }));
  return true;
});

/* Clicking the toolbar icon opens or closes the assistant on the current page. */
chrome.action.onClicked.addListener((tab) => {
  if (tab.id) chrome.tabs.sendMessage(tab.id, { type: "toggle" }).catch(() => {});
});
