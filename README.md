HAPI Kubernetes Deploy
====================

This package installs scripts that can run from the command line. In addition, the script deploys applications to the HAPI K8s Clusters.

## Install
I made the `hapi-k8s-deploy` repository private. This was done because of default_vars. The `target_image_registry` has the AWS account number and thought that may be revealing sensitive information. 

git clone repository.

        cd hapi-k8s-deploy/
        pip install .

## Upgrade

        cd hapi-k8s-deploy/
        pip install  -U .


## Operation

Must be logged into the appropriate AWS account for secrets  `stack/secretname` to exist.

        usage: k8sdeploy [-h] [-s STACK] [-a ACTION] [-f FILENAME]

        Create K8s artifacts within cluster.

        options:
        -h, --help            show this help message and exit
        -s STACK, --stack STACK
                                stack(default='dev')
        -a ACTION, --action ACTION
                                Action verb: create, delete, apply (default='apply')
        -f FILENAME, --filename FILENAME
                                Specific filename to pass in k8s vars yaml file. Default: {current directory}/k8s_vars/{stack}_k8s_vars.yml
        


## K8s Variables

Variable | Type | Description | Default Value
-------- | ---- | ----------- | -------------
target_namespace| string | Required field - Kubernetes namespace |
target_app_name | string | Required field with application name (Alphanumeric with dash separator) |
target_app_port | int | required field - port exposed within container |
target_image_name| str | Optional image name of ECR image | target_app_name
target_image_tag | str | Required field - Specific image tag within ECR | 
target_app_secrets_ref | json | Optional AWS Secrets Manager secret references |
target_app_env | json | Optional environment values to pass to the container |
target_memory_mb | int | Memory allocated to the container | Not used currently
target_replica_count | int | Optional field - Desired container count | 3
create_ingress | str | Optional Boolean | True
ingress_hostname | str | Required field if create_ingress is True - Hostname for ALB | 
ingress_path | str | Optional field if create_ingress is True - Path route to set within ALB | /
ingress_health_check_path| str | Optional field if create_ingress is True - Health Check Path | /
successful_response_codes| str | Optional field if create_ingress is True - Health Check Path | '200'
ingress_load_balancer_name | str | Required Field if create_ingress is True - Name of AWS ALB | 
ingress_group_name | str | Application Load Balancer group, combine multiple applications within one ALB | ingress_load_balancer_name
ingress_inbound_security_groups | str | Inbound Security group Ids | Apigee Edge IPs and DMSDEVOPS Tunnel