"""Render the conference list as a self-contained HTML page for GitHub Pages.

The data is inlined into the page at build time, so the result is a single
static file with no external requests — easy to publish on GitHub Pages and
embed in a Google Site (Insert → Embed → By URL).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import List

from .models import CSV_FIELDS, Conference
from .status import ENDED, PARTICIPATION, SUBMISSION, UNKNOWN, parse_date

# Submission first (deadline still open), then Participation, then Unknown,
# then Ended.
_STATUS_ORDER = {SUBMISSION: 0, PARTICIPATION: 1, UNKNOWN: 2, ENDED: 3}


def _sort_key(c: Conference):
    when = parse_date(c.submission_deadline) or parse_date(c.start_date) or date.max
    return (_STATUS_ORDER.get(c.status, 4), when)


def _ga_snippet(measurement_id: str) -> str:
    """Google Analytics (gtag.js) loader, or empty when no ID is configured."""
    if not measurement_id:
        return ""
    mid = json.dumps(measurement_id)  # safely quoted
    return (
        '<script async src="https://www.googletagmanager.com/gtag/js?id='
        + measurement_id
        + '"></script>\n<script>\n'
        "window.dataLayer = window.dataLayer || [];\n"
        "function gtag(){dataLayer.push(arguments);}\n"
        "gtag('js', new Date());\n"
        "gtag('config', " + mid + ");\n"
        "</script>"
    )


def render_html(
    conferences: List[Conference],
    *,
    title: str = "Conference Tracker",
    ga_measurement_id: str = "",
) -> str:
    # Only surface conferences that are still actionable — hide ended ones.
    visible = [c for c in conferences if c.status != ENDED]
    rows = sorted(visible, key=_sort_key)
    data = [{k: getattr(c, k) for k in CSV_FIELDS} for c in rows]
    # Escaping for safe inlining inside a <script> tag.
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (
        _TEMPLATE.replace("__TITLE__", title)
        .replace("__GENERATED__", generated)
        .replace("__GA__", _ga_snippet(ga_measurement_id))
        .replace("__DATA__", payload)
    )


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
__GA__
<style>
  :root { --bg:#fff; --fg:#1b1f24; --muted:#6b7280; --line:#e5e7eb; --accent:#2563eb; }
  * { box-sizing: border-box; }
  body { margin:0; font:15px/1.45 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
         color:var(--fg); background:var(--bg); }
  .wrap { max-width:1100px; margin:0 auto; padding:18px 16px 48px; }
  h1 { font-size:20px; margin:0 0 2px; }
  .sub { color:var(--muted); font-size:13px; margin-bottom:14px; }
  .controls { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-bottom:12px; }
  #q { flex:1 1 220px; min-width:180px; padding:8px 10px; border:1px solid var(--line);
       border-radius:8px; font-size:14px; }
  .filters { display:flex; gap:6px; flex-wrap:wrap; }
  .filters button { padding:7px 11px; border:1px solid var(--line); background:#f9fafb;
       border-radius:999px; cursor:pointer; font-size:13px; color:var(--fg); }
  .filters button.active { background:var(--accent); border-color:var(--accent); color:#fff; }
  table { width:100%; border-collapse:collapse; font-size:14px; }
  th, td { text-align:left; padding:9px 10px; border-bottom:1px solid var(--line);
       vertical-align:top; }
  th { cursor:pointer; user-select:none; white-space:nowrap; font-size:12px;
       text-transform:uppercase; letter-spacing:.03em; color:var(--muted); }
  th.sorted::after { content:" \25B4"; }
  th.sorted.desc::after { content:" \25BE"; }
  td a { color:var(--accent); text-decoration:none; }
  td a:hover { text-decoration:underline; }
  .badge { display:inline-block; padding:2px 8px; border-radius:999px; font-size:12px;
       font-weight:600; white-space:nowrap; }
  .b-Submission { background:#dcfce7; color:#166534; }
  .b-Participation { background:#fef3c7; color:#92400e; }
  .b-Ended { background:#f1f5f9; color:#64748b; }
  .b-Unknown { background:#f3f4f6; color:#6b7280; }
  .nowrap { white-space:nowrap; }
  .muted { color:var(--muted); }
  .count { color:var(--muted); font-size:13px; margin:0 0 8px; }
  .empty { padding:24px; text-align:center; color:var(--muted); }
  /* Deadline countdown: understated natural-language text with a leading
     hourglass and an urgency colour — deliberately not a filled pill. */
  .cd { display:block; margin-top:3px; font-size:12px; font-weight:600; white-space:nowrap; }
  .cd::before { content:"\231B\FE0E "; font-weight:400; }
  .u-soon { color:#b91c1c; }
  .u-near { color:#b45309; }
  .u-far  { color:#15803d; }
  /* Add-to-calendar links under the website link. */
  .cal { display:block; margin-top:4px; font-size:12px; }
  .cal a { color:var(--muted); }
  .cal .sep { color:var(--line); padding:0 3px; }
  @media (max-width:640px){ th:nth-child(2), td:nth-child(2){ display:none; } }
</style>
</head>
<body>
<div class="wrap">
  <h1>__TITLE__</h1>
  <div class="sub">Updated daily &middot; last built __GENERATED__</div>
  <div class="controls">
    <input id="q" type="search" placeholder="Search name or location…" aria-label="Search">
    <div class="filters" id="filters">
      <button data-f="all" class="active">All</button>
      <button data-f="Submission">Submission</button>
      <button data-f="Participation">Participation</button>
    </div>
  </div>
  <p class="count" id="count"></p>
  <table>
    <thead><tr>
      <th data-k="name">Conference</th>
      <th data-k="location">Location</th>
      <th data-k="submission_deadline">Deadline</th>
      <th data-k="status">Status</th>
      <th data-k="start_date">Start</th>
      <th data-k="end_date">End</th>
      <th data-k="contact">Link</th>
    </tr></thead>
    <tbody id="rows"></tbody>
  </table>
  <div class="empty" id="empty" hidden>No conferences match your search.</div>
</div>
<script>
const DATA = __DATA__;
let filter = "all", query = "", sortKey = null, sortDir = 1;

function isUrl(s){ return /^https?:\/\//i.test(s || ""); }
function isEmail(s){ return /@/.test(s || "") && !isUrl(s); }

function track(a, name){ a.dataset.conf = name; a.dataset.url = a.href; }

// --- Dates: parse ISO YYYY-MM-DD as a UTC calendar day (no timezone drift) ---
function parseDay(s){
  if (!/^\d{4}-\d{2}-\d{2}/.test(s || "")) return null;
  const p = s.slice(0,10).split("-");
  return new Date(Date.UTC(+p[0], +p[1]-1, +p[2]));
}
function addDays(d, n){ const x = new Date(d); x.setUTCDate(x.getUTCDate()+n); return x; }
function pad(n){ return String(n).padStart(2,"0"); }
function ymd(d){ return "" + d.getUTCFullYear() + pad(d.getUTCMonth()+1) + pad(d.getUTCDate()); }
function iso(d){ return d.getUTCFullYear() + "-" + pad(d.getUTCMonth()+1) + "-" + pad(d.getUTCDate()); }

// Whole days from today (UTC) until the given ISO date; null if unparseable.
function daysUntil(s){
  const d = parseDay(s); if (!d) return null;
  const n = new Date();
  const today = Date.UTC(n.getUTCFullYear(), n.getUTCMonth(), n.getUTCDate());
  return Math.round((d.getTime() - today) / 86400000);
}
// Natural-language countdown — intentionally distinct from a raw "N days left".
function countdownPhrase(days){
  if (days < 0) return null;
  if (days === 0) return "closes today";
  if (days === 1) return "closes tomorrow";
  if (days < 14) return "closes in " + days + " days";
  if (days < 60){ const w = Math.round(days/7); return "closes in " + w + " week" + (w>1?"s":""); }
  const m = Math.round(days/30); return "closes in " + m + " month" + (m>1?"s":"");
}
function urgencyClass(days){ return days <= 7 ? "u-soon" : days <= 30 ? "u-near" : "u-far"; }

// Build Google Calendar / Outlook "add event" links for an all-day event
// spanning [start, end] (end is treated as exclusive by both providers).
function calEvent(title, start, end, location, details){
  const endEx = addDays(end, 1);
  const text = encodeURIComponent(title || "");
  const loc  = encodeURIComponent(location || "");
  const det  = encodeURIComponent(details || "");
  const google = "https://calendar.google.com/calendar/render?action=TEMPLATE"
    + "&text=" + text + "&dates=" + ymd(start) + "/" + ymd(endEx)
    + "&location=" + loc + "&details=" + det;
  const outlook = "https://outlook.office.com/calendar/0/deeplink/compose?path=/calendar/action/compose"
    + "&rru=addevent&subject=" + text + "&startdt=" + iso(start) + "&enddt=" + iso(endEx)
    + "&allday=true&location=" + loc + "&body=" + det;
  return { google, outlook };
}

// Context-aware calendar target: while the CFP is open, add the SUBMISSION
// DEADLINE (the thing not to miss); once it has passed, add the conference
// DATES instead. Returns {label, google, outlook} or null.
function calendarLinks(row){
  const details = isUrl(row.contact) ? row.contact : "";
  const deadline = parseDay(row.submission_deadline);
  const cfpOpen = row.status === "Submission" && deadline
    && daysUntil(row.submission_deadline) >= 0;
  if (cfpOpen){
    const ev = calEvent("Submission deadline — " + (row.name || ""),
                        deadline, deadline, row.location, details);
    return { label: "Deadline", google: ev.google, outlook: ev.outlook };
  }
  const start = parseDay(row.start_date);
  if (start){
    const end = parseDay(row.end_date) || start;
    const ev = calEvent(row.name || "", start, end, row.location, details);
    return { label: "Dates", google: ev.google, outlook: ev.outlook };
  }
  return null;
}

function linkCell(td, contact, name){
  if (isUrl(contact)) { const a=document.createElement("a"); a.href=contact; a.target="_blank";
    a.rel="noopener"; a.textContent="Website ↗"; track(a,name); td.appendChild(a); }
  else if (isEmail(contact)) { const a=document.createElement("a"); a.href="mailto:"+contact;
    a.textContent=contact; track(a,name); td.appendChild(a); }
  else { td.textContent = contact || "—"; }
}

function nameCell(td, row){ td.textContent = row.name; }

// Report each outbound conference click to Google Analytics (no-op if GA is off).
document.addEventListener("click", function(e){
  const a = e.target.closest && e.target.closest("a[data-conf]");
  if (a && typeof window.gtag === "function") {
    window.gtag("event", "conference_click",
      { conference_name: a.dataset.conf, link_url: a.dataset.url });
  }
}, true);

function render(){
  const tbody = document.getElementById("rows");
  tbody.textContent = "";
  let rows = DATA.filter(r => {
    if (filter !== "all" && r.status !== filter) return false;
    if (query) { const h=(r.name+" "+r.location).toLowerCase();
      if (!h.includes(query)) return false; }
    return true;
  });
  if (sortKey){
    rows = rows.slice().sort((a,b)=>{
      const x=(a[sortKey]||"").toLowerCase(), y=(b[sortKey]||"").toLowerCase();
      return x<y? -sortDir : x>y? sortDir : 0;
    });
  }
  for (const r of rows){
    const tr=document.createElement("tr");
    const c1=document.createElement("td"); nameCell(c1,r); tr.appendChild(c1);
    const c2=document.createElement("td"); c2.textContent=r.location||"—"; tr.appendChild(c2);
    const c3=document.createElement("td"); c3.className="nowrap";
      c3.appendChild(document.createTextNode(r.submission_deadline||"—"));
      if (r.submission_deadline){
        const dleft = daysUntil(r.submission_deadline);
        const phrase = (dleft===null) ? null : countdownPhrase(dleft);
        if (phrase){ const cd=document.createElement("span");
          cd.className="cd "+urgencyClass(dleft); cd.textContent=phrase; c3.appendChild(cd); }
      }
      tr.appendChild(c3);
    const c4=document.createElement("td"); const b=document.createElement("span");
      b.className="badge b-"+(r.status||"Unknown"); b.textContent=r.status||"Unknown";
      c4.appendChild(b); tr.appendChild(c4);
    const c5=document.createElement("td"); c5.className="nowrap";
      c5.textContent=r.start_date||"—"; tr.appendChild(c5);
    const c6=document.createElement("td"); c6.className="nowrap";
      c6.textContent=r.end_date||"—"; tr.appendChild(c6);
    const c7=document.createElement("td"); linkCell(c7,r.contact,r.name);
      const cal=calendarLinks(r);
      if (cal){ const wrap=document.createElement("span"); wrap.className="cal";
        wrap.appendChild(document.createTextNode("📅 " + cal.label + ": "));
        const g=document.createElement("a"); g.href=cal.google; g.target="_blank";
          g.rel="noopener"; g.textContent="Google";
        const sep=document.createElement("span"); sep.className="sep"; sep.textContent="·";
        const o=document.createElement("a"); o.href=cal.outlook; o.target="_blank";
          o.rel="noopener"; o.textContent="Outlook";
        wrap.appendChild(g); wrap.appendChild(sep); wrap.appendChild(o); c7.appendChild(wrap); }
      tr.appendChild(c7);
    tbody.appendChild(tr);
  }
  document.getElementById("empty").hidden = rows.length>0;
  document.getElementById("count").textContent =
    rows.length + " conference" + (rows.length===1?"":"s");
}

document.getElementById("q").addEventListener("input", e=>{
  query=e.target.value.trim().toLowerCase(); render(); });
document.getElementById("filters").addEventListener("click", e=>{
  if (e.target.tagName!=="BUTTON") return;
  filter=e.target.dataset.f;
  for (const b of e.target.parentNode.children) b.classList.toggle("active", b===e.target);
  render();
});
document.querySelectorAll("th").forEach(th=>th.addEventListener("click", ()=>{
  const k=th.dataset.k;
  sortDir = (sortKey===k) ? -sortDir : 1; sortKey=k;
  document.querySelectorAll("th").forEach(h=>h.classList.remove("sorted","desc"));
  th.classList.add("sorted"); if (sortDir<0) th.classList.add("desc");
  render();
}));
render();
</script>
</body>
</html>
"""
