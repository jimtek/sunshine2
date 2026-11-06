# Researcher interview guide

30 minutes, one team lead or researcher per slot. Aim for at least one per team
and 10-15 in total. Record answers in `interview-summary.md`, not verbatim notes.

## Workload
1. What do you run most: multi-node training, single-node jobs, notebooks, eval/inference?
2. Typical job size (GPUs) and duration? Largest in the last quarter?
3. Roughly what share of your GPU time is interactive or dev work?

## Scheduling and Slurm
4. How do you get GPUs today? Who do you ask, and how long does it take?
5. Do you use Slurm scripts (`sbatch`, `srun`)? Could you port them to a wrapper CLI if it accepted similar flags?
6. What would make you stop using direct access?

## Reliability
7. Do your jobs checkpoint? Have you resumed one from a checkpoint in the last month, and did it work?
8. How often do jobs die from hardware or infrastructure? What happens next?

## Data and cost
9. Where does training data live (S3, FSx, other)? Have you seen data loading stall GPUs?
10. Do you know what an experiment costs? Would you use that number?

## Support
11. Last three times you needed help: what was it, and how long did it take?

## Close
12. One thing the platform must not break for you.
