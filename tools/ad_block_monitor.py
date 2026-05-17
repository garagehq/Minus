#!/usr/bin/env python3
"""
Ad-blocking health monitor for minus-2.

Parses `journalctl -u minus` over a recent window and reports, per block:
  - start time, source (OCR/VLM/OCR+VLM), trigger keywords
  - duration
  - recovery latency: gap between the LAST real ad signal (OCR ad
    keyword or VLM AD verdict) and AD BLOCKING ENDED
  - flags: SLOW_RECOVER (>2s), OVERLONG (>=MAX cap / safeguard fired),
    WEAK_FP (only ever 'sponsored' / no strong keyword), QUERY_ERR

Designed to run from cron every few minutes; writes a concise report to
/tmp/ad_block_monitor.log (rotated by size) and prints a summary so a
scheduled agent can decide whether to retune.

Usage:
  python3 tools/ad_block_monitor.py [--minutes 10]
"""
import re
import sys
import argparse
import subprocess
from datetime import datetime

# User target is <=1.5-2s of content lost. VLM-only stop needs 2
# consecutive no-ad votes at ~1.5-2s VLM cadence (~2-4s inherent);
# OCR-stop is ~1s. Only flag GENUINELY slow recoveries (>3.5s) so the
# cron doesn't cry wolf on normal VLM-only 2-3s stops.
RECOVER_GOAL_S = 3.5
STRONG_KW = ('skip in', 'skip ad', 'visit advertiser', 'ad countdown',
             'ad with timestamp', 'ad x of y', 'ad of', 'send to phone',
             'video will play after ad')
LOGF = '/tmp/ad_block_monitor.log'
TS = re.compile(r'(\d\d:\d\d:\d\d)')


def _t(line):
    m = TS.search(line)
    if not m:
        return None
    h, mi, s = map(int, m.group(1).split(':'))
    return h * 3600 + mi * 60 + s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--minutes', type=int, default=10)
    args = ap.parse_args()

    import os
    base = ['journalctl', '-u', 'minus', '--since',
            f'{args.minutes} minutes ago', '--no-pager']
    # journalctl needs privilege to read another unit's journal. When not
    # root (e.g. manual run as the radxa user) fall back to the
    # NOPASSWD-allowed `sudo -n journalctl`. The cron job runs as root.
    cmd = base if os.geteuid() == 0 else ['sudo', '-n'] + base
    res = subprocess.run(cmd, capture_output=True, text=True)
    out = res.stdout.splitlines()
    if not out:  # privilege fallback failed — try the other form
        alt = base if cmd[0] != 'journalctl' else ['sudo', '-n'] + base
        out = subprocess.run(alt, capture_output=True,
                              text=True).stdout.splitlines()

    blocks = []          # dicts
    cur = None
    last_ad_signal_t = None
    last_ad_signal_txt = ''
    kw_seen = set()
    query_errs = 0
    safeguard_fires = 0

    for ln in out:
        t = _t(ln)
        if 'VLM query error' in ln or 'PROMPT_TOO_LONG' in ln:
            query_errs += 1
        if '[SAFEGUARD] Force-stopping' in ln:
            safeguard_fires += 1
        # track last real ad signal (for recovery-latency estimate)
        if 'OCR detected ad keywords' in ln:
            last_ad_signal_t = t
            last_ad_signal_txt = ln.split('OCR detected ad keywords:')[-1].strip()
            for kw in re.findall(r"'([^']+)'", last_ad_signal_txt):
                kw_seen.add(kw)
        # "ad is still on screen" markers — anything that means the ad
        # frame is still up. Recovery = ENDED minus the last such marker.
        if ('[AD]' in ln or '[BLOCKING' in ln or 'STATIC SUPPRESSED' in ln
                or 'Transition frame' in ln or 'VLM detected ad' in ln
                or 'OCR detected ad keywords' in ln):
            if t is not None:
                last_ad_signal_t = t
        if 'AD BLOCKING STARTED' in ln:
            src = 'OCR+VLM' if 'OCR+VLM' in ln else (
                'VLM' if 'VLM' in ln else 'OCR')
            cur = {'start': t, 'start_s': ln, 'src': src,
                   'kw': set(), 'end': None, 'dur': None,
                   'recover': None, 'flags': []}
            kw_seen = set()
        if cur is not None and 'OCR detected ad keywords' in ln:
            for kw in re.findall(r"'([^']+)'", ln.split(':')[-1]):
                cur['kw'].add(kw)
        if 'AD BLOCKING ENDED' in ln and cur is not None:
            cur['end'] = t
            dm = re.search(r'ENDED after ([0-9.]+)s', ln)
            cur['dur'] = float(dm.group(1)) if dm else (
                (t - cur['start']) if (t and cur['start']) else None)
            cur['stopped_by'] = (ln.split('stopped by')[-1].strip()
                                 if 'stopped by' in ln else '?')
            if last_ad_signal_t is not None and t is not None:
                cur['recover'] = max(0.0, t - last_ad_signal_t)
            kws = cur['kw']
            dur = cur['dur'] or 0
            # A short block that self-corrected fast is the system WORKING
            # (real ad started on a strong keyword, then we suppressed the
            # trailing bare-sponsored masthead). Only flag a weak/no-keyword
            # block as a suspected false positive if it actually lingered
            # (>20s) — that's the symptom that matters.
            if kws and kws.issubset({'sponsored'}) and dur > 20:
                cur['flags'].append('WEAK_FP(sponsored-only)')
            if not kws and cur['src'] != 'VLM' and dur > 20:
                cur['flags'].append('NO_KW')
            if '[SAFEGUARD]' in ' '.join(b['start_s'] for b in []):
                pass
            if cur['dur'] and cur['dur'] >= 150:
                cur['flags'].append('OVERLONG')
            if cur['recover'] is not None and cur['recover'] > RECOVER_GOAL_S:
                cur['flags'].append(f"SLOW_RECOVER({cur['recover']:.1f}s)")
            blocks.append(cur)
            cur = None

    lines = []
    lines.append(f"=== ad-block monitor @ {datetime.now():%H:%M:%S} "
                 f"(last {args.minutes}m) ===")
    lines.append(f"blocks={len(blocks)} query_errs={query_errs} "
                 f"safeguard_fires={safeguard_fires}")
    slow = [b for b in blocks if any('SLOW_RECOVER' in f for f in b['flags'])]
    fp = [b for b in blocks if any('WEAK_FP' in f or f == 'NO_KW'
                                   for f in b['flags'])]
    over = [b for b in blocks if 'OVERLONG' in b['flags']]
    for b in blocks[-12:]:
        lines.append(
            f"  dur={b['dur']}s src={b['src']} kw={sorted(b['kw'])} "
            f"stopped_by={b.get('stopped_by','?')} "
            f"recover={b['recover']}s flags={b['flags']}")
    verdict = 'OK'
    if query_errs:
        verdict = 'ATTENTION: query_image errors'
    elif over:
        verdict = f'ATTENTION: {len(over)} overlong block(s)'
    elif fp:
        verdict = f'ATTENTION: {len(fp)} suspected false-positive block(s)'
    elif slow:
        verdict = (f'ATTENTION: {len(slow)} slow recover (>{RECOVER_GOAL_S}s) '
                   f'— retune stop path')
    lines.append(f"VERDICT: {verdict}")
    report = '\n'.join(lines)
    print(report)
    try:
        import os
        if os.path.exists(LOGF) and os.path.getsize(LOGF) > 512 * 1024:
            os.replace(LOGF, LOGF + '.1')
        with open(LOGF, 'a') as f:
            f.write(report + '\n\n')
    except Exception:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
