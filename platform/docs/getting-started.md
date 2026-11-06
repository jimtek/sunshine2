# Getting started: your first GPU job

Goal: a new researcher runs a first job in under a day. Stuck? Ask in the
support channel; every question improves this guide.

## 1. Install the tool

```bash
pip install -e platform/tools/gpu       # gives you the `gpu` command
aws eks update-kubeconfig --region us-east-1 --name gpu-pilot
export GPU_TEAM=team-alpha              # your team
```

## 2. Write a job spec

```yaml
name: my-first-job            # lowercase, digits, '-'
team: team-alpha
project: llm-sft              # what this belongs to (for cost reporting)
experiment: exp-001           # unique per run
image: nvcr.io/nvidia/pytorch:24.10-py3   # pinned tag, approved registry
command: python train.py
gpus: 8                       # 1-8 on one node, or a multiple of 8 for multi-node
max_runtime: 6h
checkpoint_dir: s3://team-alpha-ml/checkpoints/exp-001   # required over 1h
```

Examples: `platform/tools/gpu/examples/`.

## 3. Check it, then submit

```bash
gpu preflight job.yaml        # catches quota, image, data and timing problems in seconds
gpu submit job.yaml
gpu status                    # queued / starting / running / succeeded / failed
gpu logs my-first-job -f      # rank 0; --rank N for others
gpu cancel my-first-job
```

## What the platform sets for you

- `NNODES`, `NPROC_PER_NODE`, `NODE_RANK`, `MASTER_ADDR`, `MASTER_PORT` for
  `torchrun`; `CHECKPOINT_DIR` and `EXPERIMENT_ID`.
- Labels for cost reporting. Jobs without them are rejected.
- A deadline of `max_runtime`. Jobs are stopped after it.

## Rules worth knowing

- **Whole nodes:** multi-node jobs use all 8 GPUs per node.
- **1 GPU** goes to the dev pool if it runs 8 hours or less; otherwise, and for **2-7 GPUs**, the job shares one 8-GPU node.
- **Quota:** your team has guaranteed GPUs and can borrow unused ones. Borrowed
  GPUs can be reclaimed by their owner, so checkpoint.
- **Preemptible** priority runs on spare capacity cheaply, but only for jobs that
  have passed a resume test (`resume_tested: true`).
- **Capacity Blocks** end on a fixed date. `gpu preflight` keeps long jobs off a
  block that would end before they finish.
- **Termination:** on preemption you get 5 minutes (SIGTERM) to write a checkpoint.
