#!/usr/bin/env python3
"""Keep the existing web console and add the frozen native rebuild pipeline."""
import sys
from pathlib import Path
import ki2ci as ci

original_names=ci.pipeline_names
original_steps=ci.pipeline_steps
original_run=ci.run_step


def names():
    return original_names()+['native-inputs','native-llvm-mesa']


def steps(config,name):
    if name not in ['native-inputs','native-llvm-mesa']:return original_steps(config,name)
    actions=['verify'] if name=='native-inputs' else ['verify','prepare','llvm','mesa','validate']
    return [ci.Step('Native candidate: '+action,[sys.executable,str(config.repo_root/'tools/ki2remote_rebuild.py'),action]) for action in actions]


def run_step(config,step,log_path):
    if step.name.startswith('Native candidate: '):
        step=ci.Step(step.name,step.command+['--job-dir',str(Path(log_path).parent)],step.allow_failure)
    return original_run(config,step,log_path)


ci.pipeline_names=names
ci.pipeline_steps=steps
ci.run_step=run_step
if __name__=='__main__':raise SystemExit(ci.main())
