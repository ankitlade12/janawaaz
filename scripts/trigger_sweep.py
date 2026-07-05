"""Cron entrypoint: start the workflow root task via the Render API.

Render Workflows has no native scheduler yet, so a Render Cron Job runs this
script on a schedule; it starts `sweep_sources` on the workflow service.
Requires RENDER_API_KEY in the cron job's environment.

The task path is <workflow service name>/<task name>.
"""

import os

from render_sdk import Render

WORKFLOW_TASK = os.environ.get("SWEEP_TASK", "janawaaz-workflows/sweep_sources")

if __name__ == "__main__":
    render = Render()  # reads RENDER_API_KEY
    run = render.workflows.start_task(WORKFLOW_TASK, [])
    print(f"started {WORKFLOW_TASK}: run id {run.id}")
