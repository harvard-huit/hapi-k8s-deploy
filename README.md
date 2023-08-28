HAPI Kubernetes Deploy
====================

This package installs scripts that can run from the command line. In addition, the script deploys application to HAPI K8s Clusters.

## Install

        pip install https://github.com/harvard-huit/hapi-k8s-deploy/zipball/main

## Upgrade

        pip install https://github.com/harvard-huit/hapi-k8s-deploy/zipball/main  -U


## Operation

Must be logged into the appropriate AWS account for secrets  `stack/secretname` to exist.

        $ k8sdeploy --help
                usage: k8sdeploy [-h] [-s STACK] [-f FILENAME]

                Deploy Namespace, Secret, ConfigMap, Deployment, Service, and Ingress.

                optional arguments:
                -h, --help            show this help message and exit
                -s STACK, --stack STACK
                                        stack(default=`dev`)
                -f FILENAME, --filename FILENAME
                                        Specific ansible yaml file. Default: {current directory}/k8s_vars/{ stack }_k8s_vars.yml
        $ # default stack=dev
          # default file location
          # {current directory}/k8s_vars/{ stack }_k8s_vars.yml
        
