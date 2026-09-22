HAPI Kubernetes Deploy
====================

This package installs scripts that can run from the command line. In addition, the script deploys applications to the HAPI K8s Clusters.
## Requirements
1. AWS Login (Within appropriate AWS Account)
1. Kubectl 
1. Kubectl config file

        aws eks --region us-east-1 update-kubeconfig --name adexk8s-eks-cluster-{stack} --alias env-{stack}
        
## Install

git clone repository.

        cd hapi-k8s-deploy/
        pip install .

## Upgrade

        cd hapi-k8s-deploy/
        pip install  -U .



## Operation
Must set ENV Variable or pass in ECR_ACCOUNT_ID

        export ECR_ACCOUNT_ID={{ ECR Account Id }} 

Must be logged into the appropriate AWS account for secrets  `stack/secretname` to exist.

        usage: k8sdeploy [-h] [-s STACK] [-a ACTION] [-d] [-f FILENAME] [-e ECR_ACCOUNT_ID]

        Create K8s artifacts within cluster.

        options:
        -h, --help            show this help message and exit
        -s STACK, --stack STACK
                                stack(default='dev')
        -a ACTION, --action ACTION
                                Action verb: create, delete, apply (default='apply')
        -d, --delete-namespace
                                Delete Namespace: only used if action is 'delete'
        -f FILENAME, --filename FILENAME
                                Specific filename to pass in k8s vars yaml file. Default: {current
                                directory}/k8s_vars/{stack}_k8s_vars.yml
        -e ECR_ACCOUNT_ID, --ecr-account-id ECR_ACCOUNT_ID
                                ECR Account ID. Default: Environment Variable 'ECR_ACCOUNT_ID'
        


## K8s Variables API deploy

Variable | Type | Description | Default Value
-------- | ---- | ----------- | -------------
deploy_type| string|deploy type: api,job,cronjob| api
target_namespace| string | Required field - Kubernetes namespace | default
target_app_name | string | Required field with application name (Alphanumeric with dash separator) |
target_app_port | int | required field - port exposed within container |
target_image_name| string | Optional image name of ECR image | target_app_name
target_image_tag | string | Required field - Specific image tag within ECR | 
target_app_secrets_ref | json | Optional AWS Secrets Manager secret references |
target_app_env | json | Optional environment values to pass to the container |
target_memory_mb | int | Deprecated / not used. See Resource Constraints section below. |
target_replica_count | int | Optional field - Desired container count | 3
create_ingress | string | Optional Boolean | true
create_service | string | deploy a service | true
ingress_hostname | string | Required field if create_ingress is True - Hostname for ALB | 
ingress_path | string | Optional field if create_ingress is True - Path route to set within ALB | /
ingress_health_check_path| string | Optional field if create_ingress is True - Health Check Path | /
successful_response_codes| string | Optional field if create_ingress is True - Health Check Path | '200'
ingress_load_balancer_name | string | Required Field if create_ingress is True - Name of AWS ALB | 
ingress_group_name | string | Application Load Balancer group, combine multiple applications within one ALB | ingress_load_balancer_name
ingress_inbound_security_groups | string | Inbound Security group Ids | Apigee Edge IPs and DMSDEVOPS Tunnel
ingress_tags | string | Comma separated string of default tags added to ingress | "Name={{ ingress_load_balancer_name }},dms_app_family=adex,dms_service=adex,dms_stack={{ stack }},environment={{ environment }},huit_assetid=9301,product=adexk8s,waf-type=external-alb"
ingress_additional_tags | string | additional tags you want added to ingress | ''

## Resource Constraints
deploy_type=api

Opt-in CPU/memory requests and limits on the container. **Backward compatible:** if `target_set_resources` is left `False` (the default), the rendered Deployment is unchanged (no `resources` block). Set it to `True` to apply constraints; any sub-value you omit falls back to the default below.

By design only a **memory limit** is set — a CPU limit is omitted unless you explicitly set `target_cpu_limit`, since CPU limits cause throttling on busy services. CPU is requested (for scheduling/QoS) but not capped.

Variable | Type | Description | Default Value
-------- | ---- | ----------- | -------------
target_set_resources | boolean | Master switch. When False, no `resources` block is rendered (legacy behavior). | False
target_cpu_request | string | CPU request (e.g. `100m`, `1`). | 100m
target_memory_request_mb | int | Memory request in MiB. | 256
target_memory_limit_mb | int | Memory limit in MiB. | 512
target_cpu_limit | string | Optional CPU limit (e.g. `2`). Omitted entirely when empty. | '' (none)

Example (in your `{stack}_k8s_vars.yml`):

        target_set_resources: True
        target_cpu_request: "500m"
        target_memory_request_mb: 512
        target_memory_limit_mb: 1024

## Health Probes, Shutdown and Rollout
deploy_type=api

Opt-in probes, shutdown grace and rolling-update pacing. **Backward compatible:** every
value below is empty by default, so a deployment that sets none of them renders exactly
as before.

Without a `readinessProbe`, Kubernetes adds a pod to the Service the moment its container
starts — before the server has bound its socket — while the default `maxUnavailable: 25%`
is already removing pods that were serving. Measured on hapi-ais-llm stage: 14 of 64
requests returned 502 during a rollout, and none once the pods had settled. With these set
(`maxUnavailable: 0` plus a readiness probe), 98 requests driven across a rolling restart
all returned 200.

`terminationGracePeriodSeconds` is the one that fails silently. Kubernetes defaults to 30
seconds and SIGKILLs at that point, so an application whose own shutdown runs longer is cut
off mid-drain with nothing logged. hapi-ais-llm sets gunicorn `graceful_timeout` to 90 and
drains its billing queue inside it — every queued charge was being dropped on each pod
recycle. **Set this higher than whatever your app's own graceful shutdown allows.**

Variable | Type | Description | Default Value
-------- | ---- | ----------- | -------------
target_readiness_probe_path | string | HTTP path for the readiness probe. Empty renders no probe. | '' (none)
target_liveness_probe_path | string | HTTP path for the liveness probe. Empty renders no probe. | '' (none)
target_startup_probe_path | string | HTTP path for the startup probe, for slow-booting apps. | '' (none)
target_probe_port | int | Port for all probes. | target_app_port
target_probe_scheme | string | `HTTP` or `HTTPS`. Must be HTTPS when the app terminates TLS itself. | HTTP
target_probe_timeout | int | Probe timeout in seconds, applied to all three. | 3
target_readiness_initial_delay | int | Seconds before the first readiness check. | 3
target_readiness_period | int | Seconds between readiness checks. | 5
target_readiness_failure_threshold | int | Consecutive failures before the pod leaves the Service. | 3
target_liveness_initial_delay | int | Seconds before the first liveness check. | 30
target_liveness_period | int | Seconds between liveness checks. | 20
target_liveness_failure_threshold | int | Consecutive failures before the container is restarted. | 3
target_startup_period | int | Seconds between startup checks. | 3
target_startup_failure_threshold | int | Startup checks allowed before the container is restarted. | 30
target_prestop_sleep_seconds | int | Sleep between endpoint removal and SIGTERM so in-flight requests finish. | '' (none)
target_termination_grace_seconds | int | Seconds before SIGKILL. Must exceed the app's own graceful shutdown. | '' (Kubernetes default, 30)
target_max_unavailable | int or string | Pods that may be unavailable during a rollout. `0` never dips below capacity. | '' (Kubernetes default, 25%)
target_max_surge | int or string | Extra pods allowed above the replica count during a rollout. | '' (Kubernetes default, 25%)
target_min_ready_seconds | int | Seconds a new pod must stay ready before it counts as available. | '' (none)

Example (in your `common_k8s_vars.yml` or `{stack}_k8s_vars.yml`):

        target_readiness_probe_path: /api/healthcheck/
        target_liveness_probe_path: /api/healthcheck/
        target_probe_scheme: HTTPS
        target_termination_grace_seconds: 120
        target_prestop_sleep_seconds: 10
        target_max_unavailable: 0
        target_max_surge: "25%"

### Three things that will bite you

**Set `target_probe_scheme: HTTPS` if your app terminates TLS itself.** The default is HTTP,
and an HTTP probe against an HTTPS listener never succeeds — no pod ever becomes ready and
the rollout hangs. This turns a fix for rollout 502s into a stuck deployment.

**Keep probes shallow.** A probe should answer "is this process serving", not "are my
dependencies healthy". One that checks a database fails every pod at once the moment that
database blips, turning degradation into an outage. Use a path that returns a static 200
without touching anything, and put dependency health in alerting instead.

**`target_max_unavailable: 0` is the value worth setting, and `0` is falsy.** It is checked
against `none` rather than for truthiness so it is not silently dropped. If you add similar
variables, do the same.

## Variables Job/CronJob 
deploy_type=job or cronjob

Variable | Type | Description | Default Value
-------- | ---- | ----------- | -------------
job_interval| string | [Cron Syntax](https://en.wikipedia.org/wiki/Cron) if job_interval not set will perform once as a Kubernetes Job.| None
restart_policy | string | Restart Policy: Never or OnFailure is allowed. | OnFailure
backoff_limit | string | There are situations where you want to fail a Job after some amount of retries due to a logical error. Specify the number of retries before considering a Job as failed. | 6 
concurrency_policy| string |  Specifies how to treat concurrent executions of a job that is created by this CronJob. Concurrency policies: Allow, Forbid, Replace | Allow 

## Volume Mount 
deploy_type=api

Variable | Type | Description | Default Value
-------- | ---- | ----------- | -------------
target_volume_mount| list of objects | description of volume mounts|
target_volume_mount.name | string | name of volume |
target_volume_mount.path | string | path of mount |
target_volume_mount.type | string| secret or configmap|
target_volume_mount.secret_name | string | specific secret name added outside of deploy process| secret name generated by deploy process
target_volume_mount.configmap_name | string | specific configmap name added outside of deploy process| configmap name generated by deploy process
target_volume_mount.mode | string | file permissions | 420
target_volume_mount.data_items | list of objects |  key and path |
target_volume_mount.data_items.key | string| key within secret or configmap |
target_volume_mount.data_items.path | string| path with filename |




