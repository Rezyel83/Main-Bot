from flask import Blueprint, abort
from app import dget, runasync

bp = Blueprint("rl_public", __name__)

def _wr(w, l, d=0):
    t = w + l + d
    return round(w/t*100) if t else 0

@bp.route("/public/<gid>/rl")
def public_rl(gid):
    from utils import col, _find
    from flask import current_app
    bot = current_app.bot
    g = dget(f"/guilds/{gid}", isbot=True)
    if not g: abort(404)
    teams = runasync(_find(col("rl_teams"), {"guild_id": int(gid)}, sort=("wins",-1)), bot) or []
    teams = [t for t in teams if isinstance(t, dict)]

    STATUS_COLOR = {"Aktiv":"#22c55e","Sucht Spieler":"#eab308","Inaktiv":"#6b7280"}

    cards = ""
    for t in teams:
        w,l,d = t.get("wins",0),t.get("losses",0),t.get("draws",0)
        wr = _wr(w,l,d)
        wrc = "#22c55e" if wr>=60 else ("#eab308" if wr>=40 else "#f87171")
        status = t.get("status","Aktiv")
        sc = STATUS_COLOR.get(status,"#6b7280")
        members = [m for m in t.get("members",[]) if isinstance(m,dict)]
        matches = t.get("matches",[])
        last5 = "".join(
            f'<span style="color:{"#22c55e" if m.get("result")=="W" else "#f87171" if m.get("result")=="L" else "#eab308"};font-weight:700">{m.get("result","?")}</span>'
            for m in reversed(matches[-5:])
        )
        cards += f'''<div style="background:#13121f;border:1px solid #1e1b2e;border-radius:14px;padding:1.25rem">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:.75rem">
    <div>
      <div style="font-size:1.05rem;font-weight:700">🚗 {t.get("name","")}</div>
      <div style="font-size:.72rem;color:#6b7280;margin-top:.2rem">{t.get("format","?")} &bull; <span style="color:{sc}">{status}</span></div>
    </div>
    <div style="width:50px;height:50px;border-radius:50%;background:conic-gradient({wrc} {wr}%,#1c1a2e {wr}%);display:flex;align-items:center;justify-content:center;font-weight:800;font-size:.82rem;color:{wrc}">{wr}%</div>
  </div>
  <div style="display:flex;gap:.5rem;margin-bottom:.75rem">
    <div style="flex:1;background:#0d0c17;border:1px solid #1c1a2e;border-radius:8px;padding:.5rem;text-align:center">
      <div style="font-size:1.1rem;font-weight:700;color:#22c55e">{w}</div><div style="font-size:.65rem;color:#6b7280">W</div>
    </div>
    <div style="flex:1;background:#0d0c17;border:1px solid #1c1a2e;border-radius:8px;padding:.5rem;text-align:center">
      <div style="font-size:1.1rem;font-weight:700;color:#f87171">{l}</div><div style="font-size:.65rem;color:#6b7280">L</div>
    </div>
    <div style="flex:1;background:#0d0c17;border:1px solid #1c1a2e;border-radius:8px;padding:.5rem;text-align:center">
      <div style="font-size:1.1rem;font-weight:700;color:#eab308">{d}</div><div style="font-size:.65rem;color:#6b7280">D</div>
    </div>
  </div>
  <div style="font-size:.78rem;color:#6b7280">👥 {len(members)} Spieler &bull; Letzte 5: {last5 or "—"}</div>
</div>'''

    return f'''<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RL Teams — {g.get("name","")}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:system-ui,sans-serif;background:#07070d;color:#e5e7eb;min-height:100vh}}
</style>
</head>
<body>
<div style="background:#0a0a14;border-bottom:1px solid #211e35;padding:.9rem 1.5rem;display:flex;justify-content:space-between;align-items:center">
  <div style="font-size:1.1rem;font-weight:800;background:linear-gradient(90deg,#a78bfa,#8b5cf6);-webkit-background-clip:text;background-clip:text;color:transparent">🚗 RL Teams — {g.get("name","")}</div>
  <div style="font-size:.78rem;color:#4b5563">{len(teams)} Teams</div>
</div>
<div style="padding:1.5rem;max-width:1100px;margin:0 auto">
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:1rem">
    {cards or '<div style="color:#4b5563;text-align:center;padding:3rem;grid-column:1/-1">Keine Teams</div>'}
  </div>
</div>
<div style="text-align:center;padding:1rem;color:#211e35;font-size:.75rem;margin-top:2rem">RLD Dashboard &mdash; Made by Rezyel</div>
</body>
</html>'''