"""Isolated compatibility seam for runtime settings; runs in ENGINE Python.

Uses upstream CLI unchanged. Never calls params.save() or writes credential JSON.
This script needs only Python stdlib before importing the external engine.
"""

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from pathlib import Path


def main() -> int:
    root = Path(os.environ["LOCALIZER_ENGINE_ROOT"]).resolve()
    sys.path.insert(0, str(root))
    from videotrans.configure.config import params

    overrides = json.loads(os.environ.get("LOCALIZER_ENGINE_OVERRIDES", "{}"))
    for key, value in overrides.items():
        if not hasattr(params, key):
            raise RuntimeError(f"pyVideoTrans config parameter not supported: {key}")
        params[key] = value
    import cli
    from videotrans.task.trans_create import TransCreate

    def instrument(method, stage):
        @wraps(method)
        def report(self, *args, **kwargs):
            print("LOCALIZER_STAGE " + json.dumps({"stage": stage}), flush=True)
            return method(self, *args, **kwargs)

        return report

    for method, stage in [
        ("recogn", "transcribing"),
        ("trans", "translating"),
        ("dubbing", "dubbing"),
    ]:
        setattr(TransCreate, method, instrument(getattr(TransCreate, method), stage))

    if os.environ.get("LOCALIZER_ENGINE_EXECUTOR", "process") == "process":
        return cli.main()

    # Windows restricted environments can reject the engine's multiprocessing pipes.
    # Keep the engine in its own external process; adapt its CPU task submission only.
    # The real upstream callback still performs all recognition/processing work.
    from videotrans.process.signelobj import GlobalProcessManager
    from videotrans.task import _rate

    original_submit = GlobalProcessManager.__dict__["submit_task_cpu"]
    original_rate_executor = _rate.ProcessPoolExecutor
    os.environ["MKL_NUM_THREADS"] = "1"
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="pyvideotrans-cpu") as executor:

        def submit_cpu(func, **kwargs):
            return executor.submit(func, **kwargs)

        GlobalProcessManager.submit_task_cpu = staticmethod(submit_cpu)
        _rate.ProcessPoolExecutor = ThreadPoolExecutor
        try:
            return cli.main()
        finally:
            GlobalProcessManager.submit_task_cpu = original_submit
            _rate.ProcessPoolExecutor = original_rate_executor


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    raise SystemExit(main())
