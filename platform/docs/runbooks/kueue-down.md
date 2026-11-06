# Runbook: KueueDown (page)

**Impact:** no new GPU jobs are admitted. Running jobs keep running.

1. `kubectl -n kueue-system get pods` — is the controller running, crash-looping or pending?
2. `kubectl -n kueue-system logs deploy/kueue-controller-manager --tail=200`
   - Config parse error after a change to `controller-config.yaml`: roll back that change.
   - Webhook certificate errors: restart the deployment; check internal cert management.
3. If pending: system node group capacity (`kubectl get nodes -l platform.gpu/role=system`).
4. Once healthy, check `kubectl get clusterqueues` shows pending workloads draining.
5. Post in the support channel when admission resumes.

Kueue's admission webhook also blocks job creation while the controller is
down, so researchers will see submit errors. That is expected.
