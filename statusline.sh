#!/usr/bin/env bash
# Claude Code status line, configurable. Default output:
#   "<model> | <cwd> | <NN>% ctx | 5h N% (HH:MM) | wk N% (Day HH:MM) | $M mo"
#
# Reads the status-line JSON payload on stdin and prints one line. Which items
# show, their order and their format come from config.txt (key=value lines,
# written by config_server.py); every key has a built-in default below, and
# tests/test_statusline.py checks those defaults match config_server.DEFAULTS.
#
# No jq -- it is not installed on this machine. Written 2026-09-22.
# 2026-10-08: usage stats; rewritten with bash builtins only -- every external
# process costs ~120 ms under Git Bash here (a grep/sed version took 8-11 s per
# refresh). The steady-state path forks nothing; only the 5-minutely ccusage
# refresh spawns a process. Month total = cost since the first weekly reset of
# the month; week total = cost since the current weekly reset.
# 2026-10-08: config-driven items/formats + preview mode for the config page.
#
# Env: STATUSLINE_CONFIG  config file to use instead of <state>/config.txt
#      STATUSLINE_NOW     epoch to use as "now" for pace and reset text (preview sim)
#      STATUSLINE_PREVIEW=1  print every item as "id<TAB>colour<TAB>text" lines
#                            (all items, shown or not) instead of the line;
#                            colour "hidden" = auto-hidden below its threshold
# ~\.claude\settings.json points here; Setup_Statusline.bat wires it up.

IFS= read -r -d '' input
# STATUSLINE_NOW (preview only) simulates the clock for pace and reset text;
# the totals-cache freshness check always uses the real clock (real_now)
real_now=$EPOCHSECONDS
now=${STATUSLINE_NOW:-$real_now}

local_app=${LOCALAPPDATA:-$USERPROFILE\\AppData\\Local}
local_app=${local_app//\\//}
[[ $local_app =~ ^([A-Za-z]):(.*) ]] && local_app="/${BASH_REMATCH[1],,}${BASH_REMATCH[2]}"
dir="$local_app/Tools/claude_statusline"
preview=${STATUSLINE_PREVIEW:-}

# keep the latest payload so the config page can preview with real values
[ -z "$preview" ] && [ -d "$dir" ] && [ -n "$input" ] && printf '%s' "$input" > "$dir/last_payload.json"

# ---- config: built-in defaults, then config.txt on top -----------------------
declare -A C=(
  [order]=model,cwd,ctx,q5,qwk,mo,wkcost,sess
  [show]=model,cwd,ctx,q5,qwk,mo
  [model.style]=display [model.effort]=0 [model.colour]=default
  [cwd.path]=last2 [cwd.max]=0 [cwd.colour]=default
  [ctx.label]=ctx [ctx.measure]=used [ctx.display]=bar [ctx.colour]=threshold [ctx.warn]=80 [ctx.pctat]=0
  [q5.label]=5h [q5.measure]=used [q5.display]=both [q5.colour]=threshold [q5.warn]=80 [q5.pctat]=0 [q5.reset]=clock [q5.resetat]=60
  [qwk.label]=wk [qwk.measure]=used [qwk.display]=pct [qwk.colour]=threshold [qwk.warn]=80 [qwk.pctat]=0 [qwk.reset]=clock [qwk.resetat]=60
  [qwk.hide]=fixed [qwk.hidefixed]=80 [qwk.hidepace]=14.29 [qwk.pacedays]=all [qwk.paceunit]=continuous
  [mo.dec]=0 [mo.sep]=1 [mo.label]=mo [mo.colour]=dim
  [wkcost.dec]=0 [wkcost.sep]=1 [wkcost.label]=wk [wkcost.colour]=default
  [sess.dec]=2 [sess.sep]=1 [sess.label]=sess [sess.colour]=default
)
cfg_file=${STATUSLINE_CONFIG:-$dir/config.txt}
if [ -f "$cfg_file" ]; then
  while IFS='=' read -r k v || [ -n "$k" ]; do
    v=${v%$'\r'}
    [[ -n $k && $k != '#'* ]] && C[$k]=$v
  done < "$cfg_file"
fi

# ---- payload helpers -----------------------------------------------------------
# first value of "key": in $2 (default: the whole payload) -> $REPLY
num() {
  REPLY=
  [[ ${2-$input} =~ \"$1\"[[:space:]]*:[[:space:]]*([0-9.]+) ]] && REPLY=${BASH_REMATCH[1]}
}
str() {
  REPLY=
  [[ ${2-$input} =~ \"$1\"[[:space:]]*:[[:space:]]*\"((\\.|[^\"\\])*)\" ]] && REPLY=${BASH_REMATCH[1]}
}
block() {  # flat {...} object under "key" -> $REPLY
  REPLY=
  [[ $input =~ \"$1\"[[:space:]]*:[[:space:]]*(\{[^\}]*\}) ]] && REPLY=${BASH_REMATCH[1]}
}

declare -A T K   # item text and colour (dim|accent|warn|"")

colour() {  # $1 = item id, $2 = used % (for threshold) -> K[$1]
  case ${C[$1.colour]} in
    dim) K[$1]=dim ;;
    accent) K[$1]=accent ;;
    threshold) if [ -n "$2" ] && (( ${2%.*} >= ${C[$1.warn]:-80} )); then K[$1]=warn; else K[$1]=; fi ;;
    *) K[$1]= ;;
  esac
}
mkbar() {  # $1 = percent -> 8-cell bar in $REPLY
  local n=$(( ($1 * 8 + 50) / 100 )) i
  REPLY=
  for (( i = 0; i < 8; i++ )); do
    if (( i < n )); then REPLY+='█'; else REPLY+='░'; fi
  done
}
pct_item() {  # $1 id, $2 used % (int), $3 "1" = label after the value, $4 reset text
  local id=$1 used=$2 v word= body lab=${C[$1.label]}
  if [ "${C[$id.measure]}" = used ]; then v=$used; else v=$(( 100 - used )); fi
  if [ -n "$3" ]; then
    [ "${C[$id.measure]}" = used ] && word=' used'
  else
    [ "${C[$id.measure]}" = left ] && word=' left'
  fi
  # the number shows only from <id>.pctat used %: "both" falls back to the bar,
  # and "pct" has nothing left to show, so the item is auto-hidden
  local num="$v%$word" hide=
  (( used < ${C[$id.pctat]:-0} )) && num=
  case ${C[$id.display]} in
    bar) mkbar "$v"; body=$REPLY ;;
    both) mkbar "$v"; body="$REPLY${num:+ $num}" ;;
    *) body=${num:-$v%$word}; [ -z "$num" ] && hide=1 ;;
  esac
  if [ -n "$3" ]; then T[$id]="$body${lab:+ $lab}"; else T[$id]="${lab:+$lab }$body"; fi
  T[$id]+=$4
  colour "$id" "$used"
  [ -n "$hide" ] && K[$id]=hidden
}
money() {  # $1 id, $2 usd
  local id=$1 t int frac lab=${C[$1.label]}
  if [ "${C[$id.dec]}" = 2 ]; then printf -v t '%.2f' "$2"; else printf -v t '%.0f' "$2"; fi
  if [ "${C[$id.sep]}" = 1 ]; then
    int=${t%%.*}; frac=${t#"$int"}
    while [[ $int =~ ^([0-9]+)([0-9]{3})(.*)$ ]]; do
      int="${BASH_REMATCH[1]},${BASH_REMATCH[2]}${BASH_REMATCH[3]}"
    done
    t=$int$frac
  fi
  T[$id]="\$$t${lab:+ $lab}"
  colour "$id"
}
reset_text() {  # $1 id, $2 resets_at epoch, $3 strftime format, $4 used % -> $REPLY
  REPLY=
  [ -z "$2" ] && return
  (( ${4:-0} < ${C[$1.resetat]:-0} )) && return  # only shown from <id>.resetat used %
  case ${C[$1.reset]} in
    clock) printf -v REPLY " (%($3)T)" "$2" ;;
    countdown)
      local s=$(( $2 - now )) d h m
      (( s < 0 )) && s=0
      d=$(( s / 86400 )); h=$(( s % 86400 / 3600 )); m=$(( s % 3600 / 60 ))
      if (( d > 0 )); then REPLY=" (in ${d}d ${h}h)"
      elif (( h > 0 )); then REPLY=" (in ${h}h ${m}m)"
      else REPLY=" (in ${m}m)"; fi ;;
  esac
}

# ---- items ---------------------------------------------------------------------
# model
block model; mblk=$REPLY
str display_name "$mblk"; disp=$REPLY
str id "$mblk"; mid=$REPLY
case ${C[model.style]} in
  short) T[model]=${disp%% *} ;;
  id) T[model]=$mid ;;
  *) T[model]=$disp ;;
esac
if [ "${C[model.effort]}" = 1 ]; then
  block effort; str level "$REPLY"
  [ -n "$REPLY" ] && T[model]+=" · $REPLY"
fi
[ -z "${T[model]}" ] && T[model]='?'
colour model

# cwd -- a Windows path, so backslashes arrive JSON-escaped
str current_dir; cwd=${REPLY//\\\\/\\}
case ${C[cwd.path]} in
  full) p=$cwd ;;
  last2) tmp=${cwd%\\*}; p="${tmp##*\\}\\${cwd##*\\}" ;;
  name) p=${cwd##*\\}; [ -z "$p" ] && p=$cwd ;;
  *)
    p=$cwd; home=${USERPROFILE:-$HOME}
    if [ -n "$home" ] && [ "${cwd#"$home"}" != "$cwd" ]; then p="~${cwd#"$home"}"; fi ;;
esac
max=${C[cwd.max]:-0}
(( max > 1 && ${#p} > max )) && p="…${p: -$(( max - 1 ))}"
T[cwd]=${p:-?}
colour cwd

# context window -- remaining_percentage is absent before the first response
num remaining_percentage
if [ -n "$REPLY" ]; then
  printf -v rem '%.0f' "$REPLY"
  pct_item ctx $(( 100 - rem )) 1
else
  T[ctx]="--${C[ctx.label]:+ ${C[ctx.label]}}"; K[ctx]=
fi

# rate_limits.{five_hour,seven_day} -- the same numbers /usage shows; only on
# subscription plans, and only after the first API response.
# Verified Ultra has no 5-hour window, yet the payload still carries one (at 0%); the
# plan is only in ~/.claude.json. Reading that (~110 KB) costs ~120 ms here,
# so the plan is cached in plan.txt ("<epoch> <plan>") for 5 minutes.
p_at=0 plan=
[ -f "$dir/plan.txt" ] && read -r p_at plan < "$dir/plan.txt"
if (( real_now - ${p_at:-0} > 300 )); then
  cj=${CLAUDE_CONFIG_DIR:-${USERPROFILE:-$HOME}}/.claude.json; cj=${cj//\\//}
  [[ $cj =~ ^([A-Za-z]):(.*) ]] && cj="/${BASH_REMATCH[1],,}${BASH_REMATCH[2]}"
  [ -f "$cj" ] && IFS= read -r -d '' cj < "$cj"
  str planDisplayName "$cj"; plan=$REPLY
  [ -d "$dir" ] && printf '%s %s\n' "$real_now" "$plan" > "$dir/plan.txt"
fi
block five_hour
if [ -n "$REPLY" ]; then
  b=$REPLY; num used_percentage "$b"; printf -v u '%.0f' "${REPLY:-0}"
  num resets_at "$b"; reset_text q5 "${REPLY%.*}" '%H:%M' "$u"
  pct_item q5 "$u" '' "$REPLY"
  # unverified Ultra accounts still have a 5-hour window, so hide only at 0%
  [ "$plan" = Ultra ] && (( u == 0 )) && K[q5]=hidden
fi
thr= el= el_all=
block seven_day
if [ -n "$REPLY" ]; then
  b=$REPLY; num used_percentage "$b"; printf -v u '%.0f' "${REPLY:-0}"
  num resets_at "$b"; wk_reset=${REPLY%.*}; reset_text qwk "$wk_reset" '%a %H:%M' "$u"
  pct_item qwk "$u" '' "$REPLY"
  # Auto-hide while used % is below a threshold: a fixed %, or a pace of
  # qwk.hidepace % per counted day since the reset (default 100/7, an even
  # week). Counted days: every day, or Mon-Fri only (qwk.pacedays); each
  # accrues continuously, or only once it is over (qwk.paceunit=whole).
  # Compared in hundredths of a percent so the pace keeps its fraction.
  case ${C[qwk.hide]} in
    fixed) thr=$(( 10#${C[qwk.hidefixed]:-0} * 100 )) ;;
    pace)
      r=${C[qwk.hidepace]:-0}; ri=${r%%.*} rf=
      [[ $r == *.* ]] && rf=${r#*.}
      rf="${rf}00"
      # el = counted seconds the pace uses; el_all = the same days counted hour by hour
      el=0 el_all=0 ws=$(( wk_reset - 604800 ))
      for (( d = 0; d < 7; d++ )); do
        ds=$(( ws + d * 86400 ))
        printf -v wd '%(%u)T' $(( ds + 43200 ))  # 1 = Mon ... 7 = Sun; midday dodges DST
        [ "${C[qwk.pacedays]}" = weekdays ] && (( wd > 5 )) && continue
        s=$(( now - ds )); (( s > 86400 )) && s=86400
        (( s < 0 )) && s=0
        el_all=$(( el_all + s ))
        [ "${C[qwk.paceunit]}" = whole ] && (( s < 86400 )) && s=0
        el=$(( el + s ))
      done
      thr=$(( (10#${ri:-0} * 100 + 10#${rf:0:2}) * el / 86400 )) ;;
    *) thr=0 ;;
  esac
  # on Ultra the weekly quota is the only quota, so it always shows (JC 2026-11-06)
  (( u * 100 < thr )) && [ "$plan" != Ultra ] && K[qwk]=hidden
fi

# session cost -- from the payload, an API-equivalent estimate
block cost; num total_cost_usd "$REPLY"
[ -n "$REPLY" ] && money sess "$REPLY"

# ---- week / month totals (cached ccusage) --------------------------------------
# Week starts 7 days before seven_day.resets_at; the month starts at the latest
# weekly reset that was the first of its calendar month (day-of-month <= 7). The
# reset is at local midnight, so whole days match ccusage's local-date grouping.
# Arithmetic is done at reset + 12 h so a DST shift cannot move a day.
wk_from= mo_from=
if [ -n "$wk_reset" ]; then
  t=$(( wk_reset - 604800 + 43200 ))
  printf -v wk_from '%(%Y%m%d)T' "$t"
  printf -v dom '%(%d)T' "$t"
  while (( 10#$dom > 7 )); do
    t=$(( t - 604800 ))
    printf -v dom '%(%d)T' "$t"
  done
  printf -v mo_from '%(%Y%m%d)T' "$t"
fi

# A detached `ccusage` run (~7 s) refreshes the cache at most every 5 minutes;
# this line only reads it. Cache: "<mo_from> <wk_from> <epoch> <week> <month>".
cache="$dir/totals.txt"
lock="$dir/refresh.lock"
c_mo= c_wk= c_at=0 c_week= c_month=
[ -f "$cache" ] && read -r c_mo c_wk c_at c_week c_month < "$cache"
# no rate_limits yet (start of a session): keep using the cached windows
[ -z "$wk_from" ] && wk_from=$c_wk mo_from=$c_mo

if [ -n "$wk_from" ] && [[ -n $preview || ,${C[show]}, == *,mo,* || ,${C[show]}, == *,wkcost,* ]] \
  && { [ "$c_mo $c_wk" != "$mo_from $wk_from" ] || (( real_now - ${c_at:-0} > 300 )); }; then
  lock_at=0
  [ -f "$lock" ] && read -r lock_at < "$lock"
  (( real_now - ${lock_at:-0} > 600 )) && rm -f "$lock" 2>/dev/null  # stale lock
  [ -d "$dir" ] || mkdir -p "$dir"
  if ( set -C; printf '%s\n' "$real_now" > "$lock" ) 2>/dev/null; then
    (
      wk_iso="${wk_from:0:4}-${wk_from:4:2}-${wk_from:6:2}"
      v=$(npx -y ccusage@20.0.26 claude daily --json --since "$mo_from" 2>/dev/null \
        | node -e '
            let s = ""; process.stdin.on("data", d => s += d).on("end", () => {
              let w = 0, m = 0;
              for (const d of JSON.parse(s).daily) {
                m += d.totalCost; if (d.date >= process.argv[1]) w += d.totalCost;
              }
              console.log(w.toFixed(2), m.toFixed(2));
            });' "$wk_iso")
      [ -n "$v" ] && printf '%s %s %s %s\n' "$mo_from" "$wk_from" "$EPOCHSECONDS" "$v" > "$cache.tmp" \
        && mv -f "$cache.tmp" "$cache"
      rm -f "$lock"
    ) </dev/null >/dev/null 2>&1 &
  fi
fi
# cached totals count only while they belong to the current windows
if [ -n "$c_month" ] && [ "$c_mo $c_wk" = "$mo_from $wk_from" ]; then
  money mo "$c_month"
  money wkcost "$c_week"
fi

# ---- output --------------------------------------------------------------------
IFS=, read -r -a ids <<< "${C[order]}"
if [ -n "$preview" ]; then
  for id in "${ids[@]}"; do printf '%s\t%s\t%s\n' "$id" "${K[$id]}" "${T[$id]}"; done
  # the weekly auto-hide threshold in % used, so the page can show it
  [ -n "$thr" ] && (( thr > 0 )) && printf 'qwk.thr\t\t%d.%02d\n' $(( thr / 100 )) $(( thr % 100 ))
  # pace only: "<counted days elapsed> <counted days credited>", in hundredths of a day
  [ "${C[qwk.hide]}" = pace ] && [ -n "$el_all" ] && printf 'qwk.days\t\t%d %d\n' \
    $(( el_all * 100 / 86400 )) $(( el * 100 / 86400 ))
  exit 0
fi
declare -A ANSI=([dim]=$'\e[2m' [accent]=$'\e[36m' [warn]=$'\e[33m')
line=
for id in "${ids[@]}"; do
  [[ ,${C[show]}, == *,$id,* && -n ${T[$id]} && ${K[$id]} != hidden ]] || continue
  seg=${T[$id]}
  [ -n "${K[$id]}" ] && seg="${ANSI[${K[$id]}]}$seg"$'\e[0m'
  line+="${line:+ | }$seg"
done
printf '%s' "$line"
