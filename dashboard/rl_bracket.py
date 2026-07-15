from flask import Blueprint, session, redirect, url_for, request, current_app
from functools import wraps
from app import dget, bguilds, uguilds, runasync

bp = Blueprint("rl_bracket", __name__)

BRACKET_CSS = """
*{margin:0;padding:0;box-sizing:border-box}
:root{--p:#8b5cf6;--pd:#7c3aed}
body{font-family:system-ui,sans-serif;background:#0a0a12;color:#e5e7eb;min-height:100vh}
.nav{background:#0d0d14;border-bottom:1px solid #1e1b2e;padding:.875rem 1.5rem;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:100}
.logo{font-size:1.1rem;font-weight:700;color:var(--p)}
.btn{padding:.45rem .9rem;border-radius:7px;font-size:.82rem;font-weight:500;cursor:pointer;border:none;transition:all .15s}
.bp{background:var(--p);color:#fff}.bp:hover{background:var(--pd)}
.bs{background:#1e1b2e;color:#d1d5db}.bs:hover{background:#2a2740}
.wrap{padding:1.5rem;max-width:1200px;margin:0 auto}
.bracket{display:flex;gap:2rem;overflow-x:auto;padding-bottom:1rem}
.round{display:flex;flex-direction:column;justify-content:space-around;min-width:180px}
.round-title{font-size:.75rem;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:.06em;margin-bottom:1rem;text-align:center}
.match{background:#111120;border:1px solid #1e1b2e;border-radius:8px;margin:auto;width:100%;margin-bottom:1rem;overflow:hidden}
.team-slot{padding:.6rem .875rem;border-bottom:1px solid #1e1b2e;display:flex;justify-content:space-between;align-items:center;cursor:pointer;transition:all .15s}
.team-slot:last-child{border-bottom:none}
.team-slot:hover{background:rgba(139,92,246,.08)}
.team-slot.winner{background:rgba(139,92,246,.15);color:var(--p);font-weight:600}
.team-slot input{background:transparent;border:none;color:inherit;font-size:.85rem;width:100%;outline:none}
.team-slot input::placeholder{color:#374151}
.score-inp{width:35px;background:#1a1a2e;border:1px solid #2d2b4e;border-radius:4px;color:#fff;font-size:.8rem;padding:.2rem .4rem;text-align:center}
.controls{background:#111120;border:1px solid #1e1b2e;border-radius:10px;padding:1rem;margin-bottom:1.5rem;display:flex;gap:.75rem;align-items:center;flex-wrap:wrap}
.sel{padding:.5rem .75rem;background:#1a1a2e;border:1px solid #2d2b4e;border-radius:7px;color:#fff;font-size:.85rem}
.sel:focus{outline:none;border-color:var(--p)}
"""

def _lreq(f):
    @wraps(f)
    def dec(*a, **kw):
        if "user_id" not in session: return redirect(url_for("auth.login"))
        return f(*a, **kw)
    return dec

def _build_bracket_html(size):
    rounds = []
    n = size
    round_names = {size: "Vorrunde", size//2: "Viertelfinale", 4: "Halbfinale", 2: "Finale"}
    while n >= 2:
        name = round_names.get(n, f"Runde {n}")
        matches = n // 2
        match_html = ""
        for i in range(matches):
            match_html += f'''
<div class="match">
  <div class="team-slot">
    <input placeholder="Team..." oninput="saveState()">
    <input class="score-inp" type="number" min="0" placeholder="0" oninput="saveState()">
  </div>
  <div class="team-slot">
    <input placeholder="Team..." oninput="saveState()">
    <input class="score-inp" type="number" min="0" placeholder="0" oninput="saveState()">
  </div>
</div>'''
        rounds.append((name, match_html))
        n //= 2

    # Winner
    rounds.append(("🏆 Sieger", '<div class="match"><div class="team-slot" style="background:rgba(234,179,8,.1);color:#eab308"><input placeholder="Sieger" oninput="saveState()"></div></div>'))

    cols = ""
    for name, content in rounds:
        cols += f'<div class="round"><div class="round-title">{name}</div>{content}</div>'
    return cols

@bp.route("/g/<gid>/rl-bracket")
@_lreq
def bracket(gid):
    size = int(request.args.get("size", 8))
    if size not in (8, 16, 32): size = 8
    guild = dget(f"/guilds/{gid}", isbot=True) or {"name": gid}
    gname = guild.get("name", gid)

    bracket_html = _build_bracket_html(size)

    size_opts = "".join(f'<option value="{s}" {"selected" if s==size else ""}>{s} Teams</option>' for s in (8,16,32))

    return f'''<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Turnier Bracket — {gname}</title>
<style>{BRACKET_CSS}</style>
</head>
<body>
<nav class="nav">
  <div class="logo">🏆 Turnier Bracket — {gname}</div>
  <div style="display:flex;gap:.5rem;align-items:center">
    <a href="javascript:window.close()" class="btn bs">✕ Schließen</a>
  </div>
</nav>
<div class="wrap">
  <div class="controls">
    <label style="color:#6b7280;font-size:.85rem">Bracket Größe:</label>
    <select class="sel" onchange="location.href='/g/{gid}/rl-bracket?size='+this.value">{size_opts}</select>
    <button class="btn bp" onclick="clearBracket()">🗑️ Zurücksetzen</button>
    <button class="btn bs" onclick="exportBracket()">📋 Kopieren</button>
    <span style="color:#6b7280;font-size:.78rem;margin-left:.5rem">Wird automatisch gespeichert</span>
  </div>
  <div class="bracket" id="bracket">{bracket_html}</div>
</div>
<script>
const KEY = 'rl_bracket_{gid}_{size}';

function saveState() {{
  const inputs = document.querySelectorAll('#bracket input');
  const vals = [...inputs].map(i => i.value);
  localStorage.setItem(KEY, JSON.stringify(vals));
}}

function loadState() {{
  const saved = localStorage.getItem(KEY);
  if (!saved) return;
  const vals = JSON.parse(saved);
  const inputs = document.querySelectorAll('#bracket input');
  inputs.forEach((inp, i) => {{ if (vals[i] !== undefined) inp.value = vals[i]; }});
}}

function clearBracket() {{
  if (!confirm('Bracket zurücksetzen?')) return;
  localStorage.removeItem(KEY);
  document.querySelectorAll('#bracket input').forEach(i => i.value = '');
}}

function exportBracket() {{
  const inputs = document.querySelectorAll('#bracket input');
  let txt = 'Turnier Bracket\\n\\n';
  inputs.forEach(i => {{ if (i.value) txt += i.value + '\\n'; }});
  navigator.clipboard.writeText(txt).then(() => alert('In Zwischenablage kopiert!'));
}}

loadState();
</script>
</body>
</html>'''