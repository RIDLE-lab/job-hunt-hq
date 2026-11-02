/* Under every "where" box: show what the place was understood as ("Leeds, West Yorkshire, England, United Kingdom")
   and pick the matching country. */
(() => {
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
          if (!d.label) { note.innerHTML = "<span class='warn'>Not found – try a nearby town or a postcode.</span>"; return; }
          note.innerHTML = "📍 <b></b>";
          note.querySelector("b").textContent = d.label;
          if (country && d.country && [...country.options].some((o) => o.value === d.country)) country.value = d.country;
        }).catch(() => { note.textContent = ""; });
    };
    input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(look, 700); });
    if (input.value.trim()) look();
  });
})();
