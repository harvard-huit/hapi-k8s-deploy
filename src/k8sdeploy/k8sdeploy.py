import boto3
import os
import yaml
import jinja2
import json
import tempfile
import base64
import sys
from contextlib import contextmanager
from botocore.exceptions import ClientError, NoCredentialsError
from subprocess import run, check_output, CalledProcessError
from six import b
from time import sleep

class KubernetesDeploy():
    def __init__(self,var_filename,stack,ecr_account_id):
        self.stack=stack
        self.default_path=f"{os.path.dirname(os.path.abspath(__file__))}"
        self.account=""
        self.vars=self.__deploy_data__(var_filename,ecr_account_id)
        self.rollout_restart=False
        self.eks=boto3.client('eks')
        self.cluster_name=f"adexk8s-eks-cluster-{self.stack}"

    def __deploy_data__(self,filename,ecr_account_id):
        self.checkAWSToken(ecr_account_id)
        var_data=self.read_variable_file(filename)
        # manual inputs
        var_data['ecr_account_id'] = ecr_account_id
        var_data['target_stack']=self.stack
        var_data['target_image_tag']=self.get_target_image_tag(var_data,self.stack)
        # secrets and config map vars
        secret_cm=self.generate_secret_configmap_data(var_data)
        data = secret_cm | var_data 
        data=self.get_cert_arn(data)
        data=self.get_tag_data(data)
        data = self.load_defaults('default_vars.yml',data) | data
        data = self.set_ingress_tag_data(data)
        d=data.pop("target_app_secrets_ref",None)
        d=data.pop("target_app_env",None)
        d=data.pop("ingress_additional_tags",None)
        return data
    
    def get_target_image_tag(self,val,target_stack):
        """
            get target_image_tag 
        """
        if "target_app_env" in val.keys():
            for itm in val["target_app_env"]:
                if itm['name'] == "VERSION":
                    return itm['value']
        if val.get('target_image_tag', ''):
            return val['target_image_tag']
        else:
            return target_stack
            
    def load_defaults(self,filename,data):
        path=f"{self.default_path}/default_vars"
        templateLoader = jinja2.FileSystemLoader(searchpath=path)
        template_env=jinja2.Environment(loader=templateLoader, autoescape=True)
        template=template_env.get_template(filename)
        return yaml.safe_load(template.render(**data))

    def set_ingress_tag_data(self,var_data):
        if var_data['ingress_additional_tags']:
            # Default tags
            default_tags=self.parse_tags(var_data['ingress_tags'],'ingress_tags')
            # Additional tags
            additonal_tags=self.parse_tags(var_data['ingress_additional_tags'],'ingress_additional_tags')
            # Merge tags
            tags=default_tags | additonal_tags
            tags_string=",".join([f"{key}={value}" for key, value in tags.items()])
            var_data['ingress_tags']=tags_string
        return var_data
    
    def parse_tags(self,tags_string,variable_name):
        """
            Parse "key=value,key=value" into a dict, falling back to ":" as the
            separator when "=" does not fit every tag.
        """
        tags=[tag.strip() for tag in tags_string.split(",")]
        for separator in ("=",":"):
            try:
                return dict(tag.split(separator) for tag in tags)
            except ValueError:
                continue
        raise ValueError(f"{variable_name} must be comma-separated key=value (or key:value) pairs, got: {tags_string!r}")

    def get_tag_data(self, var_data):
        lookup={"dev":"Development","prod":"Production","stage":"Stage","sand":"Development"}
        var_data['stack']=self.stack
        var_data['environment']=lookup[self.stack]
        return var_data

    def get_secret(self,secret_name,region_name="us-east-1"):
        session = boto3.session.Session()
        client = session.client(
            service_name='secretsmanager',
            region_name=region_name,
        )

        try:
            get_secret_value_response = client.get_secret_value(
                SecretId=secret_name
            )
        except ClientError as e:
            print(e.response['Error']['Code'])
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                print("The requested secret " + secret_name + " was not found")
            elif e.response['Error']['Code'] == 'InvalidRequestException':
                print("The request was invalid due to:", e)
            elif e.response['Error']['Code'] == 'InvalidParameterException':
                print("The request had invalid params:", e)
            elif e.response['Error']['Code'] == 'DecryptionFailure':
                print("The requested secret can't be decrypted using the provided KMS key:", e)
            elif e.response['Error']['Code'] == 'InternalServiceError':
                print("An error occurred on service side:", e)
        else:
            # Secrets Manager decrypts the secret value using the associated KMS CMK
            # Depending on whether the secret was a string or binary, only one of these fields will be populated
            if 'SecretString' in get_secret_value_response:
                text_secret_data = get_secret_value_response['SecretString']
                return base64.b64encode(b(text_secret_data)).decode('utf-8') 
            else:
                print("binary data", get_secret_value_response['SecretBinary'])
                binary_secret_data = get_secret_value_response['SecretBinary']
                return binary_secret_data

    @contextmanager
    def disable_exception_traceback(self):
        """
        All traceback information is suppressed and only the exception type and value are printed
        """
        default_value = getattr(sys, "tracebacklimit", 1000)  # `1000` is a Python's default value
        sys.tracebacklimit = 0
        yield
        sys.tracebacklimit = default_value  # revert changes

    def checkAWSToken(self,ecr_account):
        """
        Check if AWS Token has expired
        """
        try:
            sts = boto3.client('sts')
            account=sts.get_caller_identity()['Account']
            self.account=account
            if (self.stack in ['stage','prod'] and account == ecr_account ) or (self.stack in ['dev','sand'] and account != ecr_account ):
                with self.disable_exception_traceback():
                    raise Exception(f"Stack '{self.stack}' is not consistent with AWS Account. Please login to the correct AWS Account. ")
        except ClientError as e:
            with self.disable_exception_traceback():
                if e.response['Error']['Code'] == 'ExpiredToken':
                    raise Exception("ExpiredToken: AWS Token has expired") from None
                else:
                    raise Exception(f"{repr(e)}. k8sdeploy requires valid AWS Token") from None
        except NoCredentialsError as e1:
            with self.disable_exception_traceback():
                raise Exception(f"{repr(e1)}. k8sdeploy requires valid AWS Token") from None

    def get_cert_arn(self,var_data):
        arn= None
        if 'aws_load_balancer_ssl_cert' in var_data:
            arn= var_data['aws_load_balancer_ssl_cert']
        else:
            acm=boto3.client('acm')
            all_certs=acm.list_certificates()
            for cert in all_certs['CertificateSummaryList']:
                if cert['DomainName'].endswith(f"{self.stack}.apis.huit.harvard.edu"):
                    arn= cert['CertificateArn']
        if not arn:
            raise Exception("Unable to find ARN for ALB Certificate")

        var_data['aws_load_balancer_ssl_cert']=arn
        return var_data

    def read_variable_file(self,filename):
        with open(filename, 'r') as f1:
            return yaml.safe_load(f1.read())

    def generate_secret_configmap_data(self,var_data):
        data={"secret":{},"configmap":{}} 
        if 'target_app_secrets_ref' in var_data:
            for itm in var_data['target_app_secrets_ref']:
                for i in itm:
                    secret_name="{0}/{1}".format(self.stack,itm[i])
                    value=self.get_secret(secret_name)
                    data["secret"][i]="".join(value.split())
        if 'target_app_env' in var_data:
            for itm in var_data['target_app_env']:
                data["configmap"][itm['name']]="".join(itm['value'].split())
        return data

    def load_template(self,template_name,data):
        path=f"{self.default_path}/templates"
        templateLoader = jinja2.FileSystemLoader(searchpath=path)
        template_env=jinja2.Environment(loader=templateLoader, autoescape=True)
        template=template_env.get_template(f"{template_name}.j2")
        return template.render(**data)
    
    def wait_api_availability(self):
        attempts=0
        wait=True
        while wait: 
            cluster=self.eks.describe_cluster(name=self.cluster_name)
            if cluster['cluster']['status'] !='ACTIVE':
                sleep(10)
                if attempts >30:
                    with self.disable_exception_traceback():
                        raise Exception("EKS Cluster is not ready! Waited for 5 minutes and still unavailable. Please retry later.")
            else:
                wait=False
            attempts += 1
        return  cluster['cluster']['resourcesVpcConfig']
    
    def wait_api_reachable(self,attempts=18,delay_seconds=10):
        """
            An ACTIVE cluster is not necessarily reachable from this runner: a
            just-added publicAccessCidrs entry can lag. Retry before the first
            apply so that lag fails here, clearly, rather than as a confusing
            openapi download timeout on the namespace manifest.
        """
        command=['kubectl','get','--raw=/readyz','--request-timeout=10s']
        for attempt in range(1,attempts+1):
            result=run(command, capture_output=True, encoding='UTF-8')
            if result.returncode == 0:
                return
            print(f"Kubernetes API not reachable yet (attempt {attempt}/{attempts}): {result.stderr.strip()}")
            if attempt < attempts:
                sleep(delay_seconds)
        print(f"ERROR: Kubernetes API for {self.cluster_name} unreachable; check this runner's IP is in the cluster's publicAccessCidrs", file=sys.stderr)
        raise CalledProcessError(result.returncode, command, output=result.stdout, stderr=result.stderr)

    def load_deploy(self,template,action):
        """
            Render a template and hand it to kubectl. A non-zero kubectl exit
            raises CalledProcessError so the deploy fails instead of going green.
        """
        rendered=self.load_template(template,self.vars)
        with tempfile.NamedTemporaryFile(mode='w+', suffix='.yaml', delete=False) as temp_file:
            temp_file.write(rendered)
        command=['kubectl', action ,'-f',temp_file.name ]
        if action == "delete":
            # Already gone is the goal of a delete, not a failure
            command.append('--ignore-not-found')
        try:
            if template == "deployment":
                result=check_output(command, encoding='UTF-8')
                if "unchanged" in result:
                    self.rollout_restart=True
                else:
                    print(result)
            else:
                run(command, check=True)
        except CalledProcessError as error:
            if error.output:
                print(error.output)
            print(f"ERROR: kubectl {action} of the {template} manifest failed (exit {error.returncode})", file=sys.stderr)
            raise
        finally:
            # Rendered secrets must not outlive the run
            os.unlink(temp_file.name)

    def deployment_rollout_restart(self):
        run(['kubectl', "rollout", "restart" ,
             f"deployment.apps/{self.vars['target_app_name']}",
             "-n", f"{self.vars['target_namespace']}"], check=True)

    def wait_for_rollout(self):
        """
            Block until the Deployment's new pods are ready. kubectl apply only
            proves the API server accepted the manifest; an image that cannot be
            pulled, or a pod that never passes readiness, only shows up here.
            A stuck rollout fails on the Deployment's progressDeadlineSeconds;
            the timeout is only a backstop against waiting forever.
        """
        timeout=self.vars.get('target_rollout_timeout_seconds')
        if timeout is None or timeout == '' or int(timeout) == 0:
            return
        run(['kubectl', "rollout", "status",
             f"deployment.apps/{self.vars['target_app_name']}",
             "-n", f"{self.vars['target_namespace']}",
             f"--timeout={int(timeout)}s"], check=True)

    def deploy_objects(self,action="apply",delete_namespace=False):
        # First double check API is Ready after adding 
        # GH Runner Ip4 to cluster config 
        self.wait_api_availability()
        self.wait_api_reachable()
        # Check AWS Token
        self.checkAWSToken(self.vars['ecr_account_id'])
        # Namespace
        if action != "delete":
            self.load_deploy("namespace",action)
        # secrets and configmaps
        if self.vars['secret']:
            self.load_deploy("secret",action)
        if self.vars['configmap']:
            self.load_deploy("configmap",action)
        # Deploy k8s objects
        if self.vars['deploy_type'].lower() == 'api':
            self.load_deploy("deployment",action)
            if self.vars['create_service']:
                self.load_deploy("service",action)
            if self.vars['create_ingress']:
                self.load_deploy("ingress",action)
            if self.rollout_restart:
                self.deployment_rollout_restart()
            if action != "delete":
                self.wait_for_rollout()
        elif self.vars['deploy_type'].lower() in ['job','cronjob']:
            self.load_deploy("job",action)
        # namespace delete
        if action=="delete" and delete_namespace:
            self.load_deploy("namespace",action)

class EksUpateConfig():
    def __init__(self,stack: str,github_runner_ip: str):
        self.stack=stack
        self.cluster_name=f"adexk8s-eks-cluster-{self.stack}"
        self.ip4 = github_runner_ip
        self.eks=boto3.client('eks')

    @contextmanager
    def disable_exception_traceback(self):
        """
        All traceback information is suppressed and only the exception type and value are printed
        """
        default_value = getattr(sys, "tracebacklimit", 1000)  # `1000` is a Python's default value
        sys.tracebacklimit = 0
        yield
        sys.tracebacklimit = default_value  # revert changes

    def get_cluster_config(self):
        attempts=0
        wait=True
        while wait: 
            cluster=self.eks.describe_cluster(name=self.cluster_name)
            if cluster['cluster']['status'] !='ACTIVE':
                sleep(10)
                if attempts >30:
                    with self.disable_exception_traceback():
                        raise Exception("EKS Cluster is not ready! Thirty tries and waited for 5 minutes. Please retry later.")
            else:
                wait=False
            attempts += 1
        return  cluster['cluster']['resourcesVpcConfig']
    
    def wait_for_update(self,update_id: str):
        """
            update_cluster_config returns as soon as EKS accepts the change; the
            new publicAccessCidrs only apply once the update reaches Successful.
        """
        attempts=0
        while True:
            update=self.eks.describe_update(name=self.cluster_name,updateId=update_id)['update']
            if update['status'] == 'Successful':
                print(f"EKS endpoint access update {update_id} applied")
                return
            if update['status'] in ('Failed','Cancelled'):
                with self.disable_exception_traceback():
                    raise Exception(f"EKS endpoint access update {update_id} {update['status']}: {update.get('errors')}")
            if attempts >60:
                with self.disable_exception_traceback():
                    raise Exception(f"EKS endpoint access update {update_id} still {update['status']} after 10 minutes on {self.cluster_name}")
            sleep(10)
            attempts += 1

    def update_config(self,action: str):
        wait=True
        attempts=0
        while wait:
            resources_vpc_config= self.get_cluster_config()
            if action.lower() != 'delete':
                resources_vpc_config['publicAccessCidrs'].append(f"{self.ip4}/32")
                resources_vpc_config['publicAccessCidrs']=list(set(resources_vpc_config['publicAccessCidrs']))
            else:
                if f"{self.ip4}/32" in resources_vpc_config['publicAccessCidrs']:
                    resources_vpc_config['publicAccessCidrs'].remove(f"{self.ip4}/32")
            try:
                response=self.eks.update_cluster_config(name=self.cluster_name,resourcesVpcConfig={"publicAccessCidrs":resources_vpc_config['publicAccessCidrs']})
                if action.lower() != 'delete':
                    # The runner cannot reach the API until the update lands, and a
                    # cleanup that runs before then finds no IP to remove and leaks it
                    self.wait_for_update(response['update']['id'])
                wait=False
            except self.eks.exceptions.InvalidParameterException as e:
                # parameters should be correct unless Cluster is already at the desired configuration
                if "Cluster is already at the desired configuration" in str(e):
                    print("Cluster is already at the desired configuration")
                    wait=False
            except self.eks.exceptions.ResourceInUseException as e:
                print("ResourceInUseException")
                sleep(30)
            if attempts >10:
                with self.disable_exception_traceback():
                    raise Exception(f"Attempting to {action} GH Runner IP. Please double check IP: {self.ip4} access on {self.cluster_name}")
            attempts += 1
        return resources_vpc_config