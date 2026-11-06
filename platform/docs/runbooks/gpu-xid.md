# Runbook: GPU XID error / AcceleratedHardwareNotReady (ticket)

Phase 1 handles these by hand; the Phase 2 remediation controller automates
steps 1-3 with rate limits.

1. **Quarantine:** `kubectl cordon <node>` so nothing new lands on it.
   Leave running jobs unless the XID is fatal (e.g. 48, 79, 94, 95): those jobs are already broken.
2. **Evidence bundle** (attach all to the AWS case):
   - `nvidia-bug-report.sh` output from the node (SSM session)
   - XID lines: `journalctl -k | grep -i xid`
   - `dcgmi diag -r 3`
   - instance ID, reservation / Capacity Block ID, AZ, timeline, affected jobs (`kubectl get pods -A -o wide --field-selector spec.nodeName=<node>`)
3. **Open an AWS support case** within 1 hour of quarantine (target in Goals).
4. **Tell affected researchers** in the support channel; jobs resume from their checkpoint.
5. **Record** the fault (instance family, reservation, XID, outcome) in the fault log for fleet learning.
6. Return the node only after a clean `dcgmi diag -r 3`, then `kubectl uncordon <node>`.

Unknown XID codes don't trip AcceleratedHardwareReady; the GpuXidError alert
catches them from DCGM.
