/* Under every "where" box: show what the place was understood as ("Leeds, West Yorkshire, England, United Kingdom")
   and pick the matching country. */
(() => {
  const NOT_FOUND = {
    en: "Not found – try a nearby town or a postcode.", fr: "Introuvable – essayez une ville proche ou un code postal.",
    de: "Nicht gefunden – versuchen Sie einen Ort in der Nähe oder eine Postleitzahl.", nl: "Niet gevonden – probeer een plaats in de buurt of een postcode.",
    es: "No encontrado: prueba con una ciudad cercana o un código postal.", pt: "Não encontrado – experimente uma localidade próxima ou um código postal.",
    ar: "لم يُعثر عليه – جرّب مدينة قريبة أو رمزًا بريديًا."}[(document.documentElement.lang || "en").slice(0, 2)] ||
    "Not found – try a nearby town or a postcode.";
  document.querySelectorAll("input[data-place]").forEach((input) => {
    const note = document.createElement("p");
    note.className = "place-note";
    note.setAttribute("aria-live", "polite");
    input.insertAdjacentElement("afterend", note);
    const country = input.form && input.form.querySelector("[data-country]");
    let timer = null, last = "";
    const look = () => {
      const q = input.value.trim();
      if (q === last) return;
      last = q;
      if (q.length < 2) { note.textContent = ""; return; }
      note.textContent = "…";
      fetch("/api/place?q=" + encodeURIComponent(q + (country && country.value !== "GB" && !q.includes(",") ? ", " + country.selectedOptions[0].text : "")))
        .then((r) => r.json()).then((d) => {
          if (!d.label) { note.innerHTML = "<span class='warn'></span>"; note.firstChild.textContent = NOT_FOUND; return; }
          note.innerHTML = "📍 <b></b>";
          note.querySelector("b").textContent = d.label;
          if (country && d.country && [...country.options].some((o) => o.value === d.country)) country.value = d.country;
        }).catch(() => { note.textContent = ""; });
    };
    input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(look, 700); });
    if (input.value.trim()) look();
  });
})();
