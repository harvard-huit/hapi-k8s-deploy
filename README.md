HAPI Kubernetes Deploy
====================

This package installs scripts that can run from the command line. In addition, the script deploys applications to the HAPI K8s Clusters.

## Install
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
        
