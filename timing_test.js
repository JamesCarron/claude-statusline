// Times a Claude Code status-line command the way the harness runs it (piped
// stdio), to check that a detached background refresh does not hold the line.
// Written 2026-10-08 for the terminal usage-stats status line; verified by
// running it with and without a fresh ccusage cache.
// Usage: node timing_test.js   (times statusline.sh beside this file)
const { spawn } = require('child_process');
const path = require('path');
const t0 = Date.now();
const p = spawn('C:\\Program Files\\Git\\bin\\bash.exe',
  [path.join(__dirname, 'statusline.sh')], { stdio: 'pipe' });
let out = '';
p.stdout.on('data', d => out += d);
p.on('exit', () => console.log('exit  ', Date.now() - t0, 'ms'));
p.on('close', () => console.log('close ', Date.now() - t0, 'ms ->', out));
p.stdin.end(JSON.stringify({
  model: { display_name: 'Opus 5.5' },
  workspace: { current_dir: process.env.USERPROFILE + '\\Documents' },
  cost: { total_cost_usd: 0.6 },
  context_window: { used_percentage: 9, remaining_percentage: 91 },
  rate_limits: { five_hour: { used_percentage: 5, resets_at: 1791450000 },
                 seven_day: { used_percentage: 54, resets_at: 1791669600 } },
}));
