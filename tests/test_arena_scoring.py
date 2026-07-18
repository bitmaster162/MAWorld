import sys, os, random
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT,"libs"))
from maworld_core.arena_scoring import (leaderboard, required_episodes, bootstrap_ci, shrunk_mean,
    paired_bt, MIN_EPISODES_PROVISIONAL, MIN_EPISODES_PUBLISH, InsufficientEpisodes)
P=F=0
def ok(n,c,d=""):
    global P,F; b=bool(c); P+=b; F+=(not b); print(("  PASS " if b else "  FAIL ")+n+("" if b else f" <- {d}"))
R=random.Random(11)

# ---- H: power analysis matches the audit's quoted numbers ----
ok("power: ~32 episodes for a large 0.5-sigma effect", required_episodes(0.5)==32, str(required_episodes(0.5)))
ok("power: ~87 episodes for a medium 0.3-sigma effect", 85 <= required_episodes(0.3) <= 90, str(required_episodes(0.3)))
ok("power: ~196 episodes for a small 0.2-sigma effect", 193 <= required_episodes(0.2) <= 200, str(required_episodes(0.2)))

# ---- F: THE refutation — n=1 lucky outlier must not outrank a steady long track ----
lucky=[100.0]; steady=[1.0+R.gauss(0,0.05) for _ in range(100)]
lb=leaderboard({"A_lucky_n1":lucky,"B_steady_n100":steady})
rows={r["agent_id"]:r for r in lb["rows"]}
ok("F: raw mean would crown the lucky agent (the bug we shipped)", rows["A_lucky_n1"]["mean"] > rows["B_steady_n100"]["mean"])
ok("F: but n=1 is UNRANKED (below min episodes)", rows["A_lucky_n1"]["status"]=="UNRANKED_INSUFFICIENT_N")
ok("F: the steady n=100 agent IS ranked", rows["B_steady_n100"]["status"]=="RANKED")
ok("F: shrinkage pulls the lucky outlier toward the grand mean",
   rows["A_lucky_n1"]["shrunk_mean"] < rows["A_lucky_n1"]["mean"])
ok("F: no winner while only one agent clears the bar", lb["winner"] is None and not lb["publishable"], lb["reason"])

# ---- H: even two long tracks need separation, not just a higher mean ----
x=[1.0+R.gauss(0,3) for _ in range(120)]; y=[1.05+R.gauss(0,3) for _ in range(120)]
lb2=leaderboard({"X":x,"Y":y})
ok("H: two noisy agents with overlapping CIs -> NO winner declared",
   lb2["winner"] is None and "CI" in lb2["reason"] or "overlap" in lb2["reason"], lb2["reason"])
ok("H: both are ranked though (sufficient n)", all(r["status"]=="RANKED" for r in lb2["rows"]))
strong=[10.0+R.gauss(0,0.5) for _ in range(120)]; weak=[1.0+R.gauss(0,0.5) for _ in range(120)]
lb3=leaderboard({"STRONG":strong,"WEAK":weak})
ok("H: a real, separated effect over a long track DOES yield a winner", lb3["winner"]=="STRONG", lb3["reason"])
ok("H: winner requires min_publish episodes",
   leaderboard({"S":strong[:50],"W":weak[:50]})["winner"] is None)

# ---- CI / shrinkage / paired BT mechanics ----
lo,hi = bootstrap_ci([1.0]*50); ok("CI on a constant series is degenerate", lo==hi==1.0)
lo,hi = bootstrap_ci(strong); ok("CI brackets the mean", lo < sum(strong)/len(strong) < hi)
ok("shrinkage with big n barely moves", abs(shrunk_mean(steady, 0.0) - sum(steady)/len(steady)) < 0.2)
ok("shrinkage with n=1 moves a lot", abs(shrunk_mean([100.0], 0.0) - 100.0) > 80)
bt = paired_bt({"P":[1,1,1,1],"Q":[0,0,0,0]})
ok("paired BT compares aligned episodes, not unrelated averages", bt["P"]==1.0 and bt["Q"]==0.0, str(bt))
bt2 = paired_bt({"P":[1,0,1,0],"Q":[0,1,0,1]})
ok("paired BT on an even split is 0.5/0.5", bt2["P"]==0.5 and bt2["Q"]==0.5, str(bt2))
try: leaderboard({}); ok("empty rejected", False, "no raise")
except InsufficientEpisodes: ok("an empty arena cannot be ranked", True)
ok("defaults are the audit's: rank>=30, winner>=100",
   MIN_EPISODES_PROVISIONAL==30 and MIN_EPISODES_PUBLISH==100)

print(f"\nTALLY arena-scoring: PASS={P} FAIL={F}"); sys.exit(1 if F else 0)
