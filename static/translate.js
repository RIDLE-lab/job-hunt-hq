/* For any English text the built-in translations don't cover, use the browser's own on-device translator
   (Chrome and Edge have one) – the page never leaves the computer. Where there isn't one, the text stays English. */
(async () => {
  const lang = document.currentScript ? document.currentScript.dataset.lang : document.querySelector("script[data-lang]").dataset.lang;
  if (!("Translator" in self) || !lang) return;
  try {
    const ok = await Translator.availability({ sourceLanguage: "en", targetLanguage: lang });
    if (ok === "unavailable") return;
    const tr = await Translator.create({ sourceLanguage: "en", targetLanguage: lang });
    const english = /\b(the|and|your|you|to|of|for|with|this|is|it|on|in|a|or|from|will|each|every)\b/i;
    const walker = document.createTreeWalker(document.querySelector("main") || document.body, NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => {
        const p = n.parentElement;
        if (!p || p.closest("script,style,textarea,input,select,code,pre,[contenteditable],.paper,#jhq-assistant")) return NodeFilter.FILTER_REJECT;
        const t = n.nodeValue.trim();
        return t.length > 3 && english.test(t) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      }
    });
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const n of nodes) {
      const lead = n.nodeValue.match(/^\s*/)[0], tail = n.nodeValue.match(/\s*$/)[0];
      try { n.nodeValue = lead + (await tr.translate(n.nodeValue.trim())) + tail; } catch (e) { break; }
    }
  } catch (e) { /* stays English */ }
})();
