"""EventBridge → Lambda: start or stop the GEX alerts EC2 instance.

EventBridge target input must include {"action": "start"} or {"action": "stop"}.
"""

import boto3
import os

INSTANCE_ID = os.environ["INSTANCE_ID"]
REGION = os.environ.get("AWS_REGION", "ap-south-1")

ec2 = boto3.client("ec2", region_name=REGION)


def handler(event, context):
    action = event.get("action")
    if action == "start":
        ec2.start_instances(InstanceIds=[INSTANCE_ID])
        return {"status": f"started {INSTANCE_ID}"}
    elif action == "stop":
        ec2.stop_instances(InstanceIds=[INSTANCE_ID])
        return {"status": f"stopped {INSTANCE_ID}"}
    else:
        raise ValueError(f"Unknown action: {action!r}. Must be 'start' or 'stop'.")
